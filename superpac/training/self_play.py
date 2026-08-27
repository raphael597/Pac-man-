"""Version-versus-version testing and league play (brief sections 41, 45).

A new version is only an improvement if it beats the old one on *identical*
scenarios with *identical* opponents.  Anything less and you are measuring
map luck, which in this game is worth tens of percentage points.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..ai.evaluator import Weights
from ..game.rules import DEFAULT_RULES, RuleSet
from ..simulation.scenario import Scenario, standard_scenarios
from ..simulation.tournament import head_to_head
from .benchmark import Entry, validation_population
from .optimize_weights import SuperPacFactory


def version_duel(champion: Weights, challenger: Weights,
                 games: int = 24, n_players: int = 4,
                 rules: Optional[RuleSet] = None,
                 fillers: Optional[Sequence[Entry]] = None,
                 ) -> Dict[str, Dict[str, float]]:
    """Champion vs challenger, both in every seat of every scenario.

    :func:`head_to_head` seats each version in every position of the same
    scenario, so spawn advantage cancels exactly rather than approximately.
    """
    scenarios = standard_scenarios(games, n_players, rules or DEFAULT_RULES,
                                   base_seed=33000)
    report = head_to_head(
        ("champion", SuperPacFactory(champion, seed=11, time_budget_ms=40.0)),
        ("challenger", SuperPacFactory(challenger, seed=11, time_budget_ms=40.0)),
        scenarios, fillers=list(fillers or validation_population()),
        n_players=n_players)
    out: Dict[str, Dict[str, float]] = {}
    for name in ("champion", "challenger"):
        stats = report.get(name)
        out[name] = {
            "win_rate": stats.win_rate, "placement": stats.avg_placement,
            "score": stats.avg_score, "survival": stats.survival_rate,
            "ms_per_move": stats.ms_per_move, "games": float(stats.games),
        }
    return out


def accept_challenger(result: Dict[str, Dict[str, float]],
                      margin: float = 0.03) -> bool:
    """Promote only on a clear win, not a coin flip.

    Match outcomes are noisy enough that a one-point edge over a few dozen
    games is indistinguishable from luck.  Requiring a real margin on win rate
    *and* no regression in placement keeps the champion from drifting sideways
    forever (brief section 41).
    """
    champion, challenger = result["champion"], result["challenger"]
    better_wins = challenger["win_rate"] >= champion["win_rate"] + margin
    no_placement_regression = challenger["placement"] <= champion["placement"] + 0.02
    return better_wins and no_placement_regression


def render_duel(result: Dict[str, Dict[str, float]]) -> str:
    lines = [f"{'version':<12s} {'win':>7s} {'place':>7s} {'score':>8s} "
             f"{'surv':>7s} {'ms/mv':>7s} {'games':>6s}"]
    lines.append("-" * len(lines[0]))
    for name, row in result.items():
        lines.append(f"{name:<12s} {row['win_rate']:>6.1%} {row['placement']:>7.3f} "
                     f"{row['score']:>8.2f} {row['survival']:>6.1%} "
                     f"{row['ms_per_move']:>7.2f} {int(row['games']):>6d}")
    verdict = "PROMOTE challenger" if accept_challenger(result) else "KEEP champion"
    lines.append(f"verdict: {verdict}")
    return "\n".join(lines)


__all__ = ["version_duel", "accept_challenger", "render_duel"]
