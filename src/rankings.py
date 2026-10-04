"""Importación explícita de un snapshot oficial, sin crawler ni refresco de red.

Uso: python -m src.rankings fichero.html --fecha AAAA-MM-DD
     python -m src.rankings --paises      (completa las banderas del ranking)
El fichero original se respalda con hash; la UI solo lee SQLite.

Banderas: hasta octubre de 2026 el país sólo se conocía para quien salía en
una cartelera de UFC con bandera por esquina (18 atletas, todos de UFC 333):
de los 176 del ranking, 161 quedaban sin bandera, Makhachev, Topuria y
Pereira incluidos. --paises lo completa con la MISMA fuente: la bandera que
UFC pone a cada esquina en la página del evento, identificada por la URL de
la ficha. Se descartó la «Ciudad natal» de la ficha del atleta: es dónde vive
o entrena, no su país (Joshua Van pelea con la bandera de Myanmar).
"""
import argparse
import hashlib
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import config as C
from src import storage as DB


def parsear(html):
    soup = BeautifulSoup(html, "html.parser")
    divisiones = []
    for champion in soup.select(".rankings--athlete--champion"):
        heading = champion.select_one("h4")
        link = champion.select_one("h5 a")
        if not heading or not link:
            continue
        titulo = heading.find(string=True, recursive=False)
        titulo = str(titulo).strip() if titulo else heading.get_text(" ", strip=True)
        tabla = champion.find_parent("table")
        rows = [] if "pound-for-pound" in titulo.lower() else [{"puesto": 0,
                 "nombre": link.get_text(" ", strip=True),
                 "perfil_ufc": urljoin("https://www.ufc.com", link.get("href", ""))}]
        if tabla:
            for tr in tabla.select("tbody tr"):
                a = tr.select_one('a[href*="/athlete/"]')
                rank = tr.select_one(".views-field-weight-class-rank")
                if not a or not rank:
                    continue
                try:
                    numero = int(rank.get_text(strip=True))
                except ValueError:
                    continue
                rows.append({"puesto": numero, "nombre": a.get_text(" ", strip=True),
                    "perfil_ufc": urljoin("https://www.ufc.com", a["href"])})
        if len(rows) > 1:
            divisiones.append({"nombre": titulo, "peleadores": rows})
    if len(divisiones) < 10:
        raise ValueError("La captura no contiene todos los rankings oficiales. No se sustituye la anterior.")
    return divisiones


def importar(path, fecha):
    date.fromisoformat(fecha)
    raw = Path(path).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    respaldo = C.ROOT / "data/originales" / sha / Path(path).name
    respaldo.parent.mkdir(parents=True, exist_ok=True)
    if not respaldo.exists():
        respaldo.write_bytes(raw)
    d = {"fecha": fecha, "fuente": "https://www.ufc.com/rankings", "sha256": sha,
         "divisiones": parsear(raw.decode("utf-8")), "importacion": "manual"}
    DB.write_text(C.DATA_RAW / "rankings_oficiales.json", json.dumps(d, ensure_ascii=False))
    return d


# --------------------------------------------------------------------------- #
# Países del ranking (red, sólo bajo pedido explícito)
# --------------------------------------------------------------------------- #
PAUSA = 1.5                    # entre peticiones a UFC: es un pase de ~150 páginas
REINTENTO_FICHA_DIAS = 7       # una ficha sin bandera se vuelve a mirar tras una semana


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _evento_canonico(href):
    """'https://www.ufcespanol.com/event/ufc-330#12910' -> 'https://www.ufc.com/event/ufc-330'."""
    p = urlsplit(urljoin("https://www.ufc.com", str(href or "")))
    if p.scheme != "https" or p.hostname not in ("ufc.com", "www.ufc.com", "ufcespanol.com", "www.ufcespanol.com"):
        return None
    partes = [x for x in p.path.split("/") if x]
    if len(partes) != 2 or partes[0] != "event" or not partes[1]:
        return None
    return "https://www.ufc.com/event/" + partes[1]


def eventos_de_ficha(html):
    """Carteleras enlazadas en la ficha de un atleta, en su orden (la más nueva primero)."""
    vistos = []
    for a in BeautifulSoup(html, "html.parser").select('a[href*="/event/"]'):
        url = _evento_canonico(a.get("href"))
        if url and url not in vistos:
            vistos.append(url)
    return vistos


def perfiles_ranking(d=None):
    """{URL de ficha UFC: nombre} de todos los del ranking, en orden de aparición."""
    from webui import paises as P
    ruta = C.DATA_RAW / "rankings_oficiales.json"
    if d is None:
        d = DB.read_json(ruta) if DB.exists(ruta) else {"divisiones": []}
    perfiles = {}
    for division in d.get("divisiones", []):
        for r in division.get("peleadores", []):
            url = P._ufc(r.get("perfil_ufc"))
            if url:
                perfiles.setdefault(url, r.get("nombre"))
    return perfiles


