"""
oposicion.py
CALIDAD DE LA OPOSICIÓN reciente: contra quién peleó, y cómo le fue.

El problema que resuelve: el modelo veía `streak_diff` (racha cruda) y `elo_diff`,
pero una racha de 5 victorias contra rivales flojos vale lo mismo que 5 contra
contendientes. Y una derrota por KO hace 2 meses no pesa igual que una decisión
dividida hace 3 años.

Para cada (peleador, fecha) mira sus últimas N peleas ANTERIORES a esa fecha y
resume:
  * opp_elo       - ELO promedio de los rivales que enfrentó (calidad del calendario)
  * opp_elo_max   - el mejor rival al que le GANÓ (techo demostrado)
  * ko_infl       - cuántas de sus victorias recientes fueron por KO/TKO
  * sub_infl      - ídem por sumisión
  * ko_recibido   - cuántas veces lo finalizaron (durabilidad; señal de declive)
  * momentum      - resultados recientes PONDERADOS por la calidad del rival y
                    por lo reciente que son

ANTI-LEAKAGE: todo se calcula con `date < fecha_de_la_pelea`, nunca <=. El ELO de
cada rival es el que tenía ANTES de esa pelea (pre-fight), no el actual — usar el
ELO de hoy para juzgar una pelea de 2019 es exactamente el bug que ya infló el AUC
a 0.93 una vez (ver kaggle_ingest).

Fuente: data/processed/ufcstats_fights.csv (8.794 peleas desde 1994, más profundo
que features.csv que arranca en 2010).
"""
from __future__ import annotations

import re
import sys
from bisect import bisect_left
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src.fighter_names import canonical_key

FIGHTS_CSV = C.DATA_PROCESSED / "ufcstats_fights.csv"

# Cuántas peleas recientes se miran.
#
# SE PROBÓ SUBIRLO A 12 Y SE REVIRTIÓ — no repetir el experimento sin leer esto.
# El barrido sobre el test 2025+ daba monótono (3: 0,7150 | 5: 0,7159 | 8: 0,7166
# | 12: 0,7186) y 12-vs-5 ganaba en 7 de 8 semillas (+0,0035 AUC). Parecía sólido.
# Pero esas 8 semillas eran 8 corridas sobre EL MISMO período de test, o sea
# consistencia entre semillas, no entre épocas. Al validar en períodos que NO se
# usaron para elegir N:
#     test 2022 -> gana N=5    (0,6658 vs 0,6638)
#     test 2023 -> gana N=5    (0,6541 vs 0,6513)
#     test 2024 -> gana N=12   (0,6734 vs 0,6799)
# 1 de 3. La ventaja no replica: era ajuste al conjunto de test.
# Se queda en 5, que además es la convención del deporte ("last five") y coincide
# con lo que muestra el reporte.
N_RECIENTES = 5

# Cuántas se MUESTRAN en el reporte (hoy igual a la ventana del modelo, pero
# separado para poder cambiarlas por su cuenta).
N_MOSTRAR = 5

# Vida media del peso por antigüedad, en días. Una pelea de hace 18 meses pesa
# la mitad que una de hace 0. Barrido medido (AUC, ventana de 5):
#   180d 0,7142 | 365d 0,7165 | 540d 0,7159 | 1095d 0,7136 | sin decaimiento 0,7108
# El óptimo es plano entre 365 y 540; se deja 540. Lo importante del barrido es
# que SIN decaimiento se pierden 5 milésimas de AUC: el peso por antigüedad es
# la parte que más aporta de todo el bloque de momentum.
VIDA_MEDIA_DIAS = 540.0

_IDX: dict | None = None

# Valores neutros para quien no tiene historial (debutante en UFC). Se usa el ELO
# base porque asumir 0 haría que "no sé nada de él" se leyera como "es pésimo",
# que es el mismo error que ya costó caro con las tasas de control (ver
# control_stats.PROMEDIO_LIGA).
NEUTRO = {
    "n": 0, "opp_elo": C.ELO_BASE, "opp_elo_max": C.ELO_BASE,
    "ko_infl": 0.0, "sub_infl": 0.0, "ko_recibido": 0.0, "momentum": 0.0,
    "peleas": [],
}


def _norm(s: str) -> str:
    return canonical_key(s)


def _es_finish(metodo: str) -> str:
    """'KO/TKO' | 'Submission' | 'Decision' desde el texto libre de UFCStats."""
    m = str(metodo).upper()
    if "SUB" in m:
        return "Submission"
    if "KO" in m or "TKO" in m:
        return "KO/TKO"
    return "Decision"


