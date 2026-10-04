"""Cruce de nombres de cada fuente contra la base: match EXACTO, nada de fuzzy.

Por qué tanto cuidado: los dos bugs más caros del proyecto fueron cruces de
nombres (el récord de Ankalaev asignado a Temirov; los dos "Mike Davis"). Un
apellido parecido no es la misma persona.

Receta:
1. Normalizar (tildes, mayúsculas, espacios, puntuación) con
   src/fighter_names.canonical_key, que además aplica los alias YA auditados
   ("Ian Garry" → "Ian Machado Garry", "Cong Wang" → "Wang Cong", ...).
2. Si la fuente escribe un nombre de una forma que ninguna otra usa, se agrega
   a ALIAS_MANUAL a mano, con evidencia. Nunca por similitud.
3. Buscar la clave exacta en las fichas de UFCStats (ufcstats_bio.csv vía
   src/storage). Una sola ficha → calza con su id.
4. Dos o más fichas con el mismo nombre (homónimos: "Mike Davis", "Jean Silva",
   "Bruno Silva"...) → desempate explícito por DESEMPATE_MANUAL (nombre + rival
   exactos → id). Sin desempate, el nombre sirve para la pelea (el `pelea_id`
   es por nombre y ambos se llaman igual) pero el `id` queda en null y se
   registra: mejor sin ficha que con la ficha de otro.
   Por qué no se desempata por el historial de peleas: ufcstats_fights.csv
   guarda solo nombres, no ids, así que no distingue a dos homónimos.
5. Lo que no calza se registra en `cuotas_no_calzados` (fuente, texto, fecha).
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import threading
import time

import config as C
from src import storage as DB
from src.fighter_names import canonical_key, normalize_name

BIO = C.DATA_PROCESSED / "ufcstats_bio.csv"

# texto normalizado de la fuente → nombre exacto de la ficha en la base.
# Solo variantes verificadas a mano (misma pelea, mismo rival, misma fecha).
ALIAS_MANUAL: dict[str, str] = {
    # BFO y algunas casas indexan a Garry por el apellido compuesto solo.
    normalize_name("Machado Garry"): "Ian Machado Garry",
    # BFO, 3-oct-2026: "Darya Zheleznyakova" vs Alice Pereira (UFC 10-oct-2026).
    # Polymarket y la ficha UFCStats 07047eb7d17fb0a2 la escriben
    # "Daria Zhelezniakova": misma pelea, mismo rival, misma fecha.
    normalize_name("Darya Zheleznyakova"): "Daria Zhelezniakova",
}

# (clave del nombre, clave del rival) → id de la ficha UFCStats (16 hex).
# Para homónimos que pelean en una cartelera con cuotas: se completa a mano
# mirando la ficha oficial. Vacío a propósito hasta que haga falta.
DESEMPATE_MANUAL: dict[tuple[str, str], str] = {}

_lock = threading.Lock()
_indice: dict[str, list[tuple[str, str]]] | None = None
_firma: tuple | None = None
_comprobado = 0.0


@dataclass(frozen=True)
class Resultado:
    clave: str             # lo que entra al pelea_id
    nombre: str | None     # nombre exacto de la base, o None si no calzó
    id: str | None         # ficha UFCStats o None (no calzó u homónimo sin desempate)
    motivo: str | None     # None | "no_calza" | "homonimo"

    @property
    def en_base(self) -> bool:
        return self.nombre is not None


def _cargar_indice() -> dict[str, list[tuple[str, str]]]:
    """clave canónica → [(nombre, id)]. Se recarga solo si cambia la base."""
    global _indice, _firma, _comprobado
    with _lock:
        ahora = time.monotonic()
        if _indice is not None and _firma and _firma[0] == str(DB.db_path()) and ahora - _comprobado < 5:
            return _indice
        _comprobado = ahora
        firma = (str(DB.db_path()), DB.signature(BIO))
        if firma == _firma and _indice is not None:
            return _indice
        indice: dict[str, list[tuple[str, str]]] = {}
        try:
            bio = DB.read_csv(BIO, usecols=["fighter_url", "name"]) if DB.exists(BIO) else None
        except (OSError, ValueError, KeyError):
            bio = None
        if bio is not None:
            for url, nombre in zip(bio["fighter_url"], bio["name"]):
                m = re.fullmatch(r"https?://ufcstats\.com/fighter-details/([a-f0-9]{16})", str(url))
                if not m or not isinstance(nombre, str) or not nombre.strip():
                    continue
                indice.setdefault(canonical_key(nombre), []).append((nombre, m[1]))
        _indice, _firma = indice, firma
        return indice


def invalidar() -> None:
    global _indice, _firma
    with _lock:
        _indice, _firma = None, None


def clave(texto: str) -> str:
    """La clave con la que un texto entra a un pelea_id (alias manual incluido)."""
    n = normalize_name(texto)
    return canonical_key(ALIAS_MANUAL.get(n, texto))


def resolver(texto: str, rival: str | None = None) -> Resultado:
    k = clave(texto)
    candidatos = _cargar_indice().get(k, [])
    if not candidatos:
        return Resultado(k, None, None, "no_calza")
    if len(candidatos) == 1:
        nombre, fid = candidatos[0]
        return Resultado(k, nombre, fid, None)
    fid = DESEMPATE_MANUAL.get((k, clave(rival))) if rival else None
    if fid and any(fid == c[1] for c in candidatos):
        nombre = next(n for n, i in candidatos if i == fid)
        return Resultado(k, nombre, fid, None)
    # Homónimo sin desempate: mismo nombre, así que la pelea se arma igual,
    # pero no se elige una ficha al azar.
    return Resultado(k, candidatos[0][0], None, "homonimo")


def pelea_id(a: str, b: str) -> str:
    """Contrato 2.2: las dos claves normalizadas, ordenadas, unidas con '|'."""
    return "|".join(sorted((clave(a), clave(b))))
