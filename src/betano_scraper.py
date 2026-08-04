"""
betano_scraper.py
Scraper de cuotas de Betano (lat.betano.com) para carteleras de MMA/UFC.

Genera un CSV con el formato que usa cards/ (ver src/card.py):
    fighter_a,fighter_b,segment,odds_a,odds_b,
    odds_a_ko,odds_a_sub,odds_a_dec,odds_b_ko,odds_b_sub,odds_b_dec

Nada de esto necesita navegador: Betano renderiza el listado de carteleras y
de peleas en HTML plano con un JSON embebido (mismo patrón que UFCStats), y
cada pelea tiene además una API REST propia con TODOS sus mercados:
    /api/cuotas-de-partido/<slug-de-la-pelea>/<id>/

LIMITACIÓN REAL DE DATOS (no es un bug, es lo que Betano ofrece):
Betano NO siempre separa KO de Sumisión. Por pelea puede haber:
  * "Método de victoria (7-way)"  -> KO/TKO/DQ, Sumisión y Decisión SEPARADOS
    por peleador (7 = 3 métodos x 2 peleadores + empate). Esta es la única
    fuente real para llenar odds_a_ko/odds_a_sub por separado.
  * "Método de victoria (5-way)"  -> KO/TKO/DQ/Sumisión COMBINADOS en una sola
    cuota + Decisión, por peleador (5 = 2 x 2 + empate). Aquí NO existe un
    número real de "solo KO" ni "solo sumisión", así que esas dos columnas
    quedan vacías; solo se llena la de decisión.
  * Ningún mercado de método activado (a veces solo está "Ganador").

Regla (pedida explícitamente por el usuario): scrapear SOLO lo que el
mercado realmente tenga activado en cada pelea; lo que no exista queda
como celda vacía en el CSV, nunca inventado ni duplicado entre columnas.

Uso:
    python -m src.betano_scraper                        # lista las carteleras de MMA disponibles
    python -m src.betano_scraper "UFC Fight Night"       # scrapea esa cartelera -> cards/betano_<slug>.csv
    python -m src.betano_scraper "UFC 330" salida.csv    # nombre de archivo de salida explícito
"""
from __future__ import annotations

import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C

_SESSION = requests.Session()
_SESSION.headers.update({**C.HEADERS, "Accept-Language": "es-CL,es;q=0.9"})

