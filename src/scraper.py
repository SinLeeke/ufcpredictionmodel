"""
scraper.py
FASE 1 — Recolección de datos.

Estrategia realista:
  * UFCStats  -> HTML estático, se scrapea bien con requests + BeautifulSoup.
                 Es la fuente PRINCIPAL de métricas técnicas (SLpM, Str.Acc, etc.).
  * Sherdog   -> historial / rachas. Suele estar detrás de Cloudflare y bloquea
                 requests "pelados". Dejo la estructura + parser, pero en producción
                 conviene cloudscraper o Selenium con delays largos.
  * Tapology  -> biometría (edad, reach, stance). Anti-bot agresivo. Misma idea.

Plan de contingencia (recomendado y activado por defecto):
  Si el scraping directo falla o te bloquean, usa load_from_kaggle(), que ingiere
  el dataset público 'rajeevw/ufcdata' con exactamente estas variables ya limpias.

IMPORTANTE: los selectores CSS de sitios web cambian con el tiempo. Trata los
selectores de abajo como un punto de partida verificado contra la estructura
conocida de cada sitio; si algo devuelve None, inspecciona el HTML y ajústalo.
Haz scraping respetando robots.txt y con los delays de config.py.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C


# --------------------------------------------------------------------------- #
# Utilidades HTTP
# --------------------------------------------------------------------------- #
def _get(url: str) -> Optional[BeautifulSoup]:
    """GET con reintentos, headers de navegador y delay. Devuelve None si falla."""
    for attempt in range(1, C.MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=C.HEADERS, timeout=C.REQUEST_TIMEOUT_SEC)
            time.sleep(C.REQUEST_DELAY_SEC)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
            # 403/503 típico de anti-bot (Cloudflare) -> no insistas eternamente
            if r.status_code in (403, 429, 503):
                print(f"[!] {url} devolvió {r.status_code} (anti-bot). "
                      f"Considera cloudscraper/Selenium o el fallback Kaggle.")
                return None
        except requests.RequestException as e:
            print(f"[retry {attempt}/{C.MAX_RETRIES}] {url} -> {e}")
            time.sleep(C.REQUEST_DELAY_SEC * attempt)
    return None


def _pct_to_float(txt: str) -> float:
    """'52%' -> 0.52 ; '--' -> 0.0"""
    if not txt or "--" in txt:
        return 0.0
    return round(float(re.sub(r"[^\d.]", "", txt)) / 100.0, 4)


def _num(txt: str) -> float:
    """'4.35' / '1.20' -> float ; '--' -> 0.0"""
    if not txt:
        return 0.0
    m = re.search(r"[\d.]+", txt)
    return float(m.group()) if m else 0.0


# --------------------------------------------------------------------------- #
# Modelo de datos de un peleador
# --------------------------------------------------------------------------- #
@dataclass
class Fighter:
    name: str
    # --- UFCStats: eficiencia técnica ---
    slpm: float = 0.0        # significant strikes landed per minute
    str_acc: float = 0.0     # striking accuracy (0-1)
    sapm: float = 0.0        # significant strikes absorbed per minute
    str_def: float = 0.0     # striking defense (0-1)
    td_avg: float = 0.0      # takedowns per 15 min
    td_acc: float = 0.0      # takedown accuracy (0-1)
    td_def: float = 0.0      # takedown defense (0-1)
    sub_avg: float = 0.0     # submission attempts per 15 min
    # --- Tapology / UFCStats: biometría ---
    age: float = 0.0
    height_cm: float = 0.0
    reach_cm: float = 0.0
    stance: str = "Orthodox"
    weight_class: str = "Lightweight"
    # --- Sherdog: historial y vulnerabilidad ---
    wins: int = 0
    losses: int = 0
    streak: int = 0                  # + = racha ganadora, - = racha perdedora
    days_since_last_fight: float = 0.0
    win_ko_rate: float = 0.0         # % de sus victorias por KO/TKO
    win_sub_rate: float = 0.0        # % por sumisión
    win_dec_rate: float = 0.0        # % por decisión
    lost_by_finish_rate: float = 0.0 # % de sus derrotas en las que fue finalizado (vulnerabilidad)


# --------------------------------------------------------------------------- #
# 1) UFCSTATS  (fuente principal, funcional)
# --------------------------------------------------------------------------- #
def scrape_ufcstats_fighter(details_url: str) -> Optional[dict]:
    """
    Parsea una página de detalle de peleador en UFCStats, p.ej.:
        http://ufcstats.com/fighter-details/e1248941f9bf7bd5
    Extrae SLpM, Str.Acc, SApM, Str.Def, TD Avg, TD Acc, TD Def, Sub.Avg,
    además de altura, reach, stance y DOB (para derivar la edad).
    """
    soup = _get(details_url)
    if soup is None:
        return None

    # Los stats están en <li class="b-list__box-list-item"> con "Label: value"
    stats = {}
    for li in soup.select("li.b-list__box-list-item"):
        label = li.find("i")
        if not label:
            continue
        key = label.get_text(strip=True).rstrip(":")
        value = li.get_text(strip=True).replace(label.get_text(strip=True), "").strip()
        stats[key] = value

    name_tag = soup.select_one("span.b-content__title-highlight")
    name = name_tag.get_text(strip=True) if name_tag else "Unknown"

    return {
        "name": name,
        "slpm": _num(stats.get("SLpM", "0")),
        "str_acc": _pct_to_float(stats.get("Str. Acc.", "0")),
        "sapm": _num(stats.get("SApM", "0")),
        "str_def": _pct_to_float(stats.get("Str. Def.", "0")),
        "td_avg": _num(stats.get("TD Avg.", "0")),
        "td_acc": _pct_to_float(stats.get("TD Acc.", "0")),
        "td_def": _pct_to_float(stats.get("TD Def.", "0")),
        "sub_avg": _num(stats.get("Sub. Avg.", "0")),
        "height_cm": _height_to_cm(stats.get("Height", "")),
        "reach_cm": _reach_to_cm(stats.get("Reach", "")),
        "stance": stats.get("STANCE", "Orthodox") or "Orthodox",
        "dob": stats.get("DOB", ""),   # 'Mar 01, 1992' -> se convierte a edad aparte
    }


def iter_ufcstats_fighter_urls() -> list[str]:
    """
    UFCStats lista peleadores alfabéticamente en:
        http://ufcstats.com/statistics/fighters?char=a&page=all
    Recorre a-z y devuelve todas las URLs de detalle.
    """
    urls = []
    for char in "abcdefghijklmnopqrstuvwxyz":
        page = _get(f"{C.UFCSTATS_BASE}/statistics/fighters?char={char}&page=all")
        if page is None:
            continue
        for a in page.select("a.b-link.b-link_style_black[href*='fighter-details']"):
            href = a.get("href")
            if href and href not in urls:
                urls.append(href)
    return urls


def _height_to_cm(txt: str) -> float:
    """'5' 11"' -> 180.3"""
    m = re.match(r"(\d+)'\s*(\d+)", txt or "")
    if not m:
        return 0.0
    feet, inches = int(m.group(1)), int(m.group(2))
    return round((feet * 12 + inches) * 2.54, 1)


