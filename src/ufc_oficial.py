"""
ufc_oficial.py
Lo que publica UFC, para la portada de la UI: noticias y carteleras confirmadas.

Fuente: ufc.com, que desde Chile redirige a ufcespanol.com, en castellano. Se
consulta con el User-Agent propio del proyecto, igual que fotos.py y
title_bouts.py: UFC rechaza con 403 el Chrome viejo de los scrapers, no a una
aplicación que se identifica.

Educado y sin red obligatoria (la UI tiene que abrir sin internet):
  * noticias -> el RSS (30 titulares con fecha) y la imagen de las primeras
                notas (el og:image de su página). Caché de 30 min.
  * eventos  -> el listado /events (próximos y recientes, con la hora exacta de
                cada parte de la cartelera) y la página de los próximos, que
                trae sus peleas. Caché de 1 h.
Si la red falla se sirve lo último guardado, marcado como desactualizado, y no
se vuelve a insistir hasta pasados 10 minutos.

Las imágenes se bajan una vez a disco y la UI las pide al servidor por un id
que solo existe si vino en estos datos: nunca se baja una URL que mande el
navegador.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

import config as C
from src import storage as DB
from src.fighter_names import canonical_key

BASE = "https://www.ufc.com"
HEADERS = {**C.HEADERS, "User-Agent": "UFCFightPredictor/1.0"}
HOSTS = ("www.ufc.com", "ufc.com", "www.ufcespanol.com", "ufcespanol.com")
CACHE = C.DATA_RAW / "ufc_oficial.json"
IMAGENES = C.DATA_RAW / "ufc_imagenes"
TTL_NOTICIAS = 30 * 60
TTL_EVENTOS = 60 * 60
ESPERA_FALLO = 10 * 60
NOTAS_CON_IMAGEN = 3          # portada y las dos destacadas: 3 peticiones, no 30
EVENTOS_CON_PELEAS = 8        # todas las anunciadas: 8 páginas por hora, a 1 s entre una y otra
PAUSA = 1.0                   # entre peticiones a UFC
VERSION = 1

_lock = threading.Lock()
_fallos: dict[str, float] = {}


# --------------------------------------------------------------------------- #
# Red y caché
# --------------------------------------------------------------------------- #
def _de_ufc(url: str) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme == "https" and p.hostname in HOSTS


def _get(url: str) -> requests.Response | None:
    """GET a UFC, o None. Una redirección fuera de UFC no se sigue como dato."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=C.REQUEST_TIMEOUT_SEC)
    except requests.RequestException:
        return None
    if r.status_code != 200 or not _de_ufc(r.url or url):
        return None
    r.encoding = "utf-8"
    return r


def _leer() -> dict:
    try:
        datos = DB.read_json(CACHE)
        if isinstance(datos, dict) and datos.get("version") == VERSION:
            return datos
    except (OSError, ValueError):
        pass
    return {"version": VERSION}


