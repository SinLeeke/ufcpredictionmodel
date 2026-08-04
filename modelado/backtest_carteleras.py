"""
modelado/backtest_carteleras.py
Prueba el modelo contra carteleras REALES completas, reconstruyendo el estado de
cada peleador tal como estaba EL DÍA DEL EVENTO.

Por qué no basta con usar la ficha de UFCStats: esa ficha muestra los promedios
de HOY, que ya incluyen las peleas posteriores al evento. Usarla sería hacer
trampa (el modelo "vería el futuro" y sus aciertos serían falsos).

Acá cada stat — golpeo, derribos, récord, racha, edad y control — se recalcula
usando SOLO las peleas anteriores a la fecha del evento.

Uso:
    python -m modelado.backtest_carteleras            # las últimas 4 carteleras
    python -m modelado.backtest_carteleras 8          # las últimas 8
    python -m modelado.backtest_carteleras 4 --cuotas # compara modelo vs mercado vs mezcla

Con --cuotas solo entran carteleras que tengan cuotas reales en el dataset (que
llega hasta marzo 2026, o sea NO las más recientes) y se comparan tres formas de
predecir la misma pelea: el modelo solo, el mercado solo y la mezcla calibrada
que usa card.py cuando le das cuotas.
"""
from __future__ import annotations

import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import config as C
from src.control_stats import enriquecer, MIN_PELEAS_FIABLE
from src.features import columnas_disponibles
from src import oposicion
from src import reemplazos
from src.model import load_models
from src.ufcstats_ingest import _acumulado, _emparejar, cargar, _cargar_bio, features_pelea

_HIST = None
_BIO = None


def _historial():
    global _HIST, _BIO
    if _HIST is None:
        _HIST = _emparejar(cargar()).sort_values("date")
        _BIO = _cargar_bio()
    return _HIST


def stats_a_fecha(nombre: str, fecha: pd.Timestamp) -> dict | None:
    """Stats del peleador usando SOLO sus peleas anteriores a 'fecha'."""
    h = _historial()
    sub = h[(h["fighter"] == nombre) & (h["date"] < fecha)]
    if sub.empty:
        return None
    d = _acumulado(sub)
    d["name"] = nombre
    d["days_since_last_fight"] = float((fecha - sub["date"].max()).days)

    bio = _BIO.get(nombre.lower())
    if bio:
        d["height_cm"], d["reach_cm"] = bio["height_cm"], bio["reach_cm"]
        d["stance"] = bio["stance"]
        if pd.notna(bio["dob"]):
            d["age"] = round((fecha - bio["dob"]).days / 365.25, 1)

    d = enriquecer(d, fecha)         # control también recortado a la fecha
    # Con pocas peleas en UFC, completar con la carrera completa (Sherdog),
    # recortada TAMBIÉN a la fecha del evento para no mirar el futuro.
    if int(d.get("n_peleas_hist", 99)) < 3:
        try:
            from src import sherdog
            d = sherdog.completar(d, hasta=fecha)
        except Exception:
            pass
    return d


def _cuotas_lookup() -> dict:
    """
    {(fecha, {nombre_a, nombre_b}): {nombre_lower: cuota}} desde el dataset Kaggle.

    Se indexa por el PAR de nombres y la fecha porque hay revanchas: el mismo
    par de peleadores puede aparecer en dos eventos distintos.
    """
    ruta = C.DATA_RAW / "kaggle_ufc.csv"
    if not ruta.exists():
        return {}
    k = pd.read_csv(ruta, low_memory=False)
    k["date"] = pd.to_datetime(k["date"], errors="coerce")
    k = k.dropna(subset=["date", "R_fighter", "B_fighter"])
    out = {}
    for r in k.itertuples():
        if pd.isna(r.R_odds) or pd.isna(r.B_odds):
            continue
        ra, rb = str(r.R_fighter).lower(), str(r.B_fighter).lower()
        out[(r.date, frozenset({ra, rb}))] = {ra: r.R_odds, rb: r.B_odds}
    return out


def _elo_a_fecha(nombre: str) -> float:
    """ELO de la tabla (calculada con datos hasta el corte del dataset Kaggle)."""
    if C.ELO_TABLE.exists():
        df = pd.read_csv(C.ELO_TABLE)
        hit = df[df["fighter"].str.lower() == nombre.lower()]
        if not hit.empty:
            return float(hit.iloc[0]["elo"])
    return C.ELO_BASE


