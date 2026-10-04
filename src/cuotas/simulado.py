"""Modo simulado del mercado en vivo (UFC_MERCADO_SIMULADO=1 → config.MERCADO_SIMULADO).

Sirve para probar la sección "Mercado en vivo" de Inicio sin esperar a un
sábado de UFC: un evento falso "en curso", cuatro peleas con peleadores reales
de la base (para que fotos, banderas y el cruce de nombres funcionen igual que
con una cartelera de verdad) y cuotas INVENTADAS que caminan al azar cada 10 s.

Por qué todo vive en memoria y nada pasa por SQLite
---------------------------------------------------
La primera versión entregaba sus cuotas a la capa como una fuente más. Como
usa nombres reales, su `pelea_id` era el mismo que el de esas parejas en el
mercado real: en modo simulado el consenso y el historial de "Pereira vs
Ankalaev" mezclaban cuotas inventadas con las de BFO o Polymarket, y la tabla
`cuotas_peleas` quedaba con el evento y la hora del evento falso aunque
después se apagara el modo. Ahora la fuente `simulada` sigue registrada (para
que /api/mercado/estado la muestre), pero su `obtener()` no entrega nada a la
capa: las series se generan acá, en memoria, y solo las lee webui/vivo.py.
Resultado: lo simulado nunca toca el historial, el consenso ni las peleas
reales, y apagado no deja rastro porque nunca escribió nada.

Cómo se simula
--------------
- Las series se derivan del reloj, no de un hilo: cada lectura extiende la
  caminata hasta el tick actual (10 s). Así funciona igual con o sin el hilo
  de polling de la capa, y en los tests basta con pasar `ahora`.
- Las casas mueven su línea de a saltos (no en cada tick) y redondeada a
  múltiplos de 5, como publica una casa; el "Polymarket simulado" se mueve
  más seguido y sin margen, como un mercado de predicción.
- La pelea "en curso" se mueve más (las cuotas en vivo saltan con cada
  asalto); el estado de cada pelea sale de un ciclo de 20 min por pelea, que
  se reinicia cuando termina la estelar para que la prueba no se acabe.
"""
from __future__ import annotations

import random
import threading
import time
import zlib

from src.cuotas.conversion import CuotaInvalida, cotizacion, prob_a_americana
from src.cuotas.fuentes.base import Fuente
from src.cuotas.tiempo import a_iso

# En el orden de UFC.com: la estelar primero. Se pelean al revés.
# (nombre A, nombre B, probabilidad inicial de A)
PELEAS = (
    ("Alex Pereira", "Magomed Ankalaev", 0.55),
    ("Islam Makhachev", "Arman Tsarukyan", 0.70),
    ("Merab Dvalishvili", "Umar Nurmagomedov", 0.45),
    ("Ilia Topuria", "Charles Oliveira", 0.78),
)
NOMBRE_EVENTO = "Evento simulado"
TICK = 10                                 # segundos entre pasos de la caminata
SLOT = 20 * 60                            # lo que "dura" cada pelea en el ciclo
CICLO = SLOT * len(PELEAS)
HISTORIA = 40 * 60                        # el gráfico parte con 40 min de datos
_INICIO = time.time() - 45 * 60           # "empezó hace 45 min" al importar el módulo

# Las series: (fuente, casa, tipo, cada cuántos ticks puede moverse, margen).
# Los nombres dicen "sim." a propósito: aunque la sección ya grita DATOS
# SIMULADOS, una captura recortada no debe poder pasar por cuotas reales.
SERIES = (
    ("simulada", "Casa sim. A", "casa", 3, 0.045),
    ("simulada", "Casa sim. B", "casa", 4, 0.060),
    ("simulada", "Casa sim. C", "casa", 5, 0.038),
    ("simulada", "Polymarket sim.", "mercado_prediccion", 1, 0.0),
)

_lock = threading.Lock()
_estado: dict | None = None


def _clave(nombre: str) -> str:
    from src.cuotas import cruce
    return cruce.clave(nombre)


