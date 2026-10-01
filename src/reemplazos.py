"""
reemplazos.py
Detecta qué peleadores entraron como REEMPLAZO (corto aviso) usando Wikipedia.

Por qué importa: un peleador que acepta con poco aviso no hace campamento
completo. El dato público dice que quien entra con menos de un mes pierde el 63%
de las veces, y medido sobre nuestras propias carteleras da lo mismo: los
reemplazos ganan solo **34,9%** (n=63, ±11,8). Es la señal más gruesa que le
faltaba al modelo, y NO está en UFCStats ni en Kaggle.

Fuente: Wikipedia. Se eligió tras descartar Tapology, que devuelve HTTP 403
(igual que ya pasaba con el scraper viejo). Las páginas de evento traen una
sección "Background" con frases del tipo:
    "However, Gafurov withdrew due to a leg injury and was replaced by Cody Gibson."
De ahí sale el NOMBRE del que entra. La fecha del anuncio casi nunca está en la
misma frase (medido: 6% de los casos), así que NO se intenta calcular "días de
aviso" — se guarda un flag binario, que es lo que se puede extraer de forma
fiable. Un reemplazo es casi siempre corto aviso, así que el flag captura la
mayor parte del efecto.

ANTI-LEAKAGE: que alguien sea reemplazo se sabe ANTES de la pelea (es noticia
pública al anunciarse), así que usarlo como feature es legítimo. Lo que NO se
puede es leer el resultado de la página, y no se lee.

Uso:
    python -m src.reemplazos            # baja/actualiza el caché (~780 eventos)
    python -m src.reemplazos --revisar  # mide la tasa de victoria de los reemplazos
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src.fighter_names import canonical_key

CACHE = C.DATA_RAW / "reemplazos_wiki.json"
API = "https://en.wikipedia.org/w/api.php"
# Wikipedia pide identificarse; sin User-Agent propio contestan 403. Su política
# pide un modo de contacto: si vas a scrapear en volumen, pon el tuyo en
# CONTACTO (o en la variable de entorno WIKI_CONTACT).
CONTACTO = os.environ.get("WIKI_CONTACT", "https://github.com/SinLeeke/ufcpredictionmodel")
HEADERS = {"User-Agent": f"ufc-predictor/1.0 (personal research; {CONTACTO})"}

# "replaced by [promotional newcomer] Nombre Apellido"
_RE_REPL = re.compile(
    r"replaced by(?: promotional newcomer| newcomer| short[- ]notice replacement)?"
    r" \[?\[?([A-Z][\w'.-]+(?: [A-Z][\w'.-]+){1,2})"
)

_IDX: dict | None = None


def _norm(s: str) -> str:
    return canonical_key(s)


def _wiki(params: dict) -> dict | None:
    for intento in range(3):
        try:
            r = requests.get(API, headers=HEADERS, timeout=20, params=params)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(1.0 * (intento + 1))
    return None


def _texto_evento(nombre: str) -> str | None:
    """Wikitext de la página del evento, buscándola por nombre aproximado."""
    q = nombre.replace("UFC Fight Night: ", "UFC Fight Night ")
    j = _wiki({"action": "query", "list": "search", "srsearch": q,
               "format": "json", "srlimit": 1})
    if not j or not j.get("query", {}).get("search"):
        return None
    titulo = j["query"]["search"][0]["title"]
    j2 = _wiki({"action": "query", "prop": "revisions", "rvprop": "content",
                "rvslots": "main", "titles": titulo, "format": "json"})
    if not j2:
        return None
    pg = list(j2["query"]["pages"].values())[0]
    if "revisions" not in pg:
        return None
    tx = pg["revisions"][0]["slots"]["main"]["*"]
    # Las citas <ref> traen nombres de periodistas que ensucian el regex.
    return re.sub(r"<ref[^>]*>.*?</ref>", "", tx, flags=re.S)


def construir(limite: int | None = None, refrescar: bool = False) -> dict:
    """Recorre los eventos de ufcstats_fights.csv y cachea los reemplazos."""
    cache = {}
    if CACHE.exists() and not refrescar:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    h = pd.read_csv(C.DATA_PROCESSED / "ufcstats_fights.csv")
    eventos = h.groupby("event")["date"].first().sort_values(ascending=False)
    if limite:
        eventos = eventos.head(limite)

    pendientes = [e for e in eventos.index if e not in cache]
    print(f"[reemplazos] {len(cache)} en caché, {len(pendientes)} por consultar")
    for i, ev in enumerate(pendientes, 1):
        tx = _texto_evento(ev)
        # Se guarda incluso la lista vacía: así no se vuelve a consultar un
        # evento que simplemente no tuvo reemplazos.
        cache[ev] = sorted({_norm(m.group(1)) for m in _RE_REPL.finditer(tx)}) if tx else []
        if i % 25 == 0:
            print(f"    {i}/{len(pendientes)}...")
            CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        time.sleep(0.15)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    n = sum(len(v) for v in cache.values())
    print(f"[reemplazos] {len(cache)} eventos, {n} reemplazos detectados -> {CACHE}")
    return cache


def _indice() -> dict:
    """{(evento_normalizado, peleador_normalizado)} de los que entraron de reemplazo."""
    global _IDX
    if _IDX is None:
        if not CACHE.exists():
            print("[reemplazos] sin caché -> corre 'python -m src.reemplazos'")
            _IDX = set()
        else:
            d = json.loads(CACHE.read_text(encoding="utf-8"))
            _IDX = {(_norm(ev), _norm(n)) for ev, nombres in d.items() for n in nombres}
    return _IDX


def es_reemplazo(nombre: str, evento: str) -> int:
    return int((_norm(evento), _norm(nombre)) in _indice())


_POR_FECHA: set | None = None


def _indice_por_fecha() -> set:
    """
    {(fecha, peleador)} de los reemplazos.

    El caché viene indexado por NOMBRE DE EVENTO, pero features.csv no trae esa
    columna (viene de Kaggle) — sí trae fecha y nombres. Se traduce evento->fecha
    con ufcstats_fights.csv, que es el que tiene las dos cosas.
    """
    global _POR_FECHA
    if _POR_FECHA is not None:
        return _POR_FECHA
    if not CACHE.exists():
        _POR_FECHA = set()
        return _POR_FECHA
    d = json.loads(CACHE.read_text(encoding="utf-8"))
    h = pd.read_csv(C.DATA_PROCESSED / "ufcstats_fights.csv")
    h["date"] = pd.to_datetime(h["date"], errors="coerce")
    fecha_de = h.groupby("event")["date"].first().to_dict()
    _POR_FECHA = {
        (fecha_de[ev].date(), _norm(n))
        for ev, nombres in d.items() if ev in fecha_de and pd.notna(fecha_de[ev])
        for n in nombres
    }
    return _POR_FECHA


def flag(nombre: str, fecha, dias: int = 0) -> int:
    """
    1 si ese peleador entró de reemplazo en la cartelera de esa fecha.

    `dias` > 0 amplía la búsqueda a una ventana de ±N días alrededor de la fecha.
    Sirve para el camino EN VIVO: ahí no se conoce la fecha exacta del evento
    (el CSV de cartelera solo trae nombres), así que se pasa "hoy" y se busca en
    los días cercanos. Es seguro porque nadie entra de reemplazo dos veces en el
    mismo mes. Para el ENTRENAMIENTO se usa dias=0: ahí la fecha es exacta y
    ampliar la ventana sería inventar coincidencias.
    """
    n = _norm(nombre)
    f = pd.Timestamp(fecha).date()
    idx = _indice_por_fecha()
    if dias <= 0:
        return int((f, n) in idx)
    import datetime as _dt
    return int(any((f + _dt.timedelta(days=d), n) in idx
                   for d in range(-dias, dias + 1)))


def features(nombre_a: str, nombre_b: str, fecha) -> dict:
    """Diferencial A-B: +1 si solo A es reemplazo, -1 si solo lo es B, 0 si ninguno."""
    return {"reemplazo_diff": flag(nombre_a, fecha) - flag(nombre_b, fecha)}


def revisar() -> None:
    """Mide la tasa de victoria de los reemplazos contra los resultados reales."""
    import math
    h = pd.read_csv(C.DATA_PROCESSED / "ufcstats_fights.csv")
    idx = _indice()
    g = p = 0
    for r in h.itertuples(index=False):
        ev = _norm(r.event)
        for f in (r.fighter_a, r.fighter_b):
            if (ev, _norm(f)) in idx:
                if _norm(r.winner) == _norm(f):
                    g += 1
                else:
                    p += 1
    n = g + p
    if not n:
        print("[reemplazos] no crucé ningún reemplazo con los resultados.")
        return
    tasa = g / n
    err = 1.96 * math.sqrt(tasa * (1 - tasa) / n)
    print(f"\nReemplazos cruzados con resultados: {n}")
    print(f"  ganaron {g}, perdieron {p}  ->  {tasa*100:.1f}% (±{err*100:.1f})")
    print(f"  (sin efecto sería ~50%; el dato público de corto aviso da ~37%)")


if __name__ == "__main__":
    if "--revisar" in sys.argv:
        revisar()
    else:
        lim = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
        construir(limite=lim, refrescar="--refrescar" in sys.argv)
        revisar()
