"""Timestamps del mercado: todos en ISO 8601, UTC, al segundo.

Todos con el mismo formato a propósito: así SQLite los compara como texto
(`timestamp >= ?`) sin convertir, y el orden lexicográfico es el cronológico.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time


def a_iso(valor) -> str | None:
    """epoch (s o ms), datetime o texto ISO (con o sin 'Z') → '2026-10-03T22:15:00+00:00'."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        dt = valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    elif isinstance(valor, (int, float)):
        v = float(valor)
        dt = datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    else:
        texto = str(valor).strip().replace("Z", "+00:00").replace(" ", "T", 1)
        dt = datetime.fromisoformat(texto)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def ahora_iso() -> str:
    return a_iso(time.time())


def a_epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()
