"""Consenso de mercado, etiquetas y mejor cuota de una pelea (contrato 2.3).

El consenso es el promedio de las probabilidades SIN margen, una cotización por
casa. Sin quitar el margen, una casa con 8% de vig pesaría como si el favorito
fuera más favorito de lo que el mercado cree; y si la misma casa llega por dos
fuentes (DraftKings vía BFO y vía The Odds API) contaría doble.
"""
from __future__ import annotations

import re

from src.cuotas.conversion import prob_a_americana

# Una pelea "pareja" es la que las casas pagan casi igual de los dos lados:
# ambas cuotas entre −115 y +115 (≈ 53,5% / 46,5% como mucho).
PAREJA_MAX = 115


def _casa_clave(casa: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(casa).lower())


def etiquetas(am_a: int, am_b: int, prob_a: float, prob_b: float) -> tuple[str, str, bool]:
    if abs(am_a) <= PAREJA_MAX and abs(am_b) <= PAREJA_MAX:
        return "Pareja", "Pareja", True
    if prob_a >= prob_b:
        return "Favorito", "Underdog", False
    return "Underdog", "Favorito", False


def consenso(cotizaciones: list[dict]) -> dict | None:
    """None si no hay ninguna cotización (la UI no inventa un 50/50)."""
    por_casa: dict[str, dict] = {}
    for c in cotizaciones:
        k = _casa_clave(c["casa"])
        # Una por casa: la más reciente manda.
        if k not in por_casa or c["timestamp"] > por_casa[k]["timestamp"]:
            por_casa[k] = c
    if not por_casa:
        return None
    pa = sum(c["prob_sin_margen"]["a"] for c in por_casa.values()) / len(por_casa)
    # Se renormaliza por si el redondeo a 4 decimales de cada cotización deja
    # una suma de 0,9999: a y b tienen que ser complementarias.
    pa = min(max(pa, 1e-4), 1 - 1e-4)
    pb = 1 - pa
    am_a, am_b = prob_a_americana(pa), prob_a_americana(pb)
    et_a, et_b, pareja = etiquetas(am_a, am_b, pa, pb)
    return {"a": {"prob": round(pa, 4), "americana": am_a, "etiqueta": et_a},
            "b": {"prob": round(pb, 4), "americana": am_b, "etiqueta": et_b},
            "pareja": pareja, "n_cotizaciones": len(por_casa)}


def mejor(cotizaciones: list[dict]) -> dict | None:
    """La cuota que más paga por peleador, solo entre casas.

    Polymarket queda fuera: su precio es el punto medio del libro, no un precio
    al que de verdad se pueda comprar, y "pagaría más" por construcción.
    """
    casas = [c for c in cotizaciones if c["tipo"] == "casa"]
    if not casas:
        return None
    salida = {}
    for lado in ("a", "b"):
        top = max(casas, key=lambda c: (c[lado]["decimal"], c["timestamp"]))
        salida[lado] = {"fuente": top["fuente"], "casa": top["casa"], "americana": top[lado]["americana"]}
    return salida


def invertir(pelea: dict) -> dict:
    """La misma pelea con las esquinas al revés (para orientar a la cartelera)."""
    def lado(c, x):
        return {**c, "a": c["b"], "b": c["a"]} if x else c
    cots = []
    for c in pelea.get("cotizaciones", []):
        c = dict(c)
        c["a"], c["b"] = c["b"], c["a"]
        c["prob_sin_margen"] = {"a": c["prob_sin_margen"]["b"], "b": c["prob_sin_margen"]["a"]}
        cots.append(c)
    out = {**pelea, "a": pelea["b"], "b": pelea["a"], "cotizaciones": cots,
           "a_id": pelea.get("b_id"), "b_id": pelea.get("a_id")}
    if pelea.get("consenso"):
        out["consenso"] = lado(pelea["consenso"], True)
    if pelea.get("mejor"):
        out["mejor"] = lado(pelea["mejor"], True)
    return out
