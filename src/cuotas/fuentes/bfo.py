"""BestFightOdds: envuelve src/cuotas_fuentes.consultar('bfo') tal como funciona hoy.

Misma petición (la portada de BFO, todas las carteleras de una vez), mismo
User-Agent y mismo TTL de 30 min: consultar() ya decide si pide o si devuelve
la captura guardada, así que la capa no agrega tráfico. Cada captura queda
además en `cuotas_snapshots`, como antes.
"""
from __future__ import annotations

from datetime import date
import re

from src.cuotas.conversion import CuotaInvalida, decimal_a_americana
from src.cuotas.fuentes.base import Fuente, FuenteError
from src.cuotas.tiempo import a_iso

_MESES = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


def fecha_bfo(texto: str, hoy: date | None = None) -> str | None:
    """'October 4th' → '2026-10-04'. BFO no publica el año: se elige el más
    cercano a hoy (una cartelera de enero vista en diciembre es del año que viene)."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*", str(texto or ""))
    if not m or m[1].lower() not in _MESES:
        return None
    hoy = hoy or date.today()
    candidatas = []
    for anio in (hoy.year - 1, hoy.year, hoy.year + 1):
        try:
            candidatas.append(date(anio, _MESES[m[1].lower()], int(m[2])))
        except ValueError:
            pass
    if not candidatas:
        return None
    return min(candidatas, key=lambda d: abs((d - hoy).days)).isoformat()


def evento_bfo(titulo: str) -> str:
    """'UFC 332 Odds' → 'UFC 332'."""
    return re.sub(r"\s+odds\s*$", "", str(titulo or ""), flags=re.I).strip() or None


class BFO(Fuente):
    clave = "bfo"
    nombre = "BestFightOdds"
    tipo = "casa"

    def intervalo(self, en_vivo: bool) -> int:
        # El TTL de cuotas_fuentes manda; en vivo NO se acelera (decisión del dueño).
        from src import cuotas_fuentes
        return int(cuotas_fuentes.TTL)

    def obtener(self) -> list[dict]:
        from src import cuotas_fuentes
        try:
            d = cuotas_fuentes.consultar("bfo")
        except ValueError as e:
            # Sus mensajes ya son seguros ("No pude consultar la fuente...").
            raise FuenteError(str(e)) from None
        crudas = self.traducir(d.get("eventos") or [], d.get("capturado"))
        if d.get("desactualizado"):
            # Devolvió la captura anterior porque BFO no respondió: las cuotas
            # sirven, pero el estado tiene que decirlo.
            self._crudas_viejas = crudas
            raise FuenteError("BestFightOdds no respondió; se usa la última captura guardada")
        return crudas

    def ejecutar(self):
        self._crudas_viejas = None
        crudas = super().ejecutar()
        if crudas is None and self._crudas_viejas:
            return self._crudas_viejas
        return crudas

    def traducir(self, eventos: list[dict], capturado: str | None) -> list[dict]:
        ts = a_iso(capturado) if capturado else None
        crudas = []
        for e in eventos:
            evento, fecha = evento_bfo(e.get("titulo")), fecha_bfo(e.get("fecha"))
            for p in e.get("peleas") or []:
                for casa in (p.get("casas") or {}).values():
                    try:
                        # parsear_bfo guarda decimal calculado desde la americana
                        # original: la vuelta es exacta al redondear.
                        am_a, am_b = decimal_a_americana(casa["a"]), decimal_a_americana(casa["b"])
                    except (CuotaInvalida, KeyError, TypeError):
                        self.rechazadas += 1
                        continue
                    crudas.append({"fuente": self.clave, "casa": casa.get("casa") or "BFO",
                                   "evento": evento, "fecha": fecha,
                                   "a_texto": p["a"], "b_texto": p["b"],
                                   "a_americana": am_a, "b_americana": am_b, "timestamp": ts})
        return crudas
