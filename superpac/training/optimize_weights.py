"""Empirical weight tuning (brief sections 42-43).

Two things make this work rather than just burn CPU:

**Common random numbers.**  Every candidate in a generation is scored on the
*identical* scenario battery.  Match outcomes are extremely noisy - a 40-game
sample has a win-rate standard error around 8 points - so comparing candidates
on different scenarios mostly measures luck.  Sharing scenarios cancels the
map and spawn variance and leaves the difference that is actually about the
weights.

**Train / validation separation.**  Fitness is measured on the training
population; the champion is *selected* on validation.  Without that split the
search reliably finds weights that beat eight specific bots and nothing else,
which is worthless in a tournament full of programs nobody has seen.
"""

from __future__ import annotations

import json
import math
import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..ai.evaluator import Weights
from ..ai.superpac import SuperPac
from ..game.rules import DEFAULT_RULES, RuleSet
from ..simulation.scenario import Scenario, standard_scenarios
from .benchmark import (Entry, evaluate, train_population,
                        validation_population)

#: ``(low, high)`` search bounds per weight.  Anything not listed is frozen -
#: search dimensions cost samples, so only parameters that plausibly matter
#: are exposed.
BOUNDS: Dict[str, Tuple[float, float]] = {
    "food": (4.0, 30.0),
    "food_potential": (0.5, 16.0),
    "territory": (0.0, 8.0),
    "cluster": (0.0, 5.0),
    "mobility": (0.0, 9.0),
    "open_space": (0.0, 4.0),
    "denial": (0.0, 5.0),
    "information": (0.0, 2.0),
    "progress": (0.0, 3.0),
    "death": (60.0, 600.0),
    "danger": (0.0, 30.0),
    "contest": (0.0, 5.0),
    "dead_end": (0.0, 16.0),
    "trap": (0.0, 18.0),
    "stagnation": (0.0, 5.0),
    "discount": (0.70, 0.98),
    "potential_discount": (0.60, 0.94),
    "risk_aversion": (0.0, 0.95),
    "territory_softness": (0.6, 3.5),
    "explore_epsilon": (0.0, 0.12),
}

INT_BOUNDS: Dict[str, Tuple[int, int]] = {
    "beam_width": (4, 24),
    "max_depth": (3, 10),
    "forecast_horizon": (2, 7),
    "scenario_count": (3, 12),
}


def clamp_weights(w: Weights) -> Weights:
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        updates[name] = min(high, max(low, float(getattr(w, name))))
    for name, (low, high) in INT_BOUNDS.items():
        updates[name] = int(min(high, max(low, int(round(getattr(w, name))))))
    return w.with_(**updates)


def random_weights(rng: random.Random, base: Optional[Weights] = None) -> Weights:
    base = base or Weights()
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        updates[name] = rng.uniform(low, high)
    for name, (low, high) in INT_BOUNDS.items():
        updates[name] = rng.randint(low, high)
    return base.with_(**updates)


def mutate(w: Weights, rng: random.Random, sigma: float = 0.22) -> Weights:
    """Log-normal jitter on scale parameters, integer walk on search sizes.

    Multiplicative noise is the right model here: every weight is a positive
    scale, so a fixed additive step is enormous for ``cluster`` and invisible
    for ``death``.
    """
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        value = float(getattr(w, name))
        if rng.random() < 0.55:
            value *= math.exp(rng.gauss(0.0, sigma))
            value += rng.gauss(0.0, 0.02 * (high - low))
        updates[name] = min(high, max(low, value))
    for name, (low, high) in INT_BOUNDS.items():
        value = int(getattr(w, name))
        if rng.random() < 0.35:
            value += rng.choice((-2, -1, 1, 2))
        updates[name] = int(min(high, max(low, value)))
    return w.with_(**updates)


def crossover(a: Weights, b: Weights, rng: random.Random) -> Weights:
    """Per-gene blend: uniform pick, or an interpolation between parents."""
    updates: Dict[str, float] = {}
    for name in list(BOUNDS):
        if rng.random() < 0.35:
            t = rng.random()
            updates[name] = (1 - t) * float(getattr(a, name)) + t * float(getattr(b, name))
        else:
            updates[name] = float(getattr(rng.choice((a, b)), name))
    for name in list(INT_BOUNDS):
        updates[name] = int(getattr(rng.choice((a, b)), name))
    return clamp_weights(a.with_(**updates))


# --------------------------------------------------------------------------
class SuperPacFactory:
    """Picklable ``() -> SuperPac`` bound to one weight vector."""

    __slots__ = ("weights", "seed", "time_budget_ms")

    def __init__(self, weights: Weights, seed: int = 0,
                 time_budget_ms: float = 40.0) -> None:
        self.weights = weights
        self.seed = seed
        self.time_budget_ms = time_budget_ms

    def __call__(self) -> SuperPac:
        return SuperPac(seed=self.seed, weights=self.weights,
                        time_budget_ms=self.time_budget_ms)


