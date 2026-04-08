from flask import Flask, render_template, request, session, send_file, flash, redirect, url_for, make_response
from PIL import Image, ImageDraw, ImageFont
import random, io, os, re
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)

# -------------------------
# Helpers, los helpers se usan en varias vistas
# -------------------------
def _only_digits(text: str) -> str:
    import re as _re
    return _re.sub(r'\D+', '', text or '')

def _parse_number(text: str):
    """Intenta parsear un número aceptando:
    - Enteros ("12")
    - Decimales con punto o coma ("3.5", "3,5")
    Devuelve int si no hay parte decimal significativa, si no float. Si falla -> None.
    """
    if text is None:
        return None
    raw = text.strip().replace(',', '.')
    if not raw:
        return None
    try:
        val = float(raw)
        # Si es equivalente a un entero exacto, devolver int
        if val.is_integer():
            return int(val)
        return val
    except ValueError:
        return None

def _no_cache_response(html):
    """Devuelve una respuesta HTML con cabeceras no-cache para evitar páginas en el historial."""
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

def _normalize_text(text: str) -> str:
    """Normaliza texto a minúsculas sin acentos para comparación flexible."""
    if not text:
        return ''
    import unicodedata
    t = unicodedata.normalize('NFD', text.lower())
    t = ''.join(c for c in t if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-zñ]+', '', t)

# -------------------------
# Home (menú)
# -------------------------
@app.route('/home')
def home():
    return _no_cache_response(render_template('home.html'))

# -------------------------
# CAPTCHA aritmético
# -------------------------
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        user_answer = request.form.get('captcha')
        real_answer = session.get('captcha_answer')  # Puede ser int o float

        # Intento de comparación numérica flexible
        ua_num = _parse_number(user_answer)
        correcto = False
        if real_answer is not None and ua_num is not None:
            # Comparación con tolerancia si es float
            try:
                diff = abs(float(ua_num) - float(real_answer))
                correcto = diff <= 1e-9
            except Exception:
                correcto = False
        # Fallback a comparación textual exacta (por si acaso)
        if not correcto and user_answer and real_answer is not None:
            correcto = user_answer.strip() == str(real_answer)

        if correcto:
            session['just_logged_in'] = True
            flash("CAPTCHA correcto. ¡Bienvenido!", "success")
            return redirect(url_for('bienvenido'))
        flash("CAPTCHA incorrecto. Inténtalo de nuevo.", "danger")
        return redirect(url_for('index'))

    cache_buster = int(datetime.utcnow().timestamp())
    return _no_cache_response(render_template('index.html', cache_buster=cache_buster))

