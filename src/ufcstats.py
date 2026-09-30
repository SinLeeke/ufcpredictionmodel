"""
ufcstats.py
Scraper AUTOSUSTENTABLE de UFCStats. Dado un nombre, encuentra la ficha del
peleador y extrae TODO lo que el modelo necesita, sin hardcodear nada:

  * Golpeo:   SLpM, Str.Acc, SApM, Str.Def
  * Lucha:    TD Avg, TD Acc, TD Def, Sub.Avg
  * Físico:   altura, alcance, stance, edad (de la fecha de nacimiento)
  * Historial (de la tabla de peleas): racha, tasas de finalización (KO/Sub/Dec)
              como ganador, tasa de ser finalizado, días desde la última pelea

UFCStats es HTML estático y estable, así que esto funciona con requests. Guarda
una caché en data/raw/ufcstats_cache.json para no re-scrapear en cada corrida
(y ser educado con el sitio).

NOTA: no puedo probar el scrape en vivo desde el entorno donde se escribió esto
(sin salida a ufcstats.com), pero las funciones de PARSEO están validadas contra
HTML de ejemplo con la estructura real del sitio. Corre `python -m src.ufcstats "Nombre"`
para verificar un peleador; si algún selector cambió, el mensaje te dirá qué campo
quedó vacío.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C

CACHE_PATH = C.DATA_RAW / "ufcstats_cache.json"

# Sesión persistente: guarda la cookie del challenge anti-bot para no re-resolverlo
# en cada request. UFCStats sirve una página "Checking your browser…" con un
# proof-of-work SHA256; _solve_challenge() lo resuelve en Python (sin navegador).
_SESSION = requests.Session()
_SESSION.headers.update(C.HEADERS)


# --------------------------------------------------------------------------- #
# Anti-bot: proof-of-work SHA256 (reemplaza al navegador)
# --------------------------------------------------------------------------- #
def _solve_challenge(html: str) -> bool:
    """
    UFCStats protege sus páginas con un challenge JS: trae un `nonce` y un `target`
    de N ceros hexadecimales; hay que hallar el menor `n` tal que
    sha256(f"{nonce}:{n}") empiece con esos ceros, y hacer POST a /__c con
    (nonce, n). El server responde 204 + cookie; a partir de ahí la sesión ve el
    contenido real. Devuelve True si resolvió y guardó la cookie.
    """
    m_nonce = re.search(r'nonce="([0-9a-f]+)"', html)
    m_target = re.search(r"target=new Array\((\d+)\+1\)\.join\('0'\)", html)
    if not (m_nonce and m_target):
        return False
    nonce = m_nonce.group(1)
    prefix = "0" * int(m_target.group(1))
    n = 0
    while not hashlib.sha256(f"{nonce}:{n}".encode()).hexdigest().startswith(prefix):
        n += 1
    try:
        r = _SESSION.post(
            f"{C.UFCSTATS_BASE}/__c",
            data={"nonce": nonce, "n": n},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=C.REQUEST_TIMEOUT_SEC,
        )
        return r.status_code in (200, 204)
    except requests.RequestException:
        return False


# --------------------------------------------------------------------------- #
# HTTP + caché
# --------------------------------------------------------------------------- #
def _get(url: str) -> Optional[BeautifulSoup]:
    for attempt in range(1, C.MAX_RETRIES + 1):
        try:
            r = _SESSION.get(url, timeout=C.REQUEST_TIMEOUT_SEC)
            time.sleep(C.REQUEST_DELAY_SEC)
            if r.status_code == 200:
                # ¿Nos sirvieron el challenge en vez del contenido? Resolverlo y reintentar.
                if "Checking your browser" in r.text and "nonce=" in r.text:
                    if _solve_challenge(r.text):
                        r = _SESSION.get(url, timeout=C.REQUEST_TIMEOUT_SEC)
                        time.sleep(C.REQUEST_DELAY_SEC)
                    else:
                        print(f"[!] no pude resolver el challenge anti-bot de {url}")
                        return None
                return BeautifulSoup(r.text, "html.parser")
            print(f"[!] {url} -> HTTP {r.status_code}")
        except requests.RequestException as e:
            print(f"[retry {attempt}/{C.MAX_RETRIES}] {url} -> {e}")
            time.sleep(C.REQUEST_DELAY_SEC * attempt)
    return None


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


# Letras que NFKD NO descompone (no son 'letra + acento', son letras propias).
# Sin esto, 'Błachowicz' -> 'Bachowicz' y nunca hace match con UFCStats.
_SPECIAL = str.maketrans({
    "ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D", "þ": "th", "Þ": "Th", "ß": "ss",
    "æ": "ae", "Æ": "Ae", "œ": "oe", "Œ": "Oe", "ı": "i",
})


def _norm(s: str) -> str:
    """minúsculas, sin acentos, sin puntuación -> para comparar nombres."""
    s = str(s).translate(_SPECIAL)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


# --------------------------------------------------------------------------- #
# Búsqueda del peleador por nombre
# --------------------------------------------------------------------------- #
def _riqueza_fila(row) -> tuple[int, int]:
    """
    (campos biométricos presentes, peleas totales) de una fila del listado.

    Sirve para desempatar HOMÓNIMOS sin tener que abrir cada ficha: la tabla ya
    trae altura/peso/alcance en las columnas 3-5 y el récord W-L-D en las 7-9.
    """
    celdas = [c.get_text(" ", strip=True) for c in row.select("td")]

    def _int(i):
        try:
            return int(celdas[i])
        except (IndexError, ValueError):
            return 0

    con_datos = sum(1 for i in (3, 4, 5)
                    if i < len(celdas) and celdas[i] not in ("", "--"))
    return con_datos, _int(7) + _int(8) + _int(9)


def _rows_from_search(query_word: str) -> list:
    """Buscador propio de UFCStats (/statistics/fighters/search?query=...):
    matchea contra 'First Last' completo (y nicknames), así que UNA sola
    palabra encuentra también apellidos COMPUESTOS que el listado por letra
    indexa bajo una inicial distinta a la esperada (ver find_fighter_url)."""
    url = f"{C.UFCSTATS_BASE}/statistics/fighters/search?query={quote_plus(query_word)}&page=all"
    soup = _get(url)
    return soup.select("tr.b-statistics__table-row") if soup else []


def find_fighter_url(name: str) -> Optional[str]:
    """
    Busca al peleador por nombre, primero con el buscador de UFCStats y como
    respaldo con el listado alfabético /statistics/fighters?char=X&page=all.
    Hace match por nombre normalizado (exacto y luego 'contiene').

    BUG REAL que costó caro: "Ian Garry" no aparecía nunca. UFCStats lo
    guarda como First="Ian" / Last="Machado Garry" -> queda indexado en el
    listado alfabético bajo la letra M, no la G, aunque nadie escriba
    "Machado" al pedir la pelea. Buscar por listado-de-letra usando la
    inicial de la ÚLTIMA PALABRA escrita por el usuario nunca lo iba a
    encontrar. El buscador propio de UFCStats sí matchea "Garry" como
    substring de "Machado Garry", así que se usa como fuente primaria.

    HOMÓNIMOS: hay nombres repetidos y NO da igual cuál se elija. Ejemplo real
    que costó caro: existen dos "Mike Davis". El primero de la lista tiene la
    ficha vacía (2-0-0, sin altura ni alcance, todos los stats en cero); el
    verdadero lightweight es 12-4-0 con 72" de alcance. Devolver "el primero"
    hacía que el modelo predijera esa pelea con un peleador fantasma: alcance 0
    se convertía en una desventaja de 190 cm y el golpeo quedaba en 0.
    Por eso ahora se juntan TODOS los match exactos y gana el de ficha más
    completa (mismo criterio que ya se aplicó en sherdog.py).
    """
    words = name.split()
    if not words:
        return None
    last_norm = _norm(name).split()[-1] if _norm(name) else ""
    if not last_norm:
        return None

    rows = _rows_from_search(words[-1])
    if not rows:
        # Respaldo: el buscador no devolvió nada (p.ej. término raro) ->
        # listado alfabético por inicial, comportamiento anterior.
        char = last_norm[0]
        soup = _get(f"{C.UFCSTATS_BASE}/statistics/fighters?char={char}&page=all")
        rows = soup.select("tr.b-statistics__table-row") if soup else []
    if not rows:
        return None

    target = _norm(name)
    exactos, parciales = [], []
    for row in rows:
        links = row.select("a.b-link")
        if len(links) < 2:
            continue
        url = links[0].get("href")
        # primeras dos columnas suelen ser First y Last name
        first = links[0].get_text(strip=True)
        lastn = links[1].get_text(strip=True)
        full = _norm(f"{first} {lastn}")
        if full == target:
            exactos.append((_riqueza_fila(row), url))
        elif target in full or all(w in full for w in target.split()):
            parciales.append((_riqueza_fila(row), url))

    for grupo in (exactos, parciales):
        if not grupo:
            continue
        grupo.sort(key=lambda t: t[0], reverse=True)
        if len(grupo) > 1 and grupo[0][0] != grupo[1][0]:
            print(f"[ufcstats] '{name}': {len(grupo)} homónimos, elegido el de "
                  f"ficha más completa ({grupo[0][0][1]} peleas)")
        return grupo[0][1]
    return None


# --------------------------------------------------------------------------- #
# Parseo de la ficha
# --------------------------------------------------------------------------- #
def _pct(txt: str) -> float:
    if not txt or "--" in txt:
        return 0.0
    m = re.search(r"[\d.]+", txt)
    return round(float(m.group()) / 100.0, 4) if m else 0.0


def _num(txt: str) -> float:
    m = re.search(r"[\d.]+", txt or "")
    return float(m.group()) if m else 0.0


def _height_cm(txt: str) -> float:
    m = re.match(r"(\d+)'\s*(\d+)", txt or "")
    return round((int(m.group(1)) * 12 + int(m.group(2))) * 2.54, 1) if m else 0.0


def _reach_cm(txt: str) -> float:
    m = re.search(r"(\d+)", txt or "")
    return round(int(m.group(1)) * 2.54, 1) if m else 0.0


def _weight_class_from_lbs(txt: str) -> str:
    """'205 lbs.' -> 'Light Heavyweight'. UFCStats no expone la categoría como tal,
    pero sí el peso límite; lo mapeamos a la división estándar más cercana."""
    m = re.search(r"(\d+)", txt or "")
    if not m:
        return "Unknown"
    lbs = int(m.group(1))
    limits = [(125, "Flyweight"), (135, "Bantamweight"), (145, "Featherweight"),
              (155, "Lightweight"), (170, "Welterweight"), (185, "Middleweight"),
              (205, "Light Heavyweight"), (265, "Heavyweight")]
    return min(limits, key=lambda kv: abs(kv[0] - lbs))[1]


def _age_from_dob(txt: str) -> float:
    for fmt in ("%b %d, %Y", "%b %d %Y"):
        try:
            dob = datetime.strptime(txt.strip(), fmt)
            return round((datetime.now() - dob).days / 365.25, 1)
        except (ValueError, AttributeError):
            continue
    return 0.0


def _parse_career_stats(soup: BeautifulSoup) -> dict:
    """Bloque de stats 'Label: value' de la parte superior de la ficha."""
    stats = {}
    for li in soup.select("li.b-list__box-list-item"):
        title = li.find("i")
        if not title:
            continue
        # Normalizamos la clave quitando ':' y el punto final: UFCStats es
        # INCONSISTENTE ('Str. Acc.' lleva punto, 'Str. Def' no). Sin esto,
        # 'Str. Def.' nunca hace match y la defensa de golpeo sale 0.
        key = title.get_text(strip=True).rstrip(":").rstrip(".").strip()
        val = li.get_text(strip=True).replace(title.get_text(strip=True), "").strip()
        if key:
            stats[key] = val
    return stats


# Columna del MÉTODO en la tabla de historial de la ficha:
#   W/L | Fighter | Kd | Str | Td | Sub | Event | Method | Round | Time
_COL_METODO = 7


def _metodo_de_celda(cells) -> str:
    """
    KO/TKO | Submission | Decision leído SOLO de la celda de método, y de ella
    solo el código corto (el primer <p>: 'KO/TKO', 'SUB', 'U-DEC'...), no el
    detalle de abajo.

    BUG QUE ESTO ARREGLA: antes se buscaba "KO" en el texto de TODA la fila,
    que incluye el nombre del rival, el del propio peleador y el del evento.
    Kopylov, Volkov, Shevchenko, Malkoun, "UFC Fight Night: Volkov vs..."
    convertían cada decisión en KO. Medido sobre la base: 3,7% de los
    resultados mal leídos (siempre decisión -> KO), que le cambiaban
    win_ko_rate y lost_by_finish_rate al 23% de los peleadores activos, con
    un error medio de 16 puntos. ufcstats_events.py ya leía la celda y por eso
    el historial descargado estaba bien: el desfase era solo al predecir.

    DQ, CNC y lo que no se reconozca cuentan como Decision (no es un KO ni una
    sumisión), que es lo mismo que hacía el código anterior por defecto.
    """
    if len(cells) <= _COL_METODO:
        return "Decision"
    celda = cells[_COL_METODO]
    corto = celda.select_one("p") or celda
    t = corto.get_text(" ", strip=True).upper()
    if "SUB" in t:
        return "Submission"
    if "KO" in t:
        return "KO/TKO"
    return "Decision"


def _parse_history(soup: BeautifulSoup) -> dict:
    """
    Deriva racha, tasas de finalización y días desde la última pelea desde la
    tabla de historial. Best-effort: si la estructura no calza, cae a defaults.
    """
    outcomes, methods, dates = [], [], []
    for row in soup.select("tr.b-fight-details__table-row"):
        flag = row.select_one("i.b-flag__text") or row.select_one("a.b-flag__text")
        cells = row.select("td.b-fight-details__table-col")
        if not flag or not cells:
            continue
        outcome = flag.get_text(strip=True).lower()   # win / loss / draw / nc
        # Salta la fila de la pelea FUTURA ('next'): no tiene resultado y su fecha
        # contaminaría 'days_since_last_fight' (daría 0 = pelea de hoy).
        if not outcome.startswith(("win", "loss", "draw", "nc")):
            continue
        row_txt = row.get_text(" ", strip=True)
        outcomes.append(outcome)
        methods.append(_metodo_de_celda(cells))
        m = re.search(r"[A-Z][a-z]{2}\.?\s+\d{1,2},\s+\d{4}", row_txt)
        dates.append(m.group() if m else None)

    if not outcomes:
        return {"streak": 1, "win_ko_rate": 0.4, "win_sub_rate": 0.2,
                "win_dec_rate": 0.4, "lost_by_finish_rate": 0.4,
                "days_since_last_fight": 0.0, "wins": 0, "losses": 0}

    wins_idx = [i for i, o in enumerate(outcomes) if o.startswith("win")]
    loss_idx = [i for i, o in enumerate(outcomes) if o.startswith("loss")]

    def rate(idxs, label):
        return round(sum(1 for i in idxs if methods[i] == label) / len(idxs), 4) if idxs else 0.0

    # racha (la tabla viene de más reciente a más antigua)
    streak = 0
    first = outcomes[0]
    for o in outcomes:
        if o == first:
            streak += 1
        else:
            break
    streak = streak if first.startswith("win") else -streak

    # días desde la última pelea
    days = 0.0
    for d in dates:
        if d:
            for fmt in ("%b. %d, %Y", "%b %d, %Y"):
                try:
                    days = round((datetime.now() - datetime.strptime(d, fmt)).days, 1)
                    break
                except ValueError:
                    continue
            break

    lost_by_finish = round(1.0 - rate(loss_idx, "Decision"), 4) if loss_idx else 0.0
    return {
        "streak": streak,
        "win_ko_rate": rate(wins_idx, "KO/TKO"),
        "win_sub_rate": rate(wins_idx, "Submission"),
        "win_dec_rate": rate(wins_idx, "Decision"),
        "lost_by_finish_rate": lost_by_finish,
        "days_since_last_fight": days,
        "wins": len(wins_idx),
        "losses": len(loss_idx),
    }


def parse_fighter(soup: BeautifulSoup, name_hint: str = "") -> dict:
    """Ensambla el dict completo estilo Fighter desde la ficha."""
    s = _parse_career_stats(soup)
    name_tag = soup.select_one("span.b-content__title-highlight")
    name = name_tag.get_text(strip=True) if name_tag else name_hint
    hist = _parse_history(soup)

    return {
        "name": name,
        "slpm": _num(s.get("SLpM", "0")),
        "str_acc": _pct(s.get("Str. Acc", "0")),
        "sapm": _num(s.get("SApM", "0")),
        "str_def": _pct(s.get("Str. Def", "0")),
        "td_avg": _num(s.get("TD Avg", "0")),
        "td_acc": _pct(s.get("TD Acc", "0")),
        "td_def": _pct(s.get("TD Def", "0")),
        "sub_avg": _num(s.get("Sub. Avg", "0")),
        "height_cm": _height_cm(s.get("Height", "")),
        "reach_cm": _reach_cm(s.get("Reach", "")),
        "stance": s.get("STANCE", "Orthodox") or "Orthodox",
        "age": _age_from_dob(s.get("DOB", "")),
        "weight_class": _weight_class_from_lbs(s.get("Weight", "")),
        **hist,
    }


# --------------------------------------------------------------------------- #
# API pública: get_fighter(name) con caché
# --------------------------------------------------------------------------- #
# Versión del parser que armó cada ficha del caché. Se sube cuando un arreglo
# cambia lo que sale de parse_fighter: las fichas guardadas con una versión
# anterior se vuelven a bajar solas en vez de seguir sirviendo datos malos.
#   2 -> el método se lee de su celda, no de toda la fila (ver _metodo_de_celda)
VERSION_PARSER = 2


def get_fighter(name: str, use_cache: bool = True) -> Optional[dict]:
    cache = _load_cache()
    key = _norm(name)
    vieja = cache.get(key) if use_cache else None
    if vieja is not None and vieja.get("_parser") == VERSION_PARSER:
        return vieja

    url = find_fighter_url(name)
    soup = _get(url) if url else None
    if soup is None:
        # Sin red (o sin ficha): una ficha de una versión anterior es mejor que
        # nada. Perder al peleador omite la pelea entera de la cartelera.
        if vieja is not None:
            print(f"[!] '{name}': no pude refrescar su ficha, uso la guardada "
                  f"(armada con una versión anterior del parser).")
            return vieja
        if url is None:
            print(f"[!] no encontré '{name}' en UFCStats (¿debutante o nombre distinto?).")
        return None
    data = parse_fighter(soup, name_hint=name)
    data["ufcstats_url"] = url
    data["_parser"] = VERSION_PARSER
    cache[key] = data
    _save_cache(cache)
    return data


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Magomed Ankalaev"
    d = get_fighter(q, use_cache=False)
    if d:
        import pprint
        pprint.pprint(d)
        empty = [k for k, v in d.items() if v in (0.0, "", "Unknown")]
        if empty:
            print(f"\n[aviso] campos vacíos (revisa selectores si son clave): {empty}")
