import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, send_from_directory, abort, g
)
from werkzeug.security import generate_password_hash, check_password_hash

# ==============================================================================
# CONFIGURACIÓN & SEGURIDAD GENERAL
# ==============================================================================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    if os.environ.get("RENDER"):
        raise RuntimeError("Falta la variable de entorno SECRET_KEY en producción.")
    # Desarrollo local: clave aleatoria (las sesiones se cierran al reiniciar el servidor)
    app.secret_key = os.urandom(32)

# Cookies y Sesión Segura
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024  # Máx 2 MB para evitar ataques de carga
)

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "avicola.db"))

# Constantes del Dominio de Negocio (KISS)
MAPLES_POR_CAJON = 12
COLORES_VALIDOS = {'Blanco', 'De Color'}
CALIBRES_VALIDOS = {'Chico', 'Mediano', 'Grande', 'Especial'}
ROLES_VALIDOS = {'Admin', 'Operario'}
TIPOS_OPERACION = {'ingreso_galpon', 'clasificacion', 'venta', 'ajuste'}
ESTADOS_STOCK = {'por_seleccionar', 'seleccionado'}

# Todos los compartimentos de stock, en el orden en que se muestran en el conteo de inventario
COMPARTIMENTOS_STOCK = (
    [('por_seleccionar', color, 'Sin Clasificar') for color in ('Blanco', 'De Color')] +
    [('seleccionado', color, calibre) for color in ('Blanco', 'De Color')
     for calibre in ('Chico', 'Mediano', 'Grande', 'Especial')]
)

# Nombres que usa la granja (en la base siguen siendo por_seleccionar / seleccionado)
NOMBRE_ESTADO = {'por_seleccionar': 'Sin hacer', 'seleccionado': 'Hecho'}
NOMBRE_TIPO_MOVIMIENTO = {
    'Ingreso Galpón': 'Ingreso al galpón',
    'Clasificación': 'Clasificación',
    'Venta / Despacho': 'Despacho',
    'Ajuste Stock': 'Ajuste de inventario',
}

# La base guarda las fechas en UTC (CURRENT_TIMESTAMP); Argentina es UTC-3 todo el año
OFFSET_ARGENTINA = '-3 hours'

from turso_db import get_db_client

# ==============================================================================
# CAPA DE ACCESO A DATOS (PERSISTENCIA TURSO CLOUD / SQLITE)
# ==============================================================================
def get_db():
    """Retorna cliente de base de datos Turso Cloud o SQLite local según configuración."""
    return get_db_client()

def init_db():
    """Inicializa esquemas, índices y datos base (definidos solo en init_turso.py)."""
    from init_turso import init_tables
    init_tables(safe_mode=True)