@app.route('/captcha_image')
def captcha_image():
    """CAPTCHA aritmético simple de 2 números con + - * /. División redondeada a 2 decimales."""
    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)
    operator = random.choice(['+', '-', '*', '/','^'])

    if operator == '+':
        answer = num1 + num2
        op_symbol = '+'
    elif operator == '-':
        answer = num1 - num2
        op_symbol = '−'
    elif operator == '*':
        answer = num1 * num2
        op_symbol = '×'
    elif operator == '/':
        raw_result = num1 / num2
        rounded = round(raw_result, 2)
        answer = int(rounded) if rounded.is_integer() else rounded
        op_symbol = '/'
    elif operator == '^':
        answer = num1 ** num2
        op_symbol = '^'

    session['captcha_answer'] = answer
    captcha_text = f"{num1} {op_symbol} {num2} = ?"

    img = Image.new('RGB', (180, 60), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()

    for _ in range(15):
        x1, y1 = random.randint(0, 180), random.randint(0, 60)
        x2, y2 = x1 + random.randint(-8, 8), y1 + random.randint(-8, 8)
        draw.line((x1, y1, x2, y2), fill=(220, 220, 220), width=1)

    draw.text((20, 15), captcha_text, font=font, fill=(0, 0, 0))

    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

# --- CAPTCHA multi-número (nuevo) ---
@app.route('/captcha-multi', methods=['GET', 'POST'])
def captcha_multi():
    if request.method == 'POST':
        user_answer = request.form.get('captcha')
        real_answer = session.get('captcha_answer_multi')
        ua_num = _parse_number(user_answer)
        correcto = False
        if real_answer is not None and ua_num is not None:
            try:
                correcto = abs(float(ua_num) - float(real_answer)) <= 1e-9
            except Exception:
                correcto = False
        if not correcto and user_answer and real_answer is not None:
            correcto = user_answer.strip() == str(real_answer)
        if correcto:
            session['just_logged_in'] = True
            flash("CAPTCHA multi correcto. ¡Bienvenido!", "success")
            return redirect(url_for('bienvenido'))
        flash("Resultado incorrecto. Intenta de nuevo.", "danger")
        return redirect(url_for('captcha_multi'))
    cache_buster = int(datetime.utcnow().timestamp())
    return _no_cache_response(render_template('captcha_multi.html', cache_buster=cache_buster))

@app.route('/captcha_multi_image')
def captcha_multi_image():
    """Genera un CAPTCHA con 3 o 4 números, aplica precedencia estándar (* y / antes que + y -) y añade paréntesis aleatorios.
    Estrategia:
      1. Generar lista de números y operadores.
      2. Insertar opcionalmente un par de paréntesis envolviendo una subexpresión válida (sin anidación compleja) para aumentar dificultad.
      3. Evaluar de forma segura tokenizando y aplicando precedencia.
    """
    count = random.choice([3, 4])
    nums = [random.randint(1, 20) for _ in range(count)]
    ops = [random.choice(['+', '-', '*', '/']) for _ in range(count - 1)]

    # Construir tokens intercalados: n0 op0 n1 op1 n2 ...
    tokens = []
    for i, n in enumerate(nums):
        tokens.append(str(n))
        if i < len(ops):
            tokens.append(ops[i])

    # Posible inserción de paréntesis (30% de probabilidad) sobre un segmento n op n
    if len(nums) >= 3 and random.random() < 0.7:
        # Elegir índice de inicio de subexpresión (n op n)
        idx_num = random.randint(0, len(nums) - 2)  # índice del primer número del bloque
        # Convertir a índice en tokens (cada número y operador alternan)
        t_start = idx_num * 2
        t_end = t_start + 2  # número, operador, número
        # Insertar paréntesis si no hay ya
        if '(' not in tokens and ')' not in tokens:
            tokens.insert(t_start, '(')
            tokens.insert(t_end + 2, ')')  # +2 porque insert anterior desplaza

    expr_display = ' '.join(tokens)

    # Evaluador seguro: tokenizar números, operadores y paréntesis
    def eval_tokens(tok_list):
        # Shunting-yard simplificado -> convertir a RPN
        prec = {'+':1, '-':1, '*':2, '/':2}
        output = []
        stack = []
        for t in tok_list:
            if t.isdigit():
                output.append(float(t))
            elif t in prec:
                while stack and stack[-1] in prec and prec[stack[-1]] >= prec[t]:
                    output.append(stack.pop())
                stack.append(t)
            elif t == '(':
                stack.append(t)
            elif t == ')':
                while stack and stack[-1] != '(':
                    output.append(stack.pop())
                if stack and stack[-1] == '(':
                    stack.pop()
        while stack:
            output.append(stack.pop())
        # Evaluar RPN
        st = []
        for it in output:
            if isinstance(it, float):
                st.append(it)
            else:
                b = st.pop(); a = st.pop()
                if it == '+':
                    st.append(a + b)
                elif it == '-':
                    st.append(a - b)
                elif it == '*':
                    st.append(a * b)
                elif it == '/':
                    st.append(a / b)
        return st[0] if st else 0.0

    # Preparar lista simple de tokens sin espacios
    clean_tokens = [t for t in tokens if t]
    result = eval_tokens(clean_tokens)
    rounded = round(result, 2)
    answer = int(rounded) if float(rounded).is_integer() else rounded
    session['captcha_answer_multi'] = answer

    # Reemplazar símbolos para mostrar (visual ×, −)
    display_expr = expr_display.replace('*', '×').replace('-', '−') + ' = ?'

    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except Exception:
        font = ImageFont.load_default()
    dummy_img = Image.new('RGB', (1, 1))
    dummy_draw = ImageDraw.Draw(dummy_img)
    try:
        bbox = dummy_draw.textbbox((0, 0), display_expr, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except Exception:
        text_w, text_h = font.getsize(display_expr)
    padding_x = 20
    padding_y = 15
    width = max(220, text_w + padding_x * 2)
    height = max(60, text_h + padding_y * 2)
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    for _ in range(18):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = x1 + random.randint(-10, 10), y1 + random.randint(-10, 10)
        draw.line((x1, y1, x2, y2), fill=(220, 220, 220), width=1)
    draw.text((padding_x, padding_y), display_expr, font=font, fill=(0, 0, 0))
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

# --- CAPTCHA Secuencia (nuevo) ---
@app.route('/captcha_secuencia', methods=['GET', 'POST'])
def captcha_secuencia():
    if request.method == 'POST':
        user_answer = request.form.get("sequence", "").strip()
        correct_answer = session.get("captcha_sequence_answer")

        correcto = False
        if correct_answer and user_answer:
            ua_num = _parse_number(user_answer)
            try:
                correcto = (ua_num is not None and float(ua_num) == float(correct_answer))
            except Exception:
                correcto = user_answer == str(correct_answer)

        if correcto:
            session['just_logged_in'] = True
            flash("CAPTCHA de secuencia correcto. ¡Bienvenido!", "success")
            return redirect(url_for('bienvenido'))
        flash("Respuesta incorrecta. Inténtalo de nuevo.", "danger")
        return redirect(url_for('captcha_secuencia'))

    cache_buster = int(datetime.utcnow().timestamp())
    return _no_cache_response(render_template('captcha_secuencia.html', cache_buster=cache_buster))


@app.route("/captcha_secuencia_image")
def captcha_secuencia_image():
    start = random.randint(1, 9)
    step = random.randint(1, 5)
    sequence = [start + i * step for i in range(3)]
    answer = start + 3 * step
    session["captcha_sequence_answer"] = str(answer)

    text = f"{sequence[0]}, {sequence[1]}, {sequence[2]}, ?"

    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()

    dummy = Image.new('RGB', (1, 1))
    ddraw = ImageDraw.Draw(dummy)
    try:
        bbox = ddraw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw, th = font.getsize(text)

    pad = 20
    w = tw + pad * 2
    h = th + pad * 2
    img = Image.new("RGB", (w, h), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Ruido de fondo
    for _ in range(15):
        x1, y1 = random.randint(0, w), random.randint(0, h)
        x2, y2 = x1 + random.randint(-12, 12), y1 + random.randint(-12, 12)
        draw.line((x1, y1, x2, y2), fill=(230, 230, 230), width=1)

    draw.text((pad, pad), text, font=font, fill=(0, 0, 0))
    img_io = io.BytesIO()
    img.save(img_io, "PNG")
    img_io.seek(0)
    return send_file(img_io, mimetype="image/png")


# -------------------------
# CAPTCHA por identificación (2 pasos)
# -------------------------
@app.route('/captcha-id', methods=['GET', 'POST'])
def captcha_id_step1():
    if request.method == 'POST':
        user_id = _only_digits(request.form.get('identificacion'))

        if not user_id or len(user_id) < 6 or len(user_id) > 12:
            flash("La identificación debe tener entre 6 y 12 dígitos.", "danger")
            return redirect(url_for('captcha_id_step1'))

        session['user_id'] = user_id

        # Dos posiciones distintas 1-indexadas
        p1 = random.randint(1, len(user_id))
        p2 = random.randint(1, len(user_id))
        while p2 == p1:
            p2 = random.randint(1, len(user_id))
        session['id_positions'] = sorted([p1, p2])

        return redirect(url_for('captcha_id_step2'))

    return _no_cache_response(render_template('captcha_id_step1.html'))

@app.route('/captcha-id/verify', methods=['GET', 'POST'])
def captcha_id_step2():
    user_id = session.get('user_id')
    pos = session.get('id_positions')

    if not user_id or not pos:
        flash("Primero ingresa tu identificación.", "danger")
        return redirect(url_for('captcha_id_step1'))

    if request.method == 'POST':
        d1 = _only_digits(request.form.get('digit1'))
        d2 = _only_digits(request.form.get('digit2'))

        if len(d1) != 1 or len(d2) != 1:
            flash("Debes ingresar un dígito en cada campo.", "danger")
            return redirect(url_for('captcha_id_step2'))

        ok = (d1 == user_id[pos[0]-1]) and (d2 == user_id[pos[1]-1])

        if ok:
            # Marca de sesión SOLO para la siguiente vista /bienvenido
            session['just_logged_in'] = True
            flash("Verificación por identificación completada. ¡Bienvenido!", "success")
            # (Opcional) limpiar datos sensibles
            session.pop('id_positions', None)
            # session.pop('user_id', None)  # si no lo necesitas después
            return redirect(url_for('bienvenido'))
        else:
            flash("Los dígitos no coinciden. Inténtalo de nuevo.", "danger")
            # Reasignar nuevas posiciones
            p1 = random.randint(1, len(user_id))
            p2 = random.randint(1, len(user_id))
            while p2 == p1:
                p2 = random.randint(1, len(user_id))
            session['id_positions'] = sorted([p1, p2])
            return redirect(url_for('captcha_id_step2'))

    return _no_cache_response(render_template('captcha_id_step2.html', positions=pos))













# -------------------------
# Bienvenido
# -------------------------
@app.route('/bienvenido')
def bienvenido():
    # Solo mostrar si viene de un login/captcha recién completado
    if session.get('just_logged_in'):
        # Consumir la bandera para que al volver atrás NO se muestre de nuevo
        session.pop('just_logged_in', None)
        return _no_cache_response(render_template('welcome.html'))
    # Si intenta llegar sin pasar por verificación, lo mandamos al menú
    flash("Por favor, inicia desde el menú.", "danger")
    return redirect(url_for('home'))

# -------------------------
# Arranque
# -------------------------
if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=8090)
