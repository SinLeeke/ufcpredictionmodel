"""
fast_fetch.py
Descarga en PARALELO desde UFCStats. Reduce horas a minutos.

Por qué es mucho más rápido:
  * El scraper normal pide una página, espera 1.5 s, pide la siguiente. Casi todo
    el tiempo se va esperando.
  * Acá se usan varios hilos a la vez, cada uno con una pausa corta. El challenge
    anti-bot (proof-of-work SHA256) se resuelve UNA sola vez y la cookie se
    comparte entre todos los hilos.

Sobre ser respetuoso con el sitio: WORKERS=6 y una pausa de 0.25 s por hilo dan
~24 peticiones/segundo como techo teórico, pero en la práctica quedan ~15-20/s,
un ritmo que un sitio estático como UFCStats absorbe sin problemas. Si notas
errores 429/503, baja WORKERS.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

import requests
from bs4 import BeautifulSoup

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config as C
from src import ufcstats as U

WORKERS = 6
DELAY = 0.25          # pausa por hilo (no global)
_local = threading.local()


def _session() -> requests.Session:
    """Una sesión por hilo, todas con la cookie del challenge ya resuelta."""
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(C.HEADERS)
        s.cookies.update(_shared_cookies)
        _local.s = s
    return s


_shared_cookies: dict = {}


def warm_up() -> bool:
    """Resuelve el anti-bot una vez y guarda la cookie para todos los hilos."""
    global _shared_cookies
    soup = U._get(f"{C.UFCSTATS_BASE}/statistics/events/completed")
    _shared_cookies = U._SESSION.cookies.get_dict()
    if _shared_cookies:
        print(f"[fast] anti-bot resuelto; cookie compartida entre {WORKERS} hilos")
    return soup is not None


def _fetch_one(url: str, retries: int = 2) -> Optional[BeautifulSoup]:
    for intento in range(retries + 1):
        try:
            r = _session().get(url, timeout=C.REQUEST_TIMEOUT_SEC)
            time.sleep(DELAY)
            if r.status_code == 200:
                if "Checking your browser" in r.text:
                    # cookie vencida: se re-resuelve en el hilo principal
                    return None
                return BeautifulSoup(r.text, "html.parser")
            if r.status_code in (429, 503):
                time.sleep(2 * (intento + 1))     # el sitio pide calma
        except requests.RequestException:
            time.sleep(1.0 * (intento + 1))
    return None


def fetch_many(urls: list[str], on_result: Callable[[str, BeautifulSoup], None],
               label: str = "páginas") -> int:
    """
    Baja todas las URLs en paralelo y llama on_result(url, soup) por cada una
    que llegue bien. Devuelve cuántas fallaron.
    """
    if not urls:
        return 0
    if not _shared_cookies:
        warm_up()

    fallidas = 0
    hechas = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futuros = {pool.submit(_fetch_one, u): u for u in urls}
        for fut in as_completed(futuros):
            url = futuros[fut]
            soup = fut.result()
            hechas += 1
            if soup is None:
                fallidas += 1
            else:
                on_result(url, soup)
            if hechas % 50 == 0 or hechas == len(urls):
                vel = hechas / max(time.time() - t0, 0.1)
                falta = (len(urls) - hechas) / max(vel, 0.01)
                print(f"    {hechas}/{len(urls)} {label}  "
                      f"({vel:.1f}/s, faltan ~{falta/60:.1f} min)")
    if fallidas:
        print(f"[fast] {fallidas} fallaron (se reintentan en la próxima corrida)")
    return fallidas
