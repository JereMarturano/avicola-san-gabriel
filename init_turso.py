from turso_db import get_db_client
from werkzeug.security import generate_password_hash

def init_turso_fresh():
    db = get_db_client()
    cursor = db.cursor()

    print("Inicializando tablas en Turso...")

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

    # Poner TODOS los movimientos en 0 (limpiar si hubiera)
    cursor.execute("DELETE FROM movimientos;")

    # Resetear o inicializar stock en 0
    cursor.execute("DELETE FROM stock;")
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

    # Limpiar usuarios y crear admin en blanco inicial
    cursor.execute("DELETE FROM usuarios;")
    admin_pwd = generate_password_hash("admin")
    cursor.execute("""
        INSERT INTO usuarios (username, password_hash, nombre, rol)
        VALUES (?, ?, ?, ?);
    """, ("admin", admin_pwd, "Administrador Principal", "Admin"))

    print("¡Turso inicializado con éxito! Todos los stocks y movimientos están en 0.")

if __name__ == "__main__":
    init_turso_fresh()