def _guardar(datos: dict) -> None:
    if DB.key(CACHE) is not None:
        DB.write_text(CACHE, json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return
    temporal = CACHE.with_name(f".{CACHE.name}.{uuid.uuid4().hex}.tmp")
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        DB.write_text(temporal, json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        temporal.replace(CACHE)
    except OSError:
        pass                  # sin disco igual se muestra lo que se bajó
    finally:
        if DB.exists(temporal):
            try:
                DB.unlink(temporal)
            except OSError:
                pass


def _id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _vigente(entrada: dict | None, ttl: int, ahora: float) -> bool:
    return isinstance(entrada, dict) and 0 <= ahora - entrada.get("consultado", -1e18) < ttl


def guardado() -> tuple[dict | None, dict | None, bool]:
    """
    (noticias, eventos, vencido) desde el disco, SIN red. La portada responde
    al tiro con esto y se refresca aparte: esperar 15 s a UFC para abrir la
    página sería peor que mostrar lo de hace una hora.
    """
    datos, ahora = _leer(), time.time()
    n, e = datos.get("noticias"), datos.get("eventos")
    vencido = not _vigente(n, TTL_NOTICIAS, ahora) or not _vigente(e, TTL_EVENTOS, ahora)
    return n, e, vencido


# --------------------------------------------------------------------------- #
# Noticias
# --------------------------------------------------------------------------- #
_NS = {"dc": "http://purl.org/dc/elements/1.1/"}


def parsear_rss(xml: bytes | str) -> list[dict]:
    """Titulares del RSS de noticias. La fecha es dc:date (ISO, UTC): el pubDate
    viene traducido ("Vie, 2 Oct") y con otra hora."""
    try:
        raiz = ET.fromstring(xml)
    except ET.ParseError:
        return []
    notas = []
    for item in raiz.findall("./channel/item"):
        titulo = " ".join((item.findtext("title") or "").split())
        url = (item.findtext("link") or "").strip()
        fecha = (item.findtext("dc:date", namespaces=_NS) or "").strip()
        if not titulo or not _de_ufc(url) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:]+Z", fecha):
            continue
        autor = " ".join((item.findtext("dc:creator", namespaces=_NS) or "").split())
        autor = re.sub(r"^(by|por)\s+", "", autor, flags=re.I).split(" / ")[0]
        notas.append({"id": _id(url), "titulo": titulo, "url": url, "fecha": fecha, "autor": autor})
    return notas


def _og_image(html: str, url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    meta = soup.select_one('meta[property="og:image"], meta[name="twitter:image"]')
    if not meta or not meta.get("content"):
        return None
    imagen = urljoin(url, meta["content"].strip())
    return imagen if _de_ufc(imagen) else None


def noticias(forzar: bool = False) -> dict:
    """{"notas": [...], "consultado": ts, "desactualizado": bool}."""
    with _lock:
        datos = _leer()
        entrada = datos.get("noticias")
        ahora = time.time()
        if not forzar and _vigente(entrada, TTL_NOTICIAS, ahora):
            return {**entrada, "desactualizado": False}
        if ahora - _fallos.get("noticias", -1e18) < ESPERA_FALLO:
            return {**(entrada or {"notas": []}), "desactualizado": True}
        r = _get(f"{BASE}/rss/news")
        notas = parsear_rss(r.content) if r is not None else []
        if not notas:
            _fallos["noticias"] = ahora
            return {**(entrada or {"notas": []}), "desactualizado": True}
        # Las imágenes ya conocidas no se vuelven a pedir.
        previas = {n["id"]: n.get("imagen") for n in (entrada or {}).get("notas", [])}
        for i, nota in enumerate(notas):
            if nota["id"] in previas and previas[nota["id"]]:
                nota["imagen"] = previas[nota["id"]]
            elif i < NOTAS_CON_IMAGEN:
                time.sleep(PAUSA)
                pagina = _get(nota["url"])
                nota["imagen"] = _og_image(pagina.text, nota["url"]) if pagina is not None else None
        entrada = {"notas": notas, "consultado": ahora}
        datos["noticias"] = entrada
        _guardar(datos)
        _fallos.pop("noticias", None)
        return {**entrada, "desactualizado": False}


# --------------------------------------------------------------------------- #
# Eventos y carteleras confirmadas
# --------------------------------------------------------------------------- #
def nombre_evento(slug: str) -> str:
    """'ufc-332' -> 'UFC 332'; 'cryptocom-ufc-331' -> 'UFC 331'; las Fight
    Night llevan la fecha en el slug y se llaman igual todas."""
    m = re.search(r"(?:^|-)ufc-(\d+)$", slug)
    if m:
        return f"UFC {m.group(1)}"
    if "fight-night" in slug:
        return "UFC Fight Night"
    if slug.startswith("road-to-ufc"):
        return "Road to UFC"
    return " ".join(p.upper() if p == "ufc" else p.capitalize() for p in slug.split("-"))


def _ts(valor) -> int | None:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return n if 10**8 < n < 10**10 else None


def parsear_listado(html: str) -> list[dict]:
    """Las tarjetas de /events: próximos y recientes, con la hora de cada parte."""
    soup = BeautifulSoup(html, "html.parser")
    eventos, vistos = [], set()
    for tarjeta in soup.select(".c-card-event--result"):
        enlace = tarjeta.select_one('a[href*="/event/"]')
        fecha = tarjeta.select_one("[data-main-card-timestamp]")
        if not enlace or not fecha:
            continue
        url = urljoin(BASE, enlace["href"].split("#")[0].split("?")[0])
        if not _de_ufc(url) or url in vistos:
            continue
        inicio = {"estelar": _ts(fecha.get("data-main-card-timestamp")),
                  "preliminares": _ts(fecha.get("data-prelims-card-timestamp")),
                  "early": _ts(fecha.get("data-early-card-timestamp"))}
        if not inicio["estelar"]:
            continue
        vistos.add(url)
        slug = urlsplit(url).path.rstrip("/").split("/")[-1]
        titular = tarjeta.select_one(".c-card-event--result__headline")
        lugar = tarjeta.select_one(".c-card-event--result__location")
        texto = lambda sel: " ".join(lugar.select_one(sel).get_text(" ", strip=True).split())             if lugar is not None and lugar.select_one(sel) else ""
        eventos.append({
            "id": _id(url), "url": url, "slug": slug, "nombre": nombre_evento(slug),
            "titular": " ".join(titular.get_text(" ", strip=True).split()) if titular else "",
            "lugar": " ".join(lugar.get_text(" ", strip=True).replace(" ,", ",").split()) if lugar else "",
            "recinto": texto("h5"), "ciudad": texto(".locality"), "pais": texto(".country"),
            "inicio": inicio,
        })
    return eventos


_SECCIONES = (("main-card", "estelar"), ("fight-card-prelims-early", "early"),
              ("fight-card-prelims", "preliminares"))


def _peso(texto: str) -> str:
    """'Peso gallo Bout' -> 'Peso gallo'; "Women's Flyweight Title Bout" -> "Women's Flyweight"."""
    return re.sub(r"\s*(?:title\s+)?bout\s*$", "", " ".join(texto.split()), flags=re.I).strip()


def parsear_evento(html: str) -> list[dict]:
    """Las peleas de una cartelera, en el orden de UFC: la estelar primero."""
    from src.title_bouts import _bandera_etiqueta
    soup = BeautifulSoup(html, "html.parser")
    peleas = []
    for combate in soup.select(".c-listing-fight"):
        estado = " ".join([combate.get("data-status", ""), *combate.get("class", [])])
        if re.search(r"cancel|postpon|removed", estado, re.I):
            continue
        nombres, paises, perfiles = [], [], []
        for esquina in ("red", "blue"):
            el = combate.select_one(f".c-listing-fight__corner-name--{esquina}")
            nombres.append(" ".join(el.get_text(" ", strip=True).split()) if el else "")
            enlace = el.select_one('a[href]') if el else None
            perfil = urljoin(BASE, enlace['href']) if enlace else ''
            perfiles.append(perfil if _de_ufc(perfil) and urlsplit(perfil).path.startswith('/athlete/') else '')
            # Es el país que UFC atribuye a ESTA esquina, nunca el del recinto.
            bloque = combate.select_one(f'.c-listing-fight__country--{esquina}')
            bandera = bloque.select_one('img[src]') if bloque else None
            texto_pais = bloque.select_one('.c-listing-fight__country-text') if bloque else None
            codigo = re.search(r'/flags/([A-Z]{2})\.(?:png|svg)(?:\?|$)',
                               bandera.get('src', '') if bandera else '', re.I)
            paises.append({'codigo': codigo[1].upper(),
                           'nombre': texto_pais.get_text(' ', strip=True) if texto_pais else ''}
                          if codigo and texto_pais and perfiles[-1] else None)
            if paises[-1] and paises[-1]['codigo'] in ('EN', 'SC', 'WA', 'NI'):
                # UFC diferencia territorios deportivos del Reino Unido. Su
                # código de bandera no es un país ISO; se conservan ambos.
                if paises[-1]['codigo'] != 'NI':
                    paises[-1]['bandera'] = paises[-1]['codigo']
                paises[-1]['codigo'] = 'GB'
        if not all(nombres) or canonical_key(nombres[0]) == canonical_key(nombres[1]):
            continue
        clase = combate.select_one(".c-listing-fight__class-text")
        texto = clase.get_text(" ", strip=True) if clase else ""
        rangos = [" ".join(r.get_text(" ", strip=True).split())
                  for r in combate.select(".c-listing-fight__class--desktop .c-listing-fight__corner-rank")]
        seccion = next((nombre for clase_css, nombre in _SECCIONES
                        if combate.find_parent(class_=clase_css)), "estelar")
        peleas.append({"a": nombres[0], "b": nombres[1], "peso": _peso(texto),
                       "titulo": _bandera_etiqueta(texto) is True, "seccion": seccion,
                       "rango_a": rangos[0] if len(rangos) == 2 else "",
                       "rango_b": rangos[1] if len(rangos) == 2 else "",
                       "perfil_a": perfiles[0], "perfil_b": perfiles[1],
                       "pais_a": paises[0], "pais_b": paises[1]})
    return peleas


def eventos(forzar: bool = False) -> dict:
    """
    {"proximos": [...con "peleas"], "recientes": [...], "consultado", "desactualizado"}.

    Un evento sigue en "próximos" hasta 6 h después de que empieza su cartelera
    estelar: mientras se pelea es el evento EN VIVO, no uno terminado.
    """
    with _lock:
        datos = _leer()
        entrada = datos.get("eventos")
        ahora = time.time()
        if not forzar and _vigente(entrada, TTL_EVENTOS, ahora):
            return {**entrada, "desactualizado": False}
        if ahora - _fallos.get("eventos", -1e18) < ESPERA_FALLO:
            return {**(entrada or {"proximos": [], "recientes": []}), "desactualizado": True}
        r = _get(f"{BASE}/events")
        lista = parsear_listado(r.text) if r is not None else []
        if not lista:
            _fallos["eventos"] = ahora
            return {**(entrada or {"proximos": [], "recientes": []}), "desactualizado": True}
        proximos = sorted((e for e in lista if e["inicio"]["estelar"] > ahora - 6 * 3600),
                          key=lambda e: e["inicio"]["estelar"])
        recientes = sorted((e for e in lista if e["inicio"]["estelar"] <= ahora - 6 * 3600),
                           key=lambda e: -e["inicio"]["estelar"])
        previas = {e["id"]: e.get("peleas") for e in (entrada or {}).get("proximos", [])}
        for e in proximos[:EVENTOS_CON_PELEAS]:
            time.sleep(PAUSA)
            pagina = _get(e["url"])
            peleas = parsear_evento(pagina.text) if pagina is not None else []
            # Si una página falla, lo último conocido de ESA cartelera sirve más
            # que una cartelera vacía.
            e["peleas"] = peleas or previas.get(e["id"]) or []
        entrada = {"proximos": proximos, "recientes": recientes, "consultado": ahora}
        datos["eventos"] = entrada
        _guardar(datos)
        # Conserva la identidad y el país aunque el evento deje de aparecer en
        # próximos. Reutiliza el mismo HTML consultado, sin peticiones extra.
        if DB.key(CACHE) is not None:
            from webui import paises
            if DB.key(paises.CACHE) is not None:
                paises.guardar_eventos(proximos)
        _fallos.pop("eventos", None)
        return {**entrada, "desactualizado": False}


def pares_confirmados(solo_titulos: bool = False) -> set[str]:
    """Las parejas de las carteleras confirmadas, sin orden: 'a|b' por identidad.
    solo_titulos: solo las que UFC marca "Title Bout"."""
    pares = set()
    for e in eventos().get("proximos", []):
        for p in e.get("peleas") or []:
            if solo_titulos and not p.get("titulo"):
                continue
            pares.add("|".join(sorted((canonical_key(p["a"]), canonical_key(p["b"])))))
    return pares


def evento(id_evento: str) -> dict | None:
    return next((e for e in eventos().get("proximos", []) if e["id"] == id_evento), None)


def cartelera_csv(id_evento: str) -> Path:
    """
    Arma cards/ufc_<fecha>_<evento>.csv con la cartelera confirmada de UFC para
    predecirla. Sin cuotas: UFC no las publica. El título va explícito
    (es_titulo + titulo_fuente), porque viene del marcador "Title Bout" de UFC.
    """
    import datetime as dt
    import pandas as pd
    e = evento(id_evento)
    if e is None or not e.get("peleas"):
        raise ValueError("No tengo las peleas de esa cartelera: UFC todavía no la publicó "
                         "o no se pudo consultar.")
    filas = []
    for i, p in enumerate(e["peleas"]):
        segmento = "Estelar" if i == 0 else "Co-estelar" if i == 1 and p["seccion"] == "estelar" else ""
        fila = {"fighter_a": p["a"], "fighter_b": p["b"], "segment": segmento,
                "es_titulo": p["titulo"], "titulo_fuente": "UFC.com", "weight_class": p['peso']}
        for lado in ('a', 'b'):
            fila['rango_' + lado] = p.get('rango_' + lado, '')
            fila['perfil_' + lado] = p.get('perfil_' + lado, '')
            pais = p.get('pais_' + lado) or {}
            fila['pais_codigo_' + lado] = pais.get('codigo', '')
            fila['pais_nombre_' + lado] = pais.get('nombre', '')
            fila['pais_bandera_' + lado] = pais.get('bandera', pais.get('codigo', ''))
        filas.append(fila)
    filas.reverse()                       # como Betano: preliminares arriba, estelar al final
    dia = dt.datetime.fromtimestamp(e["inicio"]["estelar"]).strftime("%Y-%m-%d")
    slug = re.sub(r"[^a-z0-9]+", "_", f"{e['nombre']} {e['titular']}".lower()).strip("_")
    destino = C.ROOT / "cards" / f"ufc_{dia}_{slug}.csv"
    destino.parent.mkdir(exist_ok=True)
    DB.to_csv(pd.DataFrame(filas), destino, index=False)
    return destino


# --------------------------------------------------------------------------- #
# Imágenes de las notas
# --------------------------------------------------------------------------- #
def imagen(id_nota: str) -> Path | None:
    """La imagen de una nota ya conocida, bajada una sola vez. None si no hay."""
    if not re.fullmatch(r"[0-9a-f]{16}", id_nota or ""):
        return None
    for ruta in IMAGENES.glob(f"{id_nota}.*"):
        return ruta
    nota = next((n for n in _leer().get("noticias", {}).get("notas", []) if n["id"] == id_nota), None)
    url = nota and nota.get("imagen")
    if not url or not _de_ufc(url):
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=C.REQUEST_TIMEOUT_SEC)
    except requests.RequestException:
        return None
    tipo = r.headers.get("content-type", "")
    if r.status_code != 200 or not tipo.startswith("image/"):
        return None
    ext = {"image/png": ".png", "image/webp": ".webp"}.get(tipo.split(";")[0], ".jpg")
    IMAGENES.mkdir(parents=True, exist_ok=True)
    ruta = IMAGENES / f"{id_nota}{ext}"
    DB.write_bytes(ruta, r.content)
    return ruta
