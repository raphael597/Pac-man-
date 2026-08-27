"""Adversarial opponent search and the self-play league (brief sections 44-45).

Beating the eight bots you wrote yourself proves very little.  This module
does the opposite job: it *searches for opponents that beat SUPERPAC*, and
keeps the ones that succeed.

The loop is:

    champion  ->  search bot-parameter space for a counter-strategy
              ->  benchmark the candidate against the champion
              ->  if it wins often enough, add it to the league
              ->  re-tune the champion against the enlarged league
              ->  repeat

Every counter-bot that survives becomes a permanent regression test: the
league is never pruned of old members, so a later version cannot "improve" by
forgetting how to beat an earlier threat.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..ai.superpac import SuperPac
from ..bots.base import BotFactory
from ..bots.patterned import ModeSwitchBot, PatternBot, PeriodicBot, StochasticBot
from ..bots.reactive import (AggressiveBot, DefensiveBot, GreedyEscapeBot,
                             InterceptBot)
from ..bots.simple import (ClusterFoodBot, FixedPriorityBot, GreedyFoodBot,
                           NoisyGreedyBot, RandomBot)
from ..game.rules import DEFAULT_RULES, EAST, NORTH, SOUTH, WEST
from ..simulation.scenario import standard_scenarios
from ..simulation.tournament import run_game
from .benchmark import Entry, evaluate

#: The archetypes an adversary may be drawn from, with their parameter ranges.
#: Deliberately built from the *same* bot classes the population uses - the
#: search is over configurations, not over new code, which keeps every
#: adversary explainable and reproducible.
ARCHETYPES: Dict[str, Tuple[type, Dict[str, Sequence]]] = {
    "greedy_escape": (GreedyEscapeBot, {"threshold": (1, 2, 3, 4, 5, 6, 7, 9)}),
    "aggressive": (AggressiveBot, {"engage": (3, 5, 7, 9, 12, 16, 22)}),
    "defensive": (DefensiveBot, {"panic": (2, 3, 4, 6, 8, 11, 15)}),
    "cluster": (ClusterFoodBot, {"radius": (1, 2, 3, 4, 6, 8, 11)}),
    "noisy_greedy": (NoisyGreedyBot, {"noise": (0.02, 0.06, 0.12, 0.2, 0.35, 0.5)}),
    "periodic": (PeriodicBot, {
        "period": (3, 5, 7, 11, 15, 19, 25),
        "preferred": (NORTH, SOUTH, WEST, EAST),
        "jitter": (0, 1, 2, 4),
    }),
    "stochastic": (StochasticBot, {"temperature": (0.3, 0.6, 1.0, 1.6, 2.4, 3.5)}),
    "intercept": (InterceptBot, {"lead": (1, 2, 3, 5, 8)}),
    "mode_switch": (ModeSwitchBot, {"boundaries": ((15, 35), (30, 60), (50, 90), (80, 130))}),
    "fixed_priority": (FixedPriorityBot, {"order": (
        (EAST, SOUTH, WEST, NORTH), (NORTH, EAST, SOUTH, WEST),
        (WEST, NORTH, EAST, SOUTH), (SOUTH, WEST, NORTH, EAST))}),
    "pattern": (PatternBot, {"script": (
        (EAST, EAST, NORTH), (EAST, NORTH, WEST, SOUTH),
        (EAST, EAST, SOUTH, SOUTH), (NORTH, EAST, EAST, SOUTH, WEST, WEST))}),
}


def sample_adversary(rng: random.Random, index: int = 0) -> Entry:
    """Draw one random configuration from the archetype space."""
    name = rng.choice(list(ARCHETYPES))
    cls, space = ARCHETYPES[name]
    kwargs = {key: rng.choice(values) for key, values in space.items()}
    label = name + "_" + "_".join(
        str(v).replace(" ", "").replace(",", "-") for v in kwargs.values())
    label = (label[:38] + str(index)) if len(label) > 38 else label
    return BotFactory(cls, label, seed=1000 + index, **kwargs).entry()


@dataclass
class LeagueMember:
    name: str
    factory: Callable[[], object]
    origin: str = "seed"
    """``seed`` | ``counter`` - how this member joined."""
    superpac_win_rate: float = 0.0
    added_round: int = 0

    def entry(self) -> Entry:
        return (self.name, self.factory)


class League:
    """The permanent opponent set.  Grows, never shrinks."""

    def __init__(self, members: Optional[Sequence[LeagueMember]] = None) -> None:
        self.members: List[LeagueMember] = list(members or [])
        self._names = {m.name for m in self.members}

    def add(self, member: LeagueMember) -> bool:
        if member.name in self._names:
            return False
        self.members.append(member)
        self._names.add(member.name)
        return True

    def entries(self) -> List[Entry]:
        return [m.entry() for m in self.members]

    def hardest(self, top: int = 5) -> List[LeagueMember]:
        return sorted(self.members, key=lambda m: m.superpac_win_rate)[:top]

    def summary(self) -> str:
        lines = [f"league: {len(self.members)} members"]
        for member in sorted(self.members, key=lambda m: m.superpac_win_rate):
            lines.append(f"  {member.name:<42s} superpac_win={member.superpac_win_rate:6.1%} "
                         f"({member.origin}, round {member.added_round})")
        return "\n".join(lines)


def seed_league() -> League:
    from .benchmark import train_population, validation_population
    league = League()
    for name, factory in train_population() + validation_population():
        league.add(LeagueMember(name, factory, origin="seed"))
    return league


# --------------------------------------------------------------------------
def score_adversary(job) -> Dict:
    """Play a candidate adversary against SUPERPAC.  Picklable, for pools.

    The candidate fills *three* of the four seats: an adversary only counts as
    a genuine counter-strategy if it beats SUPERPAC when it is the dominant
    presence on the board, not when it happens to get a lucky spawn.
    """
    from .optimize_weights import SuperPacFactory

    name, factory, weights, games, seed = job
    scenarios = standard_scenarios(games, 4, DEFAULT_RULES, base_seed=41000 + seed)
    result = evaluate(SuperPacFactory(weights, seed=7, time_budget_ms=40.0),
                      [(name, factory)], scenarios, n_players=4, repeats=1,
                      label="superpac", seed=seed)
    return {
        "name": name, "superpac_win_rate": result.win_rate,
        "superpac_placement": result.avg_placement,
        "superpac_survival": result.survival_rate,
        "games": result.games,
    }


def search_counter_bots(weights, rounds: int = 24, games: int = 8,
                        seed: int = 0, threshold: float = 0.55,
                        mapper: Optional[Callable] = None,
                        log: Optional[Callable[[str], None]] = None,
                        ) -> List[LeagueMember]:
    """Sample adversary configurations and keep the ones that hurt.

    ``threshold`` is SUPERPAC's win rate: anything at or below it means the
    adversary is holding its own against three-to-one odds, which is a real
    weakness worth keeping as a regression test.
    """
    say = log or (lambda msg: None)
    rng = random.Random(seed)
    candidates = [sample_adversary(rng, i) for i in range(rounds)]
    jobs = [(name, factory, weights, games, seed + i)
            for i, (name, factory) in enumerate(candidates)]
    results = list(mapper(jobs)) if mapper else [score_adversary(j) for j in jobs]

    found: List[LeagueMember] = []
    for (name, factory), row in zip(candidates, results):
        marker = ""
        if row["superpac_win_rate"] <= threshold:
            found.append(LeagueMember(name, factory, origin="counter",
                                      superpac_win_rate=row["superpac_win_rate"]))
            marker = "  <-- COUNTER-BOT"
        say(f"  {name:<42s} superpac_win={row['superpac_win_rate']:6.1%} "
            f"place={row['superpac_placement']:.2f}{marker}")
    found.sort(key=lambda m: m.superpac_win_rate)
    return found


__all__ = ["League", "LeagueMember", "seed_league", "sample_adversary",
           "search_counter_bots", "score_adversary", "ARCHETYPES"]