def _reach_to_cm(txt: str) -> float:
    """'76\"' -> 193.0"""
    m = re.search(r"(\d+)", txt or "")
    return round(int(m.group(1)) * 2.54, 1) if m else 0.0


# --------------------------------------------------------------------------- #
# 2) SHERDOG  (historial / momentum) — estructura + parser
# --------------------------------------------------------------------------- #
def scrape_sherdog_fighter(fighter_url: str) -> Optional[dict]:
    """
    Sherdog suele bloquear requests directos (Cloudflare). Si _get() devuelve
    None, cae al fallback Kaggle. Cuando funciona, la ficha vive en, p.ej.:
        https://www.sherdog.com/fighter/Magomed-Ankalaev-88283
    y el historial está en <table class="new_table fighter"> con columnas
    Result / Opponent / Event / Method / Round.
    """
    soup = _get(fighter_url)
    if soup is None:
        return None

    results = []  # lista de tuplas (win/loss, method_str, date)
    for row in soup.select("table.new_table.fighter tr")[1:]:
        cols = row.select("td")
        if len(cols) < 4:
            continue
        outcome = cols[0].get_text(strip=True).lower()   # 'win' / 'loss'
        method = cols[3].get_text(strip=True)            # 'KO (Punches)', 'Decision (Unanimous)'...
        results.append((outcome, method))

    return _summarize_history(results)


def _summarize_history(results: list[tuple[str, str]]) -> dict:
    """Convierte una lista cronológica de resultados en métricas de historial."""
    wins = [r for r in results if r[0].startswith("win")]
    losses = [r for r in results if r[0].startswith("loss")]

    def _rate(subset, keyword):
        if not subset:
            return 0.0
        hits = sum(1 for _, m in subset if keyword.lower() in m.lower())
        return round(hits / len(subset), 4)

    # Racha reciente (results debe venir del más reciente al más antiguo)
    streak = 0
    if results:
        first = results[0][0]
        for outcome, _ in results:
            if outcome.startswith(first.split()[0]):
                streak += 1
            else:
                break
        streak = streak if first.startswith("win") else -streak

    ko = _rate(wins, "ko") or _rate(wins, "tko")
    sub = _rate(wins, "submission")
    dec = _rate(wins, "decision")
    lost_by_finish = 1.0 - _rate(losses, "decision") if losses else 0.0

    return {
        "wins": len(wins),
        "losses": len(losses),
        "streak": streak,
        "win_ko_rate": ko,
        "win_sub_rate": sub,
        "win_dec_rate": dec,
        "lost_by_finish_rate": round(lost_by_finish, 4),
    }


# --------------------------------------------------------------------------- #
# 3) TAPOLOGY  (biometría) — estructura + parser
# --------------------------------------------------------------------------- #
def scrape_tapology_fighter(fighter_url: str) -> Optional[dict]:
    """
    Tapology tiene anti-bot fuerte. Estructura: la ficha muestra 'Age', 'Height',
    'Reach', 'Weight Class' en <div class="details detailsLite"> con pares
    label/valor. Igual que arriba: si _get() falla, usa el fallback.
    """
    soup = _get(fighter_url)
    if soup is None:
        return None

    data = {}
    for li in soup.select("div.details li"):
        strong = li.find("strong")
        if not strong:
            continue
        key = strong.get_text(strip=True).rstrip(":").lower()
        val = li.get_text(strip=True).replace(strong.get_text(strip=True), "").strip()
        data[key] = val

    age = _num(data.get("age", "0"))
    return {"age": age, "weight_class": data.get("weight class", "Lightweight")}


# --------------------------------------------------------------------------- #
# PLAN DE CONTINGENCIA: Kaggle
# --------------------------------------------------------------------------- #
def load_from_kaggle() -> pd.DataFrame:
    """
    Descarga e ingiere el dataset público de UFC de Kaggle, que ya trae todas las
    columnas técnicas que necesitamos. Es la ruta recomendada si te bloquean.

    Requisitos:
        pip install kagglehub
        # y credenciales en ~/.kaggle/kaggle.json  (Account -> Create New API Token)

    Devuelve un DataFrame con una fila por PELEA (formato ideal para model.py),
    con columnas por peleador rojo (R_) y azul (B_).
    """
    try:
        import kagglehub
        path = kagglehub.dataset_download(C.KAGGLE_DATASET)
        # El dataset trae varios CSV; 'data.csv' es el consolidado por pelea.
        csv = next(p for p in __import__("pathlib").Path(path).glob("*.csv")
                   if p.name in ("data.csv", "ufc-master.csv"))
        df = pd.read_csv(csv)
        df.to_csv(C.DATA_RAW / "kaggle_ufc.csv", index=False)
        print(f"[ok] Kaggle -> {len(df)} peleas cargadas en {C.DATA_RAW/'kaggle_ufc.csv'}")
        return df
    except Exception as e:
        raise RuntimeError(
            "No se pudo cargar desde Kaggle. Instala kagglehub y configura "
            "~/.kaggle/kaggle.json, o descarga el CSV manualmente a data/raw/. "
            f"Detalle: {e}"
        )


# --------------------------------------------------------------------------- #
# Orquestador
# --------------------------------------------------------------------------- #
def build_fighters_table(source: str = "kaggle", refrescar: bool = False) -> pd.DataFrame:
    """
    Consolida datos y deja listos features.csv + fighters.csv.
      source='kaggle' -> descarga (si hace falta) y ejecuta la ingesta real.
      source='scrape' -> combina UFCStats + Sherdog + Tapology (avanzado).

    refrescar=True intenta bajar la versión nueva del dataset aunque ya haya una
    copia local, y si la descarga falla SIGUE CON LA LOCAL. Reemplaza al viejo
    `del data\\raw\\kaggle_ufc.csv` de actualizar_bd.bat, que borraba la copia
    ANTES de saber si la descarga iba a funcionar: sin kaggle.json o sin
    internet, la base se quedaba sin su única fuente de cuotas históricas.
    load_from_kaggle solo escribe el CSV después de leerlo entero, así que una
    descarga a medias tampoco pisa la copia buena.
    """
    if source == "kaggle":
        raw_path = C.DATA_RAW / "kaggle_ufc.csv"
        if refrescar or not raw_path.exists():
            try:
                load_from_kaggle()
            except Exception as e:                      # noqa: BLE001
                if not raw_path.exists():
                    raise
                print(f"[!] no pude bajar la versión nueva de Kaggle; sigo con la copia "
                      f"local.\n    Detalle: {e}")
        # La ingesta real vive en kaggle_ingest para no mezclar responsabilidades.
        from src.kaggle_ingest import build_all
        _, fighters = build_all()
        return fighters
    raise NotImplementedError(
        "El scraping vivo requiere poblar las URLs de detalle por peleador con "
        "iter_ufcstats_fighter_urls() y combinar las 3 fuentes por nombre. "
        "Empieza con source='kaggle'."
    )


if __name__ == "__main__":
    # Ruta por defecto: contingencia Kaggle (descarga + ingesta completa).
    # --refrescar-kaggle: intenta bajar la versión nueva aunque haya copia local.
    build_fighters_table(source="kaggle", refrescar="--refrescar-kaggle" in sys.argv)
