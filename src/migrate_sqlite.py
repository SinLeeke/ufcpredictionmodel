"""Copia verificable y migración reanudable, sin tocar ningún original."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd
from pandas.testing import assert_frame_equal

import config as C
from src import storage as DB


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    for directory in (C.ROOT / "data" / "raw", C.ROOT / "data" / "processed", C.ROOT / "models"):
        if directory.exists():
            yield from sorted(p for p in directory.rglob("*") if p.is_file() and DB.key(p))


def migrate():
    with DB.lease("migration"):
        _migrate()


def _migrate():
    originales = C.ROOT / "data" / "originales"
    originales.mkdir(parents=True, exist_ok=True)
    manifest = originales / "manifiesto.json"
    entries = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
    for source in sources():
        key = DB.key(source)
        before = source.stat()
        sha = digest(source)
        backup = originales / sha / key
        if backup.exists():
            if digest(backup) != sha:
                raise RuntimeError(f"Respaldo corrupto: {backup}")
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            if digest(backup) != sha:
                raise RuntimeError(f"Falló la copia de {source}")
        # Detecta una UI u otro escritor que cambió el original durante la copia.
        if source.stat().st_mtime_ns != before.st_mtime_ns or digest(source) != sha:
            raise RuntimeError(f"El original cambió durante la copia: {source}; cierra la UI")
        checkpoint = key + "@" + sha
        previous = entries.get(checkpoint)
        if previous and previous.get("estado") == "verificado":
            if DB.exists(source) and DB.signature(source) == sha:
                verify(source, backup)
                print(f"[igual] {key}")
                continue
            # Nunca revierte una base actualizada por scraping/modelado al
            # original viejo al reejecutar la migración.
            if DB.exists(source):
                print(f"[actualizado] {key}: conserva la versión de SQLite")
                continue
        if DB.exists(source) and not previous and DB.signature(source) != sha:
            raise RuntimeError(f"{key} ya está en SQLite con otra procedencia; no se sobrescribe")
        content = backup.read_bytes()
        if source.suffix == ".csv":
            DB.write_csv_bytes(source, content, before.st_mtime_ns)
        elif source.suffix == ".json":
            DB.write_text(source, content.decode("utf-8"), mtime_ns=before.st_mtime_ns)
        else:
            DB.write_bytes(source, content, before.st_mtime_ns)
        verify(source, backup)
        entries[checkpoint] = {"ruta": key, "sha256": sha, "bytes": len(content),
                               "respaldo": backup.relative_to(originales).as_posix(),
                               "mtime_ns": before.st_mtime_ns, "estado": "verificado"}
        temp = manifest.with_suffix(".tmp")
        temp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(manifest)
        print(f"[copiado y verificado] {key}")
    with DB.connect() as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    print(f"[ok] {DB.db_path()} | manifiesto: {manifest}")


def verify(source, backup):
    if source.suffix == ".csv":
        assert_frame_equal(pd.read_csv(backup), DB.read_csv(source), check_exact=True)
        assert_frame_equal(pd.read_csv(backup, low_memory=False), DB.read_csv(source, low_memory=False), check_exact=True)
    assert hashlib.sha256(DB.read_bytes(source)).hexdigest() == digest(backup)


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    migrate()
