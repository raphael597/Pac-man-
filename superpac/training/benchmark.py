"""The measurement layer.  Nothing ships that this has not scored.

Brief sections 40-41 and 46: many games, fixed scenario batteries, seat
rotation, and - critically - separate train / validation / holdout opponent
populations so a strategy that only beats the bots it was tuned against gets
caught here rather than in the tournament.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..ai.evaluator import Weights
from ..ai.superpac import SuperPac
from ..bots.base import Bot, BotFactory
from ..bots.patterned import ModeSwitchBot, PatternBot, PeriodicBot, StochasticBot
from ..bots.reactive import AggressiveBot, DefensiveBot, GreedyEscapeBot, InterceptBot
from ..bots.simple import (ClusterFoodBot, FixedPriorityBot, GreedyFoodBot,
                           NoisyGreedyBot, RandomBot)
from ..game.rules import DEFAULT_RULES, EAST, NORTH, RULE_VARIANTS, SOUTH, WEST, RuleSet
from ..simulation.scenario import Scenario, standard_scenarios
from ..simulation.tournament import BotStats, TournamentReport, run_tournament

Entry = Tuple[str, Callable[[], object]]


# --------------------------------------------------------------------------
# Opponent populations - deliberately disjoint (brief section 46)
# --------------------------------------------------------------------------
def train_population() -> List[Entry]:
    """What the optimiser is allowed to see."""
    return [
        BotFactory(GreedyFoodBot, "greedy", seed=11).entry(),
        BotFactory(ClusterFoodBot, "cluster", seed=12).entry(),
        BotFactory(GreedyEscapeBot, "greedy_escape3", seed=13, threshold=3).entry(),
        BotFactory(DefensiveBot, "defensive", seed=14).entry(),
        BotFactory(NoisyGreedyBot, "noisy_greedy", seed=15, noise=0.12).entry(),
        BotFactory(PeriodicBot, "periodic15", seed=16, period=15).entry(),
        BotFactory(RandomBot, "random", seed=17).entry(),
        BotFactory(AggressiveBot, "aggressive", seed=18).entry(),
    ]


def validation_population() -> List[Entry]:
    """Used to *choose* between candidates, never to fit them."""
    return [
        BotFactory(GreedyEscapeBot, "greedy_escape5", seed=21, threshold=5).entry(),
        BotFactory(ClusterFoodBot, "cluster6", seed=22, radius=6).entry(),
        BotFactory(PatternBot, "pattern", seed=23).entry(),
        BotFactory(StochasticBot, "stochastic", seed=24, temperature=1.0).entry(),
        BotFactory(InterceptBot, "intercept", seed=25).entry(),
        BotFactory(ModeSwitchBot, "mode_switch", seed=26).entry(),
        BotFactory(FixedPriorityBot, "fixed_priority", seed=27).entry(),
        BotFactory(NoisyGreedyBot, "noisy_greedy25", seed=28, noise=0.25).entry(),
    ]


def holdout_population() -> List[Entry]:
    """Touched once, at the end.  Tuning against this invalidates it."""
    return [
        BotFactory(GreedyEscapeBot, "greedy_escape2", seed=31, threshold=2).entry(),
        BotFactory(GreedyEscapeBot, "greedy_escape8", seed=32, threshold=8).entry(),
        BotFactory(PeriodicBot, "periodic7", seed=33, period=7, preferred=NORTH).entry(),
        BotFactory(PeriodicBot, "periodic23j", seed=34, period=23, jitter=3).entry(),
        BotFactory(PatternBot, "pattern_long", seed=35,
                   script=(EAST, NORTH, EAST, EAST, SOUTH, WEST, SOUTH)).entry(),
        BotFactory(StochasticBot, "stochastic_hot", seed=36, temperature=2.0).entry(),
        BotFactory(AggressiveBot, "aggressive12", seed=37, engage=12).entry(),
        BotFactory(ModeSwitchBot, "mode_switch_late", seed=38, boundaries=(70, 110)).entry(),
        BotFactory(DefensiveBot, "defensive8", seed=39, panic=8).entry(),
        BotFactory(ClusterFoodBot, "cluster2", seed=40, radius=2).entry(),
    ]


# --------------------------------------------------------------------------
@dataclass
class BenchmarkResult:
    win_rate: float
    avg_placement: float
    avg_score: float
    survival_rate: float
    ms_per_move: float
    games: int
    crashes: int
    timeouts: int
    report: Optional[TournamentReport] = None

    def summary(self) -> str:
        return (f"win={self.win_rate:6.1%}  place={self.avg_placement:5.3f}  "
                f"score={self.avg_score:6.2f}  surv={self.survival_rate:6.1%}  "
                f"ms/mv={self.ms_per_move:5.2f}  n={self.games}"
                + (f"  CRASHES={self.crashes}" if self.crashes else "")
                + (f"  TIMEOUTS={self.timeouts}" if self.timeouts else ""))

    # 95% confidence half-width on the win rate, for honest comparisons.
    def win_rate_ci(self) -> float:
        if self.games <= 1:
            return 1.0
        p = self.win_rate
        return 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / self.games)


def evaluate(subject: Callable[[], object],
             population: Sequence[Entry],
             scenarios: Sequence[Scenario],
             n_players: int = 4,
             repeats: int = 2,
             label: str = "subject",
             seed: int = 0) -> BenchmarkResult:
    """Score one entrant against a population over a fixed scenario battery.

    The subject plays in *every* game; the rest of the table is drawn from the
    population.  Seats rotate, so spawn luck averages out.
    """
    entries: List[Entry] = [(label, subject)] + list(population)
    rng = random.Random(seed)
    stats = BotStats(label)

    from ..simulation.tournament import run_game
    for scenario in scenarios:
        for rep in range(repeats):
            others = rng.sample(range(len(population)), min(n_players - 1, len(population)))
            table: List[Entry] = [entries[0]] + [population[i] for i in others]
            while len(table) < n_players:
                table.append(population[rng.randrange(len(population))])
            seat = rep % n_players
            table = table[1:seat + 1] + [table[0]] + table[seat + 1:]
            subject_seat = seat

            scen = Scenario(scenario.seed + rep * 104729, scenario.spec,
                            scenario.rules, n_players)
            result = run_game([t[1] for t in table], scen)
            stats.games += 1
            stats.placement_sum += result.placements[subject_seat]
            stats.score_sum += result.scores[subject_seat]
            stats.turn_sum += result.turns
            stats.time_sum += result.move_times[subject_seat] if result.move_times else 0.0
            stats.crashes += result.crashes[subject_seat] if result.crashes else 0
            stats.timeouts += result.timeouts[subject_seat] if result.timeouts else 0
            if result.survived[subject_seat]:
                stats.survived += 1
            if result.winner == subject_seat:
                stats.wins += 1

    return BenchmarkResult(
        win_rate=stats.win_rate, avg_placement=stats.avg_placement,
        avg_score=stats.avg_score, survival_rate=stats.survival_rate,
        ms_per_move=stats.ms_per_move, games=stats.games,
        crashes=stats.crashes, timeouts=stats.timeouts,
    )


def full_benchmark(subject: Callable[[], object], games: int = 40,
                   n_players: int = 4, rules: Optional[RuleSet] = None,
                   label: str = "superpac", seed: int = 0,
                   ) -> Dict[str, BenchmarkResult]:
    """Train / validation / holdout in one call."""
    rules = rules or DEFAULT_RULES
    scenarios = standard_scenarios(games, n_players, rules, base_seed=7000 + seed)
    return {
        "train": evaluate(subject, train_population(), scenarios, n_players,
                          repeats=2, label=label, seed=seed),
        "validation": evaluate(subject, validation_population(), scenarios,
                               n_players, repeats=2, label=label, seed=seed + 1),
        "holdout": evaluate(subject, holdout_population(), scenarios,
                            n_players, repeats=2, label=label, seed=seed + 2),
    }


def rules_sweep(subject: Callable[[], object], games: int = 20,
                n_players: int = 4, label: str = "superpac",
                ) -> Dict[str, BenchmarkResult]:
    """Score the subject under every plausible reading of the unknown rules.

    This is the direct answer to having no teacher files: SUPERPAC does not
    get to be strong only under our best guess at the ruleset.
    """
    out: Dict[str, BenchmarkResult] = {}
    for name, rules in RULE_VARIANTS.items():
        scenarios = standard_scenarios(games, n_players, rules, base_seed=8100)
        out[name] = evaluate(subject, train_population() + validation_population(),
                             scenarios, n_players, repeats=1, label=label)
    return out


def render(results: Dict[str, BenchmarkResult], title: str = "") -> str:
    lines = [title] if title else []
    for name, res in results.items():
        lines.append(f"  {name:<12s} {res.summary()}")
    return "\n".join(lines)


__all__ = ["evaluate", "full_benchmark", "rules_sweep", "render",
           "BenchmarkResult", "train_population", "validation_population",
           "holdout_population"]
