"""
odds.py
Utilidades de cuotas de apuestas (formato americano).

Concepto clave — probabilidad implícita SIN el margen de la casa:
  * cuota -130 => la casa "cobra" 130 para pagar 100 => p_bruta = 130/230 = 56.5%
  * cuota +102 => p_bruta = 100/202 = 49.5%
  Suman 106% (el 6% extra es la comisión). Se normaliza para que sumen 100%:
  eso es "quitar el vig" y da la opinión real del mercado.

El mercado es el mejor predictor individual que existe (agrega lesiones,
camp, inside info y el dinero de miles de apostadores). Incorporarlo como
feature no es rendirse: el modelo aprende CUÁNDO corregirlo.
"""
from __future__ import annotations

import numpy as np


def prob_bruta(cuota_us: float) -> float:
    """Cuota americana -> probabilidad implícita CON margen."""
    c = float(cuota_us)
    if c < 0:
        return -c / (-c + 100.0)
    return 100.0 / (c + 100.0)


def prob_sin_vig(cuota_a: float, cuota_b: float) -> tuple[float, float]:
    """Probabilidades implícitas del par, normalizadas para quitar el margen."""
    pa, pb = prob_bruta(cuota_a), prob_bruta(cuota_b)
    s = pa + pb
    if s <= 0:
        return 0.5, 0.5
    return pa / s, pb / s


def market_edge(cuota_a: float, cuota_b: float) -> float:
    """
    Feature ANTISIMÉTRICA del mercado: P(mercado, gana A) - 0.5.
    Si A y B se intercambian, cambia de signo (requisito del pipeline).
    NaN si falta alguna cuota.
    """
    if cuota_a is None or cuota_b is None or np.isnan(cuota_a) or np.isnan(cuota_b):
        return np.nan
    pa, _ = prob_sin_vig(cuota_a, cuota_b)
    return pa - 0.5


def pago_por_unidad(cuota_us: float) -> float:
    """Ganancia neta por 1 unidad apostada si acierta. -130 -> 0.769; +150 -> 1.5."""
    c = float(cuota_us)
    return 100.0 / -c if c < 0 else c / 100.0
