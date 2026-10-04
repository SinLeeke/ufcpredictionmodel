"""Cuotas de consulta y snapshots inmutables en SQLite.

BFO: una petición para todas las carteleras, caché compartida de 30 minutos.
The Odds API: un mercado / una región, clave solo en el servidor, sin polling.
No hay fallback silencioso hacia Betano ni mezcla de casas en un combate.
"""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import re
import threading
import time
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup
import config as C
from src import storage as DB

TTL = 30 * 60
_lock = threading.RLock()
_consultado = {}


def _tablas(con):
    con.execute('''CREATE TABLE IF NOT EXISTS cuotas_snapshots (
        id TEXT PRIMARY KEY, proveedor TEXT NOT NULL, capturado TEXT NOT NULL,
        fecha_fuente TEXT, contenido TEXT NOT NULL, sha256 TEXT NOT NULL,
        cartelera TEXT)''')
    if 'cartelera' not in {r[1] for r in con.execute('PRAGMA table_info(cuotas_snapshots)')}:
        con.execute('ALTER TABLE cuotas_snapshots ADD COLUMN cartelera TEXT')
    con.execute('CREATE INDEX IF NOT EXISTS cuotas_fecha ON cuotas_snapshots(proveedor,capturado)')


def decimal(americana):
    return 1 + americana / 100 if americana > 0 else 1 + 100 / abs(americana)


def parsear_bfo(html):
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select_one(".table-div[id^=event] .table-scroller table.odds-table"):
        raise ValueError("La página no contiene el formato esperado de cuotas; se conserva la captura anterior.")
    eventos = []
    for grupo in soup.select(".table-div[id^=event]"):
        cab = grupo.select_one(".table-header")
        table = grupo.select_one(".table-scroller table.odds-table")
        if not cab or not table:
            continue
        title = cab.select_one("h1,h2")
        if not title or not re.search(r"\bUFC\b", title.get_text(), re.I):
            continue
        columns = table.select("thead tr th")[1:]
        casas = []
        for th in columns:
            a = th.select_one("a,span")
            casas.append((th.get("data-b"), a.get_text(strip=True) if a else ""))
        filas = []
        for tr in table.select("tbody tr"):
            a = tr.select_one('th a[href^="/fighters/"]')
            if not a:
                continue
            prices = {}
            for (book, nombre), td in zip(casas, tr.select("td")):
                # Prediction markets tienen otro producto y estructura de comisión.
                if not book or nombre.lower() in ("polymarket", "kalshi"):
                    continue
                text = td.select_one("span[id^=oID]")
                m = re.fullmatch(r"[+−-]\d{2,5}", text.get_text(strip=True) if text else "")
                if m:
                    value = int(m[0].replace("−", "-"))
                    if abs(value) >= 100:
                        prices[book] = {"casa": nombre, "cuota": decimal(value)}
            filas.append({"nombre": a.get_text(" ", strip=True), "perfil": a["href"], "precios": prices})
        peleas = []
        for i in range(0, len(filas) - 1, 2):
            a, b = filas[i:i + 2]
            books = {book: {"casa": a["precios"][book]["casa"], "a": a["precios"][book]["cuota"],
                "b": b["precios"][book]["cuota"]} for book in a["precios"].keys() & b["precios"].keys()}
            if books:
                peleas.append({"id": hashlib.sha256((a["perfil"] + "|" + b["perfil"]).encode()).hexdigest()[:20],
                    "a": a["nombre"], "b": b["nombre"], "casas": books})
        if peleas:
            fecha = cab.select_one(".table-header-date")
            link = cab.select_one('a[href^="/events/"]')
            eventos.append({"id": grupo["id"], "titulo": title.get_text(strip=True),
                "fecha": fecha.get_text(strip=True) if fecha else "", "peleas": peleas,
                "fuente": urljoin("https://www.bestfightodds.com", link["href"]) if link else "https://www.bestfightodds.com/"})
    return eventos


def _precio_valido(v, formato):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return False
    # Decimal: siempre > 1. Americana: nunca entre -100 y +100.
    return v > 1 if formato == "decimal" else abs(v) >= 100


