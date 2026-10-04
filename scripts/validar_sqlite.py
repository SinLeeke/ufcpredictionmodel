"""Línea base aislada del mismo main que se migra; nunca escribe los originales."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "backups" / "validacion_sqlite"
WORK = BASE / "work"
COMANDOS = [
    ("scraper", ["-m", "src.scraper"]),
    ("train", ["-m", "modelado.train_model"]),
    ("evaluar", ["-m", "modelado.evaluar_modelo"]),
    ("valor_refit", ["-m", "modelado.backtest_valor", "--refit"]),
    ("valor_cache", ["-m", "modelado.backtest_valor"]),
    ("metodo_refit", ["-m", "modelado.backtest_metodo", "--refit"]),
    ("metodo_cache", ["-m", "modelado.backtest_metodo"]),
    ("carteleras", ["-m", "modelado.backtest_carteleras"]),
    ("card", ["-m", "src.card", "cards/betano_2026-10-03_silva_vs_wang.csv"]),
    ("repeticion", ["-c", "from src.card import predict_card; predict_card('cards/historico_2026-08-01_ufc_fight_night_medic_vs_rodriguez.csv', corte='2026-08-01')"]),
]


def copiar_codigo():
    for nombre in ("src", "modelado", "webui", "scripts"):
        shutil.copytree(ROOT / nombre, WORK / nombre, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "config.py", WORK / "config.py")


def preparar():
    if WORK.exists():
        raise RuntimeError("La referencia ya existe; no se sobrescribe automáticamente.")
    WORK.mkdir(parents=True)
    copiar_codigo()
    for nombre in ("data", "models", "cards", "outputs"):
        shutil.copytree(ROOT / nombre, BASE / "entrada" / nombre,
                        ignore=shutil.ignore_patterns("ufc.db*", "originales"))
        shutil.copytree(BASE / "entrada" / nombre, WORK / nombre)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    (BASE / "origen.json").write_text(json.dumps({"commit": commit, "comandos": COMANDOS},
                                               ensure_ascii=False, indent=2), encoding="utf-8")


def hashes_archivos():
    resultado = {}
    for carpeta in ("data", "models", "cards", "outputs"):
        for ruta in sorted((WORK / carpeta).rglob("*")):
            if ruta.is_file():
                if "originales" in ruta.parts or ruta.name.startswith("ufc.db"):
                    continue
                contenido = ruta.read_bytes()
                if ruta.suffix == ".html":
                    # Solo IDs de divs Plotly; cualquier otro UUID conserva
                    # su valor y participa en la comparación.
                    ids = re.findall(rb'<div id="([0-9a-f-]{36})" class="plotly-graph-div"', contenido)
                    for plotly_id in ids:
                        contenido = contenido.replace(plotly_id, b"PLOTLY_UUID")
                resultado[ruta.relative_to(WORK).as_posix()] = hashlib.sha256(contenido).hexdigest()
    db = WORK / "data" / "ufc.db"
    if db.exists():
        with sqlite3.connect(db) as con:
            for key, content in con.execute("SELECT path,content FROM _resources"):
                resultado[key] = hashlib.sha256(content).hexdigest()
    return resultado


def preparar_sqlite():
    destino = BASE / "resultado_base"
    destino.mkdir()
    for nombre in ("data", "models", "cards", "outputs"):
        (WORK / nombre).rename(destino / nombre)
        shutil.copytree(BASE / "entrada" / nombre, WORK / nombre)
    copiar_codigo()
    subprocess.run([sys.executable, "-m", "src.migrate_sqlite"], cwd=WORK, check=True)


def reiniciar_sqlite():
    # Cada comparación debe partir de la MISMA entrada: una corrida previa
    # ya dejó calibradores, walk-forward y HTML nuevos. Se conserva completa.
    archived = BASE / "corridas_previas" / str(time.time_ns())
    archived.parent.mkdir(exist_ok=True)
    WORK.rename(archived)
    WORK.mkdir()
    copiar_codigo()
    for nombre in ("data", "models", "cards", "outputs"):
        shutil.copytree(BASE / "entrada" / nombre, WORK / nombre)
    subprocess.run([sys.executable, "-m", "src.migrate_sqlite"], cwd=WORK, check=True)
    retirar_fuentes()


def comparar():
    import pandas as pd
    from pandas.testing import assert_frame_equal
    report = {"stdout": {}, "sha256": {}, "tablas_exactas": []}
    for nombre, _ in COMANDOS:
        before = (BASE / "base" / f"{nombre}.stdout").read_bytes()
        after = (BASE / "sqlite" / f"{nombre}.stdout").read_bytes()
        report["stdout"][nombre] = before == after
        a = json.loads((BASE / "base" / f"{nombre}.hashes.json").read_text())
        b = json.loads((BASE / "sqlite" / f"{nombre}.hashes.json").read_text())
        report["sha256"][nombre] = [k for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
    # Usa el código migrado aislado para leer SU base, evitando consultar main.
    script = """import json