# ==============================================================================
# SEGURIDAD HTTP & ENCABEZADOS (CABECERAS ANTI-CLICKJACKING Y XSS)
# ==============================================================================
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# ==============================================================================
# DECORADORES Y AUTENTICACIÓN
# ==============================================================================
def sesion_valida():
    """
    Confirma que el usuario de la sesión sigue existiendo y refresca su rol desde la base,
    para que un usuario eliminado o degradado pierda el acceso de inmediato.
    """
    if 'user_id' not in session:
        return False
    if 'usuario_verificado' not in g:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username, nombre, rol FROM usuarios WHERE id = ?", (session['user_id'],))
            user = cursor.fetchone()
        if not user:
            session.clear()
            g.usuario_verificado = False
        else:
            session['username'] = user['username']
            session['user_nombre'] = user['nombre']
            session['user_role'] = user['rol']
            g.usuario_verificado = True
    return g.usuario_verificado

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not sesion_valida():
            flash("Por favor inicia sesión para continuar", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not sesion_valida():
            return redirect(url_for('login'))
        if session.get('user_role') != 'Admin':
            flash("Acceso restringido a Administradores.", "danger")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# ==============================================================================
# SERVICIOS DE DOMINIO Y VALIDACIÓN (SOLID: Single Responsibility)
# ==============================================================================
class StockService:
    @staticmethod
    def calcular_maples_totales(cajones_raw, maples_raw):
        """Convierte cajones y maples sueltos al total entero de maples validado."""
        try:
            c = float(cajones_raw or 0)
            m = float(maples_raw or 0)
        except (ValueError, TypeError):
            return None
        
        if c < 0 or m < 0:
            return None
        # Limitar a número razonable para evitar overflow
        if c > 100000 or m > 1000000:
            return None
            
        return int(round(c * MAPLES_POR_CAJON + m))

    @staticmethod
    def formatear(total_maples):
        """Devuelve diccionario enriquecido para la vista."""
        total_maples = max(0, int(total_maples or 0))
        cajones_decimal = round(total_maples / MAPLES_POR_CAJON, 2)
        cajones_enteros = total_maples // MAPLES_POR_CAJON
        maples_resto = total_maples % MAPLES_POR_CAJON
        
        if maples_resto == 0:
            detalle_texto = f"{cajones_enteros} caj."
        elif cajones_enteros == 0:
            detalle_texto = f"{maples_resto} map."
        else:
            detalle_texto = f"{cajones_enteros} caj. + {maples_resto} map."

        return {
            'total_maples': total_maples,
            'cajones_decimal': cajones_decimal,
            'cajones_enteros': cajones_enteros,
            'maples_resto': maples_resto,
            'detalle_texto': detalle_texto,
            'display_full': f"{cajones_decimal:g} Cajones ({total_maples} Maples)"
        }

    @classmethod
    def obtener_resumen_completo(cls):
        """Consulta eficiente única para abastecer a la UI (cacheada por request)."""
        if 'resumen_stock' not in g:
            g.resumen_stock = cls._consultar_resumen()
        return g.resumen_stock

    @classmethod
    def _consultar_resumen(cls):
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT estado, color, calibre, cantidad_maples FROM stock ORDER BY estado, color, calibre")
            rows = cursor.fetchall()
            
            por_seleccionar = {}
            seleccionado = {'Blanco': {}, 'De Color': {}}
            tot_por_sel = 0
            tot_sel = 0
            
            for r in rows:
                cant = r['cantidad_maples']
                info = cls.formatear(cant)
                if r['estado'] == 'por_seleccionar':
                    por_seleccionar[r['color']] = info
                    tot_por_sel += cant
                else:
                    seleccionado[r['color']][r['calibre']] = info
                    tot_sel += cant
                    
            resumen = {
                'total_seleccionado': cls.formatear(tot_sel),
                'total_por_seleccionar': cls.formatear(tot_por_sel),
                'total_general': cls.formatear(tot_sel + tot_por_sel)
            }
            return por_seleccionar, seleccionado, resumen

@app.template_filter('hora_local')
def hora_local(fecha_utc, formato='%d/%m %H:%M'):
    """Convierte un timestamp UTC de la base ('YYYY-MM-DD HH:MM:SS') a hora de Argentina."""
    try:
        dt = datetime.strptime(str(fecha_utc)[:19], '%Y-%m-%d %H:%M:%S') - timedelta(hours=3)
    except ValueError:
        return fecha_utc
    return dt.strftime(formato)

@app.template_filter('cant')
def cantidad_texto(total_maples):
    """Texto legible de una cantidad en maples: '18 caj. + 10 map.' (sin signo)."""
    return StockService.formatear(abs(int(total_maples or 0)))['detalle_texto']

@app.template_filter('dia_local')
def dia_local(fecha_utc):
    """Etiqueta del día (hora Argentina) para agrupar el historial: 'Hoy', 'Ayer' o 'Lun 12/10'."""
    try:
        dia = (datetime.strptime(str(fecha_utc)[:19], '%Y-%m-%d %H:%M:%S') - timedelta(hours=3)).date()
    except ValueError:
        return ''
    hoy = (datetime.now(timezone.utc) - timedelta(hours=3)).date()
    if dia == hoy:
        return 'Hoy'
    if dia == hoy - timedelta(days=1):
        return 'Ayer'
    return f"{['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'][dia.weekday()]} {dia.strftime('%d/%m')}"

@app.template_filter('nombre_tipo')
def nombre_tipo(tipo):
    return NOMBRE_TIPO_MOVIMIENTO.get(tipo, tipo)

@app.template_filter('nota_usuario')
def nota_usuario(detalle):
    """
    Extrae del 'detalle' guardado solo la parte útil para mostrar: la nota que escribió el usuario
    (y en los ajustes, el 'De X a Y maples'). El resto repite datos que ya se ven en la tarjeta.
    """
    detalle = (detalle or '').strip()
    if detalle.startswith('Venta/Despacho:'):
        return detalle.split('Cliente/Nota:', 1)[1].strip() if 'Cliente/Nota:' in detalle else ''
    if detalle.startswith('Ajuste inventario') or detalle.startswith('Conteo de inventario'):
        return detalle.split('). ', 1)[1].strip() if '). ' in detalle else ''
    return detalle.split('. ', 1)[1].strip() if '. ' in detalle else ''

# Contexto global inyectado a las plantillas
@app.context_processor
def inject_stock():
    if 'user_id' not in session:
        return {}
    por_sel, sel, res = StockService.obtener_resumen_completo()
    return {
        'global_por_seleccionar': por_sel,
        'global_seleccionado': sel,
        'global_resumen': res,
        # Maples disponibles por compartimento, para validar en el formulario antes de enviar
        'stock_js': {
            'sin_hacer': {color: info['total_maples'] for color, info in por_sel.items()},
            'hecho': {color: {cal: info['total_maples'] for cal, info in calibres.items()}
                      for color, calibres in sel.items()},
        },
    }

# ==============================================================================
# RUTAS DE AUTENTICACIÓN
# ==============================================================================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '').strip()
        
        if not username or not password:
            flash("Por favor completa tu usuario y contraseña.", "warning")
            return render_template('login.html')
            
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM usuarios WHERE LOWER(username) = ?", (username,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user['password_hash'], password):
                session.permanent = True
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['user_nombre'] = user['nombre']
                session['user_role'] = user['rol']
                flash(f"¡Bienvenido, {user['nombre']}!", "success")
                return redirect(url_for('index'))
            else:
                flash("Usuario o contraseña incorrectos", "danger")
                
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash("Has cerrado sesión correctamente", "info")
    return redirect(url_for('login'))

# ==============================================================================
# DASHBOARD DE STOCK
# ==============================================================================
@app.route('/')
@login_required
def index():
    por_seleccionar, seleccionado, resumen = StockService.obtener_resumen_completo()
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movimientos ORDER BY fecha_hora DESC LIMIT 5")
        ultimos_movimientos = cursor.fetchall()

    return render_template('index.html',
                           resumen=resumen,
                           por_seleccionar=por_seleccionar,
                           seleccionado=seleccionado,
                           ultimos_movimientos=ultimos_movimientos)

# ==============================================================================
# REGISTRO TRANSACCIONAL DE OPERACIONES (ACID SEGURO)
# ==============================================================================
@app.route('/operacion', methods=['POST'])
@login_required
def registrar_operacion():
    tipo = request.form.get('tipo', '').strip()
    color = request.form.get('color', '').strip()
    calibre = request.form.get('calibre', '').strip()
    cajones_raw = request.form.get('cajones', '0')
    maples_raw = request.form.get('maples', '0')
    nota = request.form.get('nota', '').strip()[:200]  # Sanitización de longitud

    # 1. Validaciones de Dominio y Tipos
    if tipo not in TIPOS_OPERACION:
        flash("Tipo de operación no reconocido.", "danger")
        return redirect(url_for('index'))

    if color not in COLORES_VALIDOS:
        flash("Color de huevo inválido.", "danger")
        return redirect(url_for('index'))

    if tipo in {'clasificacion', 'venta'} and calibre not in CALIBRES_VALIDOS:
        flash("Debes seleccionar un calibre válido (Chico, Mediano, Grande, Especial).", "danger")
        return redirect(url_for('index'))

    total_maples = StockService.calcular_maples_totales(cajones_raw, maples_raw)
    if total_maples is None or (total_maples <= 0 and tipo != 'ajuste'):
        flash("La cantidad ingresada debe ser un número positivo válido.", "danger")
        return redirect(url_for('index'))

    usuario = session.get('user_nombre', 'Operario')
    c_val = float(cajones_raw or 0)
    m_val = float(maples_raw or 0)

    # 2. Ejecución Atómica en Base de Datos (Transacción ACID)
    with get_db() as conn:
        cursor = conn.cursor()
        try:
            if tipo == 'ingreso_galpon':
                cursor.execute("""
                    UPDATE stock 
                    SET cantidad_maples = cantidad_maples + ?
                    WHERE estado = 'por_seleccionar' AND color = ? AND calibre = 'Sin Clasificar'
                """, (total_maples, color))
                
                detalle = f"Ingreso bruto galpón: {color}. {nota}".strip()
                cursor.execute("""
                    INSERT INTO movimientos (usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle)
                    VALUES (?, 'Ingreso Galpón', ?, 'Sin Clasificar', ?, ?, ?, ?)
                """, (usuario, color, c_val, m_val, total_maples, detalle))
                flash(f"Ingreso registrado: {cantidad_texto(total_maples)} de {color}, quedan como sin hacer.", "success")
                
            elif tipo == 'clasificacion':
                # Verificar stock disponible en galpón
                cursor.execute("""
                    SELECT cantidad_maples FROM stock 
                    WHERE estado = 'por_seleccionar' AND color = ? AND calibre = 'Sin Clasificar'
                """, (color,))
                disp_row = cursor.fetchone()
                disponible = disp_row['cantidad_maples'] if disp_row else 0
                
                if disponible < total_maples:
                    flash(f"No alcanza: hay {cantidad_texto(disponible)} de {color} sin hacer.", "danger")
                    return redirect(url_for('index'))
                    
                # Descontar de galpón y sumar a seleccionado
                cursor.execute("""
                    UPDATE stock 
                    SET cantidad_maples = cantidad_maples - ?
                    WHERE estado = 'por_seleccionar' AND color = ? AND calibre = 'Sin Clasificar'
                """, (total_maples, color))
                
                cursor.execute("""
                    UPDATE stock 
                    SET cantidad_maples = cantidad_maples + ?
                    WHERE estado = 'seleccionado' AND color = ? AND calibre = ?
                """, (total_maples, color, calibre))
                
                detalle = f"Clasificado de galpón a seleccionado: {color} {calibre}. {nota}".strip()
                cursor.execute("""
                    INSERT INTO movimientos (usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle)
                    VALUES (?, 'Clasificación', ?, ?, ?, ?, ?, ?)
                """, (usuario, color, calibre, c_val, m_val, total_maples, detalle))
                flash(f"Clasificación registrada: {cantidad_texto(total_maples)} de {color} pasaron a hecho ({calibre}).", "success")
                
            elif tipo == 'venta':
                cursor.execute("""
                    SELECT cantidad_maples FROM stock 
                    WHERE estado = 'seleccionado' AND color = ? AND calibre = ?
                """, (color, calibre))
                disp_row = cursor.fetchone()
                disponible = disp_row['cantidad_maples'] if disp_row else 0
                
                if disponible < total_maples:
                    flash(f"No alcanza: hay {cantidad_texto(disponible)} de {color} {calibre} hecho.", "danger")
                    return redirect(url_for('index'))
                    
                cursor.execute("""
                    UPDATE stock 
                    SET cantidad_maples = cantidad_maples - ?
                    WHERE estado = 'seleccionado' AND color = ? AND calibre = ?
                """, (total_maples, color, calibre))
                
                detalle = f"Venta/Despacho: {color} {calibre}. Cliente/Nota: {nota}".strip()
                cursor.execute("""
                    INSERT INTO movimientos (usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle)
                    VALUES (?, 'Venta / Despacho', ?, ?, ?, ?, ?, ?)
                """, (usuario, color, calibre, c_val, m_val, -total_maples, detalle))
                flash(f"Despacho registrado: {cantidad_texto(total_maples)} de {color} {calibre}.", "success")
                
            elif tipo == 'ajuste':
                estado_ajuste = request.form.get('estado_ajuste', 'seleccionado')
                if estado_ajuste not in ESTADOS_STOCK or (estado_ajuste == 'seleccionado' and calibre not in CALIBRES_VALIDOS):
                    flash("Estado o calibre de ajuste inválido.", "danger")
                    return redirect(url_for('index'))
                calibre_ajuste = calibre if estado_ajuste == 'seleccionado' else 'Sin Clasificar'
                nuevo_total = max(0, total_maples)
                
                cursor.execute("""
                    SELECT cantidad_maples FROM stock 
                    WHERE estado = ? AND color = ? AND calibre = ?
                """, (estado_ajuste, color, calibre_ajuste))
                ant_row = cursor.fetchone()
                anterior = ant_row['cantidad_maples'] if ant_row else 0
                diferencia = nuevo_total - anterior
                
                cursor.execute("""
                    UPDATE stock 
                    SET cantidad_maples = ?
                    WHERE estado = ? AND color = ? AND calibre = ?
                """, (nuevo_total, estado_ajuste, color, calibre_ajuste))
                
                detalle = f"Ajuste inventario {estado_ajuste} ({color} {calibre_ajuste}). De {anterior} a {nuevo_total} maples. {nota}".strip()
                cursor.execute("""
                    INSERT INTO movimientos (usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle)
                    VALUES (?, 'Ajuste Stock', ?, ?, ?, ?, ?, ?)
                """, (usuario, color, calibre_ajuste, c_val, m_val, diferencia, detalle))
                flash(f"Stock ajustado a {cantidad_texto(nuevo_total)}.", "info")

            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            flash(f"Error al procesar la operación en base de datos: {str(e)}", "danger")
            
    return redirect(url_for('index'))

# ==============================================================================
# HISTORIAL DE MOVIMIENTOS
# ==============================================================================
@app.route('/historial')
@login_required
def historial():
    filtro = request.args.get('filtro', 'hoy')
    tipo_filtro = request.args.get('tipo', '').strip()
    
    with get_db() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM movimientos WHERE 1=1"
        params = []
        
        if filtro == 'hoy':
            query += " AND DATE(fecha_hora, ?) = DATE('now', ?)"
            params += [OFFSET_ARGENTINA, OFFSET_ARGENTINA]
        elif filtro == 'semana':
            query += " AND DATE(fecha_hora, ?) >= DATE('now', ?, '-7 days')"
            params += [OFFSET_ARGENTINA, OFFSET_ARGENTINA]
            
        if tipo_filtro:
            query += " AND tipo = ?"
            params.append(tipo_filtro)
            
        query += " ORDER BY fecha_hora DESC LIMIT 150"
        cursor.execute(query, params)
        movimientos = cursor.fetchall()
        
    return render_template('historial.html', movimientos=movimientos, filtro=filtro, tipo_filtro=tipo_filtro)

# ==============================================================================
# GESTIÓN SEGURA DE USUARIOS (SOLO ADMIN)
# ==============================================================================
def validar_formato_usuario(username):
    """Valida formato de usuario alfanumérico seguro."""
    return bool(re.match(r'^[a-zA-Z0-9_.-]{3,30}$', username))

@app.route('/usuarios', methods=['GET', 'POST'])
@admin_required
def usuarios():
    with get_db() as conn:
        cursor = conn.cursor()
        
        if request.method == 'POST':
            accion = request.form.get('accion')
            if accion in ('editar', 'eliminar') and not request.form.get('user_id', '').isdigit():
                flash("Usuario inválido.", "danger")
                return redirect(url_for('usuarios'))
            
            if accion == 'crear':
                username = request.form.get('username', '').strip().lower()
                nombre = request.form.get('nombre', '').strip()[:50]
                password = request.form.get('password', '').strip()
                password_confirm = request.form.get('password_confirm', '').strip()
                rol = request.form.get('rol', 'Operario')
                
                if not username or not password or not nombre:
                    flash("Todos los campos son obligatorios.", "danger")
                elif not validar_formato_usuario(username):
                    flash("El nombre de usuario debe tener entre 3 y 30 caracteres (letras, números o guiones).", "warning")
                elif len(password) < 6:
                    flash("La contraseña debe tener al menos 6 caracteres.", "warning")
                elif password != password_confirm:
                    flash("Las contraseñas no coinciden. Por favor verifícalas.", "danger")
                elif rol not in ROLES_VALIDOS:
                    flash("Rol inválido.", "danger")
                else:
                    try:
                        cursor.execute("""
                            INSERT INTO usuarios (username, password_hash, nombre, rol)
                            VALUES (?, ?, ?, ?)
                        """, (username, generate_password_hash(password), nombre, rol))
                        conn.commit()
                        flash(f"Usuario '{username}' creado exitosamente.", "success")
                    except sqlite3.IntegrityError:
                        flash(f"El nombre de usuario '{username}' ya existe.", "danger")
                        
            elif accion == 'editar':
                user_id = request.form.get('user_id')
                username = request.form.get('username', '').strip().lower()
                nombre = request.form.get('nombre', '').strip()[:50]
                rol = request.form.get('rol', 'Operario')
                password = request.form.get('password', '').strip()
                password_confirm = request.form.get('password_confirm', '').strip()
                
                if not user_id or not username or not nombre:
                    flash("El nombre y usuario no pueden estar vacíos.", "danger")
                elif not validar_formato_usuario(username):
                    flash("Formato de usuario no válido.", "warning")
                elif rol not in ROLES_VALIDOS:
                    flash("Rol inválido.", "danger")
                else:
                    try:
                        if password:
                            if len(password) < 6:
                                flash("La nueva contraseña debe tener al menos 6 caracteres.", "warning")
                            elif password != password_confirm:
                                flash("Las contraseñas no coinciden.", "danger")
                            else:
                                cursor.execute("""
                                    UPDATE usuarios 
                                    SET username = ?, nombre = ?, rol = ?, password_hash = ?
                                    WHERE id = ?
                                """, (username, nombre, rol, generate_password_hash(password), user_id))
                                conn.commit()
                                flash(f"Usuario '{username}' y contraseña actualizados correctamente.", "success")
                                if int(user_id) == session.get('user_id'):
                                    session['username'] = username
                                    session['user_nombre'] = nombre
                                    session['user_role'] = rol
                        else:
                            cursor.execute("""
                                UPDATE usuarios 
                                SET username = ?, nombre = ?, rol = ?
                                WHERE id = ?
                            """, (username, nombre, rol, user_id))
                            conn.commit()
                            flash(f"Datos de '{username}' actualizados correctamente.", "success")
                            if int(user_id) == session.get('user_id'):
                                session['username'] = username
                                session['user_nombre'] = nombre
                                session['user_role'] = rol
                    except sqlite3.IntegrityError:
                        flash(f"El nombre de usuario '{username}' ya está en uso.", "danger")

            elif accion == 'eliminar':
                user_id = request.form.get('user_id')
                if int(user_id) == session.get('user_id'):
                    flash("No puedes eliminar tu propia cuenta en uso.", "danger")
                else:
                    cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
                    conn.commit()
                    flash("Usuario eliminado correctamente.", "info")
                    
        cursor.execute("SELECT id, username, nombre, rol, creado_en FROM usuarios ORDER BY id ASC")
        lista_usuarios = cursor.fetchall()
        
    return render_template('usuarios.html', usuarios=lista_usuarios)

# ==============================================================================
# CONTEO DE INVENTARIO (fija el stock real contado en la granja)
# ==============================================================================
@app.route('/inventario', methods=['GET', 'POST'])
@admin_required
def inventario():
    """
    Permite cargar lo que hay realmente en cada compartimento (sin hacer / hecho por calibre).
    Cada diferencia queda registrada como 'Ajuste Stock' en el historial, todo en una transacción.
    Si el stock cambió desde que se abrió el formulario, no se pisa: se pide revisar de nuevo.
    """
    if request.method == 'POST':
        nota = request.form.get('nota', '').strip()[:200]
        usuario = session.get('user_nombre', 'Admin')

        cambios = []
        for i, (estado, color, calibre) in enumerate(COMPARTIMENTOS_STOCK):
            contado = StockService.calcular_maples_totales(
                request.form.get(f'caj_{i}', '0'), request.form.get(f'map_{i}', '0'))
            original = request.form.get(f'orig_{i}', '')
            if contado is None or not original.isdigit():
                flash("Hay cantidades inválidas en el conteo. Revisá los valores.", "danger")
                return redirect(url_for('inventario'))
            if contado != int(original):
                cambios.append((estado, color, calibre, int(original), contado))

        if not cambios:
            flash("No hubo cambios: el conteo coincide con el stock actual.", "info")
            return redirect(url_for('index'))

        with get_db() as conn:
            cursor = conn.cursor()
            try:
                for estado, color, calibre, original, contado in cambios:
                    # Solo actualiza si el valor sigue siendo el que vio el usuario (evita pisar movimientos)
                    cursor.execute("""
                        UPDATE stock SET cantidad_maples = ?
                        WHERE estado = ? AND color = ? AND calibre = ? AND cantidad_maples = ?
                    """, (contado, estado, color, calibre, original))
                    if cursor.rowcount != 1:
                        conn.rollback()
                        flash("El stock cambió mientras hacías el conteo (alguien registró un movimiento). "
                              "Revisá los valores actualizados y volvé a guardar.", "warning")
                        return redirect(url_for('inventario'))

                    lugar = f"{NOMBRE_ESTADO[estado]} {color}" + (f" {calibre}" if estado == 'seleccionado' else '')
                    detalle = (f"Conteo de inventario ({lugar}). De {cantidad_texto(original)} "
                               f"a {cantidad_texto(contado)}. {nota}").strip()
                    cursor.execute("""
                        INSERT INTO movimientos (usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle)
                        VALUES (?, 'Ajuste Stock', ?, ?, ?, ?, ?, ?)
                    """, (usuario, color, calibre, contado // MAPLES_POR_CAJON, contado % MAPLES_POR_CAJON,
                          contado - original, detalle))
                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                flash(f"No se pudo guardar el conteo: {e}", "danger")
                return redirect(url_for('inventario'))

        flash(f"Conteo guardado: {len(cambios)} {'cambio registrado' if len(cambios) == 1 else 'cambios registrados'} en el historial.", "success")
        return redirect(url_for('index'))

    por_seleccionar, seleccionado, resumen = StockService.obtener_resumen_completo()
    compartimentos = []
    for i, (estado, color, calibre) in enumerate(COMPARTIMENTOS_STOCK):
        info = por_seleccionar[color] if estado == 'por_seleccionar' else seleccionado[color][calibre]
        compartimentos.append({'i': i, 'estado': estado, 'color': color, 'calibre': calibre, 'info': info})
    return render_template('inventario.html', compartimentos=compartimentos, resumen=resumen)

# ==============================================================================
# ACTIVOS PWA & MANIFEST
# ==============================================================================
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@app.route('/sw.js')
def service_worker():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

# Endpoint liviano para monitores externos (evita que Render apague la app por inactividad)
@app.route('/health')
def health():
    return "ok", 200

# ==============================================================================
# INICIO DE LA APLICACIÓN
# ==============================================================================
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
