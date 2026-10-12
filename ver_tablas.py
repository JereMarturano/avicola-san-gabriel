import sqlite3

conn = sqlite3.connect('avicola.db')
c = conn.cursor()

print("========================================")
print("1. TABLAS EN LA BASE DE DATOS:")
print("========================================")
c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
for name, sql in c.fetchall():
    print(f"\n[TABLA: {name}]")
    print(sql)

print("\n========================================")
print("2. REGISTROS EN 'usuarios':")
print("========================================")
c.execute("SELECT id, username, nombre, rol, creado_en FROM usuarios")
for r in c.fetchall():
    print(f"ID: {r[0]} | Usuario: {r[1]} | Nombre: {r[2]} | Rol: {r[3]} | Creado: {r[4]}")

print("\n========================================")
print("3. REGISTROS EN 'stock':")
print("========================================")
c.execute("SELECT id, estado, color, calibre, cantidad_maples FROM stock")
for r in c.fetchall():
    cajones = round(r[4] / 12, 2)
    print(f"ID: {r[0]:2d} | Estado: {r[1]:15s} | Color: {r[2]:8s} | Calibre: {r[3]:14s} | Maples: {r[4]:3d} ({cajones} cajones)")

print("\n========================================")
print("4. REGISTROS EN 'movimientos':")
print("========================================")
c.execute("SELECT id, fecha_hora, usuario, tipo, color, calibre, cajones_input, maples_input, total_maples, detalle FROM movimientos")
movs = c.fetchall()
if not movs:
    print("(La tabla de movimientos no tiene registros aún)")
else:
    for r in movs:
        print(f"ID: {r[0]} | Fecha: {r[1]} | Op: {r[3]} | Por: {r[2]} | {r[4]} {r[5]} | Total Maples: {r[8]} | Detalle: {r[9]}")

conn.close()