def parsear_odds_api(datos, formato="decimal"):
    """formato='american' lo usa la capa src/cuotas (pide oddsFormat=american);
    el endpoint /api/cuotas sigue pidiendo y guardando decimal, como siempre."""
    if not isinstance(datos, list) or any(not isinstance(r, dict) for r in datos):
        raise ValueError("La fuente no devolvió una lista válida de eventos.")
    eventos = []
    for r in datos:
        if r.get("sport_key") != "mma_mixed_martial_arts":
            continue
        a, b = r.get("home_team"), r.get("away_team")
        if not a or not b or a == b:
            continue
        casas = {}
        for book in r.get("bookmakers", []):
            for m in book.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                # Nombre exacto, dos salidas, sin empate ni tercero oculto.
                outs = m.get("outcomes", [])
                if len(outs) != 2 or {x.get("name") for x in outs} != {a, b}:
                    continue
                vals = {x["name"]: x.get("price") for x in outs}
                if all(_precio_valido(v, formato) for v in vals.values()):
                    casas[book["key"]] = {"casa": book["title"], "a": vals[a], "b": vals[b],
                        "actualizada": m.get("last_update")}
        if casas:
            eventos.append({"id": r["id"], "titulo": f"{a} vs {b}", "fecha": r.get("commence_time"),
                "peleas": [{"id": r["id"], "a": a, "b": b, "casas": casas}], "fuente": "https://the-odds-api.com/sports/mma-ufc-odds.html"})
    return eventos


def guardado(proveedor):
    with DB.connect() as con:
        _tablas(con)
        r = con.execute('SELECT id FROM cuotas_snapshots WHERE proveedor=? AND fecha_fuente IS NULL ORDER BY capturado DESC LIMIT 1', (proveedor,)).fetchone()
    return captura(r[0]) if r else None


def captura(sid):
    with DB.connect() as con:
        _tablas(con)
        r = con.execute('SELECT id,capturado,contenido,proveedor,fecha_fuente,cartelera FROM cuotas_snapshots WHERE id=?', (sid,)).fetchone()
    if not r:
        raise ValueError("Captura desconocida")
    d = {"snapshot": r[0], "capturado": r[1], "eventos": json.loads(r[2]),
         "proveedor": r[3], "fecha_fuente": r[4]}
    if r[5] is not None:
        d["carteleras_guardadas"] = json.loads(r[5])
    return d


def historial(proveedor=None, limite=40):
    with DB.connect() as con:
        _tablas(con)
        rows = con.execute('SELECT id,proveedor,capturado,fecha_fuente FROM cuotas_snapshots '
            'WHERE (? IS NULL OR proveedor=?) ORDER BY capturado DESC LIMIT ?',
            (proveedor, proveedor, limite)).fetchall()
    return [{"snapshot": r[0], "proveedor": r[1], "capturado": r[2], "fecha_fuente": r[3]} for r in rows]


def corte_captura(capturado):
    """Al reabrir precios de otro día, no incorporar resultados posteriores."""
    fecha = datetime.fromisoformat(capturado).astimezone().date()
    return fecha.isoformat() if fecha < datetime.now().date() else None


def _guardar(proveedor, eventos, fecha_fuente=None):
    contenido = json.dumps(eventos, ensure_ascii=False, sort_keys=True, allow_nan=False)
    from src import cartelera_completa as F
    roster, consultado = F.oficiales()
    # El hash cubre también la cartelera: idénticos precios no implican que
    # las peleas anunciadas sigan siendo las mismas. Nunca guardar NaN JSON.
    anunciado = json.dumps({"eventos": roster, "consultado": consultado},
                           ensure_ascii=False, sort_keys=True, allow_nan=False)
    sha = hashlib.sha256((contenido + "\n" + anunciado + "\n" + (fecha_fuente or "")).encode()).hexdigest()
    capturado = datetime.now(timezone.utc).isoformat()
    sid = hashlib.sha256((proveedor + capturado + sha).encode()).hexdigest()
    with DB.connect() as con:
        _tablas(con)
        con.execute('INSERT INTO cuotas_snapshots(id,proveedor,capturado,fecha_fuente,contenido,sha256,cartelera) VALUES(?,?,?,?,?,?,?)', (sid, proveedor, capturado, fecha_fuente, contenido, sha, anunciado))
    return captura(sid)


