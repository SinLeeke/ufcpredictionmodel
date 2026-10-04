"""
corte.py
La REPETICIÓN: predecir una cartelera que ya pasó como si fuera el día del
evento, con SOLO lo que se sabía antes de esa fecha.

Por qué no basta con volver a cargar el CSV viejo: la predicción normal
(card.predict_card) usa la ficha de UFCStats de HOY, el ELO final y un modelo
entrenado con todo hasta el corte de Kaggle. Para una pelea que ya se peleó, las
tres cosas saben cómo terminó: el récord, la racha y los promedios incluyen esa
pelea y las posteriores, el ELO ya sumó o restó el resultado, y el modelo pudo
entrenar con ella. Es el mismo leakage que hizo "acertar" 92% al backtest de
carteleras (ver modelado/backtest_carteleras.py, que usa estas funciones).

Acá cada pieza se recorta a la fecha de corte, siempre con `<` estricto:
  * stats del peleador -> recalculadas desde el historial pelea a pelea
  * ELO                -> tabla reconstruida con las peleas anteriores
  * oposición, corto aviso y últimas cinco -> ya reciben la fecha
  * modelos            -> si el de producción entrenó con peleas desde el corte,
                          se entrena otro SOLO con las anteriores, con los mismos
                          hiperparámetros, y se guarda en models/corte/.

Lo que NO se recorta, y la UI lo dice: los dos calibradores (dos números cada
uno, ajustados con todo el historial) y los hiperparámetros, que se eligieron
mirando peleas posteriores. Ninguno puede aprender el resultado de una pelea
puntual, pero no son 100% ciegos al futuro.

El resultado real se lee DESPUÉS de predecir y solo para mostrarlo: no entra a
ningún cálculo.
"""
from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

import config as C
from src import storage as DB
from src.fighter_names import canonical_key, normalize_name

# Kaggle empieza en 2010. Antes de 2013 la ventana de entrenamiento tendría 2-3
# años de peleas: eso no es "el sistema de ese día", es otro modelo peor.
FECHA_MINIMA = pd.Timestamp("2013-01-01")
MIN_FILAS_ENTRENAMIENTO = 2000
CARPETA_MODELOS = C.MODELS / "corte"
PELEAS_CSV = C.DATA_PROCESSED / "ufcstats_fights.csv"


# --------------------------------------------------------------------------- #
# La fecha
# --------------------------------------------------------------------------- #
def a_fecha(valor) -> pd.Timestamp | None:
    """'AAAA-MM-DD' -> Timestamp. None si viene vacía; ValueError si no sirve."""
    if valor is None:
        return None
    txt = str(valor).strip()
    if not txt:
        return None
    fecha = pd.to_datetime(txt, format="%Y-%m-%d", errors="coerce")
    if pd.isna(fecha):
        raise ValueError(f"La fecha de corte tiene que ir como AAAA-MM-DD (llegó «{txt}»).")
    fecha = fecha.normalize()
    if fecha > pd.Timestamp.now().normalize():
        raise ValueError("La fecha de corte no puede ser futura: no habría nada que recortar.")
    if fecha < FECHA_MINIMA:
        raise ValueError(f"La base no alcanza para antes de {FECHA_MINIMA.year}: "
                         "el modelo no tendría con qué entrenar.")
    return fecha


# --------------------------------------------------------------------------- #
# Datos locales (se cargan una vez por proceso)
# --------------------------------------------------------------------------- #
_HIST: pd.DataFrame | None = None
_PELEAS: pd.DataFrame | None = None
_BIO: dict | None = None
_HOMONIMOS: set | None = None
_NOMBRES: dict | None = None
_KAGGLE: dict | None = None
_ELO_POR_FECHA: dict = {}


def _clave_par(a: str, b: str) -> str:
    """El par sin orden: las fuentes no coinciden en quién va primero."""
    return "|".join(sorted((canonical_key(a), canonical_key(b))))


_FIRMA: tuple | None = None


