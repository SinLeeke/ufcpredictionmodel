"""Persistencia SQLite explícita; las rutas antiguas son claves, no fallbacks.

La tabla guarda los valores que pandas LEÍA del CSV, no los floats anteriores
a escribirlo. El texto original queda como artefacto para exportar y auditar.
No se alteran los algoritmos de fechas, identidad ni orden del modelo.
"""
from __future__ import annotations

from contextlib import contextmanager
from collections import OrderedDict
import builtins
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid
from types import SimpleNamespace

import numpy as np
import pandas as pd

import config as C

_MEMO = OrderedDict()
_MEMO_LOCK = threading.RLock()
_MEMO_LIMIT = 64 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Diario de una operación que se puede deshacer
# --------------------------------------------------------------------------- #
# Una carga de cartelera escribe cachés, el CSV de cards/ y la cartelera
# completada mientras corre. Si el usuario la cancela, todo eso tiene que
# volver a como estaba (webui/engine.py). Mientras un Diario está activo en un
# hilo, la primera escritura de cada ruta guarda su estado anterior; revertir()
# lo repone. Solo cuenta lo que escribe ESE hilo, y una ruta que otro hilo
# reescribió después no se pisa. Apagado (lo normal), no cambia nada.
_DIARIO = threading.local()


def _ruta_diario(path):
    return ("db", key(path)) if key(path) is not None else ("archivo", str(Path(path).resolve()))


def _firma_diario(path):
    if key(path) is None:
        p = Path(path)
        return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    with connect() as con:
        r = con.execute("SELECT sha256 FROM _resources WHERE path=?", (key(path),)).fetchone()
    return r[0] if r else None


class Diario:
    def __init__(self):
        self.previos = {}      # ruta -> (path, tipo, contenido, mtime_ns) o (path, None, None, None)
        self.escritos = {}     # ruta -> firma que dejó la última escritura de este hilo

    def __enter__(self):
        _DIARIO.actual = self
        return self

    def __exit__(self, *exc):
        if getattr(_DIARIO, "actual", None) is self:
            _DIARIO.actual = None
        return False

    def anotar(self, path):
        ruta = _ruta_diario(path)
        if ruta in self.previos:
            return
        if key(path) is None:
            p = Path(path)
            self.previos[ruta] = (path, "archivo", p.read_bytes(), None) if p.is_file() else (path, None, None, None)
            return
        try:
            tipo, contenido, _, mtime, *_ = _resource(path)     # materializa un json pendiente
        except FileNotFoundError:
            self.previos[ruta] = (path, None, None, None)
        else:
            self.previos[ruta] = (path, tipo, bytes(contenido), mtime)

    def revertir(self):
        """Repone cada ruta escrita a su estado previo. Devuelve las que otro hilo cambió."""
        if getattr(_DIARIO, "actual", None) is self:
            _DIARIO.actual = None
        ajenas = []
        for ruta, (path, tipo, contenido, mtime) in reversed(list(self.previos.items())):
            if _firma_diario(path) != self.escritos.get(ruta):
                ajenas.append(str(path))       # otro hilo escribió después: su versión manda
                continue
            if tipo is None:
                unlink(path, missing_ok=True)
            elif tipo == "archivo":
                Path(path).write_bytes(contenido)
            elif tipo == "csv":
                write_csv_bytes(path, contenido, mtime_ns=mtime)
            elif tipo == "json":
                write_text(path, contenido.decode("utf-8"), mtime_ns=mtime)
            else:
                write_bytes(path, contenido, mtime_ns=mtime)
        self.previos.clear()
        self.escritos.clear()
        return ajenas