def completar_paises(pausa=PAUSA, max_peticiones=400, log=print, ahora=None):
    """Busca la bandera oficial de cada atleta del ranking que aún no la tiene.

    Orden (cada página de evento resuelve a varios a la vez):
      1. las carteleras próximas y recientes ya listadas en ufc_oficial.json;
      2. por cada atleta que siga sin país, su ficha en ufc.com y, de ahí, sus
         últimas carteleras, de la más nueva a la más vieja.
    Incremental: una cartelera ya consultada no se vuelve a pedir y un atleta
    con país no genera peticiones. Devuelve un resumen con los que quedaron sin
    país y el porqué, que nunca se descarta en silencio.
    """
    from src import ufc_oficial as U
    from webui import paises as P
    ahora = ahora if ahora is not None else time.time()
    perfiles = perfiles_ranking()
    consultas = P.consultas_ufc()
    resumen = {"peticiones": 0, "fallos": [], "eventos": 0, "fichas": 0}

    def pendientes():
        return {u: n for u, n in perfiles.items() if not P.pais_perfil(n, u)}

    def bajar(url):
        if resumen["peticiones"] >= max_peticiones:
            return None
        if resumen["peticiones"]:
            time.sleep(pausa)
        resumen["peticiones"] += 1
        r = U._get(url)
        if r is None:
            resumen["fallos"].append(url)
            log(f"  sin respuesta válida: {url}")
        return r

    def evento(url):
        if url in consultas["eventos"]:
            return
        r = bajar(url)
        if r is None:
            return           # sin anotar: se reintenta en la próxima pasada
        peleas = U.parsear_evento(r.text)
        P.guardar_eventos([{"url": url, "peleas": peleas}], sobrescribir=False)
        datos = {"consultado": _iso(time.time()), "peleas": len(peleas)}
        consultas["eventos"][url] = datos
        P.anotar_consulta("eventos", url, datos)
        resumen["eventos"] += 1

    log(f"Ranking: {len(perfiles)} atletas, {len(pendientes())} sin país.")
    if pendientes():
        cache = DB.read_json(U.CACHE) if DB.exists(U.CACHE) else {}
        listados = (cache.get("eventos") or {}) if isinstance(cache, dict) else {}
        for e in list(listados.get("proximos", [])) + list(listados.get("recientes", [])):
            url = _evento_canonico(e.get("url"))
            if url and pendientes():
                evento(url)
    for url in list(pendientes()):
        if url not in pendientes():
            continue          # lo resolvió la cartelera de otro
        previa = consultas["atletas"].get(url) or {}
        if ahora - previa.get("ts", -1e18) < REINTENTO_FICHA_DIAS * 86400:
            enlaces = previa.get("eventos", [])
        else:
            r = bajar(url)
            if r is None:
                continue
            enlaces = eventos_de_ficha(r.text)
            previa = {"ts": ahora, "consultado": _iso(time.time()), "eventos": enlaces}
            consultas["atletas"][url] = previa
            P.anotar_consulta("atletas", url, previa)
            resumen["fichas"] += 1
        for enlace in enlaces:
            if url not in pendientes():
                break
            evento(enlace)
    quedan = pendientes()
    resumen["sin_pais"] = {u: {"nombre": n, "motivo": _motivo(u, n, consultas, P)} for u, n in quedan.items()}
    log(f"Peticiones: {resumen['peticiones']} ({resumen['fichas']} fichas, {resumen['eventos']} carteleras). "
        f"Sin país: {len(quedan)} de {len(perfiles)}.")
    for u, x in resumen["sin_pais"].items():
        log(f"  {x['nombre']} ({u}): {x['motivo']}")
    return resumen


def _motivo(url, nombre, consultas, P):
    registro = P._leer()[0].get(url)
    if registro:
        return f"la cartelera nombra esa ficha «{registro.get('atleta')}», no «{nombre}»"
    ficha = consultas["atletas"].get(url)
    if ficha is None:
        return "ficha no consultada (sin respuesta o límite de peticiones)"
    if not ficha.get("eventos"):
        return "la ficha UFC no enlaza ninguna cartelera"
    return "ninguna de sus carteleras trae bandera para esta ficha"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("archivo", nargs="?")
    p.add_argument("--fecha")
    p.add_argument("--paises", action="store_true", help="completar la bandera de los atletas del ranking")
    a = p.parse_args()
    if a.archivo:
        if not a.fecha:
            p.error("--fecha es obligatoria al importar un fichero")
        print(f"Importadas {len(importar(a.archivo, a.fecha)['divisiones'])} clasificaciones oficiales.")
    elif not a.paises:
        p.error("indica un fichero para importar o --paises")
    if a.paises:
        completar_paises()
