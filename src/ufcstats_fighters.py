"""
ufcstats_fighters.py
Baja la BIOMETRÍA de todos los peleadores de UFCStats: fecha de nacimiento,
altura, alcance y postura.

Por qué hace falta: las estadísticas de pelea (ufcstats_fightstats) traen lo que
pasó DENTRO del octágono, pero no la edad ni el alcance. Y `age_diff` es la
variable más importante del modelo — sin ella, el AUC cae ~0.07.

Como la fecha de nacimiento es fija, la EDAD se calcula después para cada pelea
según su fecha (en ufcstats_ingest), sin mirar el futuro.

Uso:
    python -m src.ufcstats_fighters          # ~2.700 fichas, unos 6-8 min
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src import storage as DB
from src import ufcstats as U

FIGHTERS_CACHE = C.DATA_RAW / "ufcstats_fighters.json"
BIO_CSV = C.DATA_PROCESSED / "ufcstats_bio.csv"


def listar_urls() -> list[str]:
    """Recorre el índice alfabético (a-z) y junta las URLs de todas las fichas."""
    from src.fast_fetch import fetch_many

    paginas = [f"{C.UFCSTATS_BASE}/statistics/fighters?char={c}&page=all"
               for c in "abcdefghijklmnopqrstuvwxyz"]
    urls: set[str] = set()

    def recoger(_u, soup):
        for a in soup.select("a.b-link[href*=fighter-details]"):
            href = a.get("href")
            if href:
                urls.add(href)

    fetch_many(paginas, recoger, label="páginas del índice")
    return sorted(urls)


def parse_ficha(soup, url: str) -> dict:
    s = U._parse_career_stats(soup)
    tag = soup.select_one("span.b-content__title-highlight")
    return {
        "fighter_url": url,
        "name": tag.get_text(strip=True) if tag else "",
        "dob": s.get("DOB", ""),
        "height_cm": U._height_cm(s.get("Height", "")),
        "reach_cm": U._reach_cm(s.get("Reach", "")),
        "stance": s.get("STANCE", "") or "Orthodox",
    }


def build() -> pd.DataFrame:
    cache = DB.read_json(FIGHTERS_CACHE) if DB.exists(FIGHTERS_CACHE) else {}
    urls = listar_urls()
    print(f"[fichas] {len(urls)} peleadores | en caché: {len(cache)}")

    pendientes = [u for u in urls if u not in cache]
    if pendientes:
        from src.fast_fetch import fetch_many

        def guardar(url, soup):
            cache[url] = parse_ficha(soup, url)
            if DB.key(FIGHTERS_CACHE) is not None:
                DB.put_json_entry(FIGHTERS_CACHE, url, cache[url])

        fetch_many(pendientes, guardar, label="fichas")
        DB.write_text(FIGHTERS_CACHE, json.dumps(cache, ensure_ascii=False), encoding="utf-8")

    df = pd.DataFrame(list(cache.values()))
    df = df[df["name"].astype(str).str.len() > 0].copy()
    df["dob"] = pd.to_datetime(df["dob"], format="mixed", errors="coerce")
    DB.to_csv(df, BIO_CSV, index=False)

    print(f"[ok] {len(df)} peleadores -> {BIO_CSV}")
    print(f"     con fecha de nacimiento: {df.dob.notna().sum()} "
          f"| con alcance: {(df.reach_cm > 0).sum()} | con altura: {(df.height_cm > 0).sum()}")
    return df


if __name__ == "__main__":
    build()