def _construir_indice() -> dict:
    """
    Un pase cronológico por todas las peleas construyendo el ELO, y de paso
    guardando por peleador la lista de sus combates con el ELO PRE-PELEA del
    rival. Un solo pase = imposible mirar el futuro por construcción.
    """
    if not FIGHTS_CSV.exists():
        print("[oposicion] falta ufcstats_fights.csv -> sin calidad de oposición")
        return {}

    df = pd.read_csv(FIGHTS_CSV)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "fighter_a", "fighter_b"]).sort_values("date")

    elo: dict[str, float] = {}
    hist: dict[str, list] = {}

    def get(f):
        return elo.get(f, C.ELO_BASE)

    for r in df.itertuples(index=False):
        a, b = _norm(r.fighter_a), _norm(r.fighter_b)
        if not a or not b:
            continue
        ra, rb = get(a), get(b)
        met = _es_finish(r.method)
        gan = _norm(r.winner) if pd.notna(r.winner) else ""

        # Se guarda el ELO del rival ANTES de esta pelea (rb para a, ra para b).
        for yo, rival, mi_elo, su_elo in ((a, b, ra, rb), (b, a, rb, ra)):
            if gan == yo:
                res = 1
            elif gan in (a, b):
                res = -1
            else:
                res = 0            # empate / no contest
            # El nombre del rival se guarda SIN normalizar para poder mostrarlo.
            nombre_rival = r.fighter_b if yo == a else r.fighter_a
            hist.setdefault(yo, []).append(
                (r.date, su_elo, res, met, nombre_rival,
                 getattr(r, "weight_class", None)))

        # actualizar ELO: K con bonus por finalización. Sin categoría de peso —
        # acá interesa el nivel general del rival, no su ranking divisional.
        #
        # SE PROBÓ el ELO GRADUADO acá (el de features.VALOR_POR_RESULTADO, que
        # le da 0,55 a una decisión dividida) usando el `method_detail` que ahora
        # scrapea ufcstats_events. SE REVIRTIÓ: validado en 4 períodos empeoró en
        # 3 (2022 −0,0034 | 2024 −0,0007 | 2025+ −0,0050) y solo mejoró en 2023
        # (+0,0208). El promedio salía +0,0029 pero lo cargaba entero ese outlier
        # — el mismo patrón que ya engañó con N_RECIENTES=12. No reintentar sin
        # mirar los 4 períodos por separado, no el promedio.
        # (El ELO graduado SÍ se usa en kaggle_ingest, donde sí está validado.)
        if gan in (a, b):
            perd = b if gan == a else a
            rw, rl = get(gan), get(perd)
            exp = 1.0 / (1.0 + 10 ** ((rl - rw) / 400.0))
            k = C.ELO_K * (C.ELO_FINISH_BONUS if met != "Decision" else 1.0)
            d = k * (1.0 - exp)
            elo[gan], elo[perd] = rw + d, rl - d

    # a arrays ordenados por fecha, para búsqueda binaria
    idx = {}
    for f, lst in hist.items():
        lst.sort(key=lambda t: t[0])
        idx[f] = {
            "fechas": [t[0] for t in lst],
            "opp_elo": np.array([t[1] for t in lst], dtype=float),
            "res": np.array([t[2] for t in lst], dtype=float),
            "met": [t[3] for t in lst],
            "rival": [t[4] for t in lst],
            "division": [t[5] for t in lst],
        }
    print(f"[oposicion] historial de rivales para {len(idx)} peleadores")
    return idx


def _indice() -> dict:
    global _IDX
    if _IDX is None:
        _IDX = _construir_indice()
    return _IDX


def resumen(nombre: str, hasta, n: int = N_RECIENTES) -> dict:
    """
    Calidad de oposición de `nombre` en sus últimas `n` peleas ANTERIORES a
    `hasta` (exclusivo). Devuelve NEUTRO si no hay historial.
    """
    d = _indice().get(_norm(nombre))
    if not d:
        return dict(NEUTRO)
    hasta = pd.Timestamp(hasta)
    # bisect_left => estrictamente anterior: la pelea del mismo día no cuenta.
    corte = bisect_left(d["fechas"], hasta)
    if corte == 0:
        return dict(NEUTRO)
    ini = max(0, corte - n)
    fechas = d["fechas"][ini:corte]
    opp = d["opp_elo"][ini:corte]
    res = d["res"][ini:corte]
    met = d["met"][ini:corte]
    k = len(res)

    gano = res > 0
    perdio = res < 0
    # Peso por antigüedad: decaimiento exponencial con VIDA_MEDIA_DIAS.
    dias = np.array([(hasta - f).days for f in fechas], dtype=float)
    peso = 0.5 ** (dias / VIDA_MEDIA_DIAS)

    # Momentum: gana/pierde ponderado por lo bueno que era el rival (normalizado
    # alrededor del ELO base) y por lo reciente. Ganarle a uno de 1700 suma
    # mucho más que a uno de 1400.
    calidad = (opp - C.ELO_BASE) / 200.0
    momentum = float(np.sum(res * peso * (1.0 + np.clip(calidad, -0.8, 2.0))) / peso.sum())

    return {
        "n": k,
        "opp_elo": float(np.average(opp, weights=peso)),
        # Techo demostrado: el mejor rival al que efectivamente le ganó.
        "opp_elo_max": float(opp[gano].max()) if gano.any() else float(opp.min()),
        "ko_infl": float(sum(1 for i in range(k) if gano[i] and met[i] == "KO/TKO") / k),
        "sub_infl": float(sum(1 for i in range(k) if gano[i] and met[i] == "Submission") / k),
        # Durabilidad: que te finalicen es mucho peor señal que perder por tarjetas.
        "ko_recibido": float(sum(1 for i in range(k)
                                 if perdio[i] and met[i] != "Decision") / k),
        "momentum": momentum,
        # Detalle legible de las mismas peleas que se resumieron arriba, de la
        # más reciente a la más antigua. Es lo que se imprime en el reporte.
        "peleas": [
            {"fecha": fechas[i], "rival": d["rival"][ini + i],
             "opp_elo": float(opp[i]),
             "resultado": "gana" if res[i] > 0 else ("pierde" if res[i] < 0 else "empate"),
             "metodo": met[i]}
            for i in range(k - 1, -1, -1)
        ],
    }


