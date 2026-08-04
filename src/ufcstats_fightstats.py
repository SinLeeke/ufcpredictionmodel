"""
ufcstats_fightstats.py
Baja las ESTADÍSTICAS DE CADA PELEA desde UFCStats (una página por combate).

Esto es lo que el dataset de Kaggle NO tenía:
  * Ctrl  -> tiempo de control en el suelo. La métrica clave del grappling:
             un peleador puede ganar controlando 8 de 15 minutos sin golpear mucho.
  * Golpes ABSORBIDOS y derribos DEFENDIDOS: como cada pelea trae los números de
    LOS DOS peleadores, la defensa sale calculada de verdad, no por defecto.
  * KD (knockdowns), Rev (reversiones), y el desglose de golpes por zona
    (cabeza/cuerpo/pierna) y por posición (distancia/clinch/suelo).

Además, al ser pelea-por-pelea CON FECHA, permite calcular el promedio de cada
peleador *tal como estaba antes de cada combate* -> sin data leakage.

Requiere haber corrido antes:
    python -m src.ufcstats_events

Uso:
    python -m src.ufcstats_fightstats                # todas (~18 min la 1ª vez)
    python -m src.ufcstats_fightstats --limit 200    # prueba corta
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src.ufcstats_events import EVENTS_CACHE

STATS_CACHE = C.DATA_RAW / "ufcstats_fightstats.json"
STATS_CSV = C.DATA_PROCESSED / "ufcstats_fight_stats.csv"


def _of(txt: str) -> tuple[float, float]:
    """'42 of 91' -> (42, 91). '---' -> (0, 0)."""
    m = re.findall(r"\d+", txt or "")
    if len(m) >= 2:
        return float(m[0]), float(m[1])
    return (float(m[0]), float(m[0])) if m else (0.0, 0.0)


def _num(txt: str) -> float:
    m = re.search(r"\d+", txt or "")
    return float(m.group()) if m else 0.0


def _ctrl_sec(txt: str) -> float:
    """'4:35' -> 275 segundos. '--' -> 0."""
    m = re.match(r"\s*(\d+):(\d+)", txt or "")
    return float(m.group(1)) * 60 + float(m.group(2)) if m else 0.0


def _cells(row) -> list[list[str]]:
    """Cada celda trae 2 <p> (uno por peleador). Devuelve [[valA, valB], ...]."""
    out = []
    for td in row.select("td.b-fight-details__table-col"):
        ps = [p.get_text(" ", strip=True) for p in td.select("p.b-fight-details__table-text")]
        out.append(ps if len(ps) >= 2 else (ps * 2 if ps else ["", ""]))
    return out


def parse_fight(soup, url: str) -> list[dict]:
    """
    Devuelve 2 filas (una por peleador) con sus estadísticas de esa pelea.

    OJO con las tablas: la página trae 4 y las de TOTALES no llevan clase CSS
    (las que sí la llevan son las de desglose por round). Por eso se seleccionan
    por posición: [0] = totales, [2] = golpes por zona/posición. Usar la clase
    hacía leer el Round 1 como si fuera la pelea entera.
    """
    tables = soup.select("table")
    if not tables:
        return []

    fila = tables[0].select_one("tbody tr")
    if fila is None:
        return []
    c = _cells(fila)
    if len(c) < 10:
        return []

    # Orden de columnas: Fighter, KD, Sig.str, Sig.str%, Total str, Td, Td%, Sub.att, Rev, Ctrl
    nombres = c[0]
    filas = []
    for i in range(2):
        sig_l, sig_a = _of(c[2][i])
        tot_l, tot_a = _of(c[4][i])
        td_l, td_a = _of(c[5][i])
        filas.append({
            "fight_url": url,
            "fighter": nombres[i],
            "kd": _num(c[1][i]),
            "sig_landed": sig_l, "sig_att": sig_a,
            "total_landed": tot_l, "total_att": tot_a,
            "td_landed": td_l, "td_att": td_a,
            "sub_att": _num(c[7][i]),
            "rev": _num(c[8][i]),
            "ctrl_sec": _ctrl_sec(c[9][i]),
        })

    # Desglose de golpes por zona y posición (tabla 3 del detalle)
    if len(tables) >= 3:
        f2 = tables[2].select_one("tbody tr")
        if f2 is not None:
            d = _cells(f2)
            if len(d) >= 9:
                for i in range(2):
                    for key, idx in (("head", 3), ("body", 4), ("leg", 5),
                                     ("distance", 6), ("clinch", 7), ("ground", 8)):
                        l, a = _of(d[idx][i])
                        filas[i][f"{key}_landed"] = l
                        filas[i][f"{key}_att"] = a
    return filas


def build(limit: int | None = None) -> pd.DataFrame:
    if not EVENTS_CACHE.exists():
        raise SystemExit("Falta el historial de eventos. Corre primero:\n"
                         "    python -m src.ufcstats_events")
    eventos = json.loads(EVENTS_CACHE.read_text(encoding="utf-8"))

    urls, meta = [], {}
    for fights in eventos.values():
        for f in fights:
            u = f.get("fight_url")
            if u:
                urls.append(u)
                meta[u] = f
    urls = list(dict.fromkeys(urls))
    if not urls:
        raise SystemExit(
            "El caché de eventos no tiene links de pelea (es de una versión vieja).\n"
            "Bórralo y vuelve a bajarlo (son ~90 s):\n"
            "    del data\\raw\\ufcstats_events.json\n"
            "    python -m src.ufcstats_events")

    cache = json.loads(STATS_CACHE.read_text(encoding="utf-8")) if STATS_CACHE.exists() else {}
    pendientes = [u for u in urls if u not in cache]
    if limit:
        pendientes = pendientes[:limit]
    print(f"[peleas] {len(urls)} totales | en caché: {len(cache)} | a bajar: {len(pendientes)}")

    if pendientes:
        from src.fast_fetch import fetch_many

        def guardar(url, soup):
            cache[url] = parse_fight(soup, url)

        fetch_many(pendientes, guardar, label="peleas")
        STATS_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    filas = []
    for u, fs in cache.items():
        info = meta.get(u, {})
        for f in fs:
            filas.append({**f, "date": info.get("date", ""), "event": info.get("event", ""),
                          "winner": info.get("winner", ""), "method": info.get("method", ""),
                          "weight_class": info.get("weight_class", "")})
    df = pd.DataFrame(filas)
    if df.empty:
        raise SystemExit("No se extrajo ninguna estadística; revisa los selectores.")
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df["won"] = (df["fighter"] == df["winner"]).astype(int)
    df = df.sort_values("date")
    df.to_csv(STATS_CSV, index=False)

    print(f"[ok] {len(df)} filas peleador-pelea -> {STATS_CSV}")
    print(f"     peleas: {df.fight_url.nunique()} | rango: {df.date.min():%Y-%m-%d} a {df.date.max():%Y-%m-%d}")
    print(f"     control medio: {df.ctrl_sec.mean():.0f} s | derribos medios: {df.td_landed.mean():.2f}")
    return df


if __name__ == "__main__":
    lim = None
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    build(limit=lim)
