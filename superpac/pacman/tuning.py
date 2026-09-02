"""Weight tuning for ``ThoresT``, measured on the teacher's real engine.

Two rules carried over from the earlier work on this project, both learned
the hard way:

* **Tune against strong opponents.** The engine's own bots stand still a
  third of the time; beating them says nothing. Every measurement here is
  against harvesters, sweepers and hunters.
* **Separate the populations.** Fitness comes from a training set of
  opponents, the champion is *chosen* on a disjoint validation set, and the
  holdout is touched once at the end. Without that split the search reliably
  finds weights that beat five specific bots and nothing else.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .agent import Weights

#: ``(low, high)`` per weight.  Anything absent is frozen - each extra search
#: dimension costs samples.
BOUNDS: Dict[str, Tuple[float, float]] = {
    "run_ahead": (0.3, 2.0),
    "run_discount": (0.70, 0.97),
    "density": (0.0, 0.5),
    "hunt": (0.0, 2.5),
    "hunt_decay": (0.70, 0.96),
    "exposure": (0.0, 20.0),
    "facing_discipline": (0.0, 40.0),
    "survival_bonus": (0.0, 30.0),
    "discount": (0.85, 0.999),
    "attack_margin": (0.4, 3.0),
    "harvest_rate": (0.4, 1.2),
}

INT_BOUNDS: Dict[str, Tuple[int, int]] = {
    "beam_width": (8, 40),
    "depth": (4, 14),
}


def _check_bounds() -> None:
    known = set(Weights.names())
    stale = (set(BOUNDS) | set(INT_BOUNDS)) - known
    if stale:
        raise RuntimeError(f"bounds name weights that do not exist: {sorted(stale)}")


_check_bounds()


def clamp(w: Weights) -> Weights:
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        updates[name] = min(high, max(low, float(getattr(w, name))))
    for name, (low, high) in INT_BOUNDS.items():
        updates[name] = int(min(high, max(low, int(round(getattr(w, name))))))
    return w.with_(**updates)


def mutate(w: Weights, rng: random.Random, sigma: float = 0.25) -> Weights:
    """Log-normal jitter: every weight is a positive scale, so a fixed
    additive step would be enormous for ``density`` and invisible for
    ``survival_bonus``."""
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        value = float(getattr(w, name))
        if rng.random() < 0.5:
            value = value * math.exp(rng.gauss(0.0, sigma)) + rng.gauss(0.0, 0.03 * (high - low))
        updates[name] = min(high, max(low, value))
    for name, (low, high) in INT_BOUNDS.items():
        value = int(getattr(w, name))
        if rng.random() < 0.35:
            value += rng.choice((-3, -2, -1, 1, 2, 3))
        updates[name] = int(min(high, max(low, value)))
    return w.with_(**updates)


def crossover(a: Weights, b: Weights, rng: random.Random) -> Weights:
    updates: Dict[str, float] = {}
    for name in BOUNDS:
        if rng.random() < 0.35:
            t = rng.random()
            updates[name] = (1 - t) * float(getattr(a, name)) + t * float(getattr(b, name))
        else:
            updates[name] = float(getattr(rng.choice((a, b)), name))
    for name in INT_BOUNDS:
        updates[name] = int(getattr(rng.choice((a, b)), name))
    return clamp(a.with_(**updates))


def random_weights(rng: random.Random, base: Optional[Weights] = None) -> Weights:
    base = base or Weights()
    updates: Dict[str, float] = {}
    for name, (low, high) in BOUNDS.items():
        updates[name] = rng.uniform(low, high)
    for name, (low, high) in INT_BOUNDS.items():
        updates[name] = rng.randint(low, high)
    return base.with_(**updates)


# --------------------------------------------------------------------------
# Opponent populations - deliberately disjoint
# --------------------------------------------------------------------------
TRAIN_MIX = ("harvester", "trex", "sweeper", "cautious", "hunter")
VALIDATION_MIX = ("harvester", "trex", "trex", "random", "random")
HOLDOUT_MIX = ("hunter", "trex", "harvester", "cautious", "sweeper")


def build_mix(names: Sequence[str]) -> List[Tuple[Callable, str]]:
    """Resolve opponent names to ``(class, name)`` pairs for ``Field``.

    ``random`` means the engine's own default bot and ``trex`` the example
    player the teacher ships; everything else comes from our sparring set.
    """
    import Pacman
    from .opponents import build_opponents
    catalogue = dict(build_opponents(Pacman.Pacman))
    try:
        from TRex import TRex
        catalogue["trex"] = TRex
    except Exception:
        catalogue["trex"] = Pacman.Pacman
    catalogue["random"] = Pacman.Pacman
    return [(catalogue[n], f"{n}{i}") for i, n in enumerate(names)]


def score(weights: Weights, mix_names: Sequence[str], games: int = 24,
          base_seed: int = 4000, fieldsize: int = 15,
          max_turns: int = 400) -> Dict[str, float]:
    """Play a batch and return the fitness components.

    Fitness leans on *placement* as well as wins: with six players a win rate
    is a coarse, noisy signal, and a bot that reliably finishes second is a
    better base to improve from than one that wins or dies.
    """
    import Pacman
    from .arena import evaluate
    from .thorest import build_thorest

    from .arena import default_walls

    subject = build_thorest(Pacman.Pacman, weights=weights, total_turns=None)
    report = evaluate(subject, games=games, fieldsize=fieldsize,
                      base_seed=base_seed, label="candidate",
                      fillers=build_mix(mix_names), walls=default_walls(),
                      max_turns=max_turns)
    placement = 1.0 - report.mean_rank / 5.0
    relative = report.mean_strength / max(1.0, report.mean_best_rival)
    # Two ways to come out on top now: outlive everyone, or simply end up the
    # strongest when the clock stops. Matches often do not resolve to a sole
    # survivor, so scoring only the first would throw away most of the signal.
    fitness = (0.70 * report.win_rate
               + 0.50 * report.strongest_rate
               + 0.45 * placement
               + 0.25 * min(2.0, relative)
               + 0.15 * report.survival_rate)
    if report.faults:
        fitness -= 1.0
    return {
        "fitness": fitness, "win_rate": report.win_rate,
        "rank": report.mean_rank, "strength": report.mean_strength,
        "best_rival": report.mean_best_rival,
        "survival": report.survival_rate, "ms": report.ms_sum / max(1, report.games),
        "faults": float(report.faults), "strongest": report.strongest_rate,
        "turns": report.turn_sum / max(1, report.games),
    }


__all__ = ["BOUNDS", "INT_BOUNDS", "clamp", "mutate", "crossover",
           "random_weights", "score", "TRAIN_MIX", "VALIDATION_MIX",
           "HOLDOUT_MIX", "build_mix"]
