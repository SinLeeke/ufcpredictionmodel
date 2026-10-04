"""Catálogo y estadísticas descriptivas desde SQLite, sin consultar la red.

La identidad es el ID de la ficha, nunca el primer homónimo. El historial
antiguo solo tiene nombres: si hay dos fichas iguales se deja sin atribuir.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import date
import json
import logging
import math
import re
import threading
import time
from urllib.parse import urlsplit

import pandas as pd
import config as C
from src import storage as DB
from src.fighter_names import canonical_key, normalize_name

BIO = C.DATA_PROCESSED / "ufcstats_bio.csv"
FIGHTS = C.DATA_PROCESSED / "ufcstats_fights.csv"
STATS = C.DATA_PROCESSED / "ufcstats_fight_stats.csv"
CAREER = C.DATA_RAW / "ufcstats_cache.json"
RANKINGS = C.DATA_RAW / "rankings_oficiales.json"
_lock = threading.RLock()
_firma = None
_catalogo = None
_busqueda = ()
_comprobado = 0.0

PESOS = {"Flyweight": "Mosca", "Bantamweight": "Gallo", "Featherweight": "Pluma",
    "Lightweight": "Ligero", "Welterweight": "Wélter", "Middleweight": "Medio",
    "Light Heavyweight": "Semipesado", "Heavyweight": "Pesado",
    "Women's Strawweight": "Paja femenino", "Women's Flyweight": "Mosca femenino",
    "Women's Bantamweight": "Gallo femenino", "Women's Featherweight": "Pluma femenino",
    "Open Weight": "Peso abierto", "Catch Weight": "Peso pactado"}


def _limpio(v):
    if v is None or isinstance(v, float) and not math.isfinite(v):
        return None
    return v.item() if hasattr(v, "item") else v


def _agrupar_estadisticas(stats):
    # Una sola conversión conserva valores y orden, evitando crear miles de
    # pequeños DataFrames para las fichas. Igual que groupby, omite URLs nulas.
    resultado = {}
    for r in stats.to_dict('records'):
        if pd.notna(r['fight_url']):
            resultado.setdefault(r['fight_url'], []).append(r)
    return resultado


def _leer():
    global _firma, _catalogo, _busqueda, _comprobado
    paths = [BIO, FIGHTS, STATS, CAREER]
    with _lock:
        base, ahora = str(DB.db_path()), time.monotonic()
        if _firma is not None and _firma[0] == base and ahora - _comprobado < .25:
            return _catalogo
        firma = (base, tuple(DB.stat(p).st_mtime_ns if DB.exists(p) else 0 for p in paths))
        _comprobado = ahora
        if _firma == firma:
            return _catalogo
        bio = DB.read_csv(BIO) if DB.exists(BIO) else pd.DataFrame()
        fights = DB.read_csv(FIGHTS) if DB.exists(FIGHTS) else pd.DataFrame()
        stats = DB.read_csv(STATS) if DB.exists(STATS) else pd.DataFrame()
        fichas, nombres, historial = {}, defaultdict(list), defaultdict(list)
        for r in bio.to_dict("records"):
            m = re.fullmatch(r"https?://ufcstats.com/fighter-details/([a-f0-9]{16})", str(r.get("fighter_url", "")))
            if not m:
                continue
            r = {k: _limpio(v) for k, v in r.items()}
            r["id"] = m[1]
            fichas[m[1]] = r
            nombres[r["name"]].append(m[1])
        for r in fights.to_dict("records"):
            r = {k: _limpio(v) for k, v in r.items()}
            for lado in ("fighter_a", "fighter_b"):
                historial[r[lado]].append(r)
        for rows in historial.values():
            rows.sort(key=lambda r: r["date"], reverse=True)
        por_pelea = _agrupar_estadisticas(stats) if len(stats) else {}
        career = DB.read_json(CAREER) if DB.exists(CAREER) else {}
        indice = []
        for r in fichas.values():
            ambiguo = len(nombres[r['name']]) > 1
            h = [] if ambiguo else historial.get(r['name'], [])
            fila = {'id': r['id'], 'nombre': r['name'], 'homonimo': ambiguo,
                'peso': PESOS.get(h[0]['weight_class'], h[0]['weight_class']) if h else None,
                'peleas': len(h) if not ambiguo else None,
                'ultima': h[0]['date'] if h else None, 'nacimiento': r.get('dob')}
            indice.append((normalize_name(r['name']), r['id'], fila))
        _busqueda = tuple(sorted(indice, key=lambda entrada: entrada[:2]))
        _catalogo = fichas, nombres, historial, por_pelea, career
        _firma = firma
        return _catalogo


def buscar(q="", limite=40, offset=0):
    with _lock:
        _leer()
        indice = _busqueda
    consulta = normalize_name(q)
    rows = [r for normalizado, _, r in indice if not consulta or consulta in normalizado]
    from webui import identidad_visual as I
    seleccion = [dict(r) for r in rows[offset:offset + limite]]
    campeones = campeones_por_id()
    for r in seleccion:
        r["identidad_visual"] = I.metadatos(r["nombre"], r["id"], r["peso"])
        r["campeon"] = campeones.get(r["id"])
    return {"total": len(rows), "peleadores": seleccion, "offset": offset}


def _minutos(r):
    try:
        minutos, segundos = str(r["time"]).split(":")
        if r["weight_class"] == "Open Weight":
            return None  # asaltos antiguos de duración distinta: no adivinar
        return (int(r["round"]) - 1) * 5 + int(minutos) + int(segundos) / 60
    except (ValueError, TypeError, KeyError):
        return None


def perfil(identidad):
    fichas, nombres, historial, por_pelea, career = _leer()
    bio = fichas.get(identidad)
    if not bio:
        return None
    nombre = bio["name"]
    ambiguo = len(nombres[nombre]) > 1
    h = [] if ambiguo else historial.get(nombre, [])
    ultimas, totales, rivales, tiempo, n = [], Counter(), Counter(), 0.0, 0
    metodos = Counter()
    record = Counter()
    for r in h:
        rival = r["fighter_b"] if r["fighter_a"] == nombre else r["fighter_a"]
        resultado = "V" if r["winner"] == nombre else "P" if r["winner"] else "NC" if r["method_detail"] == "NC" else "E" if r["method_detail"] == "DRAW" else "?"
        record[resultado] += 1
        if resultado == "V":
            metodos[r["method"]] += 1
        ids = nombres.get(rival, [])
        ultimas.append({"fecha": r["date"], "evento": r["event"], "rival": rival,
            "rival_id": ids[0] if len(ids) == 1 else None, "resultado": resultado,
            "metodo": r["method_detail"] or r["method"], "asalto": r["round"], "tiempo": r["time"]})
        filas = por_pelea.get(r["fight_url"], [])
        propias = [x for x in filas if x["fighter"] == nombre]
        contrarias = [x for x in filas if x["fighter"] == rival]
        duracion = _minutos(r)
        if len(propias) == len(contrarias) == 1 and duracion and duracion > 0:
            for k, v in propias[0].items():
                if isinstance(v, (int, float)) and math.isfinite(v):
                    totales[k] += v
            for k, v in contrarias[0].items():
                if isinstance(v, (int, float)) and math.isfinite(v):
                    rivales[k] += v
            tiempo += duracion
            n += 1
    def ratio(a, b):
        return a / b if b else None
    metricas = {} if not n else {
        "slpm": ratio(totales["sig_landed"], tiempo), "sapm": ratio(rivales["sig_landed"], tiempo),
        "str_acc": ratio(totales["sig_landed"], totales["sig_att"]),
        "str_def": 1 - ratio(rivales["sig_landed"], rivales["sig_att"]) if rivales["sig_att"] else None,
        "td_avg": ratio(totales["td_landed"] * 15, tiempo),
        "td_acc": ratio(totales["td_landed"], totales["td_att"]),
        "td_def": 1 - ratio(rivales["td_landed"], rivales["td_att"]) if rivales["td_att"] else None,
        "sub_avg": ratio(totales["sub_att"] * 15, tiempo),
        "ctrl_avg": ratio(totales["ctrl_sec"] / 60 * 15, tiempo),
        "kd_avg": ratio(totales["kd"] * 15, tiempo)}
    # Una ficha de carrera solo se acepta con el mismo ID explícito.
    ficha = next((x for x in career.values() if x.get("ufcstats_url") == bio["fighter_url"]), None)
    fuente = "Peleas UFC con estadísticas y duración disponibles"
    if not metricas and ficha:
        metricas = {k: _limpio(ficha.get(k)) for k in ("slpm", "sapm", "str_acc", "str_def", "td_avg", "td_acc", "td_def", "sub_avg")}
        fuente = "Ficha de carrera UFCStats identificada por URL"
    try:
        nacimiento = date.fromisoformat(bio["dob"])
        hoy = date.today()
        edad = hoy.year - nacimiento.year - ((hoy.month, hoy.day) < (nacimiento.month, nacimiento.day))
    except (TypeError, ValueError):
        edad = None
    from webui import identidad_visual as I
    return {"id": identidad, "nombre": nombre, "bio": bio, "edad": edad, "homonimo": ambiguo,
        "identidad_visual": I.metadatos(nombre, identidad, PESOS.get(h[0]["weight_class"], h[0]["weight_class"]) if h else None),
        "peso": PESOS.get(h[0]["weight_class"], h[0]["weight_class"]) if h else None,
        "record": dict(record) if h else None, "historial": ultimas,
        "metricas": metricas, "metricas_fuente": fuente, "muestra": n,
        "zonas": {k: totales[f"{k}_landed"] for k in ("head", "body", "leg")} if n else {},
        "posiciones": {k: totales[f"{k}_landed"] for k in ("distance", "clinch", "ground")} if n else {},
        "victorias": dict(metodos), "actualizado": max((r["date"] for r in h), default=None),
        "campeon": campeones_por_id().get(identidad)}


_campeones_cache = (None, {})


def campeones_por_id():
    """{ID de UFCStats: campeón} según la última captura de rankings oficiales.

    El listado y el perfil lo usan para el fondo dorado de la foto. Sale de
    rankings(), que ya resolvió cada fila con identidad exacta (ficha UFC y
    nombre, sin adivinar entre homónimos): una fila sin ID no marca a nadie.
    Solo cuenta el puesto C de una división, nunca el libra por libra. Se
    recalcula cuando cambia la captura o el catálogo, no en cada búsqueda.
    """
    global _campeones_cache
    firma = (DB.signature(RANKINGS) if DB.exists(RANKINGS) else "0", _firma)
    if _campeones_cache[0] == firma:
        return _campeones_cache[1]
    mapa = {}
    for division in rankings()["divisiones"]:
        if division.get("p4p"):
            continue
        for r in division["peleadores"]:
            if r.get("puesto") == 0 and r.get("id") and r.get("campeon"):
                mapa.setdefault(r["id"], r["campeon"])
    _campeones_cache = (firma, mapa)
    return mapa


# Nombre canónico en inglés de cada clasificación (docs/contrato-datos.md). La
# captura de UFC llega en el idioma de la portada que respondió: desde Chile,
# ufcespanol.com, con traducciones automáticas como «Peso de la mujer» (paja)
# o «De peso pesado». El orden de esta tabla es el del menú lateral.
CLAVES = {
    "Men's Pound-for-Pound": "Men's Pound-for-Pound", "Libra por libra": "Men's Pound-for-Pound",
    "Flyweight": "Flyweight", "Peso mosca": "Flyweight", "Mosca": "Flyweight",
    "Bantamweight": "Bantamweight", "Peso gallo": "Bantamweight", "Gallo": "Bantamweight",
    "Featherweight": "Featherweight", "Peso pluma": "Featherweight", "Pluma": "Featherweight",
    "Lightweight": "Lightweight", "Ligero": "Lightweight", "Peso ligero": "Lightweight",
    "Welterweight": "Welterweight", "Peso welter": "Welterweight", "Wélter": "Welterweight",
    "Middleweight": "Middleweight", "Peso medio": "Middleweight", "Medio": "Middleweight",
    "Light Heavyweight": "Light Heavyweight", "Peso semipesado": "Light Heavyweight", "Semipesado": "Light Heavyweight",
    "Heavyweight": "Heavyweight", "De peso pesado": "Heavyweight", "Peso pesado": "Heavyweight", "Pesado": "Heavyweight",
    "Women's Pound-for-Pound": "Women's Pound-for-Pound",
    "Women's Strawweight": "Women's Strawweight", "Peso de la mujer": "Women's Strawweight",
    "Paja femenino": "Women's Strawweight", "Peso paja femenino": "Women's Strawweight",
    "Women's Flyweight": "Women's Flyweight", "Mosca femenino": "Women's Flyweight", "Peso mosca femenino": "Women's Flyweight",
    "Women's Bantamweight": "Women's Bantamweight", "Gallo de las mujeres": "Women's Bantamweight",
    "Gallo femenino": "Women's Bantamweight", "Peso gallo femenino": "Women's Bantamweight",
    "Women's Featherweight": "Women's Featherweight", "Pluma femenino": "Women's Featherweight",
}
ORDEN = {"M": ["Men's Pound-for-Pound", "Flyweight", "Bantamweight", "Featherweight", "Lightweight",
               "Welterweight", "Middleweight", "Light Heavyweight", "Heavyweight"],
         "F": ["Women's Pound-for-Pound", "Women's Strawweight", "Women's Flyweight",
               "Women's Bantamweight", "Women's Featherweight"]}


def _url_ufc(perfil):
    p = urlsplit(str(perfil or ''))
    if p.scheme == 'https' and p.hostname in ('ufc.com', 'www.ufc.com', 'ufcespanol.com', 'www.ufcespanol.com'):
        return 'https://www.ufc.com' + p.path.rstrip('/')
    return None


def _clave(nombre):
    texto = str(nombre or "").strip()
    if texto in CLAVES:
        return CLAVES[texto]
    if "pound-for-pound" in texto.lower() or "libra por libra" in texto.lower():
        return "Women's Pound-for-Pound" if re.search(r"women|mujer|femenin", texto, re.I) else "Men's Pound-for-Pound"
    return None


def _campeones(divisiones):
    """{URL de ficha: [(nombre, campeon)]}: el puesto 0 de cada división, sin el P4P.

    La URL es la identidad; el nombre (normalizado) se guarda para el control
    y para el caso raro de una fila sin URL, que sólo se atribuye si el nombre
    no lo comparte nadie más entre los campeones.
    """
    por_url, por_nombre = {}, defaultdict(list)
    for division in divisiones:
        if division.get("p4p"):
            continue
        for r in division["peleadores"]:
            if r.get("puesto") != 0:
                continue
            campeon = {"division": division["nombre"], "clave": division.get("clave"),
                       "interino": r.get("tipo") == "IC"}
            url = _url_ufc(r.get("perfil_ufc"))
            if url:
                por_url.setdefault(url, []).append((normalize_name(r["nombre"]), campeon))
            por_nombre[normalize_name(r["nombre"])].append((url, campeon))
    return por_url, por_nombre


def _campeon_p4p(r, por_url, por_nombre, no_calzan):
    nombre = normalize_name(r["nombre"])
    url = _url_ufc(r.get("perfil_ufc"))
    if url:
        candidatos = [c for n, c in por_url.get(url, []) if n == nombre]
        if por_url.get(url) and not candidatos:
            # Misma ficha, otro nombre: no se adivina cuál de las dos filas manda.
            no_calzan.append({"nombre": r["nombre"], "perfil_ufc": url, "motivo": "campeón con la misma ficha y otro nombre"})
        if candidatos:
            # Un doble campeón: el contrato tiene un solo objeto; va la división
            # más liviana (el orden de la captura), igual que la presenta UFC.
            return candidatos[0]
        # Sin URL de campeón que calce, el nombre sólo vale si el campeón con
        # ese nombre no tiene URL (si la tiene y es otra, es otra persona).
        sueltos = [c for u, c in por_nombre.get(nombre, []) if u is None]
        return sueltos[0] if len(sueltos) == 1 else None
    exactos = por_nombre.get(nombre, [])
    return exactos[0][1] if len(exactos) == 1 else None


def _divisiones_p4p(fila, divisiones, fecha):
    """Divisiones de la misma ficha y nombre, sin usar su historial como categoría actual.

    Un cambio de peso o un homónimo no se resuelve eligiendo la primera fila.
    Si la captura lista al atleta en dos pesos, se conservan ambos explícitamente.
    """
    nombre = normalize_name(fila["nombre"])
    perfil = _url_ufc(fila.get("perfil_ufc"))
    candidatos = []
    for division in divisiones:
        if division["p4p"] or division.get("clave") is None:
            continue
        for atleta in division["peleadores"]:
            if normalize_name(atleta["nombre"]) != nombre:
                continue
            ficha = _url_ufc(atleta.get("perfil_ufc"))
            if perfil and ficha and perfil != ficha:
                continue
            candidatos.append((ficha, division))
    if perfil:
        verificados = [division for ficha, division in candidatos if ficha == perfil]
        if not verificados:
            # Sin ficha coincidente solo se acepta una fila realmente sin URL.
            sueltos = [division for ficha, division in candidatos if ficha is None]
            verificados = sueltos if len(sueltos) == 1 else []
    else:
        fichas = {ficha for ficha, _ in candidatos if ficha}
        verificados = [division for _, division in candidatos] if len(fichas) <= 1 else []
    salida = []
    for division in verificados:
        if not any(d["clave"] == division["clave"] for d in salida):
            salida.append({"clave": division["clave"], "nombre": division["nombre"],
                           "fuente": "ranking", "fecha": fecha})
    return salida


def rankings():
    """/api/rankings según docs/contrato-datos.md (sección 1 y «En /api/rankings»).

    País por la URL de la ficha UFC de la fila (identidad exacta). Antes se
    buscaba por el ID de UFCStats o por el nombre, y además el registro de
    países sólo tenía a los 18 de UFC 333: 161 de 176 sin bandera. El dato
    se completa con `python -m src.rankings --paises`; esto nunca usa la red.
    """
    from urllib.parse import quote
    d = DB.read_json(RANKINGS) if DB.exists(RANKINGS) else {"divisiones": [], "fecha": None,
        "fuente": "https://www.ufc.com/rankings"}
    d.setdefault("fuente", "https://www.ufc.com/rankings")
    fichas, nombres, _, _, _ = _leer()
    from webui import paises, identidad_visual as I
    por_normalizado = defaultdict(list)
    for nombre, ids in nombres.items():
        por_normalizado[canonical_key(nombre)].extend(ids)
    no_calzan = []
    for division in d["divisiones"]:
        clave = _clave(division["nombre"])
        division["clave"] = clave
        division["genero"] = "F" if clave and clave.startswith("Women's") else "M"
        division["p4p"] = bool(clave and "Pound-for-Pound" in clave)
        if clave is None:
            no_calzan.append({"division": division["nombre"], "motivo": "división sin nombre canónico conocido"})
    por_url, por_nombre = _campeones(d["divisiones"])
    for division in d["divisiones"]:
        for r in division["peleadores"]:
            url = _url_ufc(r.get("perfil_ufc"))
            ids = nombres.get(r["nombre"], [])
            if not ids:
                # «Benoît Saint Denis» no está literal en UFCStats («Benoit
                # Saint Denis»): normalizado (con los alias verificados de
                # fighter_names) y exacto, y sólo si es único.
                ids = por_normalizado.get(canonical_key(r["nombre"]), [])
                if ids:
                    no_calzan.append({"nombre": r["nombre"], "ufcstats": [fichas[i]["name"] for i in ids],
                                      "motivo": "nombre distinto entre UFC y UFCStats; calza normalizado"})
            r["id"] = ids[0] if len(ids) == 1 else None
            if len(ids) > 1:
                verificadas = [i for i in ids if url and paises.identidad_ufc(i) == url]
                r['id'] = verificadas[0] if len(verificadas) == 1 else None
            r["identidad_visual"] = I.metadatos(r["nombre"], r["id"], division["nombre"])
            # La URL de la ficha identifica sin ambigüedad; el ID o el nombre
            # sólo quedan de respaldo para una fila sin URL.
            pais = paises.pais_perfil(r["nombre"], url) if url else None
            if pais is None and not url:
                pais = r["identidad_visual"].get("pais")
            r["pais"] = paises.contrato(pais)
            # Lo que hoy pinta explorar.js sale de identidad_visual: la misma
            # bandera en los dos lugares, nunca una distinta.
            r["identidad_visual"]["pais"] = r["pais"]
            if r["pais"] is None:
                no_calzan.append({"nombre": r["nombre"], "perfil_ufc": url, "motivo": "sin país en el registro"})
            if division["p4p"]:
                r["campeon"] = _campeon_p4p(r, por_url, por_nombre, no_calzan)
            elif r.get("puesto") == 0:
                r["campeon"] = {"division": division["nombre"], "clave": division["clave"],
                                "interino": r.get("tipo") == "IC"}
            else:
                r["campeon"] = None
            if division["p4p"]:
                categorias = _divisiones_p4p(r, d["divisiones"], d.get("fecha"))
            else:
                categorias = [{"clave": division["clave"], "nombre": division["nombre"],
                               "fuente": "ranking", "fecha": d.get("fecha")}] if division["clave"] else []
            r["divisiones"] = categorias
            r["division"] = categorias[0] if len(categorias) == 1 else next(
                (categoria for categoria in categorias
                 if r["campeon"] and categoria["clave"] == r["campeon"]["clave"]), None)
            r["foto"] = "/api/foto/" + quote(r["nombre"], safe="")
    grupos = []
    for titulo, genero in (("Hombres", "M"), ("Mujeres", "F")):
        indices = [i for i, x in enumerate(d["divisiones"]) if x["genero"] == genero]
        orden = ORDEN[genero]
        indices.sort(key=lambda i: (orden.index(d["divisiones"][i]["clave"])
                                    if d["divisiones"][i]["clave"] in orden else len(orden), i))
        if indices:
            grupos.append({"titulo": titulo, "divisiones": indices})
    d["grupos"] = grupos
    _registrar(no_calzan)
    return d


NO_CALZAN = []     # último registro de cruces fallidos, para pruebas y diagnóstico
_log = logging.getLogger(__name__)


def _registrar(no_calzan):
    """Lo que no calza se anota (contrato de datos), fuera del JSON público.

    Sin duplicados: un mismo atleta aparece en su división y en el P4P. Sólo
    se escribe al log cuando el registro cambia, no en cada petición.
    """
    global NO_CALZAN
    vistos, registro = set(), []
    for x in no_calzan:
        k = json.dumps(x, sort_keys=True, ensure_ascii=False)
        if k not in vistos:
            vistos.add(k)
            registro.append(x)
    if registro != NO_CALZAN:
        for x in registro:
            _log.info("rankings: no calza %s", x)
    NO_CALZAN = registro
