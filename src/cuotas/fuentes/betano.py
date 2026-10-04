"""Betano: fuente PASIVA. La capa nunca le pide nada a Betano.

El ciclo de webui/engine.py ya baja la cartelera activa (refrescar cada 10 min,
refrescar_linea cada 10 s en EN VIVO) con UNA petición por ciclo. Pedirle a
Betano por otro lado duplicaría el tráfico y rompería esa regla (CLAUDE.md:
"no lo cambies por una petición por pelea"). Así que engine le entrega acá lo
que ya bajó y esta fuente solo lo traduce a CotizacionCruda.
"""
from __future__ import annotations

import math

from src.cuotas.conversion import CuotaInvalida, decimal_a_americana
from src.cuotas.fuentes.base import Fuente
from src.cuotas.tiempo import ahora_iso


class Betano(Fuente):
    clave = "betano"
    nombre = "Betano"
    tipo = "casa"
    pasiva = True

    def intervalo(self, en_vivo: bool) -> int | None:
        return None

    def motivo_inactiva(self) -> str | None:
        return None

    def estado(self, en_vivo: bool = False) -> dict:
        d = super().estado(en_vivo)
        if d["ultimo_ok"] is None and d["motivo"] is None:
            d["motivo"] = "Sin datos todavía: llegan al cargar o refrescar una cartelera de Betano"
        return d

    def traducir(self, cuotas, evento: str | None = None, fecha: str | None = None) -> list[dict]:
        """[(a, b, cuota_a_decimal, cuota_b_decimal), ...] → CotizacionCruda.

        Es la forma de betano_scraper.cuotas_rapidas() y de las filas del CSV
        de scrape_card: no se agrega ninguna petición ni se reinterpreta nada.
        """
        ts = ahora_iso()
        crudas = []
        self.rechazadas = 0                  # cuenta la última entrega, como ejecutar()
        for a, b, ca, cb in cuotas:
            try:
                if not isinstance(a, str) or not isinstance(b, str):
                    continue
                if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (ca, cb)):
                    continue
                crudas.append({"fuente": self.clave, "casa": "Betano", "evento": evento, "fecha": fecha,
                               "a_texto": a, "b_texto": b,
                               "a_americana": decimal_a_americana(ca),
                               "b_americana": decimal_a_americana(cb), "timestamp": ts})
            except CuotaInvalida:
                self.rechazadas += 1
        return crudas

    def obtener(self) -> list[dict]:
        # Pasiva: nada que pedir. La capa ingiere en el momento de la entrega.
        return []
