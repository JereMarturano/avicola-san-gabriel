import os
import sys
from werkzeug.security import generate_password_hash
from turso_db import get_db_client

def init_tables(safe_mode=True):
    """
    Inicializa las tablas y datos base.
    safe_mode=True (por defecto): crea tablas y registros faltantes SIN borrar datos existentes.
    safe_mode=False: requiere confirmacion explicita para resetear datos a cero.
    """
    turso_configured = bool(os.environ.get("TURSO_DATABASE_URL") and os.environ.get("TURSO_AUTH_TOKEN"))
    
    print("=" * 60)
    if turso_configured:
        print("[DESTINO] Turso Cloud DB (Produccion)")
        print(f"   URL: {os.environ.get('TURSO_DATABASE_URL')}")
    else:
        print("[DESTINO] SQLite Local (Desarrollo)")
        print("   Archivo: avicola.db")
    print("=" * 60)

    if not safe_mode:
        print("\n[ALERTA CRITICA] Se solicito MODO DE BORRADO COMPLETO (RESET)")
        print("Esta accion BORRARA permanentemente TODOS los movimientos, stock y usuarios.")
        confirm = os.environ.get("CONFIRM_RESET")
        if confirm != "CONFIRMAR_BORRADO_TOTAL":
            try:
                user_input = input("Para continuar escriba exactamente 'CONFIRMAR_BORRADO_TOTAL': ").strip()
            except EOFError:
                user_input = ""
            if user_input != "CONFIRMAR_BORRADO_TOTAL":
                print("[CANCELADO] Operacion cancelada. NO se modifico ni borro ningun dato.")
                return False

    db = get_db_client()
    cursor = db.cursor()

    print("[INFO] Verificando / creando esquemas de tablas...")

    # 1. Crear tabla usuarios
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            nombre TEXT NOT NULL,
            rol TEXT NOT NULL CHECK(rol IN ('Admin', 'Operario')),
            creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # 2. Crear tabla stock
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estado TEXT NOT NULL CHECK(estado IN ('por_seleccionar', 'seleccionado')),
            color TEXT NOT NULL CHECK(color IN ('Blanco', 'De Color')),
            calibre TEXT NOT NULL,
            cantidad_maples INTEGER NOT NULL DEFAULT 0 CHECK(cantidad_maples >= 0),
            UNIQUE(estado, color, calibre)
        );
    """)

    # 3. Crear tabla movimientos
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
        );
    """)

    if not safe_mode:
        print("[PELIGRO] Limpiando tablas existentes...")
        cursor.execute("DELETE FROM movimientos;")
        cursor.execute("DELETE FROM stock;")
        cursor.execute("DELETE FROM usuarios;")

    # Inicializar categorias de stock base (INSERT OR IGNORE protege los datos existentes)
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
            VALUES (?, ?, ?, 0);
        """, (estado, color, calibre))

    # Crear administrador inicial si no existe (contraseña tomada de ADMIN_PASSWORD)
    cursor.execute("SELECT id FROM usuarios WHERE username = 'admin'")
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if cursor.fetchone():
        print("[USUARIOS] Usuario 'admin' ya existente (no modificado).")
    elif len(admin_password) < 6:
        print("[USUARIOS] No se creo 'admin': defina ADMIN_PASSWORD (minimo 6 caracteres).")
    else:
        admin_pwd = generate_password_hash(admin_password)
        cursor.execute("""
            INSERT INTO usuarios (username, password_hash, nombre, rol)
            VALUES (?, ?, ?, ?);
        """, ("admin", admin_pwd, "Administrador Principal", "Admin"))
        print("[USUARIOS] Usuario 'admin' creado con la contrasena de ADMIN_PASSWORD.")

    if hasattr(db, "commit"):
        db.commit()

    if safe_mode:
        print("[EXITO] Base de datos inicializada de forma SEGURA. No se eliminaron datos existentes.")
    else:
        print("[AVISO] Base de datos reseteada a cero.")
    return True

if __name__ == "__main__":
    is_danger = "--danger-reset-all" in sys.argv
    init_tables(safe_mode=(not is_danger))