def consultar(proveedor="bfo", forzar=False, historico=None):
    if proveedor not in ("bfo", "odds-api"):
        raise ValueError("Proveedor desconocido")
    with _lock:
        saved = guardado(proveedor) if not historico else None
        if (not forzar and saved and "carteleras_guardadas" in saved
                and time.time() - datetime.fromisoformat(saved["capturado"]).timestamp() < TTL):
            return {**saved, "cache": True, "desactualizado": False, "proveedor": proveedor}
        consulta = (str(DB.db_path()), proveedor, historico)
        if not forzar and time.time() - _consultado.get(consulta, 0) < TTL:
            if saved:
                return {**saved, "cache": True, "desactualizado": True, "proveedor": proveedor}
            raise ValueError("La fuente no respondió. Se reintentará tras 30 minutos.")
        _consultado[consulta] = time.time()
        try:
            if proveedor == "bfo":
                if historico:
                    raise ValueError("BFO no ofrece el endpoint histórico de esta integración")
                response = requests.get("https://www.bestfightodds.com/", headers={"User-Agent": "UFCFightPredictor/1.0"}, timeout=25)
            else:
                # config lee ODDS_API_KEY del .env (y THE_ODDS_API_KEY como respaldo);
                # el entorno se mira de nuevo por si alguien la definió después de importar.
                key = C.ODDS_API_KEY or os.environ.get("ODDS_API_KEY", "") or os.environ.get("THE_ODDS_API_KEY", "")
                if not key:
                    raise ValueError("Falta ODDS_API_KEY en el .env del servidor. El plan gratuito requiere una cuenta.")
                params = {"apiKey": key, "regions": C.ODDS_API_REGION, "markets": "h2h", "oddsFormat": "decimal"}
                path = "historical/sports" if historico else "sports"
                if historico:
                    params["date"] = historico
                response = requests.get(f"https://api.the-odds-api.com/v4/{path}/mma_mixed_martial_arts/odds", params=params, timeout=25)
            # No imprimir excepciones HTTP: la URL de Odds API contiene la clave.
            if response.status_code != 200:
                raise ValueError(f"La fuente respondió HTTP {response.status_code}; no se guardó una captura vacía.")
            response.encoding = "utf-8"
            fecha_fuente = None
            if proveedor == "bfo":
                eventos = parsear_bfo(response.text)
            else:
                payload = response.json()
                if historico:
                    fecha_fuente = payload["timestamp"]
                    if datetime.fromisoformat(fecha_fuente.replace('Z', '+00:00')) > datetime.fromisoformat(historico.replace('Z', '+00:00')):
                        raise ValueError("La fuente devolvió una captura posterior al corte.")
                    payload = payload["data"]
                eventos = parsear_odds_api(payload)
            # Una lista vacía es un estado válido: no reutilizar eventos terminados.
            d = _guardar(proveedor, eventos, fecha_fuente)
            return {**d, "cache": False, "desactualizado": False, "proveedor": proveedor}
        except (requests.RequestException, ValueError, KeyError, TypeError):
            if saved:
                return {**saved, "cache": True, "desactualizado": True, "proveedor": proveedor}
            raise ValueError("No pude consultar la fuente. Comprueba conexión y configuración; no se usó Betano.") from None


def cartelera(snapshot, evento, casa):
    with DB.connect() as con:
        _tablas(con)
        r = con.execute('SELECT contenido,capturado,proveedor,fecha_fuente FROM cuotas_snapshots WHERE id=?', (snapshot,)).fetchone()
    if not r:
        raise ValueError("Captura desconocida")
    # Un snapshot histórico conserva su fecha fuente; no se anuncia como actual.
    datos = json.loads(r[0])
    e = next((e for e in datos if e["id"] == evento), None)
    if not e:
        raise ValueError("Evento desconocido")
    filas = []
    for p in e["peleas"]:
        c = p["casas"].get(casa)
        if c:
            filas.append({"fighter_a": p["a"], "fighter_b": p["b"], "segment": "",
                "odds_a": c["a"], "odds_b": c["b"], "bookmaker": c["casa"]})
    if not filas:
        raise ValueError("Esa casa no tiene cuotas completas para este evento")
    path = C.DATA_PROCESSED / f"cuotas_{snapshot[:16]}_{hashlib.sha256((evento+casa).encode()).hexdigest()[:12]}.csv"
    DB.to_csv(pd.DataFrame(filas), path, index=False)
    return path, e["titulo"], {"proveedor": r[2], "capturado": r[1], "fecha_fuente": r[3],
        "casa": filas[0]["bookmaker"], "snapshot": snapshot, "fuente": e["fuente"],
        "corte": corte_captura(r[1]),
        "peleas_sin_cuota": len(e["peleas"]) - len(filas)}
