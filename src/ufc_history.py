"""Clasificación conservadora de eventos para metadatos de historial UFC.

UFCStats también muestra otras organizaciones. Esta clasificación no cambia
las métricas del modelo: solo permite afirmar cuántas peleas fueron en UFC.
Un nombre de evento que no se reconoce conserva el conteo como desconocido.
"""
from __future__ import annotations

import re


HISTORY_METADATA_VERSION = 1


def is_ufc_event(event: str) -> bool | None:
    name = " ".join(str(event or "").upper().split())
    if re.match(r"^(?:UFC|NOCHE UFC|ULTIMATE FIGHTING CHAMPIONSHIP)\b", name):
        return True
    # Las finales son combates profesionales; los episodios de TUF no bastan.
    if ((name.startswith("THE ULTIMATE FIGHTER:") or re.match(r"^TUF\s+\d+\b", name))
            and re.search(r"\bFINALE\b", name)):
        return True
    if name == "ORTIZ VS SHAMROCK 3: THE FINAL CHAPTER":
        return True
    if re.match(r"^(?:WEC|STRIKEFORCE|PRIDE|DREAM|PANCRASE|ELITE\s*XC|AFFLICTION|"
                r"ONE|KSW|BELLATOR|PFL)\b", name):
        return False
    return None


def confirmed_ufc_debut(stats: dict) -> bool:
    """Solo cero en un historial clasificado completo demuestra el debut."""
    return (stats.get("historial_ufc_confirmado") is True
            and stats.get("n_peleas_ufc") == 0)
