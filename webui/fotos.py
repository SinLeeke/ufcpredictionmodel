"""
fotos.py
Foto de cada peleador para las tarjetas de la UI, con caché en disco.

Fuentes, en orden:
  1. ESPN: retratos PNG de sus fichas de MMA, resueltos con su buscador público.
     La URL viene en la respuesta, junto al nombre, deporte e ID del peleador.
  2. Wikipedia / Wikimedia Commons: API `prop=pageimages` como respaldo.
  3. Sherdog, de respaldo, para quien no tiene artículo en Wikipedia (la mayoría
     de los debutantes).
  4. Ninguna: la UI muestra una silueta de peleador. Nunca una imagen rota.

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
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

import config as C
from src import reemplazos, sherdog

CARPETA = C.DATA_RAW / "fotos"
WIKI_API = "https://en.wikipedia.org/w/api.php"
# Endpoint que utiliza el buscador de ESPN (módulo público espnfitt 3666).
# El filtro de deporte no siempre se aplica en el servidor: se verifica abajo.
ESPN_SEARCH = "https://site.web.api.espn.com/apis/search/v2"
ESPN_LIMITE = 100
HEADERS_ESPN = {**C.HEADERS, "Accept": "application/json", "Accept-Language": "es-CL,es;q=0.9"}
# Cambios de nombre verificados en las fichas/buscador de ESPN. No se hace match
# por apellido ni por parecido: un alias solo sirve para este nombre completo.
ALIASES_ESPN = {"bobby green": ("King Green", "2502364"),
               "ian garry": ("Ian Machado Garry", "4738092")}
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


# Una fuente encontró a DOS peleadores con ese nombre. Es distinto de "ninguno":
# en ese caso no se pregunta a otras fuentes, que podrían devolver a cualquiera.
AMBIGUO = "ambiguo"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " ")).split())


def _tokens(s: str) -> set[str]:
    return set(_norm(re.sub(r"\(.*?\)", "", s)).split())


def nombre_valido(nombre: str) -> bool:
    return bool(_NOMBRE_VALIDO.match(nombre or "")) and ".." not in nombre


# --------------------------------------------------------------------------- #
# ESPN
# --------------------------------------------------------------------------- #
def url_espn(nombre: str) -> str | None:
    """PNG del único peleador de MMA con ese nombre, None, o AMBIGUO.

    Se comprueban deporte, nombre completo, ID de ficha y URL de retrato. Los
    resultados de noticias y los homónimos de otros deportes no sirven. Nunca
    se construye una URL de imagen suponiendo que un ID tiene foto.
    """
    consulta, id_alias = ALIASES_ESPN.get(_norm(nombre), (nombre, None))
    try:
        r = requests.get(ESPN_SEARCH, headers=HEADERS_ESPN,
                         params={"query": consulta, "type": "player", "limit": ESPN_LIMITE},
                         timeout=min(8, C.REQUEST_TIMEOUT_SEC))
        if r.status_code != 200:
            raise SinRed(f"ESPN HTTP {r.status_code}")
        datos = r.json()
    except (requests.RequestException, ValueError) as e:
        raise SinRed(str(e)) from e
    if not isinstance(datos, dict) or not isinstance(datos.get("results"), list):
        raise SinRed("ESPN no devolvió resultados de búsqueda válidos")

    # Una respuesta truncada no permite descartar un segundo homónimo. Es una
    # sola petición por nombre, sin paginar ni insistir en cada repintado.
    for grupo in datos.get("resultTypes", []):
        if grupo.get("type") == "player" and grupo.get("totalFound", 0) > ESPN_LIMITE:
            return AMBIGUO

    objetivo = _norm(consulta)
    validos = {}
    for grupo in datos["results"]:
        if grupo.get("type") != "player":
            continue
        for jugador in grupo.get("contents", []):
            if jugador.get("type") != "player" or jugador.get("sport") != "mma":
                continue
            if _norm(jugador.get("displayName", "")) != objetivo:
                continue
            uid = re.fullmatch(r"s:3301~a:(\d+)", jugador.get("uid", ""))
            ficha = urlsplit((jugador.get("link") or {}).get("web", ""))
            id_ficha = re.match(r"^/mma/(?:fighter|peleador)/_/id/(\d+)(?:/|$)", ficha.path)
            if (not uid or ficha.scheme != "https"
                    or ficha.hostname not in ("www.espn.com", "www.espn.cl")
                    or not id_ficha or id_ficha.group(1) != uid.group(1)):
                continue
            id_ = uid.group(1)
            if id_alias and id_ != id_alias:
                continue                 # el alias también está ligado a su ID
            imagen = (jugador.get("image") or {}).get("default", "")
            p = urlsplit(imagen)
            es_retrato = (p.scheme == "https" and p.hostname == "a.espncdn.com"
                          and p.path == f"/i/headshots/mma/players/full/{id_}.png"
                          and not p.query and not p.fragment)
            validos[id_] = imagen if es_retrato else None
    if len(validos) > 1:
        return AMBIGUO
    return next(iter(validos.values()), None)


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
        anterior = (CARPETA / e["archivo"]) if e and e.get("archivo") else None
        if anterior and not anterior.exists():
            anterior = None
        # Las entradas anteriores a ESPN se revisan una vez para sustituir la
        # foto por el retrato. Mientras falla la red se conserva la foto local.
        if anterior and e.get("espn_revisado"):
            return anterior
        if (e and e.get("espn_revisado") and not e.get("archivo")
                and ahora - e.get("consultado", 0) < REINTENTO_SIN_FOTO_SEG):
            return None
        if ahora - _fallo_red.get(clave, 0) < ESPERA_TRAS_FALLO_RED_SEG:
            return anterior

        ruta, fuente, url = None, None, None
        fallo, espn_revisado, ambiguo = False, False, False
        try:
            url = url_espn(nombre)
            ambiguo = url == AMBIGUO
            if url and not ambiguo:
                ruta, fuente = _bajar(url, clave, HEADERS_ESPN), "espn"
            espn_revisado = True
        except SinRed:
            fallo = True

        if not ruta and not ambiguo and anterior:
            ruta, fuente, url = anterior, e.get("fuente"), e.get("url")
        if not ruta and not ambiguo:
            for resolver, origen, headers in ((url_wikipedia, "wikipedia", HEADERS_WIKI),
                                               (url_sherdog, "sherdog", sherdog.HEADERS)):
                try:
                    url = resolver(nombre)
                    if url == AMBIGUO:
                        ambiguo = True
                        break
                    if url:
                        ruta, fuente = _bajar(url, clave, headers), origen
                        break
                except SinRed:
                    fallo = True
        if fallo:
            _fallo_red[clave] = ahora
        if not ruta and fallo and not ambiguo:
            return None
        if ambiguo:
            url = None
        idx[clave] = {"nombre": nombre, "archivo": ruta.name if ruta else None,
                      "fuente": fuente, "url": url, "consultado": ahora,
                      "espn_revisado": espn_revisado}
        _guardar_indice(idx)
        return ruta