def _al_dia() -> None:
    """
    Suelta los cachés si la base cambió en disco. La UI queda abierta durante
    "Actualizar todo" (que corre aparte): sin esto, las peleas nuevas no
    aparecían en la lista hasta reiniciar el servidor.
    """
    global _FIRMA, _HIST, _PELEAS, _BIO, _HOMONIMOS, _NOMBRES
    from src.ufcstats_ingest import STATS_CSV
    firma = tuple(DB.signature(r)
                  for r in (PELEAS_CSV, STATS_CSV, C.DATA_PROCESSED / "ufcstats_bio.csv"))
    if firma != _FIRMA:
        _FIRMA = firma
        _HIST = _PELEAS = _BIO = _HOMONIMOS = _NOMBRES = None


def _historial() -> pd.DataFrame:
    """Una fila por peleador y pelea, con los números del rival al lado."""
    global _HIST
    _al_dia()
    if _HIST is None:
        from src.ufcstats_ingest import _emparejar, cargar
        _HIST = _emparejar(cargar()).sort_values("date")
    return _HIST


def _peleas() -> pd.DataFrame:
    """Resultados de UFCStats, una fila por pelea, de la más nueva a la más vieja."""
    global _PELEAS
    _al_dia()
    if _PELEAS is None:
        if not DB.exists(PELEAS_CSV):
            raise FileNotFoundError("Falta ufcstats_fights.csv: corre 'Resultados de UFCStats' "
                                    "en Mantenimiento.")
        p = DB.read_csv(PELEAS_CSV)
        p["date"] = pd.to_datetime(p["date"], errors="coerce")
        p = p.dropna(subset=["date", "fighter_a", "fighter_b", "event"])
        p["par"] = [_clave_par(a, b) for a, b in zip(p["fighter_a"], p["fighter_b"])]
        p["estelar"] = [_es_estelar(e, a, b) for e, a, b in
                        zip(p["event"], p["fighter_a"], p["fighter_b"])]
        _PELEAS = p.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)
    return _PELEAS


def _es_estelar(evento: str, a: str, b: str) -> bool:
    """
    La estelar es la que nombra el evento ("UFC 322: Della Maddalena vs.
    Makhachev"). El orden de las filas no sirve: UFCStats no siempre lista la
    estelar primero.
    """
    titulo = str(evento).split(":", 1)[-1]
    if " vs" not in titulo.lower():
        return False
    palabras = set(normalize_name(titulo).split())
    apellidos = [(normalize_name(n).split() or [""])[-1] for n in (a, b)]
    return all(ap and ap in palabras for ap in apellidos)


def _bio() -> tuple[dict, set]:
    """(biometría por nombre en minúsculas, nombres con más de un dueño)."""
    global _BIO, _HOMONIMOS
    _al_dia()
    if _BIO is None:
        from src.ufcstats_ingest import _cargar_bio
        _BIO = _cargar_bio()
        ruta = C.DATA_PROCESSED / "ufcstats_bio.csv"
        nombres = (DB.read_csv(ruta, usecols=["name"])["name"].dropna().astype(str)
                   .str.strip().str.lower() if DB.exists(ruta) else pd.Series(dtype=str))
        cuenta = nombres.value_counts()
        _HOMONIMOS = set(cuenta[cuenta > 1].index)
    return _BIO, _HOMONIMOS


def nombre_local(nombre: str) -> str | None:
    """
    El nombre exacto con que la base local conoce a este peleador, o None.

    Solo por identidad verificada (canonical_key: "Ian Garry" y "Ian Machado
    Garry" son la misma persona). Nada de parecidos ni apellidos: el cruce por
    nombre causó los dos bugs más caros del proyecto.
    """
    global _NOMBRES
    _al_dia()
    if _NOMBRES is None:
        indice: dict[str, str] = {}
        for n in _historial()["fighter"].dropna().unique():
            indice.setdefault(canonical_key(n), str(n))
        p = _peleas()
        for n in pd.concat([p["fighter_a"], p["fighter_b"]]).dropna().unique():
            indice.setdefault(canonical_key(n), str(n))
        ruta = C.DATA_PROCESSED / "ufcstats_bio.csv"
        if DB.exists(ruta):
            for n in DB.read_csv(ruta, usecols=["name"])["name"].dropna().astype(str):
                indice.setdefault(canonical_key(n), n.strip())
        _NOMBRES = indice
    return _NOMBRES.get(canonical_key(nombre))


