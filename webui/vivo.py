"""Sección "Mercado en vivo" de Inicio: arma la respuesta de GET /api/mercado/vivo.

Contrato: docs/contrato-datos.md, sección 2.4. Sin evento en curso la
respuesta lleva "activo": false y la sección queda en modo manual: la lista
de peleas con cuotas guardadas ("opciones") y, si el usuario eligió una
("elegida"), su línea y su tabla con la misma forma que la pelea actual.

Como el resto de /api/mercado/*, NUNCA espera a la red: lee la caché de UFC.com
(calendario), el SQLite de la capa de cuotas y la caché de Polymarket que los
hilos de fondo ya dejaron escrita. La parte común (estados, cuotas, peleadores)
se memoriza unos segundos para que varias pestañas abiertas no repitan la
lectura de SQLite en cada poll.

Estado de cada pelea: qué se sabe y qué tan confiable es
--------------------------------------------------------
Nadie nos dice "esta pelea está en curso". Lo que hay, de más a menos fiable:

1. **Resultado en la base local** (UFCStats, src/corte._peleas): definitivo,
   pero casi nunca está durante el evento (la base se actualiza a mano).
2. **Polymarket resolvió el mercado de la pelea**: su descubrimiento (cada
   10 min en vivo) guarda aparte los moneyline cerrados con resolución final
   y precios EXACTOS 1/0. Se cruza el par exacto y la hora del evento. Es
   una resolución de mercado, que puede esperar al oráculo; no un resultado
   oficial de UFC. Una desaparición o suspensión no confirma que terminó.
3. **El orden de la cartelera** (UFC.com, la estelar primero; se pelea al
   revés): si una pelea posterior ya terminó, todas las anteriores también.
   Fiable mientras UFC no cambie el orden la misma noche.
4. **La hora de cada parte** (early / preliminares / estelar): una pelea cuya
   parte no empezó está "por pelear". Fiable.

Con eso, "en curso" es una ESTIMACIÓN: la primera pelea, en orden, que no
tiene señal de terminada y cuya parte ya empezó. Entre dos peleas (o mientras
se anuncia a los peleadores) seguirá diciendo "en curso" la que viene. No se
estima por minutos transcurridos: una pelea dura de 20 segundos a 25 minutos
y eso sería inventar. Cada pelea lleva `motivo` con la señal que decidió su
estado, para que la UI lo diga en voz alta.

Las resultados de UFC.com durante el evento NO se usan: src/ufc_oficial.py no
los parsea y la caché se refresca a lo más cada hora.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import threading
import time
from urllib.parse import quote

import config as C
from src.cuotas import calendario, cruce
from src.cuotas.tiempo import a_epoch, a_iso, ahora_iso

# La parte común se recalcula a lo más cada 4 s (el frontend pide cada ~12 s).
TTL_BASE = 4.0
# Un peleador (país, campeón) cambia mucho menos que una cuota.
TTL_PELEADOR = 600.0
# El gráfico muestra desde 3 h antes del inicio de la cartelera: el
# movimiento de la previa más todo el evento.
VENTANA_PREVIA = 3 * 3600
# Tope de puntos por serie en la carga completa: Polymarket en vivo deja un
# punto cada 30 s y 6 h serían 720 por casa. Con 8 series el JSON se iría a
# cientos de KB en cada poll; las siguientes lecturas son incrementales.
MAX_PUNTOS = 480
# Una fuente sin respuesta buena en 15 min ya no está "dando cuotas en vivo".
FRESCO_SEG = 15 * 60
NOTA = ("Cuotas de mercado de casas de apuestas y de Polymarket, tal como las publican. "
        "No son una recomendación ni una predicción del modelo.")

MOTIVOS = {
    "resultado": "Ya está en la base local con su resultado.",
    "mercado_cerrado": "Polymarket cerró su mercado: la pelea se resolvió.",
    "mercado_resuelto": "Mercado resuelto por Polymarket; no es un resultado oficial de UFC.",
    "mercado_simulado": "El mercado simulado de esta pelea cerró.",
    "orden": "Ya terminó una pelea que va después en la cartelera.",
    "estimado": ("Estimado: es la primera pelea sin señal de terminada de una parte ya empezada. "
                 "Entre peleas sigue marcando la que viene."),
    "horario": "Su parte de la cartelera todavía no empieza.",
    "siguiente": "Va después en el orden de la cartelera.",
    "sin_orden": "Sin cartelera oficial guardada para ordenarla.",
    "manual": "Marcada por ti en este navegador.",
}

_lock = threading.Lock()
_memo: tuple[float, tuple, dict] | None = None
_peleadores: dict[tuple, tuple[float, dict]] = {}
_base_res: tuple[float, set] | None = None


def olvidar() -> None:
    """Para los tests: que la próxima consulta recalcule todo."""
    global _memo, _base_res
    with _lock:
        _memo, _base_res = None, None
        _peleadores.clear()


# --------------------------------------------------------------------------- #
# Peleador (contrato §1)
# --------------------------------------------------------------------------- #
def _campeones() -> tuple[dict, dict]:
    from webui import catalogo
    from src import storage as DB
    try:
        d = DB.read_json(catalogo.RANKINGS) if DB.exists(catalogo.RANKINGS) else {"divisiones": []}
        return catalogo._campeones(d.get("divisiones") or [])
    except Exception:                                      # noqa: BLE001
        return {}, {}


def peleador(nombre: str, id_: str | None = None, perfil: str | None = None,
             campeones: tuple[dict, dict] | None = None) -> dict:
    """Peleador del contrato: nombre literal, id, perfil, país, campeón y foto.

    País por la ficha de UFC si la cartelera la trae (la URL es la identidad);
    si no, por el registro de países con nombre EXACTO (paises.lookup ya
    devuelve None para homónimos). Mejor sin bandera que con la de otro.
    """
    clave = (nombre, id_, perfil)
    ahora = time.monotonic()
    guardado = _peleadores.get(clave)
    if guardado and ahora - guardado[0] < TTL_PELEADOR:
        return guardado[1]
    from webui import catalogo, paises
    pais = None
    try:
        if perfil:
            pais = paises.pais_perfil(nombre, perfil)
        if pais is None:
            pais = paises.lookup(nombre, id_)
    except Exception:                                      # noqa: BLE001
        pais = None
    perfil_ufc = perfil or (pais or {}).get("identidad") or None
    campeon = None
    try:
        por_url, por_nombre = campeones if campeones is not None else _campeones()
        # La misma regla que el libra por libra de /api/rankings: por la URL de
        # la ficha con control de nombre, o por nombre solo si es único.
        campeon = catalogo._campeon_p4p({"nombre": nombre, "perfil_ufc": perfil_ufc},
                                        por_url, por_nombre, [])
    except Exception:                                      # noqa: BLE001
        campeon = None
    d = {"nombre": nombre, "id": id_, "perfil_ufc": perfil_ufc,
         "pais": paises.contrato(pais), "campeon": campeon,
         "foto": "/api/foto/" + quote(nombre, safe="")}
    _peleadores[clave] = (ahora, d)
    return d


# --------------------------------------------------------------------------- #
# Estados
# --------------------------------------------------------------------------- #
def estados(orden: list[dict], terminadas: dict[str, str], ahora: float) -> dict[str, tuple[str, str]]:
    """{pelea_id: (estado, motivo)} para peleas en el orden en que se pelean.

    `orden`: [{"pelea_id", "inicio_parte": epoch | None}], la primera que se pelea primero.
    `terminadas`: {pelea_id: motivo} con señal DIRECTA de terminada
    ("resultado" | "mercado_resuelto" | "mercado_simulado" | "manual").
    Ver el docstring del módulo para la confiabilidad de cada paso.
    """
    salida: dict[str, tuple[str, str]] = {}
    # 3. Orden: lo que va antes de la última pelea con señal también terminó.
    ultima = max((i for i, p in enumerate(orden) if p["pelea_id"] in terminadas), default=-1)
    actual_dado = False
    for i, p in enumerate(orden):
        pid = p["pelea_id"]
        if pid in terminadas:
            salida[pid] = ("terminada", terminadas[pid])
        elif i < ultima:
            salida[pid] = ("terminada", "orden")
        elif p.get("inicio_parte") is not None and p["inicio_parte"] > ahora:
            salida[pid] = ("por_pelear", "horario")
        elif not actual_dado:
            salida[pid] = ("en_curso", "estimado")
            actual_dado = True
        else:
            salida[pid] = ("por_pelear", "siguiente")
    return salida


def _resultados_base(pids: set[str], dia: str | None) -> set[str]:
    """Peleas del evento que ya están en la base local con resultado (señal 1)."""
    global _base_res
    ahora = time.monotonic()
    if _base_res is None or ahora - _base_res[0] > 60:
        hechos: set[str] = set()
        try:
            from src import corte
            import pandas as pd
            p = corte._peleas()
            if dia:
                p = p[p["date"] >= pd.Timestamp(dia) - pd.Timedelta(days=1)]
            # El par de corte usa canonical_key, igual que el pelea_id (sin los
            # alias manuales de la capa, que solo corrigen grafías de casas).
            hechos = {str(x) for x, w in zip(p["par"], p["winner"]) if isinstance(w, str) and w.strip()}
        except Exception:                                  # noqa: BLE001
            hechos = set()
        _base_res = (ahora, hechos)
    return pids & _base_res[1]


def _polymarket_resueltos(pids: set[str], ev: dict) -> dict[str, dict]:
    """Señal final de Gamma para ESTE evento; la caché no provoca consultas."""
    if not pids or not ev.get("inicio") or not ev.get("fin"):
        return {}
    from src.cuotas import historial as H
    from src.cuotas.fuentes.polymarket import resultado_de_mercado
    try:
        cache = H.leer_cache("polymarket") or {}
    except Exception:                                      # noqa: BLE001
        return {}
    inicio, fin = a_epoch(ev["inicio"]), a_epoch(ev["fin"])
    salida = {}
    for m in cache.get("resueltos") or []:
        if not isinstance(m, dict):
            continue
        try:
            ganador = resultado_de_mercado(m)
            pid = cruce.pelea_id(m["a"], m["b"])
            hora = a_epoch(m["inicio"])
            # Las parejas pueden repetirse en una revancha: una resolución
            # antigua no tiene permiso de cerrar su pelea de esta noche.
            if ganador is None or pid not in pids or not inicio - 12 * 3600 <= hora <= fin:
                continue
            if {cruce.clave(n) for n in m["outcomes"]} != set(pid.split("|")):
                continue
            salida[pid] = {"ganador_clave": cruce.clave(ganador)}
        except (KeyError, TypeError, ValueError):
            continue
    return salida


# --------------------------------------------------------------------------- #
# Cuotas
# --------------------------------------------------------------------------- #
def _orientar(pelea: dict | None, a: str) -> dict | None:
    """La pelea de la capa con `a` = la esquina roja de la cartelera oficial."""
    if pelea is None:
        return None
    from src.cuotas import consenso as K
    if cruce.clave(a) != pelea["pelea_id"].split("|")[0]:
        return K.invertir(pelea)
    return pelea


def _filas(cots: list[dict], nombres: dict[str, str]) -> list[dict]:
    """La tabla de la pelea actual: una fila por fuente × casa, mejor cuota marcada.

    "Mejor" = la que más paga (decimal más alto) entre CASAS. Polymarket queda
    fuera, como en consenso.mejor: su precio es un punto medio, no un precio
    comprable. Con empate se marcan todas: no hay por qué elegir una.
    """
    casas = [c for c in cots if c["tipo"] == "casa"]
    top = {lado: max((c[lado]["decimal"] for c in casas), default=None) for lado in ("a", "b")}
    filas = []
    for c in cots:
        filas.append({
            "fuente": c["fuente"], "fuente_nombre": nombres.get(c["fuente"], c["fuente"]),
            "casa": c["casa"], "tipo": c["tipo"],
            "a": {"americana": c["a"]["americana"], "prob": c["prob_sin_margen"]["a"]},
            "b": {"americana": c["b"]["americana"], "prob": c["prob_sin_margen"]["b"]},
            "margen": c.get("margen"), "visto": c.get("visto") or c.get("timestamp"),
            "mejor_a": c["tipo"] == "casa" and top["a"] is not None and c["a"]["decimal"] >= top["a"],
            "mejor_b": c["tipo"] == "casa" and top["b"] is not None and c["b"]["decimal"] >= top["b"],
        })
    # Casas primero (por nombre) y el mercado de predicción aparte, al final.
    filas.sort(key=lambda f: (f["tipo"] != "casa", f["casa"].lower(), f["fuente"]))
    return filas


def _recortar(series: list[dict], desde_iso: str) -> list[dict]:
    """Cada serie desde `desde_iso`, con el último valor anterior anclado al borde.

    Sin el ancla, una casa que no movió su línea en toda la noche no tendría
    ningún punto en la ventana y desaparecería del gráfico, cuando en realidad
    estuvo ahí todo el tiempo con la misma cuota.
    """
    salida = []
    for s in series:
        pts = s["puntos"]
        dentro = [p for p in pts if p["t"] >= desde_iso]
        antes = [p for p in pts if p["t"] < desde_iso]
        if antes:
            dentro.insert(0, {**antes[-1], "t": desde_iso})
        if len(dentro) > MAX_PUNTOS:
            # Se conservan el primero y los últimos: el final es lo que se está mirando.
            paso = len(dentro) / MAX_PUNTOS
            dentro = [dentro[int(i * paso)] for i in range(MAX_PUNTOS - 1)] + [dentro[-1]]
        if dentro:
            salida.append({**s, "puntos": dentro})
    return salida


def _etiqueta(s: dict) -> str:
    # Polymarket se llama siempre "Polymarket": es un mercado de predicción, no una casa.
    return "Polymarket" if s["fuente"] == "polymarket" else s["casa"]


def _unir_series(series: list[dict], vistos: dict[tuple, str], nombres: dict[str, str]) -> list[dict]:
    """Una serie por casa: si DraftKings llega por BFO y por The Odds API, va la más larga.

    En el gráfico dos líneas iguales con el mismo nombre solo ensucian; en la
    tabla, en cambio, se ven las dos filas con su fuente.
    """
    por_casa: dict[tuple, dict] = {}
    for s in series:
        k = (s["tipo"], "".join(ch for ch in s["casa"].lower() if ch.isalnum()))
        if k not in por_casa or len(s["puntos"]) > len(por_casa[k]["puntos"]):
            por_casa[k] = s
    salida = []
    for s in por_casa.values():
        salida.append({"fuente": s["fuente"], "fuente_nombre": nombres.get(s["fuente"], s["fuente"]),
                       "casa": s["casa"], "tipo": s["tipo"], "etiqueta": _etiqueta(s),
                       "hasta": vistos.get((s["fuente"], s["casa"])), "puntos": s["puntos"]})
    salida.sort(key=lambda s: (s["tipo"] != "casa", s["etiqueta"].lower()))
    return salida


# --------------------------------------------------------------------------- #
# Armado
# --------------------------------------------------------------------------- #
def _estado_fuentes(capa, simulado: bool, ahora: float) -> dict:
    """¿Hay alguna fuente dando cuotas? Coherente con el indicador "sin cuotas en vivo"."""
    if simulado:
        # La respuesta acaba de generar las cuotas en memoria. No pasan por
        # obtener()/marcar_ok() del hilo: su ultimo_ok puede estar vacío aun
        # cuando el gráfico está completo. La frescura de red solo corresponde
        # a fuentes reales; acá la lectura local satisfactoria es la señal.
        return {"fuentes": [{"clave": "simulada", "nombre": "Simulada", "tipo": "casa",
                             "ok": True, "motivo": None}],
                "todas_caidas": False, "con_error": []}
    lista = []
    for f in capa.fuentes:
        if (f.clave == "simulada") != simulado:
            continue
        try:
            e = f.estado(True)
        except Exception:                                  # noqa: BLE001
            continue
        if not e.get("activa"):
            continue
        ok = e.get("ultimo_ok")
        fresca = bool(ok) and ahora - a_epoch(ok) < FRESCO_SEG
        lista.append({"clave": e["clave"], "nombre": e["nombre"], "tipo": e["tipo"],
                      "ok": fresca, "motivo": e.get("motivo")})
    return {"fuentes": lista,
            "todas_caidas": bool(lista) and not any(x["ok"] for x in lista),
            "con_error": [x["nombre"] for x in lista if x["motivo"]]}


def _peleas_del_evento(ev: dict, simulado: bool, ahora: float) -> tuple[list[dict], dict, dict]:
    """(orden de pelea, pelea consolidada por pelea_id, series por pelea_id o {})."""
    from src.cuotas import capa as capa_mod
    oficiales = list(ev.get("peleas") or [])
    secciones = ev.get("secciones") or {}
    orden = []
    for p in reversed(oficiales):                       # UFC lista la estelar primero
        try:
            pid = cruce.pelea_id(p["a"], p["b"])
        except (KeyError, TypeError):
            continue
        parte = secciones.get(p.get("seccion") or "estelar") or ev.get("estelar")
        orden.append({"pelea_id": pid, "a": p["a"], "b": p["b"], "seccion": p.get("seccion"),
                      "peso": p.get("peso"), "titulo": bool(p.get("titulo")),
                      "perfil_a": p.get("perfil_a") or None, "perfil_b": p.get("perfil_b") or None,
                      "inicio_parte": a_epoch(parte) if parte else None})
    if simulado:
        from src.cuotas import simulado as SIM
        from src.cuotas import consenso as K
        crudo = SIM.datos(ahora)
        consolidadas, series = {}, {}
        for pid, d in crudo.items():
            cots = d["cotizaciones"]
            consolidadas[pid] = {"pelea_id": pid, "a": d["a"], "b": d["b"], "a_id": None, "b_id": None,
                                 "cotizaciones": cots, "consenso": K.consenso(cots), "mejor": K.mejor(cots)}
            series[pid] = d["series"]
        return orden, consolidadas, series
    capa = capa_mod.capa()
    peleas = capa.peleas()["peleas"]
    por_id = {p["pelea_id"]: p for p in peleas}
    if not orden:
        # Sin la cartelera oficial guardada no hay orden: se muestran las
        # peleas del mercado con el nombre del evento, sin inventar estados.
        nombre = str(ev.get("nombre") or "").lower()
        for p in peleas:
            if nombre and nombre in str(p.get("evento") or "").lower():
                orden.append({"pelea_id": p["pelea_id"], "a": p["a"], "b": p["b"], "seccion": None,
                              "peso": None, "titulo": False, "perfil_a": None, "perfil_b": None,
                              "inicio_parte": None, "sin_orden": True})
    return orden, por_id, {}


def _base(ev: dict, ahora: float) -> dict:
    from src.cuotas import capa as capa_mod
    simulado = bool(ev.get("simulado"))
    capa = capa_mod.capa()
    nombres = {f.clave: f.nombre for f in capa.fuentes}
    nombres.setdefault("simulada", "Simulada")
    orden, por_id, series_sim = _peleas_del_evento(ev, simulado, ahora)
    pids = {p["pelea_id"] for p in orden}

    # Señales directas de "terminada".
    terminadas: dict[str, str] = {}
    resueltos: dict[str, dict] = {}
    if simulado:
        from src.cuotas import simulado as SIM
        terminadas = {pid: "mercado_simulado" for pid in SIM.cerradas(ahora) & pids}
    else:
        dia = None
        if ev.get("estelar"):
            dia = datetime.fromtimestamp(a_epoch(ev["estelar"])).date().isoformat()
        for pid in _resultados_base(pids, dia):
            terminadas[pid] = "resultado"
        resueltos = _polymarket_resueltos(pids, ev)
        for pid in resueltos:
            terminadas.setdefault(pid, "mercado_resuelto")

    sin_orden = any(p.get("sin_orden") for p in orden)
    est = ({p["pelea_id"]: ("por_pelear", "sin_orden") for p in orden} if sin_orden
           else estados(orden, terminadas, ahora))
    for pid, motivo in terminadas.items():               # una señal directa manda siempre
        est[pid] = ("terminada", motivo)

    campeones = _campeones()
    peleas = []
    for p in orden:
        pelea = _orientar(por_id.get(p["pelea_id"]), p["a"])
        estado, motivo = est.get(p["pelea_id"], ("por_pelear", "siguiente"))
        a_id = (pelea or {}).get("a_id") or cruce.resolver(p["a"], p["b"]).id
        b_id = (pelea or {}).get("b_id") or cruce.resolver(p["b"], p["a"]).id
        resolucion = None
        if p["pelea_id"] in resueltos:
            gana_a = resueltos[p["pelea_id"]]["ganador_clave"] == cruce.clave(p["a"])
            resolucion = {"fuente": "polymarket", "ganador": p["a"] if gana_a else p["b"],
                          "a": 1 if gana_a else 0, "b": 0 if gana_a else 1,
                          "oficial": False, "etiqueta": "Mercado resuelto"}
        peleas.append({
            "pelea_id": p["pelea_id"],
            "a": peleador(p["a"], a_id, p["perfil_a"], campeones),
            "b": peleador(p["b"], b_id, p["perfil_b"], campeones),
            "estado": estado, "motivo_clave": motivo, "motivo": MOTIVOS.get(motivo),
            "seccion": p["seccion"], "peso": p["peso"], "titulo": p["titulo"],
            "inicio_parte": a_iso(p["inicio_parte"]) if p["inicio_parte"] else None,
            "consenso": (pelea or {}).get("consenso"),
            "resolucion": resolucion,
            "_pelea": pelea,
        })

    # La pelea actual: la que está en curso; si no hay, la próxima por pelear;
    # si ya terminaron todas, la última (la estelar).
    actual = (next((x for x in peleas if x["estado"] == "en_curso"), None)
              or next((x for x in peleas if x["estado"] == "por_pelear"), None)
              or (peleas[-1] if peleas else None))
    return {"simulado": simulado, "peleas": peleas, "actual": actual,
            "series_sim": series_sim, "nombres": nombres,
            "mercado": _estado_fuentes(capa, simulado, ahora)}


def _series_actual(base: dict, ev: dict, desde: str | None, pelea_id: str | None) -> tuple[list[dict], bool]:
    """Series del gráfico de la pelea actual. Incrementales si el cliente ya tiene esa pelea."""
    actual = base["actual"]
    pid, a = actual["pelea_id"], actual["a"]["nombre"]
    inicio = ev.get("inicio")
    ventana = a_iso(a_epoch(inicio) - VENTANA_PREVIA) if inicio else None
    if base["simulado"]:
        crudas = base["series_sim"].get(pid, [])
        if cruce.clave(a) != pid.split("|")[0]:
            crudas = [{**s, "puntos": [{"t": q["t"], "a": q["b"], "b": q["a"], "pa": q["pb"], "pb": q["pa"]}
                                       for q in s["puntos"]]} for s in crudas]
    else:
        from src.cuotas import capa as capa_mod
        crudas = capa_mod.capa().historial(pid, None, a)["series"]
    pelea = actual.get("_pelea") or {}
    vistos = {(c["fuente"], c["casa"]): c.get("visto") for c in pelea.get("cotizaciones", [])}
    incremental = bool(desde) and pelea_id == pid
    if incremental:
        crudas = [{**s, "puntos": [q for q in s["puntos"] if q["t"] > desde]} for s in crudas]
    elif ventana:
        crudas = _recortar(crudas, ventana)
    return _unir_series(crudas, vistos, base["nombres"]), incremental


def _marcas_manual(base: dict, ev: dict, terminadas: list[str] | None,
                   evento_id: str | None, ahora: float) -> dict:
    """Marcas de una petición: se aplican a una copia, nunca a la memoria común."""
    if not terminadas or evento_id != ev.get("id"):
        return base
    marcadas = {p for p in terminadas if isinstance(p, str)}
    peleas = [dict(p) for p in base["peleas"]]
    senales = {p["pelea_id"]: p["motivo_clave"] for p in peleas
               if p["estado"] == "terminada" and p["motivo_clave"] != "orden"}
    for p in peleas:
        pid = p["pelea_id"]
        if pid in marcadas and pid not in senales:
            senales[pid] = "manual"
    orden = [{"pelea_id": p["pelea_id"],
              "inicio_parte": a_epoch(p["inicio_parte"]) if p["inicio_parte"] else None} for p in peleas]
    sin_orden = any(p["motivo_clave"] == "sin_orden" for p in peleas)
    nuevos = ({p["pelea_id"]: ("terminada", senales[p["pelea_id"]])
               if p["pelea_id"] in senales else ("por_pelear", "sin_orden") for p in peleas}
              if sin_orden else estados(orden, senales, ahora))
    for p in peleas:
        estado, motivo = nuevos[p["pelea_id"]]
        p.update({"estado": estado, "motivo_clave": motivo, "motivo": MOTIVOS.get(motivo)})
    actual = (next((p for p in peleas if p["estado"] == "en_curso"), None)
              or next((p for p in peleas if p["estado"] == "por_pelear"), None)
              or (peleas[-1] if peleas else None))
    return {**base, "peleas": peleas, "actual": actual}


def _manual(elegida: str | None, desde_iso: str | None, pelea_id: str | None, t: float) -> dict:
    """Sin evento en curso: la pelea que eligió el usuario, de lo que la capa ya guardó.

    Nada de red: con EN VIVO encendido el ciclo de Betano confirma la cuota
    cada 10 s (una cuota igual adelanta su `visto`), y la línea llega hasta
    esa confirmación. Sin elegir, solo la lista para el selector.
    """
    salida = {"activo": False, "opciones": [], "actual": None, "nota": NOTA, "consultado": a_iso(t)}
    try:
        from src.cuotas import capa as capa_mod
        capa = capa_mod.capa()
        peleas = capa.peleas()["peleas"]
    except Exception:                                      # noqa: BLE001
        return salida
    salida["opciones"] = [{k: p[k] for k in ("pelea_id", "a", "b", "evento", "fecha")} for p in peleas]
    p = next((x for x in peleas if x["pelea_id"] == elegida), None) if elegida else None
    if p is None:
        return salida
    nombres = {f.clave: f.nombre for f in capa.fuentes}
    filas = _filas(p["cotizaciones"], nombres)
    vistos = {(c["fuente"], c["casa"]): c.get("visto") for c in p["cotizaciones"]}
    crudas = capa.historial(p["pelea_id"], None, p["a"])["series"]
    incremental = bool(desde_iso) and pelea_id == p["pelea_id"]
    if incremental:
        crudas = [{**s, "puntos": [q for q in s["puntos"] if q["t"] > desde_iso]} for s in crudas]
    else:
        crudas = _recortar(crudas, a_iso(t - VENTANA_PREVIA))
    campeones = _campeones()
    salida["actual"] = {"pelea_id": p["pelea_id"], "evento": p["evento"], "fecha": p["fecha"],
                        "a": peleador(p["a"], p.get("a_id"), None, campeones),
                        "b": peleador(p["b"], p.get("b_id"), None, campeones),
                        "mejor": p.get("mejor"), "cotizaciones": filas,
                        "series": _unir_series(crudas, vistos, nombres), "incremental": incremental,
                        "actualizado": max((f["visto"] for f in filas if f["visto"]), default=None)}
    return salida


def vivo(desde: str | None = None, pelea_id: str | None = None, ahora: float | None = None,
         terminadas: list[str] | None = None, evento_id: str | None = None,
         elegida: str | None = None) -> dict:
    """La respuesta de /api/mercado/vivo. `desde`/`pelea_id`: el cliente ya tiene la serie hasta ahí.

    `elegida` solo cuenta sin evento en curso (modo manual, ver _manual).
    """
    global _memo
    ev = calendario.evento_en_vivo(ahora)
    t = time.time() if ahora is None else ahora
    if ev is None:
        try:
            desde_iso = a_iso(desde) if desde else None
        except (TypeError, ValueError):
            desde_iso = None
        return _manual(elegida, desde_iso, pelea_id, t)
    clave = (ev.get("id"), bool(ev.get("simulado")))
    with _lock:
        if ahora is None and _memo and _memo[1] == clave and time.monotonic() - _memo[0] < TTL_BASE:
            base = _memo[2]
        else:
            base = _base(ev, t)
            if ahora is None:
                _memo = (time.monotonic(), clave, base)
    base = _marcas_manual(base, ev, terminadas, evento_id, t)
    desde_iso = None
    if desde:
        try:
            desde_iso = a_iso(desde)
        except (TypeError, ValueError):
            desde_iso = None

    salida = {"activo": True, "simulado": base["simulado"],
              "evento": {"id": ev.get("id"), "nombre": ev.get("nombre"), "inicio": ev.get("inicio"),
                         "estelar": ev.get("estelar")},
              "actual": None,
              "peleas": [{k: v for k, v in p.items() if k != "_pelea"} for p in base["peleas"]],
              "mercado": base["mercado"], "nota": NOTA, "consultado": a_iso(t)}
    actual = base["actual"]
    if actual is not None:
        pelea = actual.get("_pelea") or {}
        filas = _filas(pelea.get("cotizaciones", []), base["nombres"])
        series, incremental = _series_actual(base, ev, desde_iso, pelea_id)
        salida["actual"] = {**{k: v for k, v in actual.items() if k != "_pelea"},
                            "mejor": pelea.get("mejor"), "cotizaciones": filas,
                            "series": series, "incremental": incremental,
                            "actualizado": max((f["visto"] for f in filas if f["visto"]), default=None)}
        salida["mercado"] = {**base["mercado"], "hay_cuotas": bool(filas)}
    else:
        salida["mercado"] = {**base["mercado"], "hay_cuotas": False}
    return salida
