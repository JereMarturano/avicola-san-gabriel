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

    def execute(self, sql, params=None):
        self._last_results = self.client.execute(sql, params)
        self._row_index = 0
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

class TursoClient:
    def __init__(self, db_url, auth_token):
        # Convertir libsql:// a https://
        clean_url = db_url.replace("libsql://", "https://")
        if not clean_url.startswith("https://"):
            clean_url = "https://" + clean_url
        self.endpoint = clean_url.rstrip("/") + "/v2/pipeline"
        self.token = auth_token

    def cursor(self):
        return TursoCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def execute(self, sql, params=None):
        stmt_args = []
        if params:
            for p in params:
                if p is None:
                    stmt_args.append({"type": "null"})
                elif isinstance(p, int):
                    stmt_args.append({"type": "integer", "value": str(p)})
                elif isinstance(p, float):
                    stmt_args.append({"type": "float", "value": p})
                else:
                    stmt_args.append({"type": "text", "value": str(p)})

        stmt = {"sql": sql}
        if stmt_args:
            stmt["args"] = stmt_args

        payload = {
            "requests": [
                {"type": "execute", "stmt": stmt},
                {"type": "close"}
            ]
        }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

        resp = requests.post(self.endpoint, headers=headers, json=payload, timeout=12)
        if resp.status_code != 200:
            raise sqlite3.OperationalError(f"Error Turso ({resp.status_code}): {resp.text}")

        data = resp.json()
        results_list = data.get("results", [])
        if not results_list:
            return []

        first = results_list[0]
        if first.get("type") == "error":
            err_msg = first.get("error", {}).get("message", "Error Turso")
            raise sqlite3.OperationalError(err_msg)

        exec_res = first.get("response", {}).get("result", {})
        cols_meta = exec_res.get("cols", [])
        cols = [c["name"] for c in cols_meta]
        raw_rows = exec_res.get("rows", [])

        parsed_rows = []
        for r in raw_rows:
            row_vals = []
            for cell in r:
                t = cell.get("type")
                v = cell.get("value")
                if t == "integer":
                    row_vals.append(int(v) if v is not None else None)
                elif t == "float":
                    row_vals.append(float(v) if v is not None else None)
                elif t == "null":
                    row_vals.append(None)
                else:
                    row_vals.append(v)
            parsed_rows.append(TursoRow(cols, row_vals))

        return parsed_rows

def get_db_client():
    """Retorna cliente Turso si las variables están configuradas, sino SQLite local."""
    url = os.environ.get("TURSO_DATABASE_URL", TURSO_URL)
    token = os.environ.get("TURSO_AUTH_TOKEN", TURSO_TOKEN)
    if url and token:
        return TursoClient(url, token)
    
    # Fallback local SQLite
    db_path = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "avicola.db"))
    conn = sqlite3.connect(db_path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn
