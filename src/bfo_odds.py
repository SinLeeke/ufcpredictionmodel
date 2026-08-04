"""
bfo_odds.py
Cuotas históricas desde BestFightOdds, para tapar el hueco que deja Kaggle.

POR QUÉ EXISTE
El dataset de Kaggle (`mdabbert/ultimate-ufc-dataset`) combina stats de UFCStats
con cuotas de bestfightodds.com. Sus stats las scrapeamos nosotros, pero las
CUOTAS no están en UFCStats — y el dataset va ~4 meses atrasado. Resultado: las
peleas más recientes se quedan sin cuotas, que es justo lo que hace falta para
seguir validando la única ventaja probada del proyecto (decisiones en el mercado
de método, ver backtest_metodo.py).

ALCANCE DELIBERADAMENTE CHICO: esto NO reemplaza a Kaggle. Solo baja los
peleadores que aparecen en el hueco (peleas posteriores al último dato de
Kaggle). Re-scrapear los 16 años completos significaría ~4.400 páginas y, peor,
recruzar 8.000 peleas por nombre entre dos fuentes: el cruce de nombres ya
provocó los dos bugs más caros de este proyecto (Ankalaev/Temirov en Sherdog y
los dos "Mike Davis"). No vale la pena para reconstruir algo que ya tenemos.

CÓMO
Una página por peleador (`/fighters/<slug>-<id>`) con su historial completo:
    Matchup | Open | Closing range | Movement | Event
Las cuotas vienen en formato americano. Se toma la de CIERRE (la última del
rango), que es la que mejor refleja la información disponible antes de pelear.

Uso:
    python -m src.bfo_odds            # baja solo el hueco (peleas sin cuota)
    python -m src.bfo_odds --revisar  # compara lo bajado contra Kaggle
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C

BASE = "https://www.bestfightodds.com"
CACHE = C.DATA_RAW / "bfo_odds.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
PAUSA = 1.0     # sitio chico: se va despacio a propósito


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _get(url: str) -> BeautifulSoup | None:
    for intento in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            if r.status_code == 200:
                return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            pass
        time.sleep(2.0 * (intento + 1))
    return None


def buscar_peleador(nombre: str) -> str | None:
    """URL de la ficha en BFO. Usa su buscador y exige match exacto del nombre."""
    soup = _get(f"{BASE}/search?query={requests.utils.quote(nombre)}")
    if soup is None:
        return None
    objetivo = _norm(nombre)
    for a in soup.find_all("a", href=True):
        if not a["href"].startswith("/fighters/"):
            continue
        # Match EXACTO. Devolver "el primero que se parezca" es exactamente el
        # bug que le asignó el récord de Ankalaev a Temirov en sherdog.py.
        if _norm(a.get_text(" ", strip=True)) == objetivo:
            return BASE + a["href"]
    return None


_RE_AM = re.compile(r"^[+-]\d{2,5}$")


def _cierre(celdas: list[str]) -> float | None:
    """
    Cuota de CIERRE de una fila. La tabla trae Open | Closing range (2 celdas) |
    Movement: se toma la ÚLTIMA americana válida, que es el cierre.
    """
    ams = [c for c in celdas if _RE_AM.match(c.strip())]
    return float(ams[-1]) if ams else None


def historial(url: str) -> list[dict]:
    """
    Peleas de esa ficha: [{rival, fecha, cuota_propia, cuota_rival}].

    La tabla alterna: fila del peleador, fila del rival, y encabezados con el
    nombre del evento y la fecha. Se recorre en pares.
    """
    soup = _get(url)
    if soup is None:
        return []
    filas = []
    for tr in soup.select("table tr"):
        celdas = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if celdas:
            filas.append(celdas)

    out, i = [], 0
    while i < len(filas) - 1:
        a, b = filas[i], filas[i + 1]
        ca, cb = _cierre(a), _cierre(b)
        if ca is None or cb is None:
            i += 1
            continue
        # La fecha aparece al final de la fila del rival ('Feb 26th 2026').
        m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})",
                      " ".join(b))
        fecha = None
        if m:
            try:
                fecha = pd.Timestamp(f"{m.group(1)} {m.group(2)} {m.group(3)}").date()
            except ValueError:
                fecha = None
        # El nombre del rival es el texto inicial de su fila, sin las cuotas.
        rival = re.split(r"[+-]\d{2,5}", b[0])[0].strip() if b else ""
        out.append({"rival": _norm(rival), "fecha": str(fecha) if fecha else "",
                    "cuota_propia": ca, "cuota_rival": cb})
        i += 2
    return out


def _hueco() -> pd.DataFrame:
    """Peleas de UFCStats posteriores al último dato con cuotas de Kaggle."""
    h = pd.read_csv(C.DATA_PROCESSED / "ufcstats_fights.csv")
    h["date"] = pd.to_datetime(h["date"])
    k_path = C.DATA_RAW / "kaggle_ufc.csv"
    if not k_path.exists():
        raise SystemExit("Falta data/raw/kaggle_ufc.csv (corre 'python -m src.scraper').")
    k = pd.read_csv(k_path, low_memory=False)
    corte = pd.to_datetime(k["date"]).max()
    return h[h["date"] > corte].copy()


def construir(limite: int | None = None) -> dict:
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    gap = _hueco()
    peleadores = sorted(set(gap["fighter_a"]) | set(gap["fighter_b"]))
    pendientes = [p for p in peleadores if _norm(p) not in cache]
    if limite:
        pendientes = pendientes[:limite]
    print(f"[bfo] hueco: {len(gap)} peleas, {len(peleadores)} peleadores | "
          f"en caché: {len(cache)} | a bajar: {len(pendientes)}")

    for i, nombre in enumerate(pendientes, 1):
        url = buscar_peleador(nombre)
        time.sleep(PAUSA)
        cache[_norm(nombre)] = historial(url) if url else []
        time.sleep(PAUSA)
        if i % 20 == 0:
            print(f"    {i}/{len(pendientes)}...")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    con = sum(1 for v in cache.values() if v)
    print(f"[bfo] {len(cache)} peleadores en caché ({con} con historial) -> {CACHE}")
    return cache


def cuotas_de(fighter_a: str, fighter_b: str, fecha) -> tuple[float, float] | None:
    """(cuota_a, cuota_b) americanas de esa pelea, o None si no está."""
    if not CACHE.exists():
        return None
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    a, b = _norm(fighter_a), _norm(fighter_b)
    f = str(pd.Timestamp(fecha).date())
    for yo, rival, invertir in ((a, b, False), (b, a, True)):
        for reg in cache.get(yo, []):
            if reg["rival"] == rival and reg["fecha"] == f:
                ca, cb = reg["cuota_propia"], reg["cuota_rival"]
                return (cb, ca) if invertir else (ca, cb)
    return None


def revisar() -> None:
    """Cuántas peleas del hueco quedaron con cuota."""
    gap = _hueco()
    ok = 0
    for r in gap.itertuples(index=False):
        if cuotas_de(r.fighter_a, r.fighter_b, r.date):
            ok += 1
    print(f"\nPeleas del hueco con cuota recuperada: {ok}/{len(gap)} "
          f"({100*ok/max(len(gap),1):.0f}%)")


if __name__ == "__main__":
    if "--revisar" in sys.argv:
        revisar()
    else:
        lim = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
        construir(limite=lim)
        revisar()