def _registrado(funcion):
    """Anota en el Diario activo del hilo, si hay uno, antes y después de escribir."""
    def envoltura(path, *args, **kwargs):
        d = getattr(_DIARIO, "actual", None)
        if d is None or path is None:
            return funcion(path, *args, **kwargs)
        d.anotar(path)
        try:
            return funcion(path, *args, **kwargs)
        finally:
            d.escritos[_ruta_diario(path)] = _firma_diario(path)
    envoltura.__name__, envoltura.__doc__ = funcion.__name__, funcion.__doc__
    return envoltura


def _memo_key(kind, path, sha):
    return kind, str(db_path().resolve()), key(path), sha


def _memo_get(k):
    with _MEMO_LOCK:
        entry = _MEMO.get(k)
        if entry is not None:
            _MEMO.move_to_end(k)
            return entry[0]
    return None


def _memo_put(k, value, size):
    if size > _MEMO_LIMIT:
        return
    with _MEMO_LOCK:
        for old in list(_MEMO):
            if old[:3] == k[:3]:
                del _MEMO[old]
        _MEMO[k] = value, size
        while sum(s for _, s in _MEMO.values()) > _MEMO_LIMIT or len(_MEMO) > 32:
            _MEMO.popitem(last=False)


def db_path():
    return Path(os.environ.get("UFC_DB", str(C.ROOT / "data" / "ufc.db")))


def key(path):
    if not isinstance(path, (str, os.PathLike)):
        return None
    p = Path(path).resolve()
    try:
        r = p.relative_to(C.ROOT.resolve())
    except ValueError:
        return None
    parts = r.parts
    if (len(parts) == 3 and parts[:2] in (("data", "raw"), ("data", "processed"))
            and p.suffix in (".csv", ".json")) or (parts and parts[0] == "models" and p.suffix == ".pkl"):
        return r.as_posix()
    if r.as_posix() == "data/raw/fotos/indice.json":
        return r.as_posix()
    return None


@contextmanager
def connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=60)
    try:
        con.execute("PRAGMA busy_timeout=60000")
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("""CREATE TABLE IF NOT EXISTS _resources (
            path TEXT PRIMARY KEY COLLATE BINARY, kind TEXT NOT NULL,
            content BLOB NOT NULL, sha256 TEXT NOT NULL, mtime_ns INTEGER NOT NULL,
            table_name TEXT, schema_json TEXT)""")
        con.execute("""CREATE TABLE IF NOT EXISTS _json_entries (
            path TEXT NOT NULL, key TEXT NOT NULL COLLATE BINARY,
            row_order INTEGER NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY(path,key), FOREIGN KEY(path) REFERENCES _resources(path) ON DELETE CASCADE)""")
        con.execute("""CREATE TABLE IF NOT EXISTS _runtime_locks (
            token TEXT PRIMARY KEY, kind TEXT NOT NULL, heartbeat REAL NOT NULL)""")
        with con:
            yield con
    finally:
        con.close()


def _resource(path, con=None, include_content=True):
    k = key(path)
    if con is None:
        with connect() as c:
            return _resource(path, c, include_content)
    selection = "kind," + ("content" if include_content else "length(content)") + ",sha256,mtime_ns,table_name,schema_json"
    row = con.execute(f"SELECT {selection} FROM _resources WHERE path=?", (k,)).fetchone()
    if row is None:
        raise FileNotFoundError(f"Falta {k} en {db_path()}; ejecuta python -m src.migrate_sqlite")
    if row[0] == "json_pending":
        # Los checkpoints escriben solo una clave. El documento se materializa
        # al leerlo, exportarlo o al guardar el resumen final del scraper.
        entries = con.execute("SELECT key,value FROM _json_entries WHERE path=? ORDER BY row_order", (k,))
        content = json.dumps({a: json.loads(b) for a, b in entries}, ensure_ascii=False).encode("utf-8")
        _put(con, path, "json", content, mtime_ns=row[3])
        row = con.execute(f"SELECT {selection} FROM _resources WHERE path=?", (k,)).fetchone()
    return row