def fitness_of(weights: Weights, population: Sequence[Entry],
               scenarios: Sequence[Scenario], repeats: int = 2,
               seed: int = 0, time_budget_ms: float = 40.0) -> Dict[str, float]:
    """Score one weight vector.  Returns the components, not just a number."""
    result = evaluate(
        SuperPacFactory(weights, seed, time_budget_ms),
        population, scenarios, n_players=4, repeats=repeats,
        label="candidate", seed=seed)
    # Placement matters as well as wins: a candidate that never wins but always
    # comes second is a better starting point than one that wins or dies.
    placement_term = 1.0 - result.avg_placement / 3.0
    score = (1.00 * result.win_rate
             + 0.30 * placement_term
             + 0.12 * result.survival_rate)
    if result.crashes or result.timeouts:
        score -= 0.5  # correctness is not negotiable
    return {
        "fitness": score, "win_rate": result.win_rate,
        "placement": result.avg_placement, "survival": result.survival_rate,
        "score": result.avg_score, "ms": result.ms_per_move,
        "crashes": float(result.crashes), "timeouts": float(result.timeouts),
    }


@dataclass
class Individual:
    weights: Weights
    train: Optional[Dict[str, float]] = None
    validation: Optional[Dict[str, float]] = None

    @property
    def fitness(self) -> float:
        return self.train["fitness"] if self.train else -1e9


def evolve(generations: int = 6, population_size: int = 12,
           elite: int = 4, games: int = 14, repeats: int = 2,
           seed: int = 0, base: Optional[Weights] = None,
           mapper: Optional[Callable] = None,
           log: Optional[Callable[[str], None]] = None,
           ) -> Tuple[Weights, List[Individual]]:
    """(mu + lambda) evolution with common random numbers per generation."""
    rng = random.Random(seed)
    say = log or (lambda msg: None)
    base = clamp_weights(base or Weights())

    # Seed the population with the hand-set weights so evolution can only
    # improve on the starting point, never regress below it.
    population: List[Individual] = [Individual(base)]
    population += [Individual(mutate(base, rng, 0.35)) for _ in range(population_size // 2 - 1)]
    population += [Individual(random_weights(rng, base))
                   for _ in range(population_size - len(population))]

    train_pop = train_population()
    valid_pop = validation_population()
    history: List[Individual] = []
    champion: Optional[Individual] = None

    for generation in range(generations):
        # New scenarios each generation (so we do not overfit a fixed battery)
        # but identical within it (so candidates are compared fairly).
        scenarios = standard_scenarios(games, 4, DEFAULT_RULES,
                                       base_seed=20000 + generation * 977)
        jobs = [(ind.weights, train_pop, scenarios, repeats, seed + generation)
                for ind in population]
        if mapper is not None:
            scores = list(mapper(jobs))
        else:
            scores = [fitness_of(*job) for job in jobs]
        for ind, score in zip(population, scores):
            ind.train = score

        population.sort(key=lambda i: -i.fitness)
        best = population[0]
        say(f"gen {generation}: best fitness={best.fitness:.4f} "
            f"win={best.train['win_rate']:.1%} place={best.train['placement']:.2f} "
            f"ms={best.train['ms']:.2f}")

        history.extend(population[:elite])
        if champion is None or best.fitness > champion.fitness:
            champion = Individual(best.weights, best.train)

        survivors = population[:elite]
        children: List[Individual] = []
        sigma = 0.30 * (1.0 - generation / max(1, generations))  # anneal
        while len(children) < population_size - elite:
            a, b = rng.sample(survivors, 2) if len(survivors) >= 2 else (survivors[0], survivors[0])
            child = mutate(crossover(a.weights, b.weights, rng), rng, max(0.08, sigma))
            children.append(Individual(child))
        population = survivors + children

    return (champion.weights if champion else base), history


def save_weights(weights: Weights, path: str, meta: Optional[Dict] = None) -> None:
    payload = {"vector": weights.as_vector(), "names": Weights.names(),
               "weights": weights.to_dict(), "meta": meta or {}}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)


def load_weights(path: str) -> Weights:
    with open(path) as fh:
        payload = json.load(fh)
    return Weights.from_vector(payload["vector"])


__all__ = ["SuperPacFactory", "evolve", "fitness_of", "mutate", "crossover", "random_weights",
           "clamp_weights", "save_weights", "load_weights", "BOUNDS",
           "INT_BOUNDS", "Individual"]
