"""
sherdog.py
Trae el historial COMPLETO de un peleador desde Sherdog, incluidas sus peleas
FUERA de UFC (Bellator, PFL, KSW, LFA, ligas regionales…).

Para qué sirve: UFCStats solo conoce lo que pasó dentro de UFC. Un debutante con
1 pelea en UFC puede tener 15 peleas profesionales atrás, y el modelo lo trataba
como un desconocido. En el backtest, 8 de 31 fallos involucraban peleadores con
menos de 3 peleas registradas — justo este agujero.

Qué se puede y qué no:
  * SÍ: récord total, racha real, cómo gana (KO/Sub/Dec) y cómo lo han vencido,
    todo contando su carrera completa.
  * NO: estadísticas finas (golpes, derribos, control). Sherdog no las publica;
    eso solo existe para las peleas de UFC.

Aviso de calidad del dato: ganar 12 peleas en shows regionales NO equivale a
ganarlas en UFC. Por eso las peleas fuera de UFC se marcan aparte, para poder
ponderarlas distinto (ver `peso_no_ufc`).
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C

BASE = "https://www.sherdog.com"
CACHE = C.DATA_RAW / "sherdog_cache.json"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
DELAY = 1.0          # Sherdog es más sensible que UFCStats: se va con calma

# Cuánto vale una pelea fuera de UFC frente a una de UFC. El nivel de rival es
# muy inferior en shows regionales; 0.5 es un compromiso razonable (no es 0,
# porque ganar 12 seguidas dice algo; no es 1, porque no es lo mismo).
PESO_NO_UFC = 0.5

_sesion = requests.Session()
_sesion.headers.update(HEADERS)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def buscar(nombre: str) -> str | None:
    """URL de la ficha de Sherdog para un nombre, vía su buscador."""
    try:
        r = _sesion.get(f"{BASE}/stats/fightfinder",
                        params={"SearchTxt": nombre}, timeout=C.REQUEST_TIMEOUT_SEC)
        time.sleep(DELAY)
        if r.status_code != 200:
            return None
        s = BeautifulSoup(r.text, "html.parser")
        objetivo = _norm(nombre)
        for a in s.select('a[href*="/fighter/"]'):
            href = a.get("href", "")
            slug = _norm(re.sub(r"-\d+$", "", href.split("/fighter/")[-1]).replace("-", " "))
            if slug == objetivo:
                return BASE + href
        # SIN match exacto -> None. Antes se devolvía "el primer resultado" y eso
        # asignó el récord de Ankalaev a Temirov: un dato equivocado es mucho
        # peor que no tener dato, porque el modelo lo usa como si fuera cierto.
        return None
    except requests.RequestException:
        return None


def _metodo(txt: str) -> str:
    t = (txt or "").lower()
    if "submission" in t or "sub " in t or "choke" in t or "armbar" in t:
        return "Submission"
    if "ko" in t or "tko" in t or "punch" in t or "knockout" in t:
        return "KO/TKO"
    if "decision" in t:
        return "Decision"
    return "Other"


def historial(nombre: str, usar_cache: bool = True) -> dict | None:
    """
    Récord completo del peleador. Devuelve None si no se encuentra.
    Claves: wins, losses, racha, tasas de victoria y de ser finalizado,
    peleas_ufc / peleas_no_ufc.
    """
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    k = _norm(nombre)
    if usar_cache and k in cache:
        return cache[k]

    url = buscar(nombre)
    if not url:
        return None
    try:
        r = _sesion.get(url, timeout=C.REQUEST_TIMEOUT_SEC)
        time.sleep(DELAY)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None

    s = BeautifulSoup(r.text, "html.parser")
    # La ficha trae VARIAS tablas: la primera es el récord PROFESIONAL y las
    # siguientes son amateur/exhibición. Sumarlas todas inflaba los récords
    # (Ankalaev salía 36-3 en vez de ~21-2). Solo se usa la primera.
    tablas = s.select("table.new_table.fighter")
    if not tablas:
        return None
    peleas = []
    for tr in tablas[0].select("tr")[1:]:
        celdas = tr.select("td")
        td = [x.get_text(" ", strip=True) for x in celdas]
        if len(td) < 4:
            continue
        # La fecha vive en un <span class="sub_line"> dentro de la celda del
        # evento ('Jul / 25 / 2026'). Guardarla permite recortar el historial a
        # una fecha y hacer backtests sin mirar el futuro.
        fecha = ""
        sub = celdas[2].select_one("span.sub_line")
        if sub:
            fecha = sub.get_text(strip=True).replace(" ", "")
        peleas.append({
            "resultado": td[0].lower(),
            "evento": td[2],
            "fecha": fecha,
            "metodo": _metodo(td[3]),
            "es_ufc": "ufc" in td[2].lower(),
        })
    if not peleas:
        return None

    ganadas = [p for p in peleas if p["resultado"].startswith("win")]
    perdidas = [p for p in peleas if p["resultado"].startswith("loss")]

    # Sherdog lista de MÁS RECIENTE a más antigua
    racha = 0
    if peleas:
        primero = peleas[0]["resultado"]
        for p in peleas:
            if p["resultado"] == primero:
                racha += 1
            else:
                break
        racha = racha if primero.startswith("win") else -racha

    def tasa(sub, m):
        return round(sum(1 for p in sub if p["metodo"] == m) / len(sub), 4) if sub else 0.0

    datos = {
        "name": nombre,
        "url": url,
        "peleas": peleas,          # crudas, para poder recortar por fecha
        "wins": len(ganadas),
        "losses": len(perdidas),
        "streak": racha,
        "peleas_ufc": sum(1 for p in peleas if p["es_ufc"]),
        "peleas_no_ufc": sum(1 for p in peleas if not p["es_ufc"]),
        "win_ko_rate": tasa(ganadas, "KO/TKO"),
        "win_sub_rate": tasa(ganadas, "Submission"),
        "win_dec_rate": tasa(ganadas, "Decision"),
        "lost_by_finish_rate": round(1.0 - tasa(perdidas, "Decision"), 4) if perdidas else 0.0,
    }
    cache[k] = datos
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return datos


def resumen(peleas: list, hasta=None) -> dict:
    """Récord y tasas a partir de una lista de peleas, opcionalmente recortada
    a las anteriores a 'hasta' (para backtests sin leakage)."""
    import pandas as pd
    if hasta is not None:
        lim = pd.Timestamp(hasta)
        sel = []
        for p in peleas:
            f = pd.to_datetime(p.get("fecha", ""), format="%b/%d/%Y", errors="coerce")
            if pd.notna(f) and f < lim:
                sel.append(p)
        peleas = sel
    if not peleas:
        return {}
    g = [p for p in peleas if p["resultado"].startswith("win")]
    l = [p for p in peleas if p["resultado"].startswith("loss")]
    racha = 0
    primero = peleas[0]["resultado"]
    for p in peleas:
        if p["resultado"] == primero:
            racha += 1
        else:
            break
    racha = racha if primero.startswith("win") else -racha

    def tasa(sub, m):
        return round(sum(1 for p in sub if p["metodo"] == m) / len(sub), 4) if sub else 0.0

    return {"wins": len(g), "losses": len(l), "streak": racha,
            "peleas_no_ufc": sum(1 for p in peleas if not p["es_ufc"]),
            "win_ko_rate": tasa(g, "KO/TKO"), "win_sub_rate": tasa(g, "Submission"),
            "win_dec_rate": tasa(g, "Decision"),
            "lost_by_finish_rate": round(1.0 - tasa(l, "Decision"), 4) if l else 0.0}


def completar(stats: dict, min_ufc: int = 3, hasta=None) -> dict:
    """
    Si el peleador tiene POCAS peleas en UFC, completa su récord y sus tasas de
    finalización con la carrera entera (Sherdog). Los que ya tienen historial
    suficiente en UFC se dejan como están: ahí el dato de UFC es mejor.
    """
    if int(stats.get("n_peleas_hist", 99)) >= min_ufc:
        return stats
    h = historial(stats.get("name", ""))
    if not h:
        return stats
    r = resumen(h.get("peleas", []), hasta) if hasta is not None else h
    if not r:
        return stats
    out = dict(stats)
    for k in ("wins", "losses", "streak", "win_ko_rate", "win_sub_rate",
              "win_dec_rate", "lost_by_finish_rate"):
        if k in r:
            out[k] = r[k]
    out["sherdog_peleas_no_ufc"] = r.get("peleas_no_ufc", 0)
    return out


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Magomed Ankalaev"
    d = historial(q, usar_cache=False)
    if d:
        for k, v in d.items():
            print(f"  {k:22} {v}")
    else:
        print(f"no encontré '{q}' en Sherdog")
