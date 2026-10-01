"""
fotos.py
Foto de cada peleador para las tarjetas de la UI, con caché en disco.

Fuentes, en orden:
  1. Wikipedia / Wikimedia Commons: licencias libres y una API pensada para esto
     (`prop=pageimages`). Es la primera opción.
  2. Sherdog, de respaldo, para quien no tiene artículo en Wikipedia (la mayoría
     de los debutantes).
  3. Ninguna: la UI muestra una silueta de peleador. Nunca una imagen rota.

UFC.com no se usa: responde 403 a cualquier cliente que no sea un navegador, y
sus fotos tienen derechos de autor.

La regla que manda en todo el archivo: **mejor sin foto que con la de otro**.
Los cruces por nombre causaron los dos bugs más caros del proyecto (el récord de
Ankalaev asignado a Temirov; los dos "Mike Davis"), así que un nombre solo se
acepta si calza exacto y no hay un segundo candidato que también calce. Ante la
duda, silueta.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup

import config as C
from src import reemplazos, sherdog

CARPETA = C.DATA_RAW / "fotos"
WIKI_API = "https://en.wikipedia.org/w/api.php"
# El mismo User-Agent con el que el proyecto ya se identifica ante Wikipedia: su
# política exige uno propio con un modo de contacto.
HEADERS_WIKI = reemplazos.HEADERS

# Un "no hay foto" se vuelve a consultar pasado este plazo: a un debutante le
# pueden crear el artículo la semana de su pelea.
REINTENTO_SIN_FOTO_SEG = 14 * 24 * 3600
# Si la red falla no se anota "sin foto" (sería mentira), pero tampoco se insiste
# en cada repintado de la tarjeta: se espera un rato antes de volver a probar.
ESPERA_TRAS_FALLO_RED_SEG = 10 * 60

_NOMBRE_VALIDO = re.compile(r"^[^\W\d_][\w .'\-]{1,79}$", re.UNICODE)
_RE_MMA = re.compile(r"mixed martial art", re.I)

_lock = threading.Lock()
_fallo_red: dict[str, float] = {}


class SinRed(Exception):
    """La consulta no se pudo hacer. No significa que el peleador no tenga foto."""


# Wikipedia encontró a DOS peleadores con ese nombre. Es distinto de "ninguno":
# en ese caso tampoco se pregunta a Sherdog, que podría devolver a cualquiera.
AMBIGUO = "ambiguo"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).strip()


def _tokens(s: str) -> set[str]:
    return set(_norm(re.sub(r"\(.*?\)", "", s)).split())


def nombre_valido(nombre: str) -> bool:
    return bool(_NOMBRE_VALIDO.match(nombre or "")) and ".." not in nombre


# --------------------------------------------------------------------------- #
# Wikipedia
# --------------------------------------------------------------------------- #
def _wiki_get(params: dict) -> dict:
    try:
        r = requests.get(WIKI_API, headers=HEADERS_WIKI, params=params,
                         timeout=C.REQUEST_TIMEOUT_SEC)
    except requests.RequestException as e:
        raise SinRed(str(e)) from e
    if r.status_code != 200:
        raise SinRed(f"HTTP {r.status_code}")
    return r.json()


def url_wikipedia(nombre: str) -> str | None:
    """
    URL de la miniatura del artículo del peleador, None, o AMBIGUO.

    Se preguntan a la vez tres títulos: el nombre tal cual y las dos formas en que
    Wikipedia desambigua a un peleador ("X (fighter)", "X (mixed martial
    artist)"). Un candidato vale si su descripción dice que es artista marcial
    mixto y si todas las palabras del nombre pedido están en el título final.
    Si valen DOS artículos distintos, no se elige ninguno.
    """
    candidatos = [nombre, f"{nombre} (fighter)", f"{nombre} (mixed martial artist)"]
    d = _wiki_get({
        "action": "query", "format": "json", "formatversion": 2, "redirects": 1,
        "titles": "|".join(candidatos), "prop": "pageimages|description",
        "piprop": "thumbnail", "pithumbsize": 480,
    })
    q = d.get("query", {})
    pedido = _tokens(nombre)
    validas = {}
    for p in q.get("pages", []):
        if p.get("missing") or p.get("invalid"):
            continue
        if not _RE_MMA.search(p.get("description", "")):
            continue                       # homónimo de otro deporte u oficio
        if not pedido <= _tokens(p.get("title", "")):
            continue                       # una redirección hacia otro nombre
        validas[p["title"]] = (p.get("thumbnail") or {}).get("source")
    if len(validas) > 1:
        return AMBIGUO                     # dos peleadores con ese nombre
    if not validas:
        return None
    return next(iter(validas.values()))    # puede ser None: artículo sin foto


# --------------------------------------------------------------------------- #
# Sherdog
# --------------------------------------------------------------------------- #
def _sherdog_get(url: str, **kw) -> requests.Response:
    try:
        r = sherdog._sesion.get(url, timeout=C.REQUEST_TIMEOUT_SEC, **kw)
    except requests.RequestException as e:
        raise SinRed(str(e)) from e
    time.sleep(sherdog.DELAY)
    if r.status_code != 200:
        raise SinRed(f"HTTP {r.status_code}")
    return r


def url_sherdog(nombre: str) -> str | None:
    """
    Foto de la ficha de Sherdog, o None.

    No se reutiliza `sherdog.buscar` tal cual porque devuelve la PRIMERA ficha
    que calza: para el historial eso ya está acotado por otras vías, pero para una
    foto dos "Mike Davis" en el buscador tienen que dar silueta, no uno al azar.
    """
    r = _sherdog_get(f"{sherdog.BASE}/stats/fightfinder", params={"SearchTxt": nombre})
    s = BeautifulSoup(r.text, "html.parser")
    objetivo = _norm(nombre)
    fichas = set()
    for a in s.select('a[href*="/fighter/"]'):
        href = a.get("href", "")
        slug = _norm(re.sub(r"-\d+$", "", href.split("/fighter/")[-1]).replace("-", " "))
        if slug == objetivo:
            fichas.add(href)
    if len(fichas) != 1:
        return None
    ficha = _sherdog_get(sherdog.BASE + fichas.pop())
    meta = BeautifulSoup(ficha.text, "html.parser").select_one('meta[property="og:image"]')
    src = (meta.get("content") or "").strip() if meta else ""
    # Sherdog pone su logo como og:image cuando la ficha no tiene foto.
    if not src or re.search(r"logo|default|placeholder", src, re.I):
        return None
    return src


# --------------------------------------------------------------------------- #
# Caché
# --------------------------------------------------------------------------- #
def _indice() -> dict:
    f = CARPETA / "indice.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def _guardar_indice(idx: dict) -> None:
    CARPETA.mkdir(parents=True, exist_ok=True)
    (CARPETA / "indice.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1),
                                         encoding="utf-8")


def _bajar(url: str, clave: str, headers: dict) -> Path:
    try:
        r = requests.get(url, headers=headers, timeout=C.REQUEST_TIMEOUT_SEC)
    except requests.RequestException as e:
        raise SinRed(str(e)) from e
    tipo = r.headers.get("content-type", "")
    if r.status_code != 200 or not tipo.startswith("image/"):
        raise SinRed(f"HTTP {r.status_code} {tipo}")
    ext = {"image/png": ".png", "image/webp": ".webp"}.get(tipo.split(";")[0], ".jpg")
    CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CARPETA / f"{clave.replace(' ', '_')}{ext}"
    ruta.write_bytes(r.content)
    return ruta


def foto(nombre: str) -> Path | None:
    """Ruta local de la foto del peleador, bajándola la primera vez. None = silueta."""
    if not nombre_valido(nombre):
        return None
    clave = _norm(nombre)
    with _lock:
        ahora = time.time()
        idx = _indice()
        e = idx.get(clave)
        if e and e.get("archivo") and (CARPETA / e["archivo"]).exists():
            return CARPETA / e["archivo"]
        if e and not e.get("archivo") and ahora - e.get("consultado", 0) < REINTENTO_SIN_FOTO_SEG:
            return None
        if ahora - _fallo_red.get(clave, 0) < ESPERA_TRAS_FALLO_RED_SEG:
            return None
        try:
            ruta, fuente = None, None
            url = url_wikipedia(nombre)
            if url == AMBIGUO:
                url = None
            elif url:
                ruta, fuente = _bajar(url, clave, HEADERS_WIKI), "wikipedia"
            else:
                url = url_sherdog(nombre)
                if url:
                    ruta, fuente = _bajar(url, clave, sherdog.HEADERS), "sherdog"
        except SinRed:
            _fallo_red[clave] = ahora
            return None
        idx[clave] = {"nombre": nombre, "archivo": ruta.name if ruta else None,
                      "fuente": fuente, "url": url, "consultado": ahora}
        _guardar_indice(idx)
        return ruta
