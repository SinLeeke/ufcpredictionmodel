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

    2) LOS VALORES PUNTUALES SON LOS EXACTOS, no los promedios de los sorteos.
       Antes se reportaba la frecuencia de victorias y de cada método en las
       10.000 corridas, que solo recuperan p y las probabilidades de método con
       ruido: medido, hasta 0,9 pts en p_a. Ese ruido no es incertidumbre, es
       error de redondeo del muestreo, y llegaba al EV de las patas del parlay
       (que no coincidía con el de "Qué apostar", calculado con la p exacta).
       La simulación queda para lo único que aporta: el intervalo creíble.
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

    # Incertidumbre sobre p: una p distinta por simulación -> intervalo creíble
    alpha, beta = _beta_params(p_a, concentration)
    p_samples = rng.beta(alpha, beta, size=n)
    ci = (float(np.percentile(p_samples, 2.5)), float(np.percentile(p_samples, 97.5)))

    # Puntuales EXACTOS (ver la nota del módulo): la media de la Beta es p, y la
    # frecuencia esperada de cada método es su probabilidad.
    p_a_mean = float(p_a)
    total = sum(float(v) for v in method_probs.values())
    method_dist = {m: round(float(v) / total, 4) for m, v in method_probs.items()}
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
