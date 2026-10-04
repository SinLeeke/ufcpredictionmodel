"""Conversión entre formatos de cuota y armado de la Cotización del contrato.

Todo lo que sale hacia la UI va en formato americano (docs/contrato-datos.md,
sección 2). El decimal y la probabilidad implícita viajan como apoyo, y se
calculan SIEMPRE desde la americana para que los tres números cuenten lo mismo.
"""
from __future__ import annotations

import math

# Una casa nunca publica una línea mejor que ±100: entre −100 y +100 no existe
# cuota americana. Lo que caiga ahí es un dato mal parseado.
_MIN_ABS = 100


class CuotaInvalida(ValueError):
    """La cotización no pasa los controles y no entra al historial."""


def prob_a_americana(p: float) -> int:
    """0,65 → −186; 0,35 → +186. p ≥ 0,5 da favorito (negativa), p < 0,5 underdog.

    Se redondea al entero porque así publican las casas: un −185,71 no lo ve nadie.
    """
    p = float(p)
    if not (0.0 < p < 1.0) or not math.isfinite(p):
        raise CuotaInvalida(f"probabilidad fuera de (0, 1): {p!r}")
    if p >= 0.5:
        return int(round(-(p / (1 - p)) * 100))
    return int(round(((1 - p) / p) * 100))


def americana_a_decimal(americana: float) -> float:
    a = float(americana)
    if not math.isfinite(a) or abs(a) < _MIN_ABS:
        raise CuotaInvalida(f"cuota americana imposible: {americana!r}")
    return 1 + a / 100 if a > 0 else 1 + 100 / abs(a)


def decimal_a_americana(decimal: float) -> int:
    """1,667 → −150; 2,25 → +125. Betano y BFO (vía cuotas_fuentes) dan decimal."""
    d = float(decimal)
    if not math.isfinite(d) or d <= 1.0:
        raise CuotaInvalida(f"cuota decimal imposible: {decimal!r}")
    if d >= 2.0:
        return int(round((d - 1) * 100))
    return int(round(-100 / (d - 1)))


def prob_implicita(americana: float) -> float:
    return 1 / americana_a_decimal(americana)


def _lado(americana: int) -> dict:
    d = americana_a_decimal(americana)
    return {"americana": int(americana), "decimal": round(d, 3), "prob_implicita": round(1 / d, 4)}


def cotizacion(fuente: str, tipo: str, casa: str, pelea_id: str, timestamp: str,
               a_americana: int | None = None, b_americana: int | None = None,
               a_prob: float | None = None, b_prob: float | None = None) -> dict:
    """Cotización 2.2 del contrato, validada. Lanza CuotaInvalida si no entra.

    Casa: se pasan americanas y la suma de probabilidades implícitas tiene que
    ser > 1 (el margen). Si suma menos, el dato está corrupto: pasó con las
    cuotas de 2025, que daban +63% de ROI falso en el backtest de método.

    Mercado de predicción (Polymarket): se pasan probabilidades, que SON el
    precio. No hay margen que exigir, pero los dos precios de un mercado binario
    tienen que sumar ≈ 1; si no, los tokens están cruzados con otra pelea.
    """
    if tipo == "mercado_prediccion":
        if a_prob is None or b_prob is None:
            raise CuotaInvalida("faltan las probabilidades del mercado")
        pa, pb = float(a_prob), float(b_prob)
        if not (0 < pa < 1 and 0 < pb < 1):
            raise CuotaInvalida("precio fuera de (0, 1)")
        if abs(pa + pb - 1) > 0.10:
            raise CuotaInvalida(f"los dos precios suman {pa + pb:.3f}, no ≈ 1")
        a = {"americana": prob_a_americana(pa), "decimal": round(1 / pa, 3), "prob_implicita": round(pa, 4)}
        b = {"americana": prob_a_americana(pb), "decimal": round(1 / pb, 3), "prob_implicita": round(pb, 4)}
        suma = pa + pb
    else:
        if a_americana is None or b_americana is None:
            raise CuotaInvalida("faltan las cuotas americanas")
        a, b = _lado(int(a_americana)), _lado(int(b_americana))
        suma = 1 / americana_a_decimal(a["americana"]) + 1 / americana_a_decimal(b["americana"])
        if suma <= 1.0:
            raise CuotaInvalida(f"probabilidades implícitas suman {suma:.4f} ≤ 1: dato corrupto")
        pa, pb = 1 / americana_a_decimal(a["americana"]), 1 / americana_a_decimal(b["americana"])
    return {
        "fuente": fuente, "tipo": tipo, "casa": casa, "pelea_id": pelea_id,
        "timestamp": timestamp, "a": a, "b": b,
        "margen": round(suma - 1, 4),
        "prob_sin_margen": {"a": round(pa / suma, 4), "b": round(pb / suma, 4)},
    }
