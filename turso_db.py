import os
import sqlite3
import requests

# Cargar variables de entorno locales desde archivo .env si existe
def _load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass

_load_env_file()

TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

class TursoRow(dict):
    """Permite acceso como diccionario o por índice tipo sqlite3.Row."""
    def __init__(self, cols, values):
        super().__init__()
        self._values = []
        for i, col in enumerate(cols):
            val = values[i]
            self[col] = val
            self._values.append(val)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

class TursoCursor:
    def __init__(self, client):
        self.client = client
        self._last_results = []
        self._row_index = 0
        self.rowcount = -1

    def execute(self, sql, params=None):
        self._last_results = self.client.execute(sql, params)
        self._row_index = 0
        self.rowcount = self.client.last_affected_rows
        return self

    def fetchone(self):
        if self._row_index < len(self._last_results):
            row = self._last_results[self._row_index]
            self._row_index += 1
            return row
        return None

    def fetchall(self):
        remaining = self._last_results[self._row_index:]
        self._row_index = len(self._last_results)
        return remaining

# Sesión HTTP compartida: reutiliza la conexión TLS entre consultas en lugar de
# negociar una nueva cada vez (cada handshake son varios viajes de red extra).
_http = requests.Session()

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE", "REPLACE")

def _encode_arg(p):
    if p is None:
        return {"type": "null"}
    if isinstance(p, bool) or isinstance(p, int):
        return {"type": "integer", "value": str(int(p))}
    if isinstance(p, float):
        return {"type": "float", "value": p}
    return {"type": "text", "value": str(p)}

def _decode_cell(cell):
    t = cell.get("type")
    v = cell.get("value")
    if t == "integer":
        return int(v) if v is not None else None
    if t == "float":
        return float(v) if v is not None else None
    if t == "null":
        return None
    return v

def _raise_turso_error(message):
    # Mismo tipo de excepción que sqlite3 para que los except de app.py funcionen igual
    if "UNIQUE constraint" in message or "CHECK constraint" in message or "constraint failed" in message:
        raise sqlite3.IntegrityError(message)
    raise sqlite3.OperationalError(message)

class TursoClient:
    """
    Cliente Turso (protocolo Hrana sobre HTTP) con semántica similar a sqlite3:
    la primera escritura abre una transacción (BEGIN) que se mantiene en el mismo
    stream del servidor mediante el 'baton' hasta commit() o rollback().
    """
    def __init__(self, db_url, auth_token):
        # Convertir libsql:// a https://
        clean_url = db_url.replace("libsql://", "https://")
        if not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url
        self.base_url = clean_url.rstrip("/")
        self.token = auth_token
        self._baton = None
        self._stream_url = None
        self.in_transaction = False
        self.last_affected_rows = -1

    def cursor(self):
        return TursoCursor(self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Igual que sqlite3: confirma si no hubo excepción, revierte si la hubo
        if exc_type is None:
            self.commit()
        else:
            self.rollback()

    def _pipeline(self, stmts, close):
        """Envía varias sentencias en un solo viaje de red y devuelve sus resultados."""
        reqs = [{"type": "execute", "stmt": s} for s in stmts]
        if close:
            reqs.append({"type": "close"})
        payload = {"baton": self._baton, "requests": reqs}
        url = (self._stream_url or self.base_url) + "/v2/pipeline"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            resp = _http.post(url, headers=headers, json=payload, timeout=12)
        except requests.RequestException as e:
            self._reset_stream()
            raise sqlite3.OperationalError(f"Error de conexión con Turso: {e}")
        if resp.status_code != 200:
            self._reset_stream()
            raise sqlite3.OperationalError(f"Error Turso ({resp.status_code}): {resp.text}")

        data = resp.json()
        if close:
            self._reset_stream()
        else:
            self._baton = data.get("baton")
            if data.get("base_url"):
                self._stream_url = data["base_url"].rstrip("/")

        results = data.get("results", [])
        for res in results[:len(stmts)]:
            if res.get("type") == "error":
                _raise_turso_error(res.get("error", {}).get("message", "Error Turso"))
        return [r.get("response", {}).get("result", {}) for r in results[:len(stmts)]]

    def _reset_stream(self):
        self._baton = None
        self._stream_url = None
        self.in_transaction = False

    def execute(self, sql, params=None):
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [_encode_arg(p) for p in params]

        stmts = [stmt]
        is_write = sql.lstrip().upper().startswith(_WRITE_PREFIXES)
        if is_write and not self.in_transaction:
            stmts.insert(0, {"sql": "BEGIN"})
            self.in_transaction = True

        # Fuera de una transacción la consulta se envía y se cierra el stream en un solo viaje
        results = self._pipeline(stmts, close=not self.in_transaction)
        exec_res = results[-1]
        self.last_affected_rows = exec_res.get("affected_row_count", -1)

        cols = [c["name"] for c in exec_res.get("cols", [])]
        return [TursoRow(cols, [_decode_cell(c) for c in r]) for r in exec_res.get("rows", [])]

    def commit(self):
        if self.in_transaction:
            self._pipeline([{"sql": "COMMIT"}], close=True)

    def rollback(self):
        if self.in_transaction:
            try:
                self._pipeline([{"sql": "ROLLBACK"}], close=True)
            except sqlite3.Error:
                # Si el stream ya expiró, el servidor descarta la transacción por su cuenta
                self._reset_stream()

class _ClosingConnection(sqlite3.Connection):
    """Conexión SQLite que, además de confirmar/revertir, se cierra al salir del 'with'."""
    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()

def get_db_client():
    """Retorna cliente Turso si las variables están configuradas, sino SQLite local."""
    url = os.environ.get("TURSO_DATABASE_URL", TURSO_URL)
    token = os.environ.get("TURSO_AUTH_TOKEN", TURSO_TOKEN)
    if url and token:
        return TursoClient(url, token)
    
    # Fallback local SQLite
    db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "avicola.db"))
    conn = sqlite3.connect(db_path, timeout=10.0, factory=_ClosingConnection)
    conn.row_factory = sqlite3.Row
    return conn
