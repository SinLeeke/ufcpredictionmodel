"""Cinturones confirmados en las carteleras oficiales de UFC.

Consulta el listado de eventos y únicamente las páginas de las fechas pedidas.
Un título requiere el marcador explícito ``Title Bout`` de la misma pareja; ni
el ranking de campeón, ni ser estelar, ni cinco rounds sustituyen ese dato.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

import config as C
from src import storage as DB
from src.fighter_names import canonical_key

BASE = "https://www.ufc.com"
LISTADO = BASE + "/events"
CACHE = C.DATA_RAW / "title_bouts_cache.json"
VERSION = 1
TTL_SEG = 60 * 60
ESPERA_FALLO_SEG = 10 * 60
MAX_PAGINAS = 6
HEADERS = {**C.HEADERS, "User-Agent": "UFCFightPredictor/1.0"}
_lock = threading.Lock()
_fallos: dict[str, float] = {}


def _fecha(valor) -> dt.date | None:
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    if isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        try:
            return dt.date.fromisoformat(valor)
        except ValueError:
            pass
    return None


def _fecha_timestamp(valor) -> dt.date | None:
    try:
        fecha = dt.datetime.fromtimestamp(float(valor), tz=dt.timezone.utc).date()
        return fecha if 1993 <= fecha.year <= 2100 else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _url_evento(valor: str) -> str | None:
    try:
        p = urlsplit(urljoin(BASE, valor))
    except (TypeError, ValueError):
        return None
    if (p.scheme == "https" and p.hostname in ("www.ufc.com", "ufc.com", "www.ufcespanol.com", "ufcespanol.com")
            and re.fullmatch(r"/event/[a-z0-9-]+", p.path) and not p.query and not p.fragment):
        return BASE + p.path
    return None


def parsear_listado(html: str, url: str = LISTADO) -> dict | None:
    """Fechas UTC del listado Drupal; no se interpretan fechas traducidas."""
    soup = BeautifulSoup(html, "html.parser")
    eventos = {}
    for tarjeta in soup.select(".c-card-event--result"):
        enlace = tarjeta.select_one('a[href*="/event/"]')
        fecha_el = tarjeta.select_one("[data-main-card-timestamp]")
        url_evento = _url_evento(enlace.get("href", "")) if enlace else None
        fecha = _fecha_timestamp(fecha_el.get("data-main-card-timestamp")) if fecha_el else None
        if not url_evento or not fecha:
            continue
        eventos.setdefault(url_evento, set()).add(fecha.isoformat())
    # Una lista vacía también puede ser un challenge o un cambio de HTML.
    if not eventos:
        return None
    alternativas = []
    query_actual = urlsplit(url).query
    pagina_actual = int(query_actual.split("=")[1]) if re.fullmatch(r"page=\d+", query_actual) else 0
    prioritarios = soup.select('.pager__item--next a[href], .pager a[rel~="next"]')
    for enlace in prioritarios or soup.select(".pager a[href]"):
        p = urlsplit(urljoin(LISTADO, enlace["href"]))
        if (p.scheme == "https" and p.hostname in ("www.ufc.com", "ufc.com", "www.ufcespanol.com", "ufcespanol.com")
                and p.path == "/events" and re.fullmatch(r"page=\d+", p.query) and not p.fragment):
            numero = int(p.query.split("=")[1])
            if numero > pagina_actual:
                alternativas.append((numero, LISTADO + "?" + p.query))
    siguiente = min(alternativas)[1] if alternativas else None
    validos = [{"url": url, "fecha": next(iter(fechas))}
               for url, fechas in eventos.items() if len(fechas) == 1]
    return {"eventos": validos, "siguiente": siguiente} if validos else None


def _bandera_etiqueta(texto: str) -> bool | None:
    texto = " ".join(texto.split())
    if not re.search(r"\bbout\b", texto, re.I):
        return None
    if re.fullmatch(r"bout", texto, re.I):
        return None
    if re.search(r"\btitle\s+bout\b", texto, re.I):
        return False if re.search(r"\b(?:non[-\s]+title|not\s+(?:a\s+)?title)\b", texto, re.I) else True
    return False


def parsear_evento(html: str) -> dict | None:
    """Extrae pareja, marcador y fecha del contenedor exacto de cada combate."""
    soup = BeautifulSoup(html, "html.parser")
    fechas = {_fecha_timestamp(el.get("data-timestamp"))
              for el in soup.select(".c-hero__headline-suffix[data-timestamp]")}
    fechas.discard(None)
    if not fechas:
        # Algunas páginas antiguas solo llevan el timestamp en la barra fija.
        fechas = {_fecha_timestamp(el.get("data-timestamp"))
                  for el in soup.select(".hero-fixed-bar__date[data-timestamp], .hero-fixed-bar__date--mobile[data-timestamp]")}
        fechas.discard(None)
    if len(fechas) != 1:
        return None
    peleas = []
    for combate in soup.select(".c-listing-fight"):
        nombres = []
        for esquina in ("red", "blue"):
            encontrados = {el.get_text(" ", strip=True) for el in combate.select(f".c-listing-fight__corner-name--{esquina}")}
            claves = {canonical_key(nombre) for nombre in encontrados if nombre}
            nombres.append(next(iter(claves)) if len(claves) == 1 else "")
        if not all(nombres) or nombres[0] == nombres[1]:
            continue
        etiquetas = [_bandera_etiqueta(el.get_text(" ", strip=True))
                     for el in combate.select(".c-listing-fight__class-text")]
        titulo = etiquetas[0] if etiquetas and None not in etiquetas and len(set(etiquetas)) == 1 else None
        estado = " ".join([combate.get("data-status", ""), *combate.get("class", [])])
        if re.search(r"cancel|postpon|removed", estado, re.I):
            titulo = None
        peleas.append({"pareja": sorted(nombres), "es_titulo": titulo})
    if not peleas:
        return None
    return {"fecha": next(iter(fechas)).isoformat(), "peleas": peleas}


def _leer_cache() -> dict:
    try:
        datos = DB.read_json(CACHE)
        if isinstance(datos, dict) and datos.get("version") == VERSION and isinstance(datos.get("paginas"), dict):
            return datos
    except (OSError, ValueError):
        pass
    return {"version": VERSION, "paginas": {}}


def _guardar_cache(datos: dict) -> None:
    if DB.key(CACHE) is not None:
        DB.write_text(CACHE, json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        return
    temporal = CACHE.with_name(f".{CACHE.name}.{uuid.uuid4().hex}.tmp")
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        DB.write_text(temporal, json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        temporal.replace(CACHE)
    except OSError:
        # La metadata encontrada sigue siendo útil aunque el disco no permita
        # cachearla. Un fallo de caché no puede interrumpir una predicción.
        pass
    finally:
        try:
            if DB.exists(temporal):
                DB.unlink(temporal)
        except OSError:
            pass


def _datos_validos(datos, parser) -> bool:
    """Un JSON legible también puede contener una caché parcial o incompatible."""
    if not isinstance(datos, dict):
        return False
    if parser is parsear_listado:
        eventos = datos.get("eventos")
        siguiente = datos.get("siguiente")
        if siguiente is not None and (not isinstance(siguiente, str) or not re.fullmatch(re.escape(LISTADO) + r"\?page=\d+", siguiente)):
            return False
        return isinstance(eventos, list) and bool(eventos) and all(
            isinstance(e, dict) and isinstance(e.get("url"), str) and _url_evento(e["url"])
            and _fecha(e.get("fecha")) for e in eventos)
    peleas = datos.get("peleas")
    if not _fecha(datos.get("fecha")) or not isinstance(peleas, list) or not peleas:
        return False
    for pelea in peleas:
        if not isinstance(pelea, dict):
            return False
        pareja = pelea.get("pareja")
        if (not isinstance(pareja, list) or len(pareja) != 2
                or not all(isinstance(n, str) and n for n in pareja)
                or sorted(pareja) != pareja or pareja[0] == pareja[1]
                or pelea.get("es_titulo") is not None and not isinstance(pelea["es_titulo"], bool)):
            return False
    return True


def _obtener(url: str, parser, cache: dict, ahora: float) -> dict | None:
    entrada = cache["paginas"].get(url)
    if isinstance(entrada, dict) and _datos_validos(entrada.get("datos"), parser):
        consultado = entrada.get("consultado")
        if isinstance(consultado, (int, float)) and 0 <= ahora - consultado < TTL_SEG:
            return entrada["datos"]
    if ahora - _fallos.get(url, float("-inf")) < ESPERA_FALLO_SEG:
        return None
    try:
        respuesta = requests.get(url, headers=HEADERS, timeout=min(8, C.REQUEST_TIMEOUT_SEC))
        if respuesta.status_code != 200:
            raise ValueError("HTTP sin HTML oficial usable")
        final = urlsplit(respuesta.url or url)
        if final.scheme != "https" or final.hostname not in ("www.ufc.com", "ufc.com", "www.ufcespanol.com", "ufcespanol.com"):
            raise ValueError("redirección fuera de UFC")
        respuesta.encoding = "utf-8"
        datos = parser(respuesta.text, url=url) if parser is parsear_listado else parser(respuesta.text)
        if not _datos_validos(datos, parser):
            raise ValueError("HTML sin fecha/listado/combates comprobables")
    except (requests.RequestException, ValueError):
        _fallos[url] = ahora
        return None
    cache["paginas"][url] = {"consultado": ahora, "datos": datos}
    _fallos.pop(url, None)
    return datos


def _cerca(a: dt.date | None, b: dt.date | None) -> bool:
    return a is not None and b is not None and abs((a - b).days) <= 1


def resolver_cartelera(filas, fecha_evento=None) -> list[dict]:
    """Metadata paralela a filas; sin mutar cuotas ni decisiones del CSV.

    Cada fila lleva fighter_a/fighter_b y, opcionalmente, fecha_evento_utc. La
    fecha de respaldo suele venir del nombre Betano del CSV. Sin fecha válida
    queda desconocido y no se consulta la red. Ante una ficha vencida y fallo
    de red tampoco se confirma un cinturón antiguo que pudo ser cancelado.
    """
    consultas = []
    for fila in filas:
        fecha = _fecha(fila.get("fecha_evento_utc")) or _fecha(fecha_evento)
        nombres = [fila.get("fighter_a"), fila.get("fighter_b")]
        pareja = sorted(canonical_key(n) for n in nombres) if all(isinstance(n, str) and n.strip() for n in nombres) else []
        consultas.append((fecha, pareja))
    salida = [{"es_titulo": None, "titulo_fuente": ""} for _ in consultas]
    fechas = {fecha for fecha, pareja in consultas if fecha and len(pareja) == 2 and pareja[0] != pareja[1]}
    if not fechas:
        return salida
    with _lock:
        cache = _leer_cache()
        ahora = time.time()
        catalogo, vistas, url = {}, set(), LISTADO
        for _ in range(MAX_PAGINAS):
            if not url or url in vistas:
                break
            vistas.add(url)
            pagina = _obtener(url, parsear_listado, cache, ahora)
            if not pagina:
                break
            for evento in pagina.get("eventos", []):
                enlace = _url_evento(evento.get("url", ""))
                dia = _fecha(evento.get("fecha"))
                if enlace and dia:
                    catalogo.setdefault(enlace, set()).add(dia)
            # Se recorre la paginación acotada completa: una fecha adyacente no
            # prueba que ya vimos la pareja, que podría figurar en otra página.
            url = pagina.get("siguiente")
        eventos = []
        for url, dias in catalogo.items():
            if len(dias) != 1 or not any(_cerca(fecha, next(iter(dias))) for fecha in fechas):
                continue
            evento = _obtener(url, parsear_evento, cache, ahora)
            # El listado y la ficha deben describir el mismo evento/fecha.
            if evento and _fecha(evento.get("fecha")) == next(iter(dias)):
                eventos.append((url, evento))
        for indice, (fecha, pareja) in enumerate(consultas):
            candidatos = [(url, pelea.get("es_titulo"))
                          for url, evento in eventos if _cerca(fecha, _fecha(evento.get("fecha")))
                          for pelea in evento.get("peleas", []) if pelea.get("pareja") == pareja]
            # Un duplicado o dos eventos con la misma pareja no permiten elegir
            # uno, aunque sus marcadores coincidan. Las ausencias no son False.
            if len(candidatos) == 1 and isinstance(candidatos[0][1], bool):
                salida[indice] = {"es_titulo": candidatos[0][1], "titulo_fuente": candidatos[0][0]}
        _guardar_cache(cache)
    return salida