COLUMNS = ["fighter_a", "fighter_b", "segment", "odds_a", "odds_b",
           "odds_a_ko", "odds_a_sub", "odds_a_dec",
           "odds_b_ko", "odds_b_sub", "odds_b_dec"]


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _get_json(url: str, params: dict | None = None) -> Optional[dict]:
    for attempt in range(1, C.MAX_RETRIES + 1):
        try:
            r = _SESSION.get(url, params=params, timeout=C.REQUEST_TIMEOUT_SEC)
            time.sleep(C.REQUEST_DELAY_SEC)
            if r.status_code == 200:
                return r.json()
            print(f"[!] {url} -> HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"[retry {attempt}/{C.MAX_RETRIES}] {url} -> {e}")
            time.sleep(C.REQUEST_DELAY_SEC * attempt)
    return None


def _get_text(url: str) -> Optional[str]:
    for attempt in range(1, C.MAX_RETRIES + 1):
        try:
            r = _SESSION.get(url, timeout=C.REQUEST_TIMEOUT_SEC)
            time.sleep(C.REQUEST_DELAY_SEC)
            if r.status_code == 200:
                return r.text
            print(f"[!] {url} -> HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"[retry {attempt}/{C.MAX_RETRIES}] {url} -> {e}")
            time.sleep(C.REQUEST_DELAY_SEC * attempt)
    return None


def _fold(s: str) -> str:
    """minúsculas sin acentos, para comparar nombres/keywords sin depender de tildes."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return s.lower().strip()


# --------------------------------------------------------------------------- #
# 1) Listado de carteleras de MMA (/sport/mma/)
# --------------------------------------------------------------------------- #
_LEAGUE_RE = re.compile(r'\{"id":"(\d+)","name":"([^"]+)","url":"(/sport/mma/[^"]+)"\}')


def list_cards() -> list[dict]:
    """
    Carteleras/eventos de MMA listados ahora mismo en Betano (UFC, Oktagon, etc.),
    sacados del JSON embebido en el HTML plano de /sport/mma/ (sin JS).
    Excluye las entradas de REGIÓN ("UFC", "Oktagon" -> /campeonatos/...), que
    agrupan carteleras pero no son una cartelera en sí.
    """
    html = _get_text(f"{C.BETANO_BASE}/sport/mma/")
    if html is None:
        return []
    out = []
    for m in _LEAGUE_RE.finditer(html):
        id_, name, url = m.group(1), m.group(2), m.group(3)
        if "/campeonatos/" in url:
            continue
        out.append({"id": id_, "name": name, "url": url})
    # dedup preservando orden (la misma cartelera puede aparecer más de una vez en el HTML)
    seen, dedup = set(), []
    for c in out:
        if c["id"] not in seen:
            seen.add(c["id"])
            dedup.append(c)
    return dedup


def find_card(query: str) -> Optional[dict]:
    """Match por substring, sin acentos ni mayúsculas, contra el nombre de la cartelera."""
    cards = list_cards()
    q = _fold(query)
    hits = [c for c in cards if q in _fold(c["name"])]
    if not hits:
        print(f"[!] no encontré ninguna cartelera de MMA que contenga '{query}'.")
        print("    Carteleras disponibles ahora mismo:")
        for c in cards:
            print(f"      - {c['name']}")
        return None
    if len(hits) > 1:
        print(f"[i] '{query}' matcheó varias carteleras, uso la primera:")
        for c in hits:
            print(f"      - {c['name']}")
    return hits[0]


# --------------------------------------------------------------------------- #
# 2) Peleas de una cartelera
# --------------------------------------------------------------------------- #
_FIGHT_RE = re.compile(
    r'"id":"(\d+)","name":"([^"]+)","startTime":(\d+),"url":"(/cuotas-de-partido/[^"]+)"'
)


def list_fights(card_url: str) -> list[dict]:
    """
    Peleas de la cartelera en el orden en que Betano las lista (cronológico,
    preliminares primero y el main event al final). Cada una trae ya el
    fighter_a/fighter_b (de 'Nombre A - Nombre B') y el slug para pedir sus
    cuotas completas.
    """
    url = card_url if card_url.startswith("http") else f"{C.BETANO_BASE}{card_url}"
    html = _get_text(url)
    if html is None:
        return []
    fights = []
    for m in _FIGHT_RE.finditer(html):
        id_, name, start_ms, path = m.groups()
        if " - " not in name:
            continue
        fa, fb = name.split(" - ", 1)
        fights.append({"id": id_, "fighter_a": fa.strip(), "fighter_b": fb.strip(),
                        "start_ms": int(start_ms), "path": path})
    # dedup por id preservando el orden de aparición
    seen, dedup = set(), []
    for f in fights:
        if f["id"] not in seen:
            seen.add(f["id"])
            dedup.append(f)
    return dedup


# --------------------------------------------------------------------------- #
# 3) Cuotas de una pelea puntual
# --------------------------------------------------------------------------- #
def _lado(nombre_sel: str, fa: str, fb: str) -> Optional[str]:
    low = _fold(nombre_sel)
    if low.startswith(_fold(fa)):
        return "a"
    if low.startswith(_fold(fb)):
        return "b"
    return None


def _metodo(nombre_sel: str) -> Optional[str]:
    low = _fold(nombre_sel)
    if "sumision" in low:
        return "sub"
    if "decision" in low:
        return "dec"
    if "ko" in low or "tko" in low or "descalificacion" in low:
        return "ko"
    return None


def get_fight_odds(fight: dict) -> dict:
    """
    Cuotas reales de una pelea. Llena SOLO lo que Betano tiene activado en
    ese momento: si no hay mercado de Ganador, odds_a/odds_b quedan vacíos;
    si no hay 7-way ni 5-way, las 6 columnas de método quedan vacías; si solo
    hay 5-way, ko/sub quedan vacíos y solo se llena decisión (ver docstring
    del módulo: Betano no separa KO de Sumisión en el 5-way, así que no hay
    número real que poner ahí).
    """
    fa, fb = fight["fighter_a"], fight["fighter_b"]
    row = {"fighter_a": fa, "fighter_b": fb, "segment": "",
           "odds_a": "", "odds_b": "",
           "odds_a_ko": "", "odds_a_sub": "", "odds_a_dec": "",
           "odds_b_ko": "", "odds_b_sub": "", "odds_b_dec": ""}

    data = _get_json(f"{C.BETANO_BASE}/api{fight['path']}", params={"bt": 2, "req": "s,stnf,c"})
    if data is None:
        print(f"[!] {fa} vs {fb}: no pude bajar sus cuotas (¿pelea cancelada/reprogramada?).")
        return row

    markets = data.get("data", {}).get("event", {}).get("markets", [])

    ganador = next((m for m in markets if m.get("type") == "H2HT" or m.get("name") == "Ganador"), None)
    if ganador and len(ganador.get("selections", [])) >= 2:
        sels = sorted(ganador["selections"], key=lambda s: s.get("columnIndex", 0))
        row["odds_a"], row["odds_b"] = sels[0]["price"], sels[1]["price"]

    metodo = next((m for m in markets if "7-way" in _fold(m.get("name", ""))), None)
    if metodo is None:
        metodo = next((m for m in markets if "5-way" in _fold(m.get("name", ""))), None)
    if metodo is None:
        print(f"[i] {fa} vs {fb}: sin mercado de método activado (¿solo Ganador por ahora?).")
        return row

    es_7way = "7-way" in _fold(metodo["name"])
    for sel in metodo.get("selections", []):
        lado = _lado(sel["name"], fa, fb)
        if lado is None:  # "Empate o Empate Técnico"
            continue
        met = _metodo(sel["name"])
        if met is None:
            continue
        if met in ("ko", "sub") and not es_7way:
            # 5-way: la cuota de "ko" acá es en realidad KO+TKO+DQ+Sumisión
            # combinados. No hay cuota real de sumisión sola -> no se llena
            # ninguna de las dos para no inventar un número.
            continue
        row[f"odds_{lado}_{met}"] = sel["price"]
    return row


# --------------------------------------------------------------------------- #
# 4) Cartelera completa -> CSV
# --------------------------------------------------------------------------- #
def _por_fecha(fights: list[dict]) -> dict:
    """Agrupa las peleas por día del evento, en orden cronológico."""
    import datetime as _dt
    out: dict = {}
    for f in fights:
        dia = _dt.datetime.fromtimestamp(f["start_ms"] / 1000).date()
        out.setdefault(dia, []).append(f)
    return dict(sorted(out.items()))


def scrape_card(query: str, out_path: Optional[str] = None,
                fecha: Optional[str] = None) -> Path:
    card = find_card(query)
    if card is None:
        raise SystemExit(1)
    print(f"[i] cartelera: {card['name']} ({C.BETANO_BASE}{card['url']})")

    fights = list_fights(card["url"])
    if not fights:
        raise SystemExit(f"[!] no encontré peleas en {card['name']}.")

    # OJO: Betano mete TODAS las "UFC Fight Night" bajo la MISMA liga (id 205870),
    # así que una sola página puede traer dos o tres eventos de fines de semana
    # distintos mezclados. Si no se separan, el CSV sale con peleas de carteleras
    # que ni siquiera son del mismo día. Se agrupa por fecha y se usa la más
    # próxima, salvo que pidan otra con --fecha.
    grupos = _por_fecha(fights)
    if len(grupos) > 1:
        print(f"[i] esta liga trae {len(grupos)} eventos distintos:")
        for d, fs in grupos.items():
            print(f"      {d}  ({len(fs)} peleas)  estelar: "
                  f"{fs[-1]['fighter_a']} vs {fs[-1]['fighter_b']}")
    if fecha:
        elegido = next((d for d in grupos if str(d) == fecha), None)
        if elegido is None:
            raise SystemExit(f"[!] no hay evento el {fecha}. Fechas: "
                             f"{', '.join(str(d) for d in grupos)}")
    else:
        elegido = next(iter(grupos))
    fights = grupos[elegido]
    if len(grupos) > 1:
        print(f"[i] uso el del {elegido} (el más próximo). Para otro: --fecha AAAA-MM-DD")

    print(f"[i] {len(fights)} peleas encontradas, pidiendo cuotas de cada una...")

    rows = [get_fight_odds(f) for f in fights]
    df = pd.DataFrame(rows, columns=COLUMNS)

    if out_path is None:
        # Se nombra por el ESTELAR (la última pelea del día), no por el nombre de
        # la liga: "UFC Fight Night" a secas pisaría el archivo de la semana
        # siguiente, que es otro evento distinto.
        est = fights[-1]
        slug = re.sub(r"[^a-z0-9]+", "_",
                      _fold(f"{est['fighter_a'].split()[-1]} vs "
                            f"{est['fighter_b'].split()[-1]}")).strip("_")
        out_path = C.ROOT / "cards" / f"betano_{elegido}_{slug}.csv"
    else:
        out_path = Path(out_path)
        if not out_path.is_absolute():
            out_path = C.ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    con_ganador = (df["odds_a"] != "").sum()
    con_metodo = ((df["odds_a_dec"] != "") | (df["odds_a_ko"] != "")).sum()
    print(f"[ok] {out_path}  ({con_ganador}/{len(df)} con cuota Ganador, "
          f"{con_metodo}/{len(df)} con algún dato de método)")
    print("     'segment' quedó vacío: Betano no expone estelar/co-estelar/prelim "
          "ni categoría de peso -> complétalo a mano si lo necesitas.")
    return out_path


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Carteleras de MMA disponibles ahora mismo en Betano:\n")
        for c in list_cards():
            print(f"  - {c['name']}")
        print("\nUso: python -m src.betano_scraper \"<nombre o parte del nombre>\" [salida.csv]")
        print("     --fecha AAAA-MM-DD  para elegir el evento cuando la liga trae varios")
    else:
        fecha = None
        for a in list(args):
            if a.startswith("--fecha="):
                fecha = a.split("=", 1)[1]
                args.remove(a)
        if "--fecha" in sys.argv:
            i = sys.argv.index("--fecha")
            if i + 1 < len(sys.argv):
                fecha = sys.argv[i + 1]
                if fecha in args:
                    args.remove(fecha)
        query = args[0]
        salida = args[1] if len(args) > 1 else None
        scrape_card(query, salida, fecha=fecha)