# --------------------------------------------------------------------------- #
# El peleador al día del corte
# --------------------------------------------------------------------------- #
def _completar(d: dict, nombre: str, fecha: pd.Timestamp) -> dict:
    """Biometría a la fecha, control/grappling recortado y Sherdog si hay pocas peleas."""
    bio, homonimos = _bio()
    if nombre.lower() in homonimos:
        # Dos peleadores con este nombre en UFCStats. El historial local no los
        # separa, así que tampoco se elige una biometría: mejor sin dato que con
        # el de otro (ver docs/auditoria-identidades.md).
        d["identidad_ambigua"] = True
    else:
        b = bio.get(nombre.lower())
        if b:
            d["height_cm"], d["reach_cm"] = b["height_cm"], b["reach_cm"]
            d["stance"] = b["stance"]
            if pd.notna(b["dob"]):
                d["age"] = round((fecha - b["dob"]).days / 365.25, 1)

    from src.control_stats import enriquecer
    d = enriquecer(d, fecha)          # control también recortado a la fecha
    # Con pocas peleas en UFC, completar con la carrera completa (Sherdog),
    # recortada TAMBIÉN a la fecha para no mirar el futuro.
    n_ufc = d.get("n_peleas_hist")
    if n_ufc is not None and int(n_ufc) < 3:
        try:
            from src import sherdog
            antes = d.get("wins", 0)
            d = sherdog.completar(d, hasta=fecha)
            if d.get("wins", 0) != antes:
                d["_sherdog"] = True
        except Exception:
            pass
    return d


def stats_a_fecha(nombre: str, fecha) -> dict | None:
    """
    Stats del peleador usando SOLO sus peleas anteriores a `fecha`, o None si
    no tiene ninguna. Por qué no la ficha de UFCStats: muestra los promedios de
    HOY, que ya incluyen las peleas posteriores.

    Es la receta del backtest de carteleras: golpeo, derribos, récord, racha,
    edad y control, todo a la fecha.
    """
    from src.ufcstats_ingest import _acumulado
    fecha = pd.Timestamp(fecha)
    h = _historial()
    sub = h[(h["fighter"] == nombre) & (h["date"] < fecha)]
    if sub.empty:
        return None
    d = _acumulado(sub)
    d["name"] = nombre
    d["days_since_last_fight"] = float((fecha - sub["date"].max()).days)
    return _completar(d, nombre, fecha)


def _peleas_ufc_previas(nombre: str, fecha: pd.Timestamp) -> tuple[int | None, bool]:
    """(peleas en UFC antes del corte, si ese conteo es confiable)."""
    from src.ufc_history import is_ufc_event
    p = _peleas()
    sub = p[((p["fighter_a"] == nombre) | (p["fighter_b"] == nombre)) & (p["date"] < fecha)]
    clases = [is_ufc_event(e) for e in sub["event"]]
    if any(c is None for c in clases):
        return None, False
    _, homonimos = _bio()
    # Si el corte cae después de la última pelea de la base, lo que pasó en el
    # medio no está: un "0" ahí no prueba un debut.
    completo = fecha <= p["date"].max() + pd.Timedelta(days=1)
    return sum(1 for c in clases if c), completo and nombre.lower() not in homonimos


def ficha_a_fecha(nombre: str, fecha) -> tuple[dict | None, str]:
    """
    (stats, fuente) como card.get_stats, pero al día del corte.

    Quien está en la base pero no tenía peleas antes del corte era, para el
    sistema de ese día, un debutante: recibe la ficha vacía que UFCStats le
    muestra a un debutante (todo en cero). Ese cero funciona como "no probado"
    (ver CLAUDE.md, "Un peleador sin datos NO es un punto ciego"), y la pelea
    sale NO FIABLE como cualquier otra con menos de 3 peleas.
    """
    local = nombre_local(nombre)
    if local is None:
        return None, "NO_ENCONTRADO"
    fecha = pd.Timestamp(fecha)
    d = stats_a_fecha(local, fecha)
    if d is None:
        from src.ufcstats_ingest import _acumulado
        d = _acumulado(_historial().iloc[0:0])
        # Sin intentos del rival, _acumulado deja la defensa en 100%. Una ficha
        # vacía de UFCStats dice 0%: es lo que el modelo vio en los debutantes.
        d.update({"name": local, "str_def": 0.0, "td_def": 0.0, "days_since_last_fight": 0.0})
        d = _completar(d, local, fecha)
    n_ufc, confirmado = _peleas_ufc_previas(local, fecha)
    d["n_peleas_ufc"] = n_ufc
    d["historial_ufc_confirmado"] = confirmado
    return d, "historial"


