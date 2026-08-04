"""
simulate.py
FASE 4a — Simulación Monte Carlo.

Nota honesta de diseño (importante):
  Si XGBoost ya te da p = P(gana A), lanzar 10.000 Bernoulli(p) y promediar
  simplemente recupera p. Eso no aporta nada. Para que la simulación SÍ tenga
  valor, hacemos dos cosas:

    1) PROPAGAMOS INCERTIDUMBRE sobre la propia p. En cada simulación muestreamos
       p_i ~ Beta(alpha, beta) centrada en p, con una "concentración" que
       representa cuánta confianza tiene el modelo (equivalente a un tamaño de
       muestra efectivo). Así obtenemos un INTERVALO CREÍBLE de la probabilidad,
       no un número puntual frágil.

    2) MUESTREAMOS EL MÉTODO. Dado un ganador en cada simulación, sorteamos el
       método (KO/TKO, Sub, Decisión) desde las probabilidades del method_model.
       Al agregar 10.000 corridas obtenemos la distribución estable de cómo
       termina la pelea y la probabilidad de que termine antes del límite.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import sys
sys.path.append(str(__import__("pathlib").Path(__file__).resolve().parent.parent))
import config as C


@dataclass
class SimulationResult:
    p_a: float                     # prob. media de que gane A
    p_b: float
    ci_a: tuple[float, float]      # intervalo creíble 95% para p_a
    method_dist: dict[str, float]  # {'KO/TKO': .., 'Submission': .., 'Decision': ..}
    p_finish: float                # prob. de que la pelea NO llegue a tarjetas
    p_decision: float
    winner: str
    fighter_a: str
    fighter_b: str


def _beta_params(p: float, concentration: float) -> tuple[float, float]:
    """
    Convierte una media p y una 'concentración' (tamaño de muestra efectivo)
    en los parámetros (alpha, beta) de una Beta. Mayor concentración = menos
    incertidumbre = intervalo más angosto.
    """
    p = min(max(p, 1e-4), 1 - 1e-4)
    alpha = p * concentration
    beta = (1 - p) * concentration
    return alpha, beta


def monte_carlo(
    p_a: float,
    method_probs: dict[str, float],
    fighter_a: str,
    fighter_b: str,
    n: int = C.N_SIMULATIONS,
    concentration: float = 40.0,
    seed: int = C.RANDOM_STATE,
) -> SimulationResult:
    """
    Ejecuta n simulaciones del combate.

    p_a          : probabilidad puntual de que gane A (salida del winner_model).
    method_probs : dict de probabilidades de método (salida del method_model),
                   interpretado como la distribución de método del GANADOR.
    concentration: confianza del modelo. ~15 = mucha incertidumbre,
                   ~80 = alta confianza. Puedes calibrarlo con el Brier score
                   del test (peor Brier -> menor concentración).
    """
    rng = np.random.default_rng(seed)

    # 1) Incertidumbre sobre p: una p distinta por simulación
    alpha, beta = _beta_params(p_a, concentration)
    p_samples = rng.beta(alpha, beta, size=n)

    # 2) Ganador por simulación
    a_wins = rng.random(n) < p_samples          # True si gana A

    # 3) Método por simulación (sorteo multinomial desde method_probs)
    methods = list(method_probs.keys())
    probs = np.array([method_probs[m] for m in methods], dtype=float)
    probs = probs / probs.sum()
    method_draws = rng.choice(len(methods), size=n, p=probs)

    # --- Agregación ---
    p_a_mean = float(a_wins.mean())
    ci = (float(np.percentile(p_samples, 2.5)), float(np.percentile(p_samples, 97.5)))

    counts = np.bincount(method_draws, minlength=len(methods))
    method_dist = {m: round(counts[i] / n, 4) for i, m in enumerate(methods)}
    p_decision = method_dist.get("Decision", 0.0)
    p_finish = round(1.0 - p_decision, 4)

    winner = fighter_a if p_a_mean >= 0.5 else fighter_b

    return SimulationResult(
        p_a=round(p_a_mean, 4),
        p_b=round(1 - p_a_mean, 4),
        ci_a=(round(ci[0], 4), round(ci[1], 4)),
        method_dist=method_dist,
        p_finish=p_finish,
        p_decision=round(p_decision, 4),
        winner=winner,
        fighter_a=fighter_a,
        fighter_b=fighter_b,
    )


if __name__ == "__main__":
    # Demo con números inventados
    demo = monte_carlo(
        p_a=0.82,
        method_probs={"KO/TKO": 0.55, "Submission": 0.10, "Decision": 0.35},
        fighter_a="Ankalaev",
        fighter_b="Guskov",
    )
    print(demo)