def ultima_division(nombre: str, hasta=None) -> str | None:
    """
    Categoría de peso de la última pelea del peleador ANTERIOR a `hasta`
    (None = hasta hoy), con los mismos nombres que usa el ELO por categoría.

    La usa card._elo para elegir de QUÉ categoría sacar el ELO. Antes se tomaba
    la primera fila del nombre, cuyo orden no tiene que ver con el peleador.
    """
    d = _indice().get(_norm(nombre))
    if not d:
        return None
    corte = len(d["fechas"]) if hasta is None else bisect_left(d["fechas"], pd.Timestamp(hasta))
    if corte == 0:
        return None
    wc = d["division"][corte - 1]
    return wc if isinstance(wc, str) and wc else None


# Features diferenciales que se agregan al modelo (A - B), salvo n_* que son de control.
COLUMNAS = ["opp_elo_diff", "opp_elo_max_diff", "ko_infl_diff", "sub_infl_diff",
            "ko_recibido_diff", "momentum_diff"]


def features(nombre_a: str, nombre_b: str, fecha, n: int = N_RECIENTES) -> dict:
    """Diferencial A-B de la calidad de oposición reciente de ambos."""
    a = resumen(nombre_a, fecha, n)
    b = resumen(nombre_b, fecha, n)
    return {
        "opp_elo_diff": a["opp_elo"] - b["opp_elo"],
        "opp_elo_max_diff": a["opp_elo_max"] - b["opp_elo_max"],
        "ko_infl_diff": a["ko_infl"] - b["ko_infl"],
        "sub_infl_diff": a["sub_infl"] - b["sub_infl"],
        "ko_recibido_diff": a["ko_recibido"] - b["ko_recibido"],
        "momentum_diff": a["momentum"] - b["momentum"],
    }


def imprimir(nombre: str, hasta=None, n: int = N_MOSTRAR) -> None:
    """Ficha legible: contra quién peleó, cómo terminó y qué tan bueno era."""
    hasta = pd.Timestamp(hasta) if hasta is not None else pd.Timestamp.now()
    r = resumen(nombre, hasta, n)
    if not r["n"]:
        print(f"  {nombre}: sin historial en UFCStats (¿debutante?)")
        return
    print(f"\n  {nombre} — últimas {r['n']} peleas")
    print(f"  {'fecha':12}{'resultado':11}{'rival':26}{'nivel':>7}  método")
    print("  " + "-" * 68)
    for p in r["peleas"]:
        nivel = ("elite" if p["opp_elo"] >= 1650 else
                 "bueno" if p["opp_elo"] >= 1550 else "medio")
        print(f"  {p['fecha']:%Y-%m-%d}  {p['resultado']:11}{p['rival'][:25]:26}"
              f"{nivel:>7}  {p['metodo']}")
    print(f"\n  nivel medio del calendario : {r['opp_elo']:.0f} ELO")
    print(f"  mejor rival al que le ganó : {r['opp_elo_max']:.0f} ELO")
    print(f"  finaliza  {r['ko_infl']*100:.0f}% por KO / {r['sub_infl']*100:.0f}% por sumisión")
    print(f"  lo finalizaron en el {r['ko_recibido']*100:.0f}% de estas peleas")
    print(f"  momentum: {r['momentum']:+.2f}  "
          f"({'en alza' if r['momentum'] > 0.5 else 'plano/en baja' if r['momentum'] < 0.2 else 'estable'})")


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Ilia Topuria"
    imprimir(q)