def elo_a_fecha(nombre: str, fecha) -> float:
    """
    ELO del peleador ANTES del corte: solo cuentan las peleas anteriores a
    `fecha`. Con la tabla final, el ganador tenía más ELO el 72% de las veces
    contra 58% con el pre-pelea (medido en 203 peleas). Se elige la fila con la
    misma regla que usa card.py al predecir.
    """
    from src import oposicion
    from src.card import elo_de_tabla
    fecha = pd.Timestamp(fecha)
    if fecha not in _ELO_POR_FECHA:
        if DB.exists(C.DATA_RAW / "kaggle_ufc.csv"):
            from src.kaggle_ingest import tabla_elo
            _ELO_POR_FECHA[fecha] = tabla_elo(hasta=fecha)
        elif DB.exists(C.ELO_TABLE):
            _ELO_POR_FECHA[fecha] = DB.read_csv(C.ELO_TABLE)
        else:
            _ELO_POR_FECHA[fecha] = pd.DataFrame(columns=["weight_class", "fighter", "elo"])
    elo = elo_de_tabla(_ELO_POR_FECHA[fecha], nombre, oposicion.ultima_division(nombre, fecha))
    return elo if elo is not None else C.ELO_BASE


def corte_efectivo(pares: list[tuple[str, str]], fecha) -> pd.Timestamp:
    """
    El corte pedido, o la fecha de UFCStats del evento si alguna pelea de la
    cartelera figura en los 3 días ANTERIORES.

    Betano fecha en hora de Chile y UFCStats en la del lugar del evento: una
    cartelera de Australia puede quedar un día antes en la base. Sin esto, cortar
    en la fecha del archivo dejaba la pelea misma DENTRO de los datos. Nadie
    vuelve a pelear con el mismo rival en tres días, así que la ventana no
    confunde una revancha.
    """
    fecha = pd.Timestamp(fecha)
    claves = {_clave_par(a, b) for a, b in pares}
    p = _peleas()
    cerca = p[(p["date"] < fecha) & (p["date"] >= fecha - pd.Timedelta(days=3))
              & p["par"].isin(claves)]
    return min([fecha, *cerca["date"].tolist()])


def base_hasta() -> pd.Timestamp | None:
    """Fecha de la última pelea que tiene la base local."""
    try:
        return _peleas()["date"].max()
    except FileNotFoundError:
        return None


