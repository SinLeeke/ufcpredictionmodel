"""Metadatos descriptivos de la UI; nunca entran en las features del modelo."""
from functools import lru_cache
import math
from numbers import Real
import re
import threading
import time

import config as C
from src import storage as DB

RANKINGS = C.DATA_RAW / "rankings_oficiales.json"
PESOS = {"Peso mosca": "Flyweight", "Mosca": "Flyweight", "Peso gallo": "Bantamweight", "Gallo": "Bantamweight",
    "Peso pluma": "Featherweight", "Pluma": "Featherweight", "Ligero": "Lightweight", "Peso ligero": "Lightweight", "Peso welter": "Welterweight", "Wélter": "Welterweight",
    "Peso medio": "Middleweight", "Medio": "Middleweight", "Peso semipesado": "Light Heavyweight", "Semipesado": "Light Heavyweight",
    "De peso pesado": "Heavyweight", "Pesado": "Heavyweight", "Peso de la mujer": "Women's Strawweight", "Paja femenino": "Women's Strawweight",
    "Gallo de las mujeres": "Women's Bantamweight", "Gallo femenino": "Women's Bantamweight", "Mosca femenino": "Women's Flyweight"}
_lock = threading.RLock()
_firma = None
_comprobado = 0.0
_datos = None


def insignia(valor):
    """Solo marcadores explícitos: una pelea por el título no convierte a nadie en C."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, Real):
        v = float(valor)
        return str(int(v)) if math.isfinite(v) and v.is_integer() and 1 <= v <= 99 else None
    text = str(valor or "").strip().upper()
    if text in ("C", "IC"):
        return text
    m = re.fullmatch(r"#?([1-9][0-9]?)", text)
    return str(int(m[1])) if m else None


@lru_cache(maxsize=2)
def _rankings(db, firma):
    return DB.read_json(RANKINGS) if firma else {"divisiones": [], "fecha": None}


def _documento():
    global _firma, _comprobado, _datos
    with _lock:
        base, ahora = str(DB.db_path()), time.monotonic()
        if _firma is not None and _firma[0] == base and ahora - _comprobado < .25:
            return _datos
        firma = DB.stat(RANKINGS).st_mtime_ns if DB.exists(RANKINGS) else None
        _datos = _rankings(base, firma)
        _firma, _comprobado = (base, firma), ahora
        return _datos


def _invalidar():
    global _firma
    with _lock:
        _firma = None


def metadatos(nombre, identidad=None, peso=None, corte=None, referencia=None):
    from webui import paises, catalogo
    from src.fighter_names import canonical_key
    pais = paises.lookup(nombre, identidad)
    referencia = referencia or {}
    # La referencia proviene de la pareja oficial guardada en la entrada CSV.
    # No se inventan fechas o cinturones para una repetición antigua.
    rango = insignia(referencia.get("rango"))
    fecha = referencia.get("fecha")
    if corte and fecha and fecha > corte:
        rango, fecha = None, None
    ficha, nombres, _, _, _ = catalogo._leer()
    ambiguo = len(nombres.get(nombre, [])) > 1
    nombre_fuente = referencia.get("nombre")
    # El CSV ya vinculó esta esquina con la pareja oficial. Recuperar su nombre
    # literal permite apóstrofes distintos sin buscar por semejanza ni elegir
    # uno de dos homónimos. La consulta de país sigue exigiendo match exacto.
    if (pais is None and not identidad and not ambiguo and isinstance(nombre_fuente, str)
            and canonical_key(nombre_fuente) == canonical_key(nombre)):
        pais = paises.lookup(nombre_fuente)
    vinculada = paises.identidad_ufc(identidad) if identidad and ambiguo else None
    d = _documento()
    rankings = []
    for division in d["divisiones"]:
        if corte and (not d.get("fecha") or d["fecha"] > corte):
            continue
        if "pound-for-pound" in division["nombre"].lower():
            continue
        for p in division["peleadores"]:
            if p["nombre"] != nombre or ambiguo and (not vinculada or p.get("perfil_ufc", "").replace("https://ufc.com", "https://www.ufc.com") != vinculada):
                continue
            rankings.append({"division": division["nombre"], "rango": "IC" if p.get("tipo") == "IC" else "C" if p["puesto"] == 0 else insignia(p["puesto"]), "fecha": d.get("fecha")})
    if not rango and (not corte or d.get("fecha") and d["fecha"] <= corte):
        posibles = [r for r in rankings if PESOS.get(r["division"], r["division"]) == PESOS.get(peso, peso)]
        if not posibles and not peso and len(rankings) == 1:
            posibles = rankings
        if len(posibles) == 1:
            rango, fecha = posibles[0]["rango"], posibles[0]["fecha"]
    if referencia.get("perfil"):
        # La URL identifica la esquina del evento, incluso cuando el historial
        # numérico antiguo no permite distinguir a dos personas del mismo nombre.
        pais = paises.lookup(referencia.get("nombre", nombre), referencia["perfil"]) or pais
    return {"pais": pais, "rango": rango, "ranking_fecha": fecha, "rankings": rankings}


def decorar_estado(estado, csv_path=None):
    # Durante la predicción sólo hace falta el progreso. Enriquecer los datos
    # anteriores abre SQLite y retrasa /estado mientras la nueva carga escribe.
    if estado.get("cargando") or not estado.get("datos"):
        return estado
    entradas = []
    if csv_path and DB.exists(csv_path):
        try:
            entradas = DB.read_csv(csv_path).to_dict("records")
        except (ValueError, KeyError):
            pass
    from src.fighter_names import canonical_key
    def pareja(a, b):
        return tuple(sorted((canonical_key(a), canonical_key(b))))
    por_par = {}
    for r in entradas:
        por_par.setdefault(pareja(r.get("fighter_a", ""), r.get("fighter_b", "")), []).append(r)
    peleas = []
    for p in estado["datos"]["peleas"]:
        pl = dict(p)
        candidates = por_par.get(pareja(p["a"], p["b"]), [])
        entrada = candidates[0] if len(candidates) == 1 else {}
        for lado in ("a", "b"):
            referencia = {}
            if entrada:
                fuente_lado = "a" if canonical_key(entrada["fighter_a"]) == canonical_key(p[lado]) else "b"
                referencia = {"rango": entrada.get("rango_" + fuente_lado),
                    "perfil": entrada.get("perfil_" + fuente_lado), "nombre": entrada["fighter_" + fuente_lado]}
                referencia = {k: v for k, v in referencia.items() if k == "rango" or isinstance(v, str) and v}
            pl["identidad_" + lado] = metadatos(p[lado], peso=entrada.get("weight_class") or (p.get("info_" + lado) or {}).get("weight_class"),
                corte=estado.get("corte"), referencia=referencia)
        peleas.append(pl)
    return {**estado, "datos": {**estado["datos"], "peleas": peleas}}