def exists(path):
    if key(path) is None:
        return Path(path).exists()
    with connect() as con:
        return con.execute("SELECT 1 FROM _resources WHERE path=?", (key(path),)).fetchone() is not None


def stat(path):
    if key(path) is None:
        return Path(path).stat()
    r = _resource(path, include_content=False)
    return SimpleNamespace(st_mtime_ns=r[3], st_mtime=r[3] / 1e9, st_size=r[1])


def signature(path):
    """Invalidación por contenido: una reescritura idéntica no invalida la UI."""
    if key(path) is None:
        return str(Path(path).stat().st_mtime_ns) if Path(path).exists() else "0"
    try:
        return _resource(path, include_content=False)[2]
    except FileNotFoundError:
        return "0"


def _put(con, path, kind, content, table=None, schema=None, mtime_ns=None):
    digest = hashlib.sha256(content).hexdigest()
    previous = con.execute("SELECT sha256,kind FROM _resources WHERE path=?", (key(path),)).fetchone()
    if previous and previous == (digest, kind):
        return
    con.execute("""INSERT INTO _resources VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(path) DO UPDATE SET kind=excluded.kind,content=excluded.content,
        sha256=excluded.sha256,mtime_ns=excluded.mtime_ns,
        table_name=excluded.table_name,schema_json=excluded.schema_json""",
        (key(path), kind, content, digest, mtime_ns if mtime_ns is not None else time.time_ns(), table, schema))


def _quote(s):
    return '"' + s.replace('"', '""') + '"'


def _table_name(path):
    # Nombres consultables sin colisiones entre raw y processed.
    k = key(path)
    return "csv_" + k.replace("/", "__").replace(".", "_")


@_registrado
def write_csv_bytes(path, content, mtime_ns=None):
    df = pd.read_csv(io.BytesIO(content))
    schema = json.dumps([(str(c), str(df[c].dtype)) for c in df.columns])
    table = _table_name(path)
    cols = list(df.columns)
    if "_row_order" in cols:
        raise ValueError("_row_order está reservado para conservar el orden CSV")
    types = ["INTEGER" if d.kind in "biu" else "REAL" if d.kind == "f" else "TEXT COLLATE BINARY" for d in df.dtypes]
    rows = []
    for i, values in enumerate(df.itertuples(index=False, name=None)):
        rows.append((i, *[None if pd.isna(v) else v.item() if isinstance(v, np.generic) else v for v in values]))
    with connect() as con:
        old = con.execute("SELECT schema_json FROM _resources WHERE path=?", (key(path),)).fetchone()
        if old is None or old[0] != schema:
            con.execute(f"DROP TABLE IF EXISTS {_quote(table)}")
            con.execute(f"CREATE TABLE {_quote(table)} (_row_order INTEGER PRIMARY KEY," +
                        ",".join(f"{_quote(c)} {t}" for c, t in zip(cols, types)) + ")")
            anteriores = {}
        else:
            anteriores = {r[0]: r for r in con.execute(f"SELECT * FROM {_quote(table)} ORDER BY _row_order")}
        cambiadas = [r for r in rows if anteriores.get(r[0]) != r]
        placeholders = ",".join("?" for _ in range(len(cols) + 1))
        updates = ",".join(f"{_quote(c)}=excluded.{_quote(c)}" for c in cols)
        con.executemany(f"INSERT INTO {_quote(table)} VALUES ({placeholders}) ON CONFLICT(_row_order) DO UPDATE SET {updates}", cambiadas)
        con.execute(f"DELETE FROM {_quote(table)} WHERE _row_order>=?", (len(rows),))
        _put(con, path, "csv", content, table, schema, mtime_ns)