def backtest(n_carteleras: int = 4, con_cuotas: bool = False,
             evento: str | None = None):
    res = pd.read_csv(C.DATA_PROCESSED / "ufcstats_fights.csv")
    res["date"] = pd.to_datetime(res["date"])
    res = res[res["winner"].astype(str).str.len() > 0]
    fechas = res.groupby("event")["date"].first().sort_values(ascending=False)

    if evento:
        hit = [e for e in fechas.index if evento.lower() in e.lower()]
        if not hit:
            raise SystemExit(f"No encontré ninguna cartelera que contenga '{evento}'.\n"
                             "Últimas disponibles:\n  " +
                             "\n  ".join(list(fechas.index[:10])))
        fechas = fechas[hit]
        n_carteleras = len(hit)

    cuotas, calibrador = {}, None
    if con_cuotas:
        from src import value
        cuotas = _cuotas_lookup()
        calibrador = value.cargar_calibrador()
        if not cuotas:
            raise SystemExit("No hay data/raw/kaggle_ufc.csv para sacar las cuotas.")
        if calibrador is None:
            raise SystemExit("Falta el calibrador. Corre:  python -m modelado.backtest_valor")
        # Solo carteleras donde TODAS las peleas tengan cuota, para que las tres
        # columnas se comparen sobre exactamente el mismo conjunto de peleas.
        def _cubierta(e, f):
            card = res[res.event == e]
            return all((f, frozenset({str(r.fighter_a).lower(),
                                      str(r.fighter_b).lower()})) in cuotas
                       for r in card.itertuples())
        fechas = fechas[[_cubierta(e, f) for e, f in fechas.items()]]
        if fechas.empty:
            raise SystemExit("Ninguna cartelera reciente tiene cuotas en el dataset.")

    eventos = fechas.head(n_carteleras)
    modelo, _ = load_models()
    # marcadores: [modelo, mercado, calibrado]
    tot_ok = np.zeros(3, int)
    tot = 0
    resumen = []

    for evento, fecha in eventos.items():
        card = res[res.event == evento]
        ok = np.zeros(3, int)
        n = conf_ok = conf_n = 0
        filas = []
        for _, r in card.iterrows():
            a = stats_a_fecha(r.fighter_a, fecha)
            b = stats_a_fecha(r.fighter_b, fecha)
            if a is None or b is None:
                continue          # debutante absoluto: sin datos previos
            feat = features_pelea(a, b, _elo_a_fecha(a["name"]),
                                  _elo_a_fecha(b["name"]))
            # Calidad de oposición A LA FECHA DEL EVENTO, no a hoy: usar hoy
            # metería las peleas POSTERIORES al evento y volvería a inflar el
            # acierto, que es justo el leakage que este backtest existe para evitar.
            feat.update(oposicion.features(a["name"], b["name"], fecha))
            # Corto aviso: también a la fecha del evento. Es info pública ex-ante
            # (se anuncia el reemplazo días antes), así que no es leakage.
            feat.update(reemplazos.features(a["name"], b["name"], fecha))
            X = pd.DataFrame([feat])
            p = float(modelo.predict_proba(X[columnas_disponibles(X)])[:, 1][0])

            # mercado y mezcla calibrada (solo si hay cuotas para esta pelea)
            p_mkt = p_cal = None
            if con_cuotas:
                par = cuotas.get((fecha, frozenset({str(r.fighter_a).lower(),
                                                    str(r.fighter_b).lower()})))
                if par:
                    from src.odds import prob_sin_vig
                    ca = par[str(r.fighter_a).lower()]
                    cb = par[str(r.fighter_b).lower()]
                    p_mkt = prob_sin_vig(ca, cb)[0]
                    p_cal = value.combinar(p, p_mkt, calibrador)
            if con_cuotas and p_cal is None:
                continue          # sin cuotas: fuera, para comparar peras con peras

            pocos = [f["name"].split()[-1] for f in (a, b)
                     if int(f.get("n_peleas_hist", 99)) < MIN_PELEAS_FIABLE]
            # p viene orientada al fighter_a de UFCStats, igual que a["name"]
            picks, aciertos = [], []
            for prob in (p, p_mkt, p_cal):
                if prob is None:
                    picks.append(None); aciertos.append(False); continue
                pk = a["name"] if prob >= 0.5 else b["name"]
                picks.append(pk); aciertos.append(pk == r.winner)
            n += 1
            ok += np.array(aciertos, int)

            # "confianza" se mide con la probabilidad que el sistema usaría hoy
            usada = p_cal if p_cal is not None else p
            conf = max(usada, 1 - usada) * 100
            if conf >= 60:
                conf_n += 1; conf_ok += aciertos[2 if p_cal is not None else 0]
            filas.append((f"{r.fighter_a.split()[-1]} vs {r.fighter_b.split()[-1]}",
                          picks, [p, p_mkt, p_cal], aciertos,
                          r.winner.split()[-1], pocos))

        if n == 0:
            continue
        tot_ok += ok; tot += n
        resumen.append((evento, fecha, ok.copy(), n, conf_ok, conf_n))

        print("=" * 92)
        print(f"  {evento}   ({fecha:%d-%b-%Y})")
        print("=" * 92)
        if con_cuotas:
            print(f"  {'PELEA':28}{'MODELO':>16}{'MERCADO':>16}{'MEZCLA':>16}"
                  f"  {'GANÓ':16}")
            for v, pk, pr, ac, g, pocos in sorted(filas, key=lambda x: -max(x[2][2], 1-x[2][2])):
                cel = ""
                for i in range(3):
                    marca = "OK" if ac[i] else "X "
                    cel += f"{pk[i].split()[-1][:9]:>10} {max(pr[i],1-pr[i])*100:>3.0f}{marca:>3}"
                av = " pocos datos" if pocos else ""
                print(f"  {v:28}{cel}  {g:16}{av}")
            print(f"  -> modelo {ok[0]}/{n} ({ok[0]/n*100:.0f}%)   "
                  f"mercado {ok[1]}/{n} ({ok[1]/n*100:.0f}%)   "
                  f"MEZCLA {ok[2]}/{n} ({ok[2]/n*100:.0f}%)")
        else:
            for v, pk, pr, ac, g, pocos in sorted(filas, key=lambda x: -max(x[2][0], 1-x[2][0])):
                av = "  pocos datos" if pocos else ""
                c = max(pr[0], 1 - pr[0]) * 100
                print(f"  {v:30}{pk[0].split()[-1]:18}{c:>5.0f}%  "
                      f"{g:18}{'OK' if ac[0] else 'X '}{av}")
            print(f"  -> {ok[0]}/{n} = {ok[0]/n*100:.0f}%"
                  + (f"   |  con confianza >=60%: {conf_ok}/{conf_n}" if conf_n else ""))
        print()

    print("=" * 92)
    print("  RESUMEN")
    print("=" * 92)
    if con_cuotas:
        print(f"  {'cartelera':44}{'MODELO':>12}{'MERCADO':>12}{'MEZCLA':>12}")
        for evento, fecha, ok, n, c_ok, c_n in resumen:
            print(f"  {evento[:43]:44}" + "".join(
                f"{f'{ok[i]}/{n}':>12}" for i in range(3)))
        print("-" * 92)
        print(f"  {'TOTAL':44}" + "".join(
            f"{f'{tot_ok[i]}/{tot}':>12}" for i in range(3)))
        print(f"  {'':44}" + "".join(
            f"{f'{tot_ok[i]/tot*100:.0f}%':>12}" for i in range(3)))
        print()
        print("  MODELO  = solo tus stats (lo que hacía el bot antes)")
        print("  MERCADO = solo la cuota, sin comisión (la opinión de las casas)")
        print("  MEZCLA  = lo que card.py usa hoy cuando le das cuotas")
        print()
        print(f"  Con {tot} peleas el margen de error es de ±{100/np.sqrt(tot)*0.5:.0f} puntos,")
        print("  así que diferencias de 2-3 peleas entre columnas no significan nada.")
        print("  El número que vale es el del backtest grande: 65.3% / 69.8% / 70.1%")
        print("  sobre 613 peleas (python -m modelado.backtest_valor).")
    else:
        print(f"  {'cartelera':46}{'acierto':>12}{'>=60% conf':>14}")
        for evento, fecha, ok, n, c_ok, c_n in resumen:
            conf = f"{c_ok}/{c_n}" if c_n else "-"
            print(f"  {evento[:45]:46}{f'{ok[0]}/{n} ({ok[0]/n*100:.0f}%)':>12}{conf:>14}")
        print("-" * 92)
        print(f"  {'TOTAL':46}{f'{tot_ok[0]}/{tot} ({tot_ok[0]/tot*100:.0f}%)':>12}")
        print()
        print("  Referencia: el backtest sobre 1.256 peleas da 65% global.")
        print("  Con 4 carteleras (~50 peleas) el margen de error es de +-7 puntos.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("n", nargs="?", type=int, default=4)
    ap.add_argument("--cuotas", action="store_true",
                    help="compara modelo vs mercado vs mezcla (solo carteleras con cuotas)")
    ap.add_argument("--evento", default=None,
                    help="prueba UNA cartelera por nombre parcial, p.ej. --evento Ankalaev")
    args = ap.parse_args()
    backtest(args.n, args.cuotas, args.evento)
