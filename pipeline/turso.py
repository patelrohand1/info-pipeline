"""Minimal sqlite3-style connection to a Turso (libSQL) database over its HTTP API.

Covers what this project uses: execute / executemany / executescript / commit, rows readable by index or
column name (like sqlite3.Row), rowcount. Every statement autocommits, so commit() is a no-op.
"""
import base64
import time

import requests


class Row(tuple):
    def __new__(cls, cols, values):
        row = super().__new__(cls, values)
        row._index = {c: i for i, c in enumerate(cols)}
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._index)


class Cursor:
    def __init__(self, cols, rows, rowcount):
        self._rows = [Row(cols, r) for r in rows]
        self.rowcount = rowcount

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


def _arg(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool) or isinstance(v, int):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, bytes):
        return {"type": "blob", "base64": base64.b64encode(v).decode()}
    return {"type": "text", "value": str(v)}


def _val(v):
    t = v["type"]
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        return base64.b64decode(v["base64"])
    return v["value"]


class Connection:
    def __init__(self, url: str, token: str | None):
        self.url = url.replace("libsql://", "https://", 1).rstrip("/") + "/v2/pipeline"
        self.http = requests.Session()
        if token:
            self.http.headers["Authorization"] = f"Bearer {token}"

    def _pipeline(self, stmts: list[tuple[str, tuple]]) -> list[dict]:
        body = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": [_arg(a) for a in args]}}
                             for sql, args in stmts] + [{"type": "close"}]}
        for attempt in range(3):
            try:
                resp = self.http.post(self.url, json=body, timeout=60)
                if resp.status_code < 500:
                    break
            except requests.ConnectionError:
                if attempt == 2:
                    raise
            time.sleep(2 * (attempt + 1))
        resp.raise_for_status()
        out = []
        for res in resp.json()["results"][: len(stmts)]:
            if res["type"] == "error":
                raise RuntimeError(f"turso: {res['error'].get('message')}")
            out.append(res["response"]["result"])
        return out

    @staticmethod
    def _cursor(result: dict) -> Cursor:
        cols = [c["name"] for c in result["cols"]]
        rows = [[_val(v) for v in r] for r in result["rows"]]
        return Cursor(cols, rows, result.get("affected_row_count", -1))

    def execute(self, sql: str, params=()) -> Cursor:
        return self._cursor(self._pipeline([(sql, tuple(params))])[0])

    def executemany(self, sql: str, seq) -> None:
        stmts = [(sql, tuple(p)) for p in seq]
        for i in range(0, len(stmts), 200):  # keep request bodies a sane size
            self._pipeline(stmts[i:i + 200])

    def executescript(self, script: str) -> None:
        stmts = [(s.strip(), ()) for s in script.split(";") if s.strip()]
        self._pipeline(stmts)

    def commit(self) -> None:
        pass

    def close(self) -> None:
        self.http.close()