from pathlib import Path
import pandas as pd
from pandas.testing import assert_frame_equal
import config as C
from src import storage as DB
checked=[]
for p in sorted((C.ROOT.parent/'resultado_base'/'data').rglob('*.csv')):
    relative=p.relative_to(C.ROOT.parent/'resultado_base')
    assert_frame_equal(pd.read_csv(p), DB.read_csv(C.ROOT/relative), check_exact=True)
    checked.append(relative.as_posix())
print(json.dumps(checked))
"""
    p = subprocess.run([sys.executable, "-c", script], cwd=WORK, capture_output=True, check=True)
    report["tablas_exactas"] = json.loads(p.stdout)
    (BASE / "comparacion.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    assert all(report["stdout"].values()), "stdout diferente"
    assert not any(report["sha256"].values()), "artefactos diferentes"


def retirar_fuentes():
    """Solo en el sandbox: demuestra que no se usan los archivos anteriores."""
    destino = BASE / "fuentes_retiradas" / str(time.time_ns())
    with sqlite3.connect(WORK / "data/ufc.db") as con:
        keys = [r[0] for r in con.execute("SELECT path FROM _resources")]
    for key in keys:
        source = (WORK / key).resolve()
        source.relative_to(WORK.resolve())
        if source.exists():
            target = destino / key
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    print(f"{len(keys)} fuentes retiradas solo de la copia aislada")


def ejecutar(fase):
    destino = BASE / fase
    destino.mkdir(exist_ok=True)
    env = {**os.environ, "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
           "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": "", "PYTHONUTF8": "1", "PYTHONHASHSEED": "0"}
    for nombre, args in COMANDOS:
        print(f"{fase}: {nombre}", flush=True)
        with (destino / f"{nombre}.stdout").open("wb") as out, (destino / f"{nombre}.stderr").open("wb") as err:
            p = subprocess.run([sys.executable, *args], cwd=WORK, env=env, stdout=out, stderr=err)
        if p.returncode:
            raise RuntimeError(f"{nombre}: código {p.returncode}; ver {destino / (nombre + '.stderr')}")
        (destino / f"{nombre}.hashes.json").write_text(json.dumps(hashes_archivos(), indent=2), encoding="utf-8")
    print(f"{fase}: terminada", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["preparar", "base", "preparar_sqlite", "reiniciar_sqlite", "retirar_fuentes", "sqlite", "comparar"])
    args = ap.parse_args()
    if args.accion == "preparar":
        preparar()
    elif args.accion == "preparar_sqlite":
        preparar_sqlite()
    elif args.accion == "comparar":
        comparar()
    elif args.accion == "retirar_fuentes":
        retirar_fuentes()
    elif args.accion == "reiniciar_sqlite":
        reiniciar_sqlite()
    else:
        ejecutar(args.accion)