def read_csv(path, **kwargs):
    if key(path) is None:
        return pd.read_csv(path, **kwargs)
    unsupported = set(kwargs) - {"low_memory", "usecols", "parse_dates", "dtype"}
    if unsupported:
        raise TypeError(f"Opciones CSV no admitidas para SQLite: {unsupported}")
    with connect() as con:
        r = _resource(path, con, include_content=False)
        schema = json.loads(r[5])
        columns = [c for c, _ in schema]
        cache_key = _memo_key("frame", path, r[2])
        cached = _memo_get(cache_key)
        if cached is not None:
            df = cached.copy(deep=True)
        else:
            # Snapshot coherente: otro proceso puede confirmar nuevas tablas
            # entre la firma y el SELECT si no hay transacción de lectura.
            con.execute("BEGIN")
            r = _resource(path, con, include_content=False)
            schema = json.loads(r[5])
            columns = [c for c, _ in schema]
            cache_key = _memo_key("frame", path, r[2])
            df = pd.read_sql_query(f"SELECT {','.join(map(_quote, columns))} FROM {_quote(r[4])} ORDER BY _row_order", con)
            # SQLite devuelve bool como int y columnas object vacías como None.
            for c, dtype in schema:
                if dtype == "object":
                    df[c] = df[c].where(df[c].notna(), np.nan).astype(object)
                else:
                    df[c] = df[c].astype(dtype)
            _memo_put(cache_key, df.copy(deep=True), int(df.memory_usage(deep=True).sum()))
    if kwargs.get("usecols") is not None:
        usecols = kwargs["usecols"]
        df = df[[c for c in columns if usecols(c)]] if callable(usecols) else df[[c for c in columns if c in usecols]]
    if kwargs.get("dtype") is not None:
        df = df.astype(kwargs["dtype"])
    for c in kwargs.get("parse_dates") or []:
        df[c] = pd.to_datetime(df[c])
    return df


def to_csv(df, path=None, **kwargs):
    if path is not None and getattr(_DIARIO, "actual", None) is not None and key(path) is None:
        return _registrado(lambda ruta: df.to_csv(ruta, **kwargs))(path)
    if key(path) is None:
        return df.to_csv(path, **kwargs)
    text = df.to_csv(None, **kwargs)
    # pandas escribe CRLF en Windows al abrir un CSV: StringIO también usa
    # os.linesep como lineterminator. Se conserva el artefacto byte a byte.
    write_csv_bytes(path, text.encode(kwargs.get("encoding") or "utf-8"))


def read_text(path, encoding="utf-8", **kwargs):
    if key(path) is None:
        return Path(path).read_text(encoding=encoding, **kwargs)
    return _resource(path)[1].decode(encoding)


def read_json(path):
    if key(path) is None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    r = _resource(path, include_content=False)
    cache_key = _memo_key("json", path, r[2])
    cached = _memo_get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)
    r = _resource(path)
    value = json.loads(r[1].decode("utf-8"))
    _memo_put(_memo_key("json", path, r[2]), copy.deepcopy(value), len(r[1]) * 4)
    return value


@_registrado
def write_text(path, text, encoding="utf-8", mtime_ns=None, **kwargs):
    if key(path) is None:
        return Path(path).write_text(text, encoding=encoding, **kwargs)
    content = text.encode(encoding)
    value = json.loads(text)
    with connect() as con:
        _put(con, path, "json", content, mtime_ns=mtime_ns)
        if isinstance(value, dict):
            old = {k: (i, v) for k, i, v in con.execute("SELECT key,row_order,value FROM _json_entries WHERE path=?", (key(path),))}
            for i, (k, v) in enumerate(value.items()):
                serialized = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
                if old.pop(k, None) != (i, serialized):
                    con.execute("""INSERT INTO _json_entries VALUES (?,?,?,?) ON CONFLICT(path,key)
                        DO UPDATE SET row_order=excluded.row_order,value=excluded.value""", (key(path), k, i, serialized))
            con.executemany("DELETE FROM _json_entries WHERE path=? AND key=?", [(key(path), k) for k in old])
    return len(text)


def read_bytes(path):
    return Path(path).read_bytes() if key(path) is None else _resource(path)[1]