def pelea_id(a: str, b: str) -> str:
    return "|".join(sorted((_clave(a), _clave(b))))


def orden_pelea() -> list[tuple[str, str, float]]:
    """Las peleas en el orden en que se pelean (la estelar al final)."""
    return list(reversed(PELEAS))


def evento_falso(ahora: float | None = None) -> dict:
    """Misma forma que calendario.evento_en_vivo(), con simulado=True."""
    inicio = a_iso(_INICIO)
    return {"id": "simulado", "nombre": NOMBRE_EVENTO, "titular": f"{PELEAS[0][0]} vs {PELEAS[0][1]}",
            "inicio": inicio, "estelar": inicio,
            "fin": a_iso(_INICIO + 6 * 3600),
            # Todas en la estelar: el estado lo deciden las señales de cierre.
            "secciones": {"estelar": inicio},
            "peleas": [{"a": a, "b": b, "seccion": "estelar", "titulo": i == 0,
                        "peso": "Simulada"} for i, (a, b, _) in enumerate(PELEAS)],
            "simulado": True}


def cerradas(ahora: float | None = None) -> set[str]:
    """pelea_id de las peleas que "terminaron" en el ciclo actual.

    Hace el papel de la señal real más fiable que hay en vivo (Polymarket
    cierra el mercado de una pelea cuando se resuelve): vivo.py la trata igual.
    """
    t = time.time() if ahora is None else ahora
    dentro = (t - _INICIO) % CICLO
    hechas = int(dentro // SLOT)
    return {pelea_id(a, b) for a, b, _ in orden_pelea()[:hechas]}


def _en_curso(t: float) -> str:
    a, b, _ = orden_pelea()[int(((t - _INICIO) % CICLO) // SLOT)]
    return pelea_id(a, b)


def _am_casa(p: float, margen: float) -> tuple[int, int]:
    """Probabilidad "verdadera" → par de americanas con margen, en pasos de 5."""
    def redondo(x: int) -> int:
        r = int(round(x / 5.0) * 5)
        return r if abs(r) >= 100 else (100 if r >= 0 else -100)
    qa, qb = p * (1 + margen), (1 - p) * (1 + margen)
    qa, qb = min(max(qa, 0.03), 0.97), min(max(qb, 0.03), 0.97)
    return redondo(prob_a_americana(qa)), redondo(prob_a_americana(qb))


def _punto(tipo: str, margen: float, p: float, ts: str) -> dict | None:
    """Un punto con la forma del historial (t, a, b, pa, pb), validado como una cotización."""
    try:
        if tipo == "mercado_prediccion":
            p = round(p, 3)
            c = cotizacion("simulada", tipo, "x", "x", ts, a_prob=p, b_prob=round(1 - p, 3))
        else:
            am_a, am_b = _am_casa(p, margen)
            c = cotizacion("simulada", tipo, "x", "x", ts, a_americana=am_a, b_americana=am_b)
    except CuotaInvalida:
        return None
    return {"t": ts, "a": c["a"]["americana"], "b": c["b"]["americana"],
            "pa": c["prob_sin_margen"]["a"], "pb": c["prob_sin_margen"]["b"],
            "_cot": c}


def _nuevo_estado() -> dict:
    est = {"tick": None, "peleas": {}}
    for a, b, p0 in PELEAS:
        pid = pelea_id(a, b)
        # El pelea_id ordena por clave: si A no es la menor, la serie se guarda
        # ya orientada al pelea_id (a = clave menor), como hace la capa real.
        invertida = _clave(a) > _clave(b)
        semilla = zlib.crc32(pid.encode())
        est["peleas"][pid] = {
            "a": b if invertida else a, "b": a if invertida else b,
            "p": 1 - p0 if invertida else p0,
            "rng": random.Random(semilla),
            "series": [{"fuente": f, "casa": c, "tipo": t, "cada": cada, "margen": m,
                        "ruido": random.Random(semilla + i + 1), "sesgo": 0.0, "puntos": []}
                       for i, (f, c, t, cada, m) in enumerate(SERIES)],
        }
    return est


def _avanzar(ahora: float) -> dict:
    """Extiende todas las caminatas hasta el tick de `ahora`. Llamar con _lock."""
    global _estado
    if _estado is None:
        _estado = _nuevo_estado()
    fin = int(ahora // TICK)
    tick = _estado["tick"]
    if tick is None:
        tick = int((_INICIO - HISTORIA) // TICK) - 1
    # Un servidor que quedó horas prendido no recalcula días de caminata:
    # como mucho la historia visible.
    tick = max(tick, fin - int((HISTORIA + 6 * 3600) // TICK))
    while tick < fin:
        tick += 1
        t = tick * TICK
        ts = a_iso(t)
        vivo = _en_curso(t) if t >= _INICIO else None
        for pid, pe in _estado["peleas"].items():
            # La pelea en curso salta más: las cuotas en vivo reaccionan a cada asalto.
            vol = 0.012 if pid == vivo else 0.0035
            pe["p"] = min(max(pe["p"] + pe["rng"].gauss(0, vol), 0.06), 0.94)
            for s in pe["series"]:
                if tick % s["cada"]:
                    continue
                # Cada casa tiene su propia opinión, que deriva lento: así las
                # líneas no son copias desplazadas unas de otras.
                s["sesgo"] = min(max(s["sesgo"] + s["ruido"].gauss(0, 0.004), -0.03), 0.03)
                pt = _punto(s["tipo"], s["margen"], min(max(pe["p"] + s["sesgo"], 0.04), 0.96), ts)
                if pt is None:
                    continue
                previo = s["puntos"][-1] if s["puntos"] else None
                if previo and (previo["a"], previo["b"], previo["pa"]) == (pt["a"], pt["b"], pt["pa"]):
                    continue                     # igual que el historial real: solo los cambios
                s["puntos"].append(pt)
                # Memoria acotada: lo que no cabe en la historia visible se va.
                if len(s["puntos"]) > 4000:
                    del s["puntos"][:1000]
    _estado["tick"] = fin
    return _estado


def datos(ahora: float | None = None) -> dict[str, dict]:
    """{pelea_id: {"a", "b", "cotizaciones", "series"}} orientado al pelea_id.

    `cotizaciones`: la última de cada serie, con la forma 2.2 del contrato
    (pelea_id real, fuente "simulada") y `visto` = ahora, como si la fuente
    acabara de confirmarla. `series`: puntos {t, a, b, pa, pb}, como
    /api/mercado/historial.
    """
    t = time.time() if ahora is None else ahora
    visto = a_iso(t)
    with _lock:
        est = _avanzar(t)
        salida = {}
        for pid, pe in est["peleas"].items():
            cots, series = [], []
            for s in pe["series"]:
                pts = s["puntos"]
                if not pts:
                    continue
                c = dict(pts[-1]["_cot"])
                c.update({"casa": s["casa"], "pelea_id": pid, "visto": visto})
                cots.append(c)
                series.append({"fuente": s["fuente"], "casa": s["casa"], "tipo": s["tipo"],
                               "puntos": [{k: p[k] for k in ("t", "a", "b", "pa", "pb")} for p in pts]})
            salida[pid] = {"a": pe["a"], "b": pe["b"], "cotizaciones": cots, "series": series}
        return salida


def olvidar() -> None:
    """Para los tests: que la próxima lectura vuelva a generar todo desde cero."""
    global _estado
    with _lock:
        _estado = None


class FuenteSimulada(Fuente):
    """La fuente `simulada` del registro: visible en /api/mercado/estado, muda para la capa.

    obtener() solo empuja la caminata (si el hilo de la capa corre, las series
    avanzan aunque nadie mire) y devuelve [] a propósito: lo simulado no entra
    al historial real. Ver el docstring del módulo.
    """
    clave = "simulada"
    nombre = "Simulada"
    tipo = "casa"

    def intervalo(self, en_vivo: bool) -> int:
        return TICK

    def obtener(self) -> list[dict]:
        with _lock:
            _avanzar(time.time())
        return []
