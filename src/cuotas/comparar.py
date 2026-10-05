"""«Comparar cuotas» para las fuentes que ya viven en la capa (Betano, Polymarket).

BFO y The Odds API se consultan por su cuenta (src/cuotas_fuentes.consultar).
Betano y Polymarket NO: Betano es pasivo (el ciclo de webui/engine.py le
entrega a la capa lo que bajó, una petición por ciclo) y Polymarket ya lo
consulta su hilo de fondo. Aquí solo se LEE lo que la capa guardó en SQLite,
así que este camino jamás hace una petición de red.

El resultado se guarda como captura en `cuotas_snapshots`, con la misma forma
de eventos que BFO, para que `cuotas_fuentes.cartelera` y el historial la abran
sin distinguir de dónde vino. Una captura idéntica (mismo sha256) se reutiliza:
la UI pide esto cada vez que se abre la sección y no debe llenar la tabla.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from src import cuotas_fuentes as F
from src import storage as DB
from src.cuotas import capa as capa_mod
from src.cuotas.conversion import CuotaInvalida, americana_a_decimal

CLAVES = ("betano", "polymarket")
# El predictor (src/value.a_americana) infiere el formato por rango: un decimal
# de 51 a 99 se descarta y uno de 100 o más se lee como americana (+100 = 2,0).
# Un decimal por encima de este tope, p. ej. Polymarket a 1 o 1,5 centavos
# (100 y 66,67), llegaría mal interpretado o perdido. Se deja fuera la pelea
# con el motivo a la vista en vez de mandarle un precio ambiguo.
DECIMAL_MAX = 50.0
_FUENTE_URL = {"betano": "https://www.betano.cl/", "polymarket": "https://polymarket.com/"}


def _decimal(c: dict, lado: str) -> float:
    """Decimal de un lado. Casa: americana → decimal. Polymarket: 1/p, sin margen."""
    if c.get("tipo") == "mercado_prediccion":
        p = c[lado]["prob_implicita"]
        if not 0 < p < 1:
            raise CuotaInvalida("precio fuera de (0, 1)")
        d = round(1 / p, 3)
    else:
        d = round(americana_a_decimal(c[lado]["americana"]), 3)
    if d > DECIMAL_MAX:
        raise CuotaInvalida(f"cuota decimal {d} sobre {DECIMAL_MAX:g}: formato ambiguo para el predictor")
    return d


def _eventos(peleas: list[dict], clave: str, descartadas: list | None = None) -> tuple[list[dict], str | None]:
    grupos: dict[tuple, dict] = {}
    actualizado = None
    for p in peleas:
        # Una fuente = un conjunto de cotizaciones; las de otras fuentes no se mezclan.
        casas = {}
        for c in p["cotizaciones"]:
            if c["fuente"] != clave:
                continue
            try:
                casas[clave] = {"casa": c["casa"], "a": _decimal(c, "a"), "b": _decimal(c, "b")}
            except (CuotaInvalida, KeyError, TypeError) as e:
                if descartadas is not None:
                    descartadas.append({"a": p["a"], "b": p["b"], "motivo": str(e) or "cuota inválida"})
                continue
            if actualizado is None or c["visto"] > actualizado:
                actualizado = c["visto"]
        if not casas:
            continue
        llave = (p["evento"] or "", p["fecha"] or "")
        g = grupos.setdefault(llave, {
            "id": "capa-" + hashlib.sha256("|".join(llave).encode()).hexdigest()[:12],
            "titulo": llave[0] or llave[1] or "Sin evento", "fecha": llave[1] or None,
            "fuente": _FUENTE_URL[clave], "peleas": []})
        g["peleas"].append({"id": p["pelea_id"], "a": p["a"], "b": p["b"], "casas": casas})
    eventos = sorted(grupos.values(), key=lambda e: (e["fecha"] or "9999", e["titulo"], e["id"]))
    return eventos, actualizado


def _guardar(clave: str, eventos: list[dict]) -> tuple[str, str]:
    contenido = json.dumps(eventos, ensure_ascii=False, sort_keys=True, allow_nan=False)
    sha = hashlib.sha256(contenido.encode()).hexdigest()
    with DB.connect() as con:
        # BEGIN IMMEDIATE toma el candado de escritura ANTES de leer la última
        # captura: dos GET simultáneos se serializan y el segundo ve la fila del
        # primero en vez de insertar un duplicado.
        con.execute("BEGIN IMMEDIATE")
        F._tablas(con)
        r = con.execute("SELECT id,capturado,sha256 FROM cuotas_snapshots WHERE proveedor=? "
                        "ORDER BY capturado DESC LIMIT 1", (clave,)).fetchone()
        # Solo se compara con la última: si el mercado vuelve a un estado
        # anterior es una captura nueva, no la vieja resucitada.
        if r and r[2] == sha:
            return r[0], r[1]
        capturado = datetime.now(timezone.utc).isoformat()
        sid = hashlib.sha256((clave + capturado + sha).encode()).hexdigest()
        con.execute("INSERT INTO cuotas_snapshots(id,proveedor,capturado,fecha_fuente,contenido,sha256,cartelera) "
                    "VALUES(?,?,?,?,?,?,NULL)", (sid, clave, capturado, None, contenido, sha))
    return sid, capturado


def consultar(clave: str) -> dict:
    if clave not in CLAVES:
        raise ValueError("Proveedor desconocido")
    capa = capa_mod.capa()
    descartadas: list[dict] = []
    eventos, actualizado = _eventos(capa.peleas()["peleas"], clave, descartadas)
    sid, capturado = _guardar(clave, eventos)
    fuente = next((f for f in capa.fuentes if f.clave == clave), None)
    activa = bool(fuente and fuente.activa())
    tipo = fuente.tipo if fuente else ("mercado_prediccion" if clave == "polymarket" else "casa")
    return {"snapshot": sid, "proveedor": clave, "tipo": tipo,
            "capturado": capturado, "actualizado": actualizado, "cache": False,
            "desactualizado": not activa, "fecha_fuente": None,
            "eventos": eventos, "carteleras": [], "descartadas": descartadas}