@_registrado
def write_bytes(path, content, mtime_ns=None):
    if key(path) is None:
        return Path(path).write_bytes(content)
    with connect() as con:
        _put(con, path, "blob", content, mtime_ns=mtime_ns)
    return len(content)


@contextmanager
def open_file(path, mode="r", *args, **kwargs):
    if key(path) is None:
        d = getattr(_DIARIO, "actual", None) if any(m in mode for m in "wax+") else None
        if d is not None:
            d.anotar(path)
        try:
            with builtins.open(path, mode, *args, **kwargs) as stream:
                yield stream
        finally:
            if d is not None:
                d.escritos[_ruta_diario(path)] = _firma_diario(path)
        return
    if mode not in ("rb", "wb"):
        raise ValueError("Los modelos SQLite se abren únicamente como rb/wb")
    stream = io.BytesIO(read_bytes(path) if mode == "rb" else b"")
    try:
        yield stream
        if mode == "wb":
            write_bytes(path, stream.getvalue())
    finally:
        stream.close()


@_registrado
def unlink(path, missing_ok=False):
    if key(path) is None:
        return Path(path).unlink(missing_ok=missing_ok)
    with connect() as con:
        r = con.execute("SELECT table_name FROM _resources WHERE path=?", (key(path),)).fetchone()
        if r is None and not missing_ok:
            raise FileNotFoundError(str(path))
        if r and r[0]:
            con.execute(f"DROP TABLE IF EXISTS {_quote(r[0])}")
        con.execute("DELETE FROM _resources WHERE path=?", (key(path),))


@_registrado
def put_json_entry(path, entry_key, value):
    """Checkpoint por página descargada, sin esperar al fin del ciclo."""
    if key(path) is None:
        current = json.loads(read_text(path)) if exists(path) else {}
        current[entry_key] = value
        write_text(path, json.dumps(current, ensure_ascii=False))
        return
    with connect() as con:
        if con.execute("SELECT 1 FROM _resources WHERE path=?", (key(path),)).fetchone() is None:
            _put(con, path, "json", b"{}")
        ordinal = con.execute("SELECT row_order FROM _json_entries WHERE path=? AND key=?", (key(path), entry_key)).fetchone()
        if ordinal is None:
            ordinal = con.execute("SELECT COALESCE(MAX(row_order)+1,0) FROM _json_entries WHERE path=?", (key(path),)).fetchone()
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        con.execute("""INSERT INTO _json_entries VALUES (?,?,?,?) ON CONFLICT(path,key)
            DO UPDATE SET value=excluded.value""", (key(path), entry_key, ordinal[0], serialized))
        con.execute("UPDATE _resources SET kind='json_pending',mtime_ns=? WHERE path=?", (time.time_ns(), key(path)))


@contextmanager
def lease(kind):
    """Impide abrir la UI durante una migración y migrar con la UI abierta.

El latido caduca tras una caída, sin archivos de bloqueo adicionales.
BEGIN IMMEDIATE hace atómica la comprobación con la reserva del permiso.
"""
    token = uuid.uuid4().hex
    with connect() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM _runtime_locks WHERE heartbeat<?", (time.time() - 90,))
        kinds = {r[0] for r in con.execute("SELECT kind FROM _runtime_locks")}
        if "migration" in kinds or (kind == "migration" and "ui" in kinds):
            raise RuntimeError("Cierra la UI antes de migrar; no puede abrirse durante la migración.")
        con.execute("INSERT INTO _runtime_locks VALUES (?,?,?)", (token, kind, time.time()))
    stop = threading.Event()

    def heartbeat():
        while not stop.wait(15):
            with connect() as con:
                con.execute("UPDATE _runtime_locks SET heartbeat=? WHERE token=?", (time.time(), token))

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)
        with connect() as con:
            con.execute("DELETE FROM _runtime_locks WHERE token=?", (token,))
