"""
Tests de la app con una base SQLite temporal.
Ejecutar desde la raíz del proyecto:  python -m unittest discover tests
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

# Forzar SQLite local: los tests NUNCA deben conectarse a Turso (aunque exista un .env)
os.environ["TURSO_DATABASE_URL"] = ""
os.environ["TURSO_AUTH_TOKEN"] = ""
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ.pop("RENDER", None)
_tmpdir = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_tmpdir, "test.db")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as app_module  # noqa: E402
from turso_db import _ClosingConnection  # noqa: E402


def db():
    conn = sqlite3.connect(os.environ["DB_PATH"], factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn


def stock(estado, color, calibre):
    with db() as conn:
        return conn.execute(
            "SELECT cantidad_maples FROM stock WHERE estado = ? AND color = ? AND calibre = ?",
            (estado, color, calibre)).fetchone()[0]


def cantidad_movimientos():
    with db() as conn:
        return conn.execute("SELECT COUNT(*) FROM movimientos").fetchone()[0]


class BaseTest(unittest.TestCase):
    def setUp(self):
        # Base nueva por test (en Windows no se puede borrar un .db con conexiones abiertas)
        os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db", dir=_tmpdir)
        app_module.init_db()
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def login(self, username="admin", password="admin123"):
        return self.client.post("/login", data={"username": username, "password": password})

    def operar(self, **datos):
        return self.client.post("/operacion", data=datos)


class TestOperacionesStock(BaseTest):
    def setUp(self):
        super().setUp()
        self.login()

    def test_ingreso_suma_al_galpon_y_registra_movimiento(self):
        self.operar(tipo="ingreso_galpon", color="Blanco", cajones="2", maples="3")
        self.assertEqual(stock("por_seleccionar", "Blanco", "Sin Clasificar"), 27)
        self.assertEqual(cantidad_movimientos(), 1)

    def test_clasificacion_mueve_stock(self):
        self.operar(tipo="ingreso_galpon", color="Blanco", cajones="2", maples="0")
        self.operar(tipo="clasificacion", color="Blanco", calibre="Grande", cajones="1", maples="0")
        self.assertEqual(stock("por_seleccionar", "Blanco", "Sin Clasificar"), 12)
        self.assertEqual(stock("seleccionado", "Blanco", "Grande"), 12)

    def test_clasificacion_sin_stock_suficiente_no_cambia_nada(self):
        self.operar(tipo="ingreso_galpon", color="Blanco", cajones="0", maples="5")
        self.operar(tipo="clasificacion", color="Blanco", calibre="Grande", cajones="1", maples="0")
        self.assertEqual(stock("por_seleccionar", "Blanco", "Sin Clasificar"), 5)
        self.assertEqual(stock("seleccionado", "Blanco", "Grande"), 0)
        self.assertEqual(cantidad_movimientos(), 1)

    def test_venta_descuenta_y_no_permite_vender_de_mas(self):
        self.operar(tipo="ingreso_galpon", color="De Color", cajones="1", maples="0")
        self.operar(tipo="clasificacion", color="De Color", calibre="Chico", cajones="1", maples="0")
        self.operar(tipo="venta", color="De Color", calibre="Chico", cajones="0", maples="5")
        self.assertEqual(stock("seleccionado", "De Color", "Chico"), 7)
        self.operar(tipo="venta", color="De Color", calibre="Chico", cajones="1", maples="0")
        self.assertEqual(stock("seleccionado", "De Color", "Chico"), 7)

    def test_ajuste_con_estado_invalido_no_registra_movimiento(self):
        self.operar(tipo="ajuste", color="Blanco", calibre="Chico", estado_ajuste="cualquiera", cajones="1", maples="0")
        self.assertEqual(cantidad_movimientos(), 0)

    def test_ajuste_valido_fija_el_stock(self):
        self.operar(tipo="ajuste", color="Blanco", calibre="Mediano", cajones="5", maples="0")
        self.assertEqual(stock("seleccionado", "Blanco", "Mediano"), 60)
        self.assertEqual(cantidad_movimientos(), 1)


class TestHistorialHoraArgentina(BaseTest):
    def test_filtro_hoy_usa_hora_argentina(self):
        self.login()
        hoy_ar = (datetime.now(timezone.utc) - timedelta(hours=3)).date()
        # 22:00 de ayer en Argentina = 01:00 UTC de hoy -> NO es de "hoy"
        ayer_noche_utc = datetime.combine(hoy_ar, datetime.min.time()) + timedelta(hours=1)
        # 22:00 de hoy en Argentina = 01:00 UTC de mañana -> SÍ es de "hoy"
        hoy_noche_utc = ayer_noche_utc + timedelta(days=1)
        with db() as conn:
            for fecha, nota in ((ayer_noche_utc, "Ingreso bruto galpón: Blanco. MOV_AYER"), (hoy_noche_utc, "Ingreso bruto galpón: Blanco. MOV_HOY")):
                conn.execute("""
                    INSERT INTO movimientos (fecha_hora, usuario, tipo, color, cajones_input, maples_input, total_maples, detalle)
                    VALUES (?, 'test', 'Ingreso Galpón', 'Blanco', 0, 1, 1, ?)
                """, (fecha.strftime("%Y-%m-%d %H:%M:%S"), nota))
        html = self.client.get("/historial?filtro=hoy").get_data(as_text=True)
        self.assertIn("MOV_HOY", html)
        self.assertNotIn("MOV_AYER", html)

    def test_filtro_hora_local(self):
        self.assertEqual(app_module.hora_local("2026-10-13 01:30:00", "%d/%m %H:%M"), "12/10 22:30")


class TestSesionYUsuarios(BaseTest):
    def crear_usuario(self, username, rol):
        from werkzeug.security import generate_password_hash
        with db() as conn:
            conn.execute("INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (?, ?, ?, ?)",
                         (username, generate_password_hash("clave123"), username, rol))

    def test_sin_admin_password_no_se_crea_admin(self):
        os.environ["DB_PATH"] = tempfile.mktemp(suffix=".db", dir=_tmpdir)
        os.environ["ADMIN_PASSWORD"] = ""
        try:
            app_module.init_db()
        finally:
            os.environ["ADMIN_PASSWORD"] = "admin123"
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 0)

    def test_usuario_eliminado_pierde_acceso(self):
        self.crear_usuario("operario1", "Operario")
        self.login("operario1", "clave123")
        self.assertEqual(self.client.get("/").status_code, 200)
        with db() as conn:
            conn.execute("DELETE FROM usuarios WHERE username = 'operario1'")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers["Location"])

    def test_admin_degradado_pierde_acceso_a_usuarios(self):
        self.crear_usuario("jefe", "Admin")
        self.login("jefe", "clave123")
        self.assertEqual(self.client.get("/usuarios").status_code, 200)
        with db() as conn:
            conn.execute("UPDATE usuarios SET rol = 'Operario' WHERE username = 'jefe'")
        self.assertEqual(self.client.get("/usuarios").status_code, 302)

    def test_user_id_no_numerico_no_da_error_500(self):
        self.login()
        resp = self.client.post("/usuarios", data={"accion": "eliminar", "user_id": "abc"})
        self.assertEqual(resp.status_code, 302)

    def test_logout_no_funciona_por_get(self):
        self.login()
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)


if __name__ == "__main__":
    unittest.main()
