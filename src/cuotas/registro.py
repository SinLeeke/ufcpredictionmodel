"""Registro de fuentes: el ÚNICO lugar donde se dice qué fuentes existen.

Agregar una fuente = escribir una subclase de fuentes.base.Fuente (clave,
nombre, tipo, intervalo(), obtener()) y sumarla a esta lista. Quitarla =
borrarla de acá. Ni la UI ni los endpoints cambian: /api/mercado/* lista lo
que haya en el registro.
"""
from __future__ import annotations

import config as C


def fuentes() -> list:
    from src.cuotas.fuentes.betano import Betano
    from src.cuotas.fuentes.bfo import BFO
    from src.cuotas.fuentes.odds_api import OddsAPI
    from src.cuotas.fuentes.polymarket import Polymarket
    lista = [Betano(), BFO(), OddsAPI(), Polymarket()]
    if C.MERCADO_SIMULADO:
        from src.cuotas.simulado import FuenteSimulada
        lista.append(FuenteSimulada())
    return lista
