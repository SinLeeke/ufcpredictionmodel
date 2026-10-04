"""
card.py
Predice una cartelera COMPLETA de forma autosustentable.

Uso:
    python -m src.card                              # usa cards/ejemplo_con_cuotas.csv
    python -m src.card cards/otro_evento.csv        # cualquier otra cartelera

El CSV de entrada solo lleva NOMBRES:
    fighter_a,fighter_b,segment
    Magomed Ankalaev,Bogdan Guskov,Estelar

Opcionalmente puedes agregar las CUOTAS de tu casa de apuestas y el programa
además busca dónde el modelo discrepa del mercado:
    fighter_a,fighter_b,segment,odds_a,odds_b
    Magomed Ankalaev,Bogdan Guskov,Estelar,1.75,2.10

Sirve cualquiera de los dos formatos, mezclados si quieres:
    decimal/europeo (el de las casas chilenas): 1.75  2.10
    americano       (el de las casas gringas) : -133  +110

Para cada peleador, el programa baja sus stats reales de UFCStats (con caché).
No hay stats hardcodeados: si quieres otro evento, creas otro CSV con los nombres.

Flujo por pelea:
    nombres -> ufcstats.get_fighter() -> features diferenciales -> probabilidad
    (XGBoost entrenado si existe, si no heurístico) -> Monte Carlo -> método.

Fuente de datos por peleador (en orden):
    1) UFCStats en vivo (con caché en data/raw/ufcstats_cache.json)
    2) fighters.csv (del dataset Kaggle) si no está en UFCStats
    3) si no se encuentra en ningún lado -> se reporta y se omite la pelea
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src import storage as DB
from src.features import (differential_features, FEATURE_COLUMNS,
                          columnas_disponibles, probabilidad_ganador,
                          probabilidades_metodo)
from src.simulate import monte_carlo
from src.visuals import build_report
from src import ufcstats
from src import oposicion
from src import reemplazos
from src.fighter_names import canonical_key, normalize_name, preferred_name
from src.ufc_history import confirmed_ufc_debut

import re


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

# La única cartelera que viene en el repo (.gitignore deja fuera el resto de
# cards/). Antes apuntaba a una que solo existía en el PC del autor, así que
# `python -m src.card` sin argumentos fallaba en cualquier clon.
DEFAULT_CARD = C.ROOT / "cards" / "ejemplo_con_cuotas.csv"

# Columnas opcionales del CSV con las 6 cuotas del mercado de MÉTODO (7 vías).
COL_METODO = ["odds_a_ko", "odds_a_sub", "odds_a_dec",
              "odds_b_ko", "odds_b_sub", "odds_b_dec"]

# Mercado de 5 vías: cuando Betano no separa KO de sumisión, lo apostable es
# "gana por finalización" y "gana por decisión". Orden = value.CLASES_METODO5.
COL_METODO5 = ["odds_a_fin", "odds_a_dec", "odds_b_fin", "odds_b_dec"]


def bandera_titulo(pelea) -> bool | None:
    """Solo una columna explícita confirma el título; vacío significa desconocido.

    Una estelar de cinco rounds también puede ser sin cinturón. Ni el segmento,
    la duración ni el nombre de los peleadores permiten inferir este dato.
    """
    valores = set()
    for campo in ("es_titulo", "title_bout"):
        dato = pelea.get(campo)
        if dato is None or pd.isna(dato):
            continue
        normal = str(dato).strip().lower()
        if normal in ("true", "1", "1.0", "yes", "si", "sí"):
            valores.add(True)
        elif normal in ("false", "0", "0.0", "no"):
            valores.add(False)
    # Dos columnas contradictorias tampoco confirman un título.
    return next(iter(valores)) if len(valores) == 1 else None


def _resolver_titulos_oficiales(filas: list[dict], fecha_evento: str | None = None) -> list[dict]:
    from src.title_bouts import resolver_cartelera
    return resolver_cartelera(filas, fecha_evento=fecha_evento)


def completar_titulos(cartelera: pd.DataFrame, csv_path: str | Path | None = None) -> None:
    """Confirma títulos en un lote, respetando las anotaciones manuales del CSV.

    Una URL de UFC también puede documentar una anotación manual: únicamente
    titulo_automatico=True identifica los datos que pueden volver a resolverse.
    Sin confirmación oficial una fila automática queda desconocida, evitando
    conservar un cinturón que haya cambiado o un combate cancelado.
    """
    if cartelera.empty:
        return
    for campo, defecto in (("es_titulo", None), ("titulo_fuente", ""), ("titulo_automatico", False)):
        cartelera[campo] = cartelera[campo].astype(object) if campo in cartelera.columns else defecto
    if "title_bout" in cartelera.columns:
        cartelera["title_bout"] = cartelera["title_bout"].astype(object)

    filas, indices = [], []
    for indice, fila in cartelera.iterrows():
        titulo = bandera_titulo(fila)
        automatico = bandera_titulo({"es_titulo": fila.get("titulo_automatico")}) is True
        directo = bandera_titulo({"es_titulo": fila.get("es_titulo")})
        alias = bandera_titulo({"es_titulo": fila.get("title_bout")})
        if not automatico and directo is not None and alias is not None and directo != alias:
            # Una contradicción manual no se transforma en una confirmación
            # automática: mantiene ambos datos originales y queda sin título.
            cartelera.at[indice, "titulo_fuente"] = ""
            cartelera.at[indice, "titulo_automatico"] = False
            continue
        if titulo is not None and not automatico:
            cartelera.at[indice, "es_titulo"] = titulo
            fuente = fila.get("titulo_fuente")
            cartelera.at[indice, "titulo_fuente"] = (str(fuente).strip() if pd.notna(fuente) else "") or "CSV"
            cartelera.at[indice, "titulo_automatico"] = False
            continue
        filas.append(fila.to_dict())
        indices.append(indice)
    if not filas:
        return

    fecha = None
    if csv_path is not None:
        coincidencia = re.fullmatch(r"(?:betano|historico)_(\d{4}-\d{2}-\d{2})_.+", Path(csv_path).stem)
        if coincidencia:
            candidato = pd.to_datetime(coincidencia.group(1), format="%Y-%m-%d", errors="coerce")
            if pd.notna(candidato):
                fecha = candidato.strftime("%Y-%m-%d")
    try:
        resultados = _resolver_titulos_oficiales(filas, fecha_evento=fecha)
    except (ImportError, OSError, ValueError):
        resultados = []
    if not isinstance(resultados, list) or len(resultados) != len(filas):
        resultados = [{} for _ in filas]
    for indice, resultado in zip(indices, resultados):
        resultado = resultado if isinstance(resultado, dict) else {}
        titulo = resultado.get("es_titulo")
        titulo = titulo if isinstance(titulo, bool) else None
        fuente = resultado.get("titulo_fuente")
        cartelera.at[indice, "es_titulo"] = titulo
        if "title_bout" in cartelera.columns:
            # Este alias previo también debe revocarse cuando cambia o falta
            # la confirmación automática, para que no reintroduzca el título.
            cartelera.at[indice, "title_bout"] = None
        cartelera.at[indice, "titulo_fuente"] = str(fuente).strip() if titulo is not None and fuente else ""
        cartelera.at[indice, "titulo_automatico"] = True


# --------------------------------------------------------------------------- #
# Fuentes de datos por peleador
# --------------------------------------------------------------------------- #
def _from_fighters_csv(name: str) -> dict | None:
    """Fallback: busca el peleador en fighters.csv (dataset Kaggle)."""
    if not DB.exists(C.FIGHTERS_CSV):
        return None
    df = DB.read_csv(C.FIGHTERS_CSV)
    identidades = df["name"].map(canonical_key)
    hit = df[identidades == canonical_key(name)]
    if hit.empty:
        hit = df[identidades.str.contains(canonical_key(name), na=False, regex=False)]
    if not hit.empty:
        vigente = hit[hit["name"].map(normalize_name) == normalize_name(preferred_name(name))]
        if not vigente.empty:
            hit = vigente
    return hit.iloc[0].to_dict() if not hit.empty else None


def _conteo_historial(stats: dict) -> int | None:
    """Un historial ausente no equivale a un debut confirmado."""
    n = pd.to_numeric(stats.get("n_peleas_hist"), errors="coerce")
    return int(n) if pd.notna(n) and np.isfinite(n) and n >= 0 else None


def get_stats(name: str) -> tuple[dict | None, str]:
    """
    Devuelve (stats, fuente). Prioridad:
      1) ficha en vivo de UFCStats + control/grappling del historial descargado
         (misma receta que el entrenamiento del modelo combinado)
      2) fighters.csv del dataset viejo
    """
    d = ufcstats.get_fighter(name)
    if d:
        # MODELO COMBINADO: la ficha da golpeo/récord/biometría (como Kaggle en el
        # entrenamiento) y aquí se le suma el control/grappling desde el historial.
        from src.control_stats import enriquecer
        d = enriquecer(d)
        # Peleadores con POCAS peleas en UFC: se completa su récord con la
        # carrera entera (Sherdog trae Bellator, PFL, KSW, ligas regionales).
        # Sin esto un debutante con 15 peleas profesionales figuraba como
        # desconocido y el modelo lo trataba como el promedio.
        n_hist = _conteo_historial(d)
        if n_hist is not None and n_hist < 3:
            try:
                from src import sherdog
                antes = d.get("wins", 0)
                d = sherdog.completar(d)
                if d.get("wins", 0) != antes:
                    d["_sherdog"] = True
            except Exception:
                pass
        return d, "ufcstats"
    d = _from_fighters_csv(name)
    if d:
        # El fallback también puede traer una variante antigua del nombre o
        # un contador generado antes de descargar el historial de UFCStats.
        from src.control_stats import enriquecer
        d = enriquecer(d)
        return d, "kaggle"
    return None, "NO_ENCONTRADO"


def _corto_aviso(fight: pd.Series, columna: str, nombre: str, fecha=None) -> int:
    """
    1 si el peleador entró de reemplazo. Lo que diga el CSV manda; una celda
    VACÍA es "no lo sé", igual que si la columna no existiera, así que se cae al
    caché de Wikipedia.

    BUG QUE ESTO ARREGLA: se leía con `int(valor or 0)`. Pandas lee la celda
    vacía como NaN y NaN es truthy, así que `nan or 0` devolvía nan y el
    int() tiraba el programa entero (en la UI, la cartelera no cargaba). Pasa
    en cuanto el usuario marca a un solo peleador y deja el resto en blanco.
    """
    valor = pd.to_numeric(fight.get(columna), errors="coerce")
    if pd.notna(valor):
        return int(valor != 0)
    # En una repetición se conoce la fecha del evento: basta ±1 día (husos
    # horarios), como al entrenar. Sin fecha, las semanas alrededor de hoy.
    if fecha is not None:
        return reemplazos.flag(nombre, fecha, dias=1)
    return reemplazos.flag(nombre, pd.Timestamp.now(), dias=21)


def elo_de_tabla(tabla: pd.DataFrame, nombre: str, division: str | None = None) -> float | None:
    """
    ELO de un peleador en una tabla con el formato de elo_ratings.csv, o None.

    El ELO es POR CATEGORÍA, y quien peleó en varias tiene una fila por cada
    una. Se usa la de `division` (la de su última pelea, ver
    oposicion.ultima_division); si no hay, la primera fila, como antes.

    Antes siempre era la primera fila, y ese orden depende de en qué categoría
    apareció primero CUALQUIER peleador, no él: a 438 peleadores les daba el
    ELO de otra división, a 44 activos con más de 40 puntos de diferencia.
    Volkanovski salía con 1498 (su ELO de peso ligero, donde perdió las dos con
    Makhachev) en vez de 1655, el de peso pluma, su división. Medido
    con el backtest de carteleras, 742 peleas en 4 semestres de 2025-2026:
    acierto +1,7 pts (mejor en 4/4), log loss neutro (2/4, -0,0014). Entra por
    corrección: reemplaza una regla arbitraria y no empeora.

    La usan la predicción (tabla final) y backtest_carteleras (tabla a la fecha
    del evento), así que las dos eligen la fila con la MISMA regla.
    """
    hit = tabla[tabla["fighter"].map(canonical_key) == canonical_key(nombre)]
    if hit.empty:
        return None
    if division:
        en_div = hit[hit["weight_class"] == division]
        if not en_div.empty:
            hit = en_div
    vigente = hit[hit["fighter"].map(normalize_name) == normalize_name(preferred_name(nombre))]
    if not vigente.empty:
        hit = vigente
    return float(hit.iloc[0]["elo"])


def _elo(stats: dict) -> float:
    """
    ELO del peleador. Prioridad:
      1) elo_ratings.csv (ELO real calculado del dataset Kaggle), si existe.
      2) proxy auto-generado desde el récord scrapeado (winrate + experiencia).
    Nada hardcodeado: el proxy sale de wins/losses que trajo el scraper.
    """
    name = stats["name"]
    if DB.exists(C.ELO_TABLE):
        elo = elo_de_tabla(DB.read_csv(C.ELO_TABLE), name, oposicion.ultima_division(name))
        if elo is not None:
            return elo
    # proxy: winrate centrado en .5 + bonus por experiencia
    w, l = float(stats.get("wins", 0)), float(stats.get("losses", 0))
    total = w + l
    if total == 0:
        return C.ELO_BASE
    winrate = w / total
    return C.ELO_BASE + 350 * (winrate - 0.5) + 4 * min(total, 25)


# --------------------------------------------------------------------------- #
# Probabilidad y método
# --------------------------------------------------------------------------- #
def _load_models():
    """Devuelve (winner_model, method_model). Cualquiera puede ser None."""
    try:
        from src.model import load_models
        return load_models()   # (winner, method)
    except Exception:
        return None, None


def _heuristic(feat: dict) -> float:
    z = (0.010 * feat["elo_diff"] + 0.45 * feat["striking_efficiency_diff"]
         + 0.35 * feat["grappling_efficiency_diff"] + 0.08 * feat["streak_diff"]
         + 0.60 * feat["finish_index_diff"] - 0.03 * feat["age_diff"]
         + 0.015 * feat["reach_diff"])
    return float(1 / (1 + np.exp(-z)))


def _project_method(fav: dict, dog: dict, feat: dict) -> dict:
    ko0 = fav.get("win_ko_rate", 0.4)
    sub0 = fav.get("win_sub_rate", 0.2)
    finish_pull = 0.5 * feat["fight_finish_potential"] + 0.5 * dog.get("lost_by_finish_rate", 0.4)
    ko = ko0 * (0.6 + finish_pull)
    sub = sub0 * (0.6 + finish_pull)
    dec = max(0.05, 1 - (ko + sub))
    s = ko + sub + dec
    return {"KO/TKO": ko / s, "Submission": sub / s, "Decision": dec / s}


# --------------------------------------------------------------------------- #
# Reporte de valor (solo si el CSV traía cuotas)
# --------------------------------------------------------------------------- #
def _imprimir_valor(valores: list[tuple[dict, object]]) -> None:
    """
    Muestra dónde discrepan modelo y mercado, separando las dos discrepancias
    que NO son lo mismo (ver src/value.py):

      CRUDA     -> el modelo contra la línea. Llamativa y perdedora: filtrar
                   por ella dio -8.1% de ROI en 2.533 apuestas reales.
      CALIBRADA -> después de descontarle al modelo su exceso de confianza.
                   Chica y apenas rentable (+1.0%, dentro del margen de error).

    Se ordena por la calibrada porque es la accionable.
    """
    print("\n" + "=" * 96)
    print("  MODELO vs MERCADO")
    print("=" * 96)
    print("  Las 3 columnas de probabilidad son del PRIMER peleador de cada fila.")
    print("  'lado' es a quién apuntaría la apuesta, y la cuota y el EV son de ESE lado.\n")
    print(f"  {'PELEA':28}{'MODELO':>8}{'MERCADO':>9}{'FINAL':>8}{'DISC':>7}"
          f"  {'lado':14}{'CUOTA':>6}{'EV':>8}  {'VEREDICTO':<22}")
    print("  " + "-" * 106)

    orden = sorted(valores, key=lambda t: -abs(t[1].discrepancia
                                               if np.isfinite(t[1].discrepancia) else 0))
    for fila, v in orden:
        if not np.isfinite(v.p_mercado_a):
            continue
        vs = f"{fila['A'].split()[-1]} vs {fila['B'].split()[-1]}"
        # El lado candidato es donde el modelo ve más valor que el mercado; no
        # tiene por qué ser A, así que se nombra para no confundir columnas.
        lado = (fila["A"] if v.discrepancia >= 0 else fila["B"]).split()[-1]
        marca = "  <<<" if v.veredicto == "VALOR" else ""
        print(f"  {vs:28}{v.p_modelo_a*100:>7.1f}%{v.p_mercado_a*100:>8.1f}%"
              f"{v.p_final_a*100:>7.1f}%{v.discrepancia*100:>+7.1f}"
              f"  {lado:14}{v.cuota_decimal:>6.2f}{v.ev*100:>+7.1f}%  "
              f"{v.veredicto:<22}{marca}")

    apuestas = [(f, v) for f, v in orden if v.veredicto == "VALOR"]
    print("\n" + "-" * 96)
    if not apuestas:
        print("  SIN APUESTAS DE VALOR en esta cartelera.")
        print("  Es lo normal: el mercado acierta 67% y el modelo 60%. Que no")
        print("  aparezca nada NO es un fallo, es el filtro haciendo su trabajo.")
    else:
        print(f"  APUESTAS DE VALOR: {len(apuestas)}")
        print(f"  {'lado':28}{'cuota':>7}{'prob':>8}{'EV':>8}{'del bankroll':>14}")
        print("  " + "-" * 63)
        for f, v in sorted(apuestas, key=lambda t: -t[1].ev):
            print(f"  {f['apuesta']:28}{v.cuota_decimal:>7.2f}{v.p_lado*100:>7.1f}%"
                  f"{v.ev*100:>+7.1f}%{v.kelly*100:>13.1f}%")
        print("\n  'del bankroll' es Kelly a 1/4 con tope de 5%: la fracción que")
        print("  aguanta una racha mala sin fundirte.")

    print("\n  RECORDATORIO INCÓMODO (medido, no opinión):")
    print("  Sobre 3.821 peleas fuera de muestra esta estrategia dio +1.0% de ROI")
    print("  con un margen de error de ±7.5. Es un empate técnico con la casa, no")
    print("  una máquina de plata. La discrepancia CRUDA (la grande y llamativa)")
    print("  sí está probada: pierde -8.1%. Detalle en 'python -m modelado.backtest_valor'.")
    print("=" * 96)


def _imprimir_metodo(metodos: list[tuple[str, str, list[dict]]]) -> None:
    """
    Mercado de método (6 vías). Es el único con ventaja probada del proyecto:
    +15.4% de ROI (t=3.0) apostando decisiones con EV>=0, porque el público
    paga de más por las finalizaciones y deja las decisiones baratas.
    """
    print("\n" + "=" * 96)
    print("  MERCADO DE MÉTODO (¿gana quién, y cómo?)")
    print("=" * 96)

    apuestas = []
    for na, nb, ops in metodos:
        vs = f"{na.split()[-1]} vs {nb.split()[-1]}"
        mejor = ops[0]
        print(f"\n  {vs}")
        print(f"    {'resultado':22}{'modelo':>8}{'mercado':>9}{'final':>8}"
              f"{'cuota':>8}{'EV':>9}")
        for o in ops:
            quien = na if o["clase"].startswith("A") else nb
            como = {"KO": "por KO/TKO", "SUB": "por sumisión",
                    "DEC": "por decisión"}[o["clase"].split("_")[1]]
            etq = f"{quien.split()[-1]} {como}"
            marca = "  <<<" if o["apostar"] else ""
            print(f"    {etq:22}{o['p_modelo']*100:>7.1f}%{o['p_mercado']*100:>8.1f}%"
                  f"{o['p_final']*100:>7.1f}%{o['cuota_decimal']:>8.2f}"
                  f"{o['ev']*100:>+8.1f}%{marca}")
            if o["apostar"]:
                apuestas.append((etq, o))

    print("\n" + "-" * 96)
    if not apuestas:
        print("  Sin valor en el mercado de método para esta cartelera.")
    else:
        dec = [(e, o) for e, o in apuestas if o["clase"].endswith("DEC")]
        print(f"  APUESTAS DE MÉTODO: {len(apuestas)}  (de ellas {len(dec)} son decisiones)")
        print(f"  {'apuesta':32}{'cuota':>7}{'prob':>8}{'EV':>8}{'del bankroll':>14}")
        print("  " + "-" * 67)
        for e, o in sorted(apuestas, key=lambda t: -t[1]["ev"]):
            print(f"  {e:32}{o['cuota_decimal']:>7.2f}{o['p_final']*100:>7.1f}%"
                  f"{o['ev']*100:>+7.1f}%{o['kelly']*100:>13.1f}%")
        print("\n  Las DECISIONES son las que el backtest valida (+15.4% ROI, t=3.0).")
        print("  Las finalizaciones con EV>=0 dieron +5.7% pero con t=0.5: ruido.")

    print("\n  ADVERTENCIA: este mercado cobra 22% de comisión, o sea que es")
    print("  recreativo. Los límites de apuesta son bajos y las casas cierran")
    print("  cuentas ganadoras. El ROI del backtest no te dice cuánto te aceptan.")
    print("=" * 96)


def _tendencia_metodo(r: dict) -> str:
    """
    Lo que hace especial a ESTA pelea, comparando la probabilidad de cada método
    contra su tasa base (config.METHOD_BASE_RATES).

    Por qué no basta con el método más probable: 'Decisión' gana el argmax en
    casi todas las peleas simplemente porque el 51% de las peleas terminan así.
    Un 'Dec 52%' no dice nada; un 'KO 45%' sobre una base de 31% sí. Esto es
    legible solo porque el modelo está CALIBRADO — con el modelo balanceado
    viejo, que anunciaba el doble de sumisiones de las reales, este lift habría
    marcado "SUB" en media cartelera.
    """
    prob = {"KO/TKO": r["KO/TKO%"] / 100.0, "Submission": r["Sub%"] / 100.0,
            "Decision": r["Dec%"] / 100.0}
    clase, lift = max(((c, prob[c] / C.METHOD_BASE_RATES[c]) for c in prob),
                      key=lambda kv: kv[1])
    if lift < 1.25:
        return "pelea promedio"
    corto = {"KO/TKO": "KO", "Submission": "sumisión", "Decision": "decisión"}[clase]
    return f"{corto} x{lift:.1f} vs base"


_FORMA_CACHE: dict[tuple, str] = {}


def _forma(nombre: str, n: int = 3, hasta=None) -> str:
    """
    De qué viene el peleador: sus últimos `n` resultados, del más reciente al
    más viejo, como 'V(TKO) V(Dec) D(Sub)'.

    V = ganó, D = perdió, E = empate/sin resultado. Entre paréntesis, cómo.
    Sale del mismo historial que usa oposicion.py, así que respeta el corte
    temporal (solo peleas anteriores a hoy).
    """
    clave = (nombre, None if hasta is None else pd.Timestamp(hasta))
    if clave in _FORMA_CACHE:
        return _FORMA_CACHE[clave]
    CORTO = {"KO/TKO": "TKO", "Submission": "Sub", "Decision": "Dec"}
    r = oposicion.resumen(nombre, pd.Timestamp.now() if hasta is None else hasta, n=n)
    if not r["n"]:
        out = "sin historial"
    else:
        out = " ".join(
            f"{'V' if p['resultado'] == 'gana' else 'D' if p['resultado'] == 'pierde' else 'E'}"
            f"({CORTO.get(p['metodo'], p['metodo'][:3])})"
            for p in r["peleas"][:n]
        )
    _FORMA_CACHE[clave] = out
    return out


def _cabecera(titulo: str, sub: str = "") -> None:
    print("\n" + "=" * 104)
    print(f"  {titulo}")
    if sub:
        print(f"  {sub}")
    print("=" * 104)


def _tabla_modelo(rows: list[dict], valores: list, hasta=None) -> None:
    """Tabla 1: SOLO el modelo, sin cuotas y SIN el dato de corto aviso."""
    _cabecera("1. MODELO SOLO  (sin cuotas y sin corto aviso)",
              "Lo que el bot saca de los stats. Acierta ~65% por su cuenta.")
    print(f"  {'PELEA':26}{'PICK DEL MODELO':22}{'P%':>5}   {'DE QUÉ VIENE (A / B)':<46}")
    print("  " + "-" * 100)
    for r in rows:
        vs = f"{r['A'].split()[-1]} vs {r['B'].split()[-1]}"
        p_a = r["p_sin_corto_A"]
        pick = r["A"] if p_a >= 0.5 else r["B"]
        alerta = "  <-- " + r["aviso"] if r.get("aviso") else ""
        print(f"  {vs:26}{pick[:21]:22}{max(p_a, 1-p_a)*100:>4.0f}%   "
              f"{_forma(r['A'], hasta=hasta):<22} {_forma(r['B'], hasta=hasta):<22}{alerta}")


def _tabla_corto(rows: list[dict]) -> None:
    """
    Tabla 3: el modelo YA SABIENDO quién entró de reemplazo.

    Solo se imprime si hay al menos una pelea de corto aviso — en una cartelera
    normal no hay ninguna y una tabla idéntica a la 1 sería puro ruido.
    Es el MISMO modelo que la tabla 1; lo único que cambia es que ahí el flag
    va neutralizado a 0 y acá va con su valor real, así que la diferencia entre
    las dos columnas es exactamente lo que aporta el dato.
    """
    _cabecera("3. MODELO + CORTO AVISO",
              "Quien entra de reemplazo no hizo campamento: gana solo el 34,9%.")
    print(f"  {'PELEA':26}{'PICK':22}{'P%':>5}{'ANTES':>8}{'CAMBIO':>8}   {'QUIÉN ENTRÓ DE REEMPLAZO':<34}")
    print("  " + "-" * 100)
    for r in rows:
        vs = f"{r['A'].split()[-1]} vs {r['B'].split()[-1]}"
        p_c, p_s = r["p_con_corto_A"], r["p_sin_corto_A"]
        pick = r["A"] if p_c >= 0.5 else r["B"]
        quien = ", ".join([n.split()[-1] for n, c in
                           ((r["A"], r["corto_a"]), (r["B"], r["corto_b"])) if c]) or "-"
        # el cambio se mide siempre sobre el MISMO lado (A) para que el signo
        # sea interpretable; si el pick cambió de peleador se avisa aparte.
        d = (p_c - p_s) * 100
        giro = "  <-- CAMBIÓ EL PICK" if (p_c >= .5) != (p_s >= .5) else ""
        print(f"  {vs:26}{pick[:21]:22}{max(p_c,1-p_c)*100:>4.0f}%"
              f"{max(p_s,1-p_s)*100:>7.0f}%{d:>+7.1f}   {quien:<34}{giro}")


def _tabla_mercado(rows: list[dict], valores: list) -> None:
    """Tabla 2: SOLO la casa de apuestas, con la comisión ya descontada."""
    _cabecera("2. MERCADO  (la casa, sin su comisión)",
              "Acierta ~69%, más que el modelo. Es el rival a batir, no un adorno.")
    pm = {(f["A"], f["B"]): v for f, v in valores}
    print(f"  {'PELEA':26}{'FAVORITO DE LA CASA':22}{'P%':>5}   {'CUOTA A':>8}{'CUOTA B':>9}")
    print("  " + "-" * 100)
    for r in rows:
        v = pm.get((r["A"], r["B"]))
        if v is None or not np.isfinite(v.p_mercado_a):
            continue
        vs = f"{r['A'].split()[-1]} vs {r['B'].split()[-1]}"
        fav = r["A"] if v.p_mercado_a >= 0.5 else r["B"]
        prob = max(v.p_mercado_a, 1 - v.p_mercado_a)
        oa, ob = r.get("cuota_a", ""), r.get("cuota_b", "")
        print(f"  {vs:26}{fav[:21]:22}{prob*100:>4.0f}%   {oa:>8}{ob:>9}")


def _tabla_mezcla(rows: list[dict], valores: list, hay_corto: bool = False) -> None:
    """Tabla 4: todo junto — modelo + mercado (+ corto aviso si lo hay)."""
    _cabecera("4. TODO JUNTO: modelo + mercado" + (" + corto aviso" if hay_corto else "")
              + "  (LA QUE MANDA)",
              "Acierta ~70%. Ojo: casi todo el mérito es del mercado (pesa 5x más).")
    pm = {(f["A"], f["B"]): v for f, v in valores}
    print(f"  {'PELEA':26}{'PICK FINAL':22}{'P%':>5}{'CONFIANZA':>12}"
          f"{'MÉTODO':>10}{'FIN%':>6}   {'TENDENCIA':<20}")
    print("  " + "-" * 100)
    for r in rows:
        vs = f"{r['A'].split()[-1]} vs {r['B'].split()[-1]}"
        top = max([("KO", r["KO/TKO%"]), ("Sub", r["Sub%"]), ("Dec", r["Dec%"])],
                  key=lambda x: x[1])
        pocos = [r["aviso"]] if r.get("aviso") else []
        fia = _fiabilidad(r["P_gana%"] / 100.0, pocos)
        v = pm.get((r["A"], r["B"]))
        delta = ""
        if v is not None and np.isfinite(v.p_modelo_a):
            d = (r["P_A%"] / 100.0) - v.p_modelo_a
            if abs(d) >= 0.10:
                delta = f"  [la casa la movió {d*100:+.0f} pts]"
        print(f"  {r['approx']}{vs:25}{r['ganador'][:21]:22}{r['P_gana%']:>4.0f}%{fia:>12}"
              f"{top[0]+' '+str(top[1])+'%':>10}{r['finaliza%']:>5}%   "
              f"{_tendencia_metodo(r):<20}{delta}")
    print("\n  MÉTODO = desenlace más probable. Casi siempre 'Dec' porque el 51% de las peleas")
    print("  van a tarjetas. TENDENCIA = lo que distingue a ESTA pelea de una promedio.")
    print("  [la casa la movió X pts] = el modelo decía otra cosa; ahí manda la casa, no nosotros.")


def _fiabilidad(prob: float, pocos: list) -> str:
    """
    Etiqueta de cuánto confiar en el pick. Los cortes salen del backtest, no
    del gusto: con 95 peleas reales el acierto sube de ~50% en los picks
    parejos a ~85% en los de 75%+, y los fallos se concentran abajo de 60%.
    """
    if pocos:
        return "NO FIABLE"
    if prob >= 0.75:
        return "fuerte"
    if prob >= 0.65:
        return "buena"
    if prob >= 0.60:
        return "justa"
    return "moneda"


def _imprimir_consenso(consenso: list[dict], con_cuotas: bool,
                       detalle: bool = False) -> None:
    """
    EL resumen de la cartelera: qué apostar primero, y una línea por pelea.

    Antes esto eran tres bloques (MODELO vs MERCADO, MERCADO DE MÉTODO con una
    tabla de 6 filas POR PELEA, y CONSENSO FINAL): más de 150 líneas para una
    cartelera de 12 peleas, con la conclusión enterrada al final. Ahora lo
    accionable va PRIMERO y el detalle queda detrás de --detalle.

    La jerarquía de apuestas NO es por EV, es por EVIDENCIA:
      1. decisión en el mercado de método -> +15.4% ROI, t=3.0  (probado)
      2. ganador (moneyline)              -> +1.0% ROI, t=0.3   (empate técnico)
      3. finalización en método           -> +5.7% ROI, t=0.5   (ruido)
    Un EV de +40% en una finalización sigue siendo peor apuesta que un +5% en
    una decisión, porque el primero no sobrevive al test estadístico.
    """
    CORTO = {"KO/TKO": "KO", "Submission": "Sub", "Decision": "Dec"}
    RESP = {"metodo-dec": "probado (+15.4% ROI)",
            "ganador": "empate técnico"}
    ORDEN = {"metodo-dec": 0, "ganador": 1}

    # --- recolectar apuestas y armar la línea de cada pelea ---
    apuestas, descartadas, filas = [], [], []
    for c in consenso:
        sim, v = c["sim"], c["v"]
        prob = max(sim.p_a, sim.p_b)
        top = max(c["method"].items(), key=lambda kv: kv[1])

        accion, mejor = "-", None
        if con_cuotas:
            # La decisión es LA MISMA apuesta en el mercado de 7 y de 5 vías, con
            # el mismo respaldo; antes solo se miraba el de 7 y la de 5 vías no
            # aparecía nunca aunque tuviera valor.
            dec = [o for o in (c["metodo6"] or []) + (c.get("metodo5") or [])
                   if o["apostar"] and o["clase"].endswith("DEC")]
            if dec:
                o = max(dec, key=lambda o: o["ev"])
                quien = c["a"] if o["clase"].startswith("A") else c["b"]
                mejor = ("metodo-dec", f"{quien.split()[-1]} x decisión",
                         o["cuota_decimal"], o["ev"], o["kelly"])
            elif v is not None and v.veredicto == "VALOR":
                quien = c["a"] if v.lado == "A" else c["b"]
                mejor = ("ganador", quien.split()[-1], v.cuota_decimal,
                         v.ev, v.kelly)
            # Una apuesta se construye sobre la probabilidad del modelo. Si esa
            # probabilidad viene de un peleador sin datos, el EV que sale es tan
            # inventado como los stats: se descarta aunque el número se vea rico.
            if mejor and c["pocos"]:
                descartadas.append((mejor, ", ".join(c["pocos"])))
                accion, mejor = "sin datos", None
            elif mejor:
                accion = f"apostar @{mejor[2]:.2f}"
                apuestas.append((mejor, c))

        filas.append((f"{c['a'].split()[-1]} vs {c['b'].split()[-1]}",
                      sim.winner[:21], prob, _fiabilidad(prob, c["pocos"]),
                      f"{CORTO.get(top[0], top[0])} {top[1]*100:.0f}%", accion))

    apuestas.sort(key=lambda t: (ORDEN[t[0][0]], -t[0][3]))
    total = sum(a[0][4] for a in apuestas)
    fiables = sum(1 for _, _, p, f, _, _ in filas if f not in ("moneda", "NO FIABLE"))

    # Cuotas de método demasiado generosas para ser de una casa real: no se
    # apuestan (value.analizar_metodo ya las bloquea) pero hay que DECIRLO, o
    # el usuario ve una cartelera sin apuestas y cree que no había valor.
    sospechosas = [c for c in consenso
                   if c["metodo6"] and c["metodo6"][0].get("sospechoso")]

    print("\n" + "=" * 88)
    print("  RESUMEN")
    print("=" * 88)

    # --- 1. lo accionable, arriba del todo ---
    if not con_cuotas:
        print("\n  Sin cuotas en el CSV no hay recomendación de apuesta.")
        print("  Agrega las columnas odds_a/odds_b (y las 6 de método) para activarla.")
    elif not apuestas:
        print("\n  QUÉ APOSTAR: nada. Es el resultado normal y esperable —")
        print("  el mercado acierta 67% y el modelo 60%, así que casi nunca hay hueco.")
    else:
        print(f"\n  QUÉ APOSTAR ({len(apuestas)}, en total {total*100:.1f}% del bankroll)\n")
        print(f"   {'#':3}{'apuesta':30}{'cuota':>7}{'EV':>8}{'bank':>7}   {'respaldo':<22}")
        print("   " + "-" * 78)
        for i, ((tipo, etq, cuota, ev, kel), _) in enumerate(apuestas, 1):
            print(f"   {i:<3}{etq:30}{cuota:>7.2f}{ev*100:>+7.1f}%{kel*100:>6.1f}%   "
                  f"{RESP[tipo]:<22}")
        print("\n   Van ordenadas por EVIDENCIA, no por EV: una decisión con +5% vale")
        print("   más que una finalización con +40%, porque solo la primera está probada.")
        if total > 0.15:
            print(f"\n   [!] {total*100:.0f}% es mucho para una sola noche. Kelly asume apuestas")
            print("       independientes y las peleas de un mismo evento no lo son.")
        if not any(a[0][0] == "metodo-dec" for a in apuestas):
            print("\n   [!] Ninguna es del tipo probado: apostarlas o no da casi lo mismo.")

    if descartadas:
        print(f"\n  DESCARTADAS por falta de datos ({len(descartadas)}) — EV calculado")
        print("  sobre stats que no existen, no es valor:")
        for (tipo, etq, cuota, ev, kel), quien in descartadas:
            print(f"    {etq:30}@{cuota:.2f}  EV {ev*100:+.1f}%  -> sin stats de {quien}")

    if sospechosas:
        s = [c["metodo6"][0]["sobrerredondeo"] for c in sospechosas]
        print(f"\n  [!] CUOTAS DE MÉTODO SOSPECHOSAS en {len(sospechosas)} de "
              f"{len(consenso)} peleas (suman {min(s):.2f}-{max(s):.2f}).")
        print("      Un mercado de método real suma 1.20-1.24 (cobra ~22% de comisión).")
        print("      Cuotas más generosas que eso no existen: casi siempre es un CSV")
        print("      con números puestos a ojo. Se bloquearon como apuesta — si fueran")
        print("      reales darían un EV enorme, y ese es justo el síntoma del dato malo.")

    # --- 2. la cartelera completa, una línea por pelea ---
    print(f"\n  {'PELEA':26}{'PICK':22}{'PROB':>6}{'CONFIANZA':>11}"
          f"{'MÉTODO':>10}   {'CUOTAS':<14}")
    print("  " + "-" * 84)
    for vs, pick, prob, fia, met, accion in filas:
        print(f"  {vs:26}{pick:22}{prob*100:>5.0f}%{fia:>11}{met:>10}   {accion:<14}")

    print(f"\n  {fiables} de {len(filas)} peleas tienen un pick confiable; el resto es")
    print("  moneda al aire o le faltan datos.")
    if con_cuotas and not detalle:
        print("  Corre con --detalle para ver modelo vs mercado pelea por pelea.")
    print("=" * 88)


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #
def predict_card(card_csv: str | Path = DEFAULT_CARD, reports: bool = True,
                 detalle: bool = False, devolver_todo: bool = False,
                 progreso: Callable[[dict], None] | None = None,
                 corte=None):
    """
    Predice una cartelera completa. Si reports=True, además de la tabla CSV
    genera un reporte visual (donut + barras) por pelea en outputs/ (Plotly vía
    CDN, ~10 KB cada uno).

    detalle=True añade las tablas largas (MODELO vs MERCADO y el mercado de
    método pelea por pelea). Por defecto solo se imprime el resumen accionable.

    devolver_todo=True devuelve el dict completo con las estructuras internas
    (rows/valores/metodos/consenso/missing) en vez de solo el DataFrame. Lo usa
    la UI web para no re-implementar este bucle: es la MISMA corrida que el CLI,
    solo que además entrega los objetos en vez de imprimirlos y tirarlos.

    progreso recibe avances de etapa/pelea, antes de cada consulta de ficha y
    después de cada pelea (también las omitidas). No cambia la salida del CLI.

    corte='AAAA-MM-DD' es la REPETICIÓN de una cartelera que ya pasó: fichas,
    ELO, oposición y modelos con SOLO lo anterior a esa fecha (src/corte.py), y
    al final el resultado real de cada pelea, que se lee después de predecir y
    no entra a ningún cálculo. Sin corte, nada de esto cambia.
    """
    def avisar(etapa, detalle, completadas=0, total=None):
        if progreso is not None:
            progreso({"etapa": etapa, "detalle": detalle,
                      "completadas": completadas, "total": total})

    avisar("preparando", "Leyendo la cartelera y cargando los modelos…")
    card = DB.read_csv(card_csv)
    avisar("preparando", "Consultando la confirmación de títulos en UFC…")
    completar_titulos(card, card_csv)
    avisar("preparando", "Cargando los modelos de predicción…")
    from src import value
    repeticion = None
    if corte is None:
        model, method_model = _load_models()
        # El clasificador lado × método sirve también para los gráficos de la
        # UI, aunque esta cartelera no incluya cuotas de método. Usa la misma
        # predicción simetrizada del análisis de valor; no se deriva
        # multiplicando ganador y método, porque no son independientes.
        method6_model, method6_cols = value.cargar_modelo_metodo() if devolver_todo else (None, None)
        fecha_corte = pd.Timestamp.now()
    else:
        from src import corte as CT
        pedida = CT.a_fecha(corte)
        fecha_corte = CT.corte_efectivo(list(zip(card["fighter_a"], card["fighter_b"])), pedida)
        avisar("preparando", f"Repetición: preparando un modelo que no vio nada desde el "
                             f"{fecha_corte:%d-%m-%Y}…")
        modelos = CT.modelos_a_fecha(fecha_corte, avisar=lambda txt: avisar("preparando", txt))
        model, method_model = modelos["ganador"], modelos["metodo"]
        method6_model, method6_cols = modelos["metodo6"] or (None, None)
        hasta = CT.base_hasta()
        repeticion = {"pedida": pedida.strftime("%Y-%m-%d"),
                      "fecha": fecha_corte.strftime("%Y-%m-%d"),
                      "ajustada": bool(fecha_corte != pedida),
                      "modelo": modelos["origen"],
                      "modelo_hasta": modelos["entrenado_hasta"],
                      "modelo_peleas": modelos["peleas"],
                      "base_hasta": hasta.strftime("%Y-%m-%d") if hasta is not None else None}
        print(f"Repetición al {fecha_corte:%Y-%m-%d}: modelo {modelos['origen']} "
              f"(entrenado hasta {modelos['entrenado_hasta']})")
    src_lbl = "XGBoost entrenado" if model is not None else "heurístico (corre 'python -m src.model' para usar el modelo)"
    print(f"\nCartelera: {Path(card_csv).name}")
    print(f"Probabilidad de ganador: {src_lbl}")
    event = _slug(Path(card_csv).stem)
    if repeticion is not None:
        # Los reportes de la repetición no pisan los de la carga normal.
        event = f"{event}_corte_{repeticion['fecha']}"
    modelo6 = (method6_model, method6_cols) if method6_model is not None else None

    # ¿El CSV trae cuotas? Si sí, se activa el análisis de valor.
    con_cuotas = {"odds_a", "odds_b"}.issubset(card.columns)
    con_metodo = set(COL_METODO).issubset(card.columns)
    con_metodo5 = set(COL_METODO5).issubset(card.columns)
    calibrador = None
    if con_cuotas:
        from src import value
        calibrador = value.cargar_calibrador()
        if calibrador is None:
            print("[!] hay cuotas pero falta el calibrador -> corre 'python -m modelado.backtest_valor'.\n"
                  "    Sin él se compara con la probabilidad CRUDA, que el backtest\n"
                  "    mostró que pierde -8% de ROI. Los avisos de valor no son fiables.")
        else:
            print(f"Cuotas detectadas -> las probabilidades mezclan modelo y mercado "
                  f"(70.1% de acierto vs 65.3% del modelo solo).")
        if con_metodo:
            print("Cuotas de método detectadas -> se analiza el mercado de 7 vías.")
        if con_metodo5:
            print("Cuotas de 5 vías detectadas -> se analiza también finalización/decisión.")
    print()

    rows, missing, valores, metodos, consenso = [], [], [], [], []
    total = len(card)
    avisar("prediccion", "Preparando las fichas de los peleadores…", 0, total)
    for indice, (_, fight) in enumerate(card.iterrows()):
        na, nb = fight["fighter_a"], fight["fighter_b"]
        seg = fight.get("segment", "")
        es_titulo = bandera_titulo(fight)
        fuente_titulo = fight.get("titulo_fuente")
        fuente_titulo = str(fuente_titulo).strip() if pd.notna(fuente_titulo) else ""
        fuente_titulo = (fuente_titulo or "CSV") if es_titulo is not None else ""
        titulo_automatico = bandera_titulo({"es_titulo": fight.get("titulo_automatico")}) is True
        avisar("prediccion", f"Pelea {indice + 1}/{total}: consultando la ficha de {na}…",
               indice, total)
        a, sa = get_stats(na) if repeticion is None else CT.ficha_a_fecha(na, fecha_corte)
        avisar("prediccion", f"Pelea {indice + 1}/{total}: consultando la ficha de {nb}…",
               indice, total)
        b, sb = get_stats(nb) if repeticion is None else CT.ficha_a_fecha(nb, fecha_corte)
        if a is None or b is None:
            missing += [n for n, s in [(na, sa), (nb, sb)] if s == "NO_ENCONTRADO"]
            print(f"[skip] {na} vs {nb}: falta data ({sa}/{sb})")
            avisar("prediccion", f"Pelea {indice + 1}/{total} omitida: faltan datos de {na} vs {nb}.",
                   indice + 1, total)
            continue

        avisar("prediccion", f"Pelea {indice + 1}/{total}: analizando {na} vs {nb}…",
               indice, total)
        opciones = None
        opciones5 = None
        # features con el MISMO cálculo que el entrenamiento (incluye grappling)
        from src.ufcstats_ingest import features_pelea
        if repeticion is None:
            feat = features_pelea(a, b, _elo(a), _elo(b))
        else:
            feat = features_pelea(a, b, CT.elo_a_fecha(a["name"], fecha_corte),
                                  CT.elo_a_fecha(b["name"], fecha_corte))
        # Calidad de la oposición reciente. Se usan los nombres DEL CSV (no los
        # canónicos de la ficha) porque oposicion normaliza igual que UFCStats,
        # y la fecha de HOY: "sus últimas 5 peleas hasta ahora" (en una
        # repetición, la del corte: las 5 anteriores al evento).
        feat.update(oposicion.features(a["name"], b["name"], fecha_corte))
        # CORTO AVISO. Prioridad: lo que diga el CSV (columnas corto_a/corto_b,
        # que el usuario llena a mano si sabe de un reemplazo de última hora) y
        # si no, el caché de Wikipedia por fecha. El caché sirve para carteleras
        # pasadas; para una futura, Wikipedia puede no estar actualizada todavía.
        # dias=21: el CSV no trae la fecha del evento, así que se busca en las
        # semanas alrededor de hoy (ver reemplazos.flag).
        dia_evento = fecha_corte if repeticion is not None else None
        ca = _corto_aviso(fight, "corto_a", a["name"], dia_evento)
        cb = _corto_aviso(fight, "corto_b", b["name"], dia_evento)
        feat["reemplazo_diff"] = ca - cb
        X = pd.DataFrame([feat])
        # El modelo de ganador SÍ usa oposición; el de método NO (ver
        # features.columnas_disponibles: le empeora el KO-vs-sumisión).
        cols = columnas_disponibles(X)
        cols_met = columnas_disponibles(X, con_oposicion=False, con_corto=False)
        # Dos pasadas del MISMO modelo para poder mostrar la tabla 1 (bot solo)
        # y la 3 (bot + corto aviso): en la primera se neutraliza el flag a 0,
        # o sea "como si nadie fuera reemplazo". Así la diferencia entre ambas
        # es exactamente lo que aporta el dato de corto aviso, sin mezclar
        # modelos distintos.
        if model is not None:
            X0 = X.copy()
            X0["reemplazo_diff"] = 0
            # Simetrizada: la p no depende de quién quedó en la columna A del
            # CSV (ver features.probabilidad_ganador).
            p_sin = float(probabilidad_ganador(model, X0, cols)[0])
            p_con = float(probabilidad_ganador(model, X, cols)[0])
            p_a = p_con
        else:
            p_sin = p_con = p_a = _heuristic(feat)

        # --- CUOTAS: si el CSV las trae, la probabilidad que MANDA es la
        # calibrada (modelo mezclado con el mercado), no la cruda. Medido sobre
        # las mismas peleas fuera de muestra: 70.1% de acierto contra 65.3% del
        # modelo solo (Brier 0.195 vs 0.220). El modelo puro no se pierde: sigue
        # en la columna MODELO de la tabla "MODELO vs MERCADO".
        # Ojo con la honestidad del titular: casi toda esa mejora la pone el
        # mercado (69.8% él solo), no el modelo.
        v = None
        if con_cuotas:
            from src import value
            v = value.analizar(p_a, fight.get("odds_a"), fight.get("odds_b"),
                               cal=calibrador)
            if calibrador is not None and np.isfinite(v.p_final_a):
                p_a = v.p_final_a

        # Método: modelo entrenado si existe; si no, proyección heurística por estilo.
        # Simetrizado: "termina por KO" es una propiedad de la PELEA, no depende
        # de a quién pusiste en la columna A del CSV (ver features.COLUMNAS_SIMETRICAS).
        if method_model is not None:
            probs = probabilidades_metodo(method_model, X, cols_met)[0]
            method = {c: float(probs[i]) for i, c in enumerate(C.METHOD_CLASSES)}
        else:
            fav, dog = (a, b) if p_a >= 0.5 else (b, a)
            method = _project_method(fav, dog, feat)
        sim = monte_carlo(p_a, method, a["name"], b["name"], n=C.N_SIMULATIONS)
        p_metodo6 = None
        if method6_model is not None and all(col in X for col in method6_cols):
            p6 = value._p6_simetrica(method6_model, X, method6_cols)
            p_metodo6 = {clase: float(p6[i]) for i, clase in enumerate(value.CLASES_METODO)}
        approx = "~" if (sa == "kaggle" or sb == "kaggle") else ""

        # Reporte visual por pelea (donut de victoria + barras de método).
        if reports:
            hist_a = {"KO/TKO": a.get("win_ko_rate", 0), "Submission": a.get("win_sub_rate", 0),
                      "Decision": a.get("win_dec_rate", 0)}
            hist_b = {"KO/TKO": b.get("win_ko_rate", 0), "Submission": b.get("win_sub_rate", 0),
                      "Decision": b.get("win_dec_rate", 0)}
            # Cada cartelera queda en su propia carpeta: outputs/<evento>/<pelea>.html
            build_report(sim, hist_a, hist_b,
                         filename=f"{event}/{_slug(a['name'])}_vs_{_slug(b['name'])}",
                         include_plotlyjs="cdn")

        # Aviso de muestra chica: con <3 peleas registradas el modelo casi no
        # tiene información de ese peleador y su probabilidad es poco fiable.
        #
        # BUG QUE COSTÓ UN PICK (Cepo vs Urbina, 01-ago-2026): la condición era
        # `0 < n < 3`, que dejaba fuera JUSTO el peor caso, n=0. Vlasto Cepo tenía
        # la ficha de UFCStats totalmente vacía (slpm=0, alcance=0, récord 0-0,
        # cero peleas de historial) y aun así salió 77% etiquetado "fuerte", sin
        # ningún aviso. Ganó Urbina por TKO.
        # Ahora se marca también n=0, y además se detecta la ficha FANTASMA por
        # sus stats: un peleador real no tiene slpm=0 y alcance=0 a la vez.
        # Si el historial no está disponible, se mantiene la advertencia sin
        # afirmar que el peleador tiene cero peleas en UFC.
        def _sin_datos(f) -> bool:
            n_hist = _conteo_historial(f)
            if confirmed_ufc_debut(f) or not f.get("historial_disponible", True) or n_hist is None or n_hist < 3:
                return True
            if f.get("identidad_ambigua"):
                return True          # dos peleadores con este nombre en la base
            return float(f.get("slpm", 1) or 0) == 0 and float(f.get("reach_cm", 1) or 0) == 0

        pocos = [f["name"].split()[-1] for f in (a, b) if _sin_datos(f)]
        fila = {
            "orden_cartelera": indice, "total_cartelera": total,
            "es_titulo": es_titulo, "titulo_fuente": fuente_titulo,
            "titulo_automatico": titulo_automatico,
            # p del modelo con el flag neutralizado / con el flag real, y quién
            # entró de reemplazo. Alimentan las tablas 1 y 3 del reporte.
            "p_sin_corto_A": p_sin, "p_con_corto_A": p_con,
            "corto_a": ca, "corto_b": cb,
            "aviso": ("pocos datos: " + ", ".join(pocos)) if pocos else "",
            "segmento": seg, "fuente": f"{sa[:3]}/{sb[:3]}",
            "ganador": sim.winner, "P_gana%": round(max(sim.p_a, sim.p_b) * 100, 1),
            "A": a["name"], "P_A%": round(sim.p_a * 100, 1),
            "B": b["name"], "P_B%": round(sim.p_b * 100, 1),
            "KO/TKO%": round(method["KO/TKO"] * 100),
            "Sub%": round(method["Submission"] * 100),
            "Dec%": round(method["Decision"] * 100),
            "finaliza%": round(sim.p_finish * 100), "approx": approx,
        }

        # --- CUOTAS: detalle del análisis de valor en la tabla de salida ---
        if v is not None:
            fila.update({
                # cuotas crudas tal como venían en el CSV, para la tabla del MERCADO
                "cuota_a": fight.get("odds_a", ""), "cuota_b": fight.get("odds_b", ""),
                "base": "modelo+mercado" if calibrador is not None else "modelo",
                "P_mercado_A%": round(v.p_mercado_a * 100, 1),
                "P_final_A%": round(v.p_final_a * 100, 1),
                "disc_cruda": round(v.discrepancia_cruda * 100, 1),
                "disc%": round(v.discrepancia * 100, 1),
                "apuesta": (a["name"] if v.lado == "A" else
                            b["name"] if v.lado == "B" else ""),
                "cuota": round(v.cuota_decimal, 2) if np.isfinite(v.cuota_decimal) else "",
                "EV%": round(v.ev * 100, 1) if np.isfinite(v.ev) else "",
                "bankroll%": round(v.kelly * 100, 1),
                "veredicto": v.veredicto,
            })
            valores.append((fila, v))

            # Mercado de MÉTODO (7 vías). Es el único donde el backtest
            # encontró ventaja real, así que se analiza aparte.
            # En una repetición sin modelo de 6 clases propio no se analiza:
            # value caería en el de models/, que sí vio peleas posteriores.
            sin_m6 = repeticion is not None and modelo6 is None
            if con_metodo and not sin_m6:
                cuotas6 = [fight.get(c) for c in COL_METODO]
                ops = value.analizar_metodo(X, cuotas6, modelo6=modelo6)
                if ops and "error" not in ops[0]:
                    metodos.append((a["name"], b["name"], ops))
                    opciones = ops
                elif ops:
                    print(f"[!] {a['name']} vs {b['name']}: {ops[0]['error']}")

            # Mercado de 5 VÍAS. No es una alternativa al de arriba: es lo que
            # Betano ofrece cuando NO separa KO de sumisión. Sin esto, esas
            # peleas se quedaban sin ninguna opción de método.
            if con_metodo5 and not sin_m6:
                cuotas4 = [fight.get(c) for c in COL_METODO5]
                ops5 = value.analizar_metodo5(X, cuotas4, modelo6=modelo6)
                if ops5 and "error" not in ops5[0]:
                    opciones5 = ops5
                elif ops5:
                    print(f"[!] {a['name']} vs {b['name']} (5 vías): {ops5[0]['error']}")
        rows.append(fila)
        # `info_*` no lo usa la consola: es para que la UI pueda EXPLICAR por qué
        # una pelea sale marcada como poco fiable ("solo 1 pelea en UFC", "sin
        # stats de golpeo") en vez de limitarse a mostrar la etiqueta.
        def _info(f, src):
            n_hist = _conteo_historial(f)
            # UFCStats tiene tasas neutras como respaldo cuando la tabla está
            # vacía. No mostrarlas como un historial real de victorias.
            historial_metodos = None
            if float(f.get("wins", 0) or 0) > 0:
                tasas = {metodo: pd.to_numeric(f.get(campo), errors="coerce")
                         for metodo, campo in (("KO/TKO", "win_ko_rate"),
                                                ("Submission", "win_sub_rate"),
                                                ("Decision", "win_dec_rate"))}
                if all(pd.notna(t) and np.isfinite(t) and 0 <= t <= 1 for t in tasas.values()) \
                        and 0 < sum(tasas.values()) <= 1.001:
                    historial_metodos = {metodo: float(tasa) for metodo, tasa in tasas.items()}
            return {"n_peleas_hist": n_hist,
                    "historial_disponible": bool(f.get("historial_disponible", n_hist is not None)),
                    "n_peleas_ufc": _conteo_historial({"n_peleas_hist": f.get("n_peleas_ufc")}),
                    "historial_ufc_confirmado": f.get("historial_ufc_confirmado") is True,
                    "debut_ufc_confirmado": confirmed_ufc_debut(f),
                    "slpm": float(f.get("slpm", 0) or 0),
                    "wins": int(f.get("wins", 0) or 0),
                    "losses": int(f.get("losses", 0) or 0),
                    "ultimas_peleas": oposicion.ultimas_peleas(f["name"], fecha_corte),
                    "metodo_victorias": historial_metodos,
                    "metodo_victorias_fuente": ("carrera profesional (Sherdog)" if f.get("_sherdog")
                                                else "victorias registradas en UFCStats" if src == "ufcstats"
                                                else "victorias en UFC anteriores al corte" if src == "historial"
                                                else "historial del dataset"),
                    "identidad_ambigua": bool(f.get("identidad_ambigua")),
                    "sherdog": bool(f.get("_sherdog")), "fuente": src}

        # El resultado se lee DESPUÉS de predecir, solo para mostrarlo.
        resultado = (CT.resultado_real(a["name"], b["name"], fecha_corte, sim.winner)
                     if repeticion is not None else None)
        consenso.append({"a": a["name"], "b": b["name"], "sim": sim, "resultado": resultado,
                         "orden_cartelera": indice, "total_cartelera": total,
                         "es_titulo": es_titulo, "titulo_fuente": fila["titulo_fuente"],
                         "titulo_automatico": titulo_automatico,
                         "method": method, "pocos": pocos, "v": v,
                         "probabilidades_metodo": p_metodo6,
                         "metodo6": opciones, "metodo5": opciones5,
                         "info_a": _info(a, sa), "info_b": _info(b, sb)})
        avisar("prediccion", f"Pelea {indice + 1}/{total} lista: {na} vs {nb}.",
               indice + 1, total)

    if not rows:
        print("No se pudo predecir ninguna pelea (revisa nombres o conexión).")
        return {"rows": [], "valores": [], "metodos": [], "consenso": [],
                "missing": sorted(set(missing)), "con_cuotas": con_cuotas,
                "con_metodo": con_metodo, "con_metodo5": con_metodo5,
                "evento": event, "repeticion": repeticion} if devolver_todo else None

    avisar("informes", "Armando el resumen y guardando el reporte de la cartelera…")
    # --- Las tres miradas, por separado ---
    # Se imprimen aparte a propósito. Cuando iban mezcladas en una sola columna,
    # un pick donde el MODELO iba tibio (59%) y la CASA muy convencida (72%)
    # aparecía como "fuerte 77%" y se leía como si el sistema estuviera seguro.
    # Caso real: Cepo vs Urbina, 01-ago-2026 (ganó Urbina por TKO).
    hay_corto = any(r.get("corto_a") or r.get("corto_b") for r in rows)
    _tabla_modelo(rows, valores, hasta=fecha_corte if repeticion is not None else None)
    if con_cuotas and valores:
        _tabla_mercado(rows, valores)
    # La 3 solo si de verdad hay algún reemplazo en la cartelera.
    if hay_corto:
        _tabla_corto(rows)
    if con_cuotas and valores:
        _tabla_mezcla(rows, valores, hay_corto)

    if missing:
        print(f"\n[!] no encontrados en ninguna fuente (revisa datos, nombres o conexión): {sorted(set(missing))}")
    print("  ~ = stats del dataset Kaggle (no UFCStats en vivo) -> algo más viejos")

    # El resumen accionable va PRIMERO; las tablas largas solo si las pides.
    if consenso:
        _imprimir_consenso(consenso, con_cuotas, detalle)
    if detalle:
        print("\n" + "=" * 88)
        print("  ÚLTIMAS 5 PELEAS DE CADA UNO (contra quién, y cómo terminó)")
        print("=" * 88)
        for c in consenso:
            oposicion.imprimir(c["a"])
            oposicion.imprimir(c["b"])
        if valores:
            _imprimir_valor(valores)
        if metodos:
            _imprimir_metodo(metodos)

    out_dir = C.OUTPUTS / event
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "tabla_predicciones.csv"
    DB.to_csv(pd.DataFrame(rows), out, index=False)
    avisar("informes", "Reporte de la cartelera guardado.")
    print(f"\n[ok] tabla -> {out}")
    print(f"[ok] todo el reporte de esta cartelera -> {out_dir}")
    if devolver_todo:
        return {"rows": rows, "valores": valores, "metodos": metodos,
                "consenso": consenso, "missing": sorted(set(missing)),
                "con_cuotas": con_cuotas, "con_metodo": con_metodo,
                "con_metodo5": con_metodo5,
                "calibrador": calibrador is not None, "evento": event,
                "hay_corto": hay_corto, "modelo_real": model is not None,
                "repeticion": repeticion}
    return pd.DataFrame(rows)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    detalle = "--detalle" in sys.argv
    card_arg = args[0] if args else DEFAULT_CARD
    predict_card(card_arg, detalle=detalle)
