"""
ufcstats_events.py
Descarga el HISTORIAL COMPLETO DE PELEAS desde UFCStats — la fuente oficial,
que se actualiza el mismo día del evento (a diferencia del dataset de Kaggle,
que suele ir meses atrasado).

Qué saca, por pelea:
    fecha, evento, peleador A, peleador B, ganador, método (KO/Sub/Dec),
    round, tiempo, categoría de peso

Es INCREMENTAL: cachea por evento en data/raw/ufcstats_events.json, así que la
primera corrida baja todo (~780 eventos, unos 25 min con los delays de cortesía)
y las siguientes solo bajan los eventos nuevos (segundos).

Uso:
    python -m src.ufcstats_events              # actualiza el historial
    python -m src.ufcstats_events --limit 20   # solo los 20 eventos más recientes
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src import storage as DB
from src import ufcstats as U

EVENTS_CACHE = C.DATA_RAW / "ufcstats_events.json"
FIGHTS_CSV = C.DATA_PROCESSED / "ufcstats_fights.csv"


def list_events() -> list[dict]:
    """Todos los eventos completados: [{url, name, date}]. El más reciente primero."""
    soup = U._get(f"{C.UFCSTATS_BASE}/statistics/events/completed?page=all")
    if soup is None:
        return []
    out = []
    for row in soup.select("tr.b-statistics__table-row"):
        a = row.select_one("a.b-link[href*=event-details]")
        if not a:
            continue
        date_el = row.select_one("span.b-statistics__date")
        out.append({
            "url": a.get("href"),
            "name": a.get_text(strip=True),
            "date": date_el.get_text(strip=True) if date_el else "",
        })
    return out


_METHOD_MAP = [
    ("SUB", "Submission"), ("S-DEC", "Decision"), ("U-DEC", "Decision"),
    ("M-DEC", "Decision"), ("DEC", "Decision"), ("KO/TKO", "KO/TKO"),
    ("CNC", "Other"), ("DQ", "Other"), ("Overturned", "Other"),
]


def _norm_method(txt: str) -> str:
    t = (txt or "").upper()
    for key, val in _METHOD_MAP:
        if key in t:
            return val
    return "Other"


# Token FINO tal como lo publica UFCStats: distingue decisión unánime, dividida y
# mayoritaria. `_norm_method` las aplasta a "Decision" para las 3 clases del
# modelo de método, pero esa distinción NO es cosmética: el ELO graduado le da
# 0,55 a una dividida y 0,91 a una unánime (ver features.VALOR_POR_RESULTADO).
# Antes ese dato salía del dataset de Kaggle, que va ~4 meses atrasado; sacarlo
# de acá lo deja disponible el mismo día del evento.
_FINOS = ("U-DEC", "S-DEC", "M-DEC", "KO/TKO", "SUB", "CNC", "DQ")


def _method_detail(txt: str) -> str:
    t = (txt or "").upper()
    for k in _FINOS:
        if k in t:
            return k
    return ""


def parse_event(url: str, name: str, date: str) -> list[dict]:
    """Lista de peleas de un evento. UFCStats pone al GANADOR primero en cada fila."""
    soup = U._get(url)
    if soup is None:
        return []
    return parse_event_soup(soup, name, date)


def parse_event_soup(soup, name: str, date: str) -> list[dict]:
    """Igual que parse_event pero recibiendo el HTML ya descargado (modo paralelo)."""
    fights = []
    for row in soup.select("tr.b-fight-details__table-row"):
        cols = row.select("td.b-fight-details__table-col")
        if len(cols) < 7:
            continue
        names = [a.get_text(strip=True) for a in cols[1].select("a")]
        if len(names) < 2:
            continue
        flag = row.select_one("i.b-flag__text")
        outcome = flag.get_text(strip=True).lower() if flag else ""
        wc = cols[6].get_text(" ", strip=True)
        texts = [c.get_text(" ", strip=True) for c in cols]
        crudo = " ".join(texts[7:9]) if len(texts) > 7 else ""
        method = _norm_method(crudo)
        rnd = texts[8] if len(texts) > 8 else ""
        # tiempo del último round ('4:31'): con el round da la duración total,
        # necesaria para convertir totales en tasas por minuto.
        tiempo = ""
        for t in texts[8:]:
            m_t = re.search(r"\b(\d{1,2}):(\d{2})\b", t)
            if m_t:
                tiempo = m_t.group()
                break

        # En UFCStats el primer nombre de la fila es el ganador (salvo empate/NC)
        winner = names[0] if outcome.startswith("win") else ""
        fights.append({
            "event": name, "date": date,
            "fighter_a": names[0], "fighter_b": names[1],
            "winner": winner, "method": method,
            "method_detail": _method_detail(crudo),
            "round": re.sub(r"\D", "", rnd)[:1], "time": tiempo, "weight_class": wc,
            # link al detalle: lo consume ufcstats_fightstats para bajar las
            # estadísticas (golpes, derribos, control) de cada pelea.
            "fight_url": row.get("data-link", ""),
        })
    return fights


def _incompleto(fights: list) -> bool:
    """
    True si el evento está cacheado pero sin resultados usables.

    Pasa cuando se scrapeó ANTES de que se peleara: UFCStats ya publica la
    cartelera pero todas las filas vienen sin ganador y sin método. Sin esto,
    ese evento se quedaba congelado en el caché para siempre y sus peleas nunca
    entraban al entrenamiento — justo las más recientes, que son las que más
    importan.
    """
    if not fights:
        return True
    return not any(f.get("winner") for f in fights)


def _sin_detalle(fights: list) -> bool:
    """Cacheado por una versión vieja del scraper, sin el método fino (U-DEC...)."""
    return bool(fights) and not any("method_detail" in f for f in fights)


def build(limit: int | None = None, refrescar_incompletos: bool = True) -> pd.DataFrame:
    cache = DB.read_json(EVENTS_CACHE) if DB.exists(EVENTS_CACHE) else {}
    events = list_events()
    if not events:
        raise SystemExit("No pude listar eventos (¿sin internet o cambió UFCStats?).")
    if limit:
        events = events[:limit]

    nuevos = [e for e in events if e["url"] not in cache]
    revisitar = []
    if refrescar_incompletos:
        revisitar = [e for e in events if e["url"] in cache
                     and (_incompleto(cache[e["url"]]) or _sin_detalle(cache[e["url"]]))]
    pendientes = nuevos + revisitar
    print(f"[eventos] {len(events)} listados | en caché: {len(cache)} | "
          f"nuevos: {len(nuevos)} | a refrescar: {len(revisitar)}")

    if pendientes:
        # Descarga PARALELA (ver fast_fetch): ~15x más rápido que uno por uno.
        from src.fast_fetch import fetch_many
        meta = {e["url"]: e for e in pendientes}

        def guardar(url, soup):
            e = meta[url]
            cache[url] = parse_event_soup(soup, e["name"], e["date"])
            if DB.key(EVENTS_CACHE) is not None:
                DB.put_json_entry(EVENTS_CACHE, url, cache[url])

        fetch_many([e["url"] for e in pendientes], guardar, label="eventos")
        DB.write_text(EVENTS_CACHE, json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    rows = [f for fights in cache.values() for f in fights]
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("No se extrajo ninguna pelea; revisa los selectores.")
    df["date"] = pd.to_datetime(df["date"], format="mixed", errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    DB.to_csv(df, FIGHTS_CSV, index=False)
    print(f"[ok] {len(df)} peleas -> {FIGHTS_CSV}")
    print(f"     rango: {df.date.min():%Y-%m-%d} a {df.date.max():%Y-%m-%d}")
    print(f"     métodos: {df.method.value_counts().to_dict()}")
    if "method_detail" in df.columns:
        finos = df[df.method_detail.astype(str).str.contains("DEC", na=False)]
        print(f"     detalle de decisiones: {finos.method_detail.value_counts().to_dict()}")
    return df


if __name__ == "__main__":
    lim = None
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    # --todo fuerza re-bajar TODO (útil si cambian los selectores del sitio).
    if "--todo" in sys.argv and DB.exists(EVENTS_CACHE):
        DB.unlink(EVENTS_CACHE)
        print("[eventos] caché borrado: se rebaja todo")
    build(limit=lim)
