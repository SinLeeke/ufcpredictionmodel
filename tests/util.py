"""Ayudas compartidas por las pruebas: peleadores sintéticos y un card.py aislado."""
from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path
from unittest import mock

import config as C


def peleador(nombre: str, **cambios) -> dict:
    """Ficha sintética con todas las claves que usa el pipeline de predicción."""
    base = {
        "name": nombre, "age": 30.0, "reach_cm": 185.0, "height_cm": 180.0,
        "stance": "Orthodox", "streak": 1, "days_since_last_fight": 120.0,
        "slpm": 4.0, "str_acc": 0.45, "sapm": 3.5, "str_def": 0.55,
        "td_avg": 1.2, "td_acc": 0.40, "td_def": 0.65, "sub_avg": 0.5,
        "win_ko_rate": 0.35, "win_sub_rate": 0.15, "win_dec_rate": 0.50,
        "lost_by_finish_rate": 0.40, "wins": 10, "losses": 3,
        "n_peleas_hist": 8, "ctrl_per_min": 0.14, "opp_ctrl_per_min": 0.14,
        "ground_share": 0.16, "kd_per15": 0.35,
    }
    base.update(cambios)
    return base


@contextlib.contextmanager
def card_aislado(flag_wikipedia: int = 0):
    """
    card.predict_card sin datos, sin modelos y sin red: fichas sintéticas,
    heurístico en vez de XGBoost y salidas a una carpeta temporal.

    Devuelve un dict donde se van anotando las consultas a Wikipedia, para
    poder verificar cuándo el CSV manda y cuándo se cae al caché.
    """
    from src import card
    consultas: list[str] = []

    def flag(nombre, fecha, dias=0):
        consultas.append(nombre)
        return flag_wikipedia

    oposicion_neutra = {c: 0.0 for c in ("opp_elo_diff", "opp_elo_max_diff", "ko_infl_diff",
                                         "sub_infl_diff", "ko_recibido_diff", "momentum_diff")}
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(C, "OUTPUTS", Path(tmp)), \
            mock.patch.object(card, "get_stats", lambda n: (peleador(n), "ufcstats")), \
            mock.patch.object(card, "_load_models", lambda: (None, None)), \
            mock.patch.object(card, "_elo", lambda s: C.ELO_BASE), \
            mock.patch.object(card.oposicion, "features", lambda a, b, f: dict(oposicion_neutra)), \
            mock.patch.object(card.oposicion, "resumen", lambda *a, **k: {"n": 0}), \
            mock.patch.object(card.reemplazos, "flag", flag):
        yield {"card": card, "tmp": Path(tmp), "consultas_wiki": consultas}


def predecir(card, csv: Path, **kw):
    """predict_card callado: devuelve el dict completo."""
    with contextlib.redirect_stdout(io.StringIO()):
        return card.predict_card(csv, reports=False, devolver_todo=True, **kw)