# --------------------------------------------------------------------------- #
# Los modelos al día del corte
# --------------------------------------------------------------------------- #
def modelos_a_fecha(fecha, avisar: Callable[[str], None] | None = None) -> dict:
    """
    Modelos que NO vieron ninguna pelea desde `fecha`.

    El de producción entrena con todo features.csv. Si el corte es posterior a
    su última fila, ya es ciego al corte y se usa tal cual. Si no, se entrena
    uno con las filas ESTRICTAMENTE anteriores, con la misma ventana y los
    mismos hiperparámetros (modelado/train_model.ajustar_modelos), y queda en
    models/corte/ para no repetirlo. La firma de features.csv invalida esa copia
    cuando la base se actualiza.
    """
    fecha = pd.Timestamp(fecha).normalize()
    avisar = avisar or (lambda _txt: None)
    if not DB.exists(C.FEATURES_CSV):
        return _modelos_produccion(None)
    df = DB.read_csv(C.FEATURES_CSV)
    df["date"] = pd.to_datetime(df["date"])
    fin = df["date"].max()
    if fecha > fin:
        return _modelos_produccion(fin)

    ruta = CARPETA_MODELOS / f"{fecha:%Y-%m-%d}.pkl"
    firma = f"{DB.signature(C.FEATURES_CSV)}:{len(df)}"
    if DB.exists(ruta):
        try:
            with DB.open_file(ruta, "rb") as fh:
                guardado = pickle.load(fh)
            if guardado.get("firma") == firma:
                return guardado["modelos"]
        except Exception:                                   # noqa: BLE001
            pass                                            # copia rota: se rehace

    previo = df[df["date"] < fecha]
    from modelado.train_model import ajustar_modelos, ventana
    full = ventana(previo, previo["date"].max()) if not previo.empty else previo
    if len(full) < MIN_FILAS_ENTRENAMIENTO:
        raise ValueError(f"Antes del {fecha:%d-%m-%Y} hay muy pocas peleas para entrenar "
                         f"({len(full) // 2}).")
    avisar(f"Entrenando un modelo solo con las {len(full) // 2:,} peleas anteriores al corte. "
           "Se hace una vez por fecha…".replace(",", "."))
    ganador, metodo = ajustar_modelos(full)

    metodo6 = None
    try:
        from modelado import backtest_metodo as BM
        avisar("Entrenando el modelo de los seis resultados con las mismas peleas…")
        m6, cols6, _ = BM.entrenar_modelo6(BM.etiquetar6(previo))
        metodo6 = (m6, cols6)
    except Exception:                                       # noqa: BLE001
        # Sin él no hay gráfico de seis resultados ni mercado de método, pero
        # el pronóstico de ganador y método sigue intacto.
        metodo6 = None

    modelos = {"ganador": ganador, "metodo": metodo, "metodo6": metodo6,
               "origen": "reentrenado", "entrenado_hasta": previo["date"].max().strftime("%Y-%m-%d"),
               "peleas": len(full) // 2}
    CARPETA_MODELOS.mkdir(parents=True, exist_ok=True)
    with DB.open_file(ruta, "wb") as fh:
        pickle.dump({"firma": firma, "modelos": modelos}, fh)
    return modelos


def _modelos_produccion(fin: pd.Timestamp | None) -> dict:
    from src import value
    try:
        from src.model import load_models
        ganador, metodo = load_models()
    except Exception:                                       # noqa: BLE001
        ganador, metodo = None, None
    m6, cols6 = value.cargar_modelo_metodo()
    return {"ganador": ganador, "metodo": metodo,
            "metodo6": (m6, cols6) if m6 is not None else None,
            "origen": "produccion",
            "entrenado_hasta": fin.strftime("%Y-%m-%d") if fin is not None else None,
            "peleas": None}


# --------------------------------------------------------------------------- #
# Cómo terminó (solo para mostrar, después de predecir)
# --------------------------------------------------------------------------- #
_DETALLE = {"U-DEC": "decisión unánime", "S-DEC": "decisión dividida",
            "M-DEC": "decisión mayoritaria", "DEC": "decisión"}


def _como_termino(metodo: str, detalle: str) -> str:
    metodo, detalle = str(metodo or ""), str(detalle or "").upper()
    if metodo == "Decision":
        return _DETALLE.get(detalle, "decisión")
    if metodo == "KO/TKO":
        return "KO/TKO"
    if metodo == "Submission":
        return "sumisión"
    if "DQ" in detalle:
        return "descalificación"
    if "NC" in detalle:
        return "sin resultado"
    return "otro"


def resultado_real(a: str, b: str, fecha, pronostico: str | None = None) -> dict | None:
    """
    La primera pelea entre `a` y `b` desde el corte (hasta 60 días después), o
    None si la base todavía no la tiene. `lado` dice quién ganó en el orden de
    la cartelera; `acierto` compara con el pronóstico (None en empate o NC).
    """
    fecha = pd.Timestamp(fecha)
    p = _peleas()
    sub = p[(p["par"] == _clave_par(a, b)) & (p["date"] >= fecha)
            & (p["date"] <= fecha + pd.Timedelta(days=60))]
    if sub.empty:
        return None
    r = sub.sort_values("date").iloc[0]
    ganador = str(r["winner"]).strip() if pd.notna(r["winner"]) else ""
    lado = ("a" if canonical_key(ganador) == canonical_key(a) else
            "b" if canonical_key(ganador) == canonical_key(b) else None) if ganador else None
    acierto = None
    if lado and pronostico:
        acierto = canonical_key(pronostico) == canonical_key(a if lado == "a" else b)
    asalto = pd.to_numeric(r.get("round"), errors="coerce")
    return {"fecha": r["date"].strftime("%Y-%m-%d"), "evento": str(r["event"]),
            "ganador": ganador, "lado": lado,
            "metodo": str(r["method"]) if pd.notna(r["method"]) else "",
            "como": _como_termino(r["method"], r.get("method_detail")),
            "asalto": int(asalto) if pd.notna(asalto) else None,
            "tiempo": str(r["time"]) if pd.notna(r.get("time")) else "",
            "acierto": acierto}


# --------------------------------------------------------------------------- #
# Peleas anteriores para elegir en la UI
# --------------------------------------------------------------------------- #
def _kaggle() -> dict:
    """{(fecha, par): fila de kaggle_ufc.csv}: la esquina roja, las cuotas y el título."""
    global _KAGGLE
    if _KAGGLE is None:
        ruta = C.DATA_RAW / "kaggle_ufc.csv"
        _KAGGLE = {}
        if DB.exists(ruta):
            k = DB.read_csv(ruta, low_memory=False)
            k["date"] = pd.to_datetime(k["date"], errors="coerce")
            k = k.dropna(subset=["date", "R_fighter", "B_fighter"])
            for fila in k.to_dict("records"):
                _KAGGLE[(fila["date"], _clave_par(fila["R_fighter"], fila["B_fighter"]))] = fila
    return _KAGGLE


def orientar(a: str, b: str, fecha, kaggle: dict | None = None) -> tuple[str, str]:
    """
    (esquina A, esquina B) SIN mirar el resultado.

    UFCStats pone al GANADOR primero en el 100% de las peleas: mostrar o
    predecir en ese orden filtraba el resultado (fuga 1 del backtest de
    carteleras). A = la esquina roja si Kaggle la conoce; si no, el orden
    alfabético.
    """
    fila = (kaggle if kaggle is not None else _kaggle()).get((pd.Timestamp(fecha), _clave_par(a, b)))
    if fila is not None:
        rojo = canonical_key(fila["R_fighter"])
        if canonical_key(b) == rojo:
            return b, a
        if canonical_key(a) == rojo:
            return a, b
    return (a, b) if normalize_name(a) <= normalize_name(b) else (b, a)


def peleas_anteriores(q: str = "", limite: int = 24) -> dict:
    """
    Peleas de la base local para elegir una y repetirla.

    Sin búsqueda: la estelar de cada evento, del más nuevo al más viejo. Con
    búsqueda: todas las peleas cuyo evento o peleadores contengan cada palabra.
    Nunca dice quién ganó: el orden ya viene sin el resultado (ver orientar).
    """
    p = _peleas()
    p = p[p["date"] >= FECHA_MINIMA]
    palabras = normalize_name(q).split()
    if palabras:
        nombres = p["fighter_a"].map(normalize_name) + " " + p["fighter_b"].map(normalize_name)
        texto = p["event"].map(normalize_name) + " " + nombres
        sel = p[np.logical_and.reduce([texto.str.contains(w, regex=False) for w in palabras])]
        # Primero las peleas DEL peleador buscado; después las de eventos que
        # solo lo nombran ("garry" no tiene que listar toda la cartelera de
        # "Machado Garry vs. Prates" antes de sus otras peleas).
        propia = np.logical_and.reduce([nombres.loc[sel.index].str.contains(w, regex=False)
                                        for w in palabras])
        sel = pd.concat([sel[propia], sel[~propia]])
    else:
        sel = p[p["estelar"]]
    total = len(sel)
    kaggle = _kaggle()
    salida = []
    for r in sel.head(max(1, int(limite))).itertuples():
        a, b = orientar(r.fighter_a, r.fighter_b, r.date, kaggle)
        # Por el título solo si Kaggle lo marca: ni la estelar ni los cinco
        # asaltos lo confirman (misma regla que card.bandera_titulo).
        titulo = (kaggle.get((r.date, r.par)) or {}).get("title_bout")
        salida.append({"evento": r.event, "fecha": r.date.strftime("%Y-%m-%d"),
                       "a": a, "b": b, "estelar": bool(r.estelar),
                       "titulo": titulo is True or str(titulo).lower() == "true",
                       "division": str(r.weight_class) if pd.notna(r.weight_class) else ""})
    return {"peleas": salida, "total": total,
            "hasta": p["date"].max().strftime("%Y-%m-%d") if not p.empty else None,
            "desde": FECHA_MINIMA.strftime("%Y-%m-%d")}


def _slug(s: str) -> str:
    plano = normalize_name(s)
    return re.sub(r"[^a-z0-9]+", "_", plano).strip("_") or "evento"


def _cuota_valida(x) -> bool:
    v = pd.to_numeric(x, errors="coerce")
    return pd.notna(v) and np.isfinite(v) and v != 0


def _decimal(cuota) -> float:
    """
    Americana (Kaggle, BestFightOdds) -> decimal, como las de Betano. card.py
    acepta las dos, pero la UI muestra la cuota tal cual viene: un +315 salía
    como "315,00".
    """
    from src.value import a_americana
    am = a_americana(cuota)
    return round(1 + (am / 100.0 if am > 0 else 100.0 / -am), 3)


def _cuotas_metodo(fila: dict, a_es_rojo: bool) -> list | None:
    """
    Las 6 cuotas de método de Kaggle en el orden de card.COL_METODO, o None.

    Solo si suman lo que suma un mercado real: desde el umbral de sospecha de
    value.py hasta 1,40. Las de 2025 en adelante vienen corruptas en Kaggle
    (suman menos de 1, ver CLAUDE.md) y muchas otras son la MEJOR cuota de
    varias casas, que suma menos que cualquier casa sola. Con ellas la
    repetición mostraría valor falso, o el aviso de cuotas inventadas sobre
    cuotas que no lo son.
    """
    from src.value import SOBRERREDONDEO_SOSPECHOSO, mercado_metodo
    lados = ("r", "b") if a_es_rojo else ("b", "r")
    cuotas = [fila.get(f"{lado}_{m}_odds") for lado in lados for m in ("ko", "sub", "dec")]
    if not all(_cuota_valida(c) for c in cuotas):
        return None
    _, sobre = mercado_metodo(cuotas)
    return cuotas if np.isfinite(sobre) and SOBRERREDONDEO_SOSPECHOSO <= sobre <= 1.40 else None


def cartelera_de_evento(evento: str, fecha: str) -> Path:
    """
    Arma cards/historico_<fecha>_<evento>.csv con las peleas de un evento de la
    base, listo para predecirlo con corte en su fecha.

    Las cuotas salen de Kaggle (o de BestFightOdds para el hueco reciente) y son
    las de CIERRE, o sea las que había antes de pelear: no son información del
    futuro. Nunca se escribe el resultado.
    """
    dia = pd.Timestamp(fecha).normalize()
    p = _peleas()
    sub = p[(p["event"] == evento) & (p["date"] == dia)]
    if sub.empty:
        raise ValueError(f"No encontré «{evento}» del {fecha} en la base local.")
    kaggle = _kaggle()
    filas = []
    for r in sub.itertuples():
        a, b = orientar(r.fighter_a, r.fighter_b, r.date, kaggle)
        fila = {"fighter_a": a, "fighter_b": b, "segment": "Estelar" if r.estelar else ""}
        k = kaggle.get((r.date, r.par))
        if k is not None:
            a_es_rojo = canonical_key(k["R_fighter"]) == canonical_key(a)
            ca, cb = (k.get("R_odds"), k.get("B_odds")) if a_es_rojo else (k.get("B_odds"), k.get("R_odds"))
            if _cuota_valida(ca) and _cuota_valida(cb):
                fila["odds_a"], fila["odds_b"] = _decimal(ca), _decimal(cb)
            metodo = _cuotas_metodo(k, a_es_rojo)
            if metodo:
                from src.card import COL_METODO
                fila.update(dict(zip(COL_METODO, map(_decimal, metodo))))
            titulo = k.get("title_bout")
            if isinstance(titulo, (bool, np.bool_)):
                fila["es_titulo"] = bool(titulo)
                fila["titulo_fuente"] = "dataset Kaggle"
        if "odds_a" not in fila:
            try:
                from src import bfo_odds
                cuotas = bfo_odds.cuotas_de(a, b, r.date)
            except Exception:                               # noqa: BLE001
                cuotas = None
            if cuotas and all(_cuota_valida(c) for c in cuotas):
                fila["odds_a"], fila["odds_b"] = map(_decimal, cuotas)
        filas.append(fila)
    # Como en Betano: preliminares arriba, la estelar al final.
    filas.sort(key=lambda f: f["segment"] == "Estelar")
    destino = C.ROOT / "cards" / f"historico_{dia:%Y-%m-%d}_{_slug(evento)}.csv"
    destino.parent.mkdir(exist_ok=True)
    DB.to_csv(pd.DataFrame(filas), destino, index=False)
    return destino
