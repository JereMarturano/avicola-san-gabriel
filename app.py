import os
import re
import sqlite3
from datetime import datetime, timedelta
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
app.secret_key = os.environ.get("SECRET_KEY", "avicola-san-gabriel-sec-key-2026-xyz789")

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

from turso_db import get_db_client

# ==============================================================================
# CAPA DE ACCESO A DATOS (PERSISTENCIA TURSO CLOUD / SQLITE)
# ==============================================================================
def get_db():
    """Retorna cliente de base de datos Turso Cloud o SQLite local según configuración."""
    return get_db_client()

def init_db():
    """Inicializa esquemas e índices optimizados."""
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Tabla de usuarios
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                nombre TEXT NOT NULL,
                rol TEXT NOT NULL CHECK(rol IN ('Admin', 'Operario')),
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Tabla de saldos de stock
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                estado TEXT NOT NULL CHECK(estado IN ('por_seleccionar', 'seleccionado')),
                color TEXT NOT NULL CHECK(color IN ('Blanco', 'De Color')),
                calibre TEXT NOT NULL,
                cantidad_maples INTEGER NOT NULL DEFAULT 0 CHECK(cantidad_maples >= 0),
                UNIQUE(estado, color, calibre)
            )
        """)
        
        # Tabla de historial de movimientos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                usuario TEXT NOT NULL,
                tipo TEXT NOT NULL,
                color TEXT NOT NULL,
                calibre TEXT,
                cajones_input REAL NOT NULL,
                maples_input REAL NOT NULL,
                total_maples INTEGER NOT NULL,
                detalle TEXT
            )
        """)

        # Índices para consultas ultra rápidas (< 1ms)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fecha ON movimientos(fecha_hora DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_tipo ON movimientos(tipo);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_stock_consulta ON stock(estado, color, calibre);")
        
        # Usuario administrador predeterminado si no existe
        cursor.execute("SELECT id FROM usuarios WHERE username = 'admin'")
        if not cursor.fetchone():
            admin_pwd = generate_password_hash("admin")
            cursor.execute("""
                INSERT INTO usuarios (username, password_hash, nombre, rol)
                VALUES (?, ?, ?, ?)
            """, ("admin", admin_pwd, "Administrador Principal", "Admin"))
            
        # Inicializar categorías de stock base
        estados_iniciales = [
            ('por_seleccionar', 'Blanco', 'Sin Clasificar'),
            ('por_seleccionar', 'De Color', 'Sin Clasificar'),
            ('seleccionado', 'Blanco', 'Chico'),
            ('seleccionado', 'Blanco', 'Mediano'),
            ('seleccionado', 'Blanco', 'Grande'),
            ('seleccionado', 'Blanco', 'Especial'),
            ('seleccionado', 'De Color', 'Chico'),
            ('seleccionado', 'De Color', 'Mediano'),
            ('seleccionado', 'De Color', 'Grande'),
            ('seleccionado', 'De Color', 'Especial')
        ]
        for estado, color, calibre in estados_iniciales:
            cursor.execute("""
                INSERT OR IGNORE INTO stock (estado, color, calibre, cantidad_maples)
                VALUES (?, ?, ?, 0)
            """, (estado, color, calibre))
            
        conn.commit()

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
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Por favor inicia sesión para continuar", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
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

# Contexto global inyectado a las plantillas
@app.context_processor
def inject_stock():
    if 'user_id' not in session:
        return {}
    por_sel, sel, res = StockService.obtener_resumen_completo()
    return {
        'global_por_seleccionar': por_sel,
        'global_seleccionado': sel,
        'global_resumen': res
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

@app.route('/logout')
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
                flash(f"✅ Ingreso registrado: {total_maples} maples ({color}) a 'Por Seleccionar'.", "success")
                
            elif tipo == 'clasificacion':
                # Verificar stock disponible en galpón
                cursor.execute("""
                    SELECT cantidad_maples FROM stock 
                    WHERE estado = 'por_seleccionar' AND color = ? AND calibre = 'Sin Clasificar'
                """, (color,))
                disp_row = cursor.fetchone()
                disponible = disp_row['cantidad_maples'] if disp_row else 0
                
                if disponible < total_maples:
                    flash(f"⚠️ Stock insuficiente en galpón. Hay {disponible} maples disponibles de {color}.", "danger")
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
                flash(f"✅ Clasificación lista: {total_maples} maples pasados a {color} {calibre}.", "success")
                
            elif tipo == 'venta':
                cursor.execute("""
                    SELECT cantidad_maples FROM stock 
                    WHERE estado = 'seleccionado' AND color = ? AND calibre = ?
                """, (color, calibre))
                disp_row = cursor.fetchone()
                disponible = disp_row['cantidad_maples'] if disp_row else 0
                
                if disponible < total_maples:
                    flash(f"⚠️ Stock insuficiente para venta. Solo hay {disponible} maples disponibles de {color} {calibre}.", "danger")
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
                flash(f"🚚 Despacho registrado: {total_maples} maples de {color} {calibre}.", "success")
                
            elif tipo == 'ajuste':
                estado_ajuste = request.form.get('estado_ajuste', 'seleccionado')
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
                flash(f"⚙️ Stock ajustado a {nuevo_total} maples.", "info")

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
            query += " AND DATE(fecha_hora, 'localtime') = DATE('now', 'localtime')"
        elif filtro == 'semana':
            query += " AND DATE(fecha_hora, 'localtime') >= DATE('now', '-7 days', 'localtime')"
            
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
