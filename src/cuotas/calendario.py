"""¿Hay un evento de UFC en vivo ahora? Decide la frecuencia del polling.

Lee la MISMA caché que la portada (data/raw/ufc_oficial.json vía
src/ufc_oficial.guardado(), sin red) y usa su misma convención: un evento está
"En vivo" desde que empieza la primera parte de su cartelera (early prelims,
si no las preliminares, si no la estelar) hasta 6 h después del inicio de la
estelar. Es lo que pinta la portada con el sello EN VIVO (app.js) y el corte
que usa ufc_oficial.eventos() para pasar un evento a "recientes".
"""
from __future__ import annotations

import threading
import time

import config as C
from src.cuotas.tiempo import a_iso

VENTANA_SEG = 6 * 3600
# La caché de UFC cambia como mucho una vez por hora: no hace falta releerla
# en cada vuelta de cada hilo de polling.
_TTL_MEMO = 15.0
_memo: tuple[float, float, dict | None] | None = None
_lock = threading.Lock()


def _eventos_guardados() -> list[dict]:
    from src import ufc_oficial
    try:
        _, eventos, _ = ufc_oficial.guardado()
    except Exception:                                    # noqa: BLE001
        return []
    return list((eventos or {}).get("proximos") or [])


def _primero(inicio: dict) -> int | None:
    return inicio.get("early") or inicio.get("preliminares") or inicio.get("estelar")


def evento_en_vivo(ahora: float | None = None) -> dict | None:
    """El evento en curso o None. Con config.MERCADO_SIMULADO, uno falso."""
    if C.MERCADO_SIMULADO:
        from src.cuotas import simulado
        return simulado.evento_falso(ahora)
    return evento_real(ahora)


def evento_real(ahora: float | None = None) -> dict | None:
    """El evento de UFC en curso según la caché de UFC.com, ignorando el modo simulado."""
    global _memo
    t = time.time() if ahora is None else ahora
    with _lock:
        if ahora is None and _memo and time.monotonic() - _memo[0] < _TTL_MEMO:
            return _memo[2]
    encontrado = None
    for e in _eventos_guardados():
        inicio = e.get("inicio") or {}
        estelar, primero = inicio.get("estelar"), _primero(inicio)
        if not estelar or not primero:
            continue
        if primero <= t < estelar + VENTANA_SEG:
            encontrado = {"id": e.get("id"), "nombre": e.get("nombre"), "titular": e.get("titular"),
                          "inicio": a_iso(primero), "estelar": a_iso(estelar),
                          "fin": a_iso(estelar + VENTANA_SEG), "peleas": e.get("peleas") or [],
                          # Hora de cada parte (early / preliminares / estelar): la sección
                          # en vivo la usa para no dar "en curso" una pelea cuya parte no empezó.
                          "secciones": {k: a_iso(v) for k, v in inicio.items() if v},
                          "simulado": False}
            break
    if ahora is None:
        with _lock:
            _memo = (time.monotonic(), t, encontrado)
    return encontrado


def en_vivo() -> bool:
    """¿Las fuentes reales deben ir a su cadencia de evento? Solo con un evento REAL.

    El evento falso del modo simulado no cuenta: si contara, prender
    UFC_MERCADO_SIMULADO pondría a The Odds API cada 2 min y gastaría
    créditos reales por una pelea que no existe.
    """
    return evento_real() is not None


def olvidar() -> None:
    """Para los tests: que la próxima consulta relea la caché."""
    global _memo
    with _lock:
        _memo = None
