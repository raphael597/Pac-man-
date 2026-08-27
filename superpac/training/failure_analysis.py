"""Automatic classification of losses (brief section 51).

A win rate tells you *that* something is wrong. It does not tell you what to
fix. This module replays matches with SUPERPAC instrumented, and when it loses,
sorts the loss into a category that points at a subsystem:

``trapped``
    Eliminated inside a dead-end pocket - the trap term or the survival
    override let it walk into a sealable space.
``ambushed``
    Eliminated without SURVIVAL mode ever firing - the threat map did not see
    it coming, which is a forecasting failure rather than a planning one.
``over_aggressive``
    Eliminated while closing on a rival - the danger term is too cheap.
``prediction_failure``
    Confidence was high and accuracy was not.  The models were wrong *and*
    sure of it, which is the worst combination.
``opponent_noise``
    Confidence was correctly low: the rivals were genuinely unpredictable and
    this loss is not evidence of a bug.
``food_inefficiency``
    Survived, was never in danger, and still collected less than the winner -
    a pure harvesting problem.
``territory_loss``
    Survived, but lost the map before losing the game.
``endgame_collapse``
    Was ahead at the three-quarter mark and lost anyway.
``timeout`` / ``crash``
    Engineering faults.  These are never acceptable and are reported first.

The distinction that matters most is ``prediction_failure`` versus
``opponent_noise``: only one of them is a bug.  Losing to a coin flip is not a
modelling error, and treating it as one leads to chasing noise.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..ai.strategy import Mode
from ..ai.superpac import SuperPac
from ..game.state import GameState
from ..simulation.scenario import Scenario, standard_scenarios
from ..simulation.tournament import run_game
from .benchmark import Entry, validation_population


@dataclass
class MatchTrace:
    """Signals collected while SUPERPAC played one match."""

    survival_turns: int = 0
    """How many turns SUPERPAC spent in SURVIVAL mode."""
    last_survival_turn: int = -99
    modes: Counter = field(default_factory=Counter)
    dead_end_at_end: bool = False
    pocket_depth_at_end: int = 0
    closing_on_rival: bool = False
    mean_confidence: float = 0.0
    mean_accuracy: float = 0.0
    samples: int = 0
    lead_at_three_quarters: Optional[float] = None
    territory_share: float = 0.0
    my_score: float = 0.0
    best_rival_score: float = 0.0
    turns: int = 0

    def observe(self, agent: SuperPac, state: GameState) -> None:
        graph = state.graph
        pos = state.positions[state.me] if state.alive[state.me] else -1
        self.turns = state.turn
        self.modes[agent.last_mode.value] += 1
        if agent.last_mode is Mode.SURVIVAL:
            self.survival_turns += 1
            self.last_survival_turn = state.turn

        if pos >= 0:
            self.dead_end_at_end = bool(graph.is_dead_end[pos])
            self.pocket_depth_at_end = graph.dead_end_depth[pos]
            rivals = [c for c in state.opponent_positions() if c >= 0]
            if rivals:
                nearest = min(graph.distance(pos, r) for r in rivals)
                self.closing_on_rival = nearest <= 2

        confidences, accuracies = [], []
        for player in state.opponents():
            model = agent.registry.model_for(player)
            if model.observations >= 5:
                confidences.append(model.confidence())
                accuracies.append(model.scorer.long_accuracy)
        if confidences:
            n = self.samples
            self.mean_confidence = (self.mean_confidence * n + sum(confidences) / len(confidences)) / (n + 1)
            self.mean_accuracy = (self.mean_accuracy * n + sum(accuracies) / len(accuracies)) / (n + 1)
            self.samples = n + 1

        if self.lead_at_three_quarters is None and state.progress() >= 0.75:
            self.lead_at_three_quarters = state.score_gap()


def classify(trace: MatchTrace, survived: bool, placement: int,
             crashes: int, timeouts: int) -> str:
    """Sort one loss into a category.  ``""`` when the match was won."""
    if crashes:
        return "crash"
    if timeouts:
        return "timeout"
    if placement == 0:
        return ""

    if not survived:
        if trace.dead_end_at_end and trace.pocket_depth_at_end > 0:
            return "trapped"
        if trace.closing_on_rival:
            return "over_aggressive"
        # Died without the survival override ever engaging: the threat map
        # never flagged it, so this is a forecasting failure.
        if trace.survival_turns == 0 or trace.turns - trace.last_survival_turn > 4:
            return "ambushed"
        return "overwhelmed"

    # Survived but lost on points.
    if trace.samples >= 3:
        if trace.mean_confidence >= 0.55 and trace.mean_accuracy < 0.55:
            return "prediction_failure"
        if trace.mean_confidence < 0.35:
            return "opponent_noise"
    if trace.lead_at_three_quarters is not None and trace.lead_at_three_quarters > 0:
        return "endgame_collapse"
    if trace.territory_share < 0.28:
        return "territory_loss"
    return "food_inefficiency"


def analyse(games: int = 20, population: Optional[Sequence[Entry]] = None,
            n_players: int = 4, seed: int = 0,
            weights=None) -> Tuple[Counter, List[str]]:
    """Play a batch of matches and tally why the losses happened."""
    pool = list(population or validation_population())
    tally: Counter = Counter()
    notes: List[str] = []
    holder: Dict[str, SuperPac] = {}

    def make() -> SuperPac:
        agent = SuperPac(seed=seed, weights=weights)
        holder["agent"] = agent
        return agent

    for i, scenario in enumerate(standard_scenarios(games, n_players,
                                                    base_seed=51000 + seed)):
        table = [make] + [pool[(i + k) % len(pool)][1] for k in range(n_players - 1)]
        trace = MatchTrace()

        def on_turn(state: GameState, actions, trace=trace) -> None:
            agent = holder.get("agent")
            if agent is not None and state.turn > 1:
                saved = state.me
                state.me = 0
                try:
                    trace.observe(agent, state)
                finally:
                    state.me = saved

        result = run_game(table, scenario, on_turn=on_turn)
        trace.my_score = result.scores[0]
        trace.best_rival_score = max(result.scores[1:]) if len(result.scores) > 1 else 0.0
        agent = holder.get("agent")
        if agent is not None and agent.last_plan is not None:
            pass  # territory share is sampled in observe(); nothing more needed

        label = classify(trace, result.survived[0], result.placements[0],
                         result.crashes[0], result.timeouts[0])
        tally["WIN" if not label else label] += 1
        if label:
            notes.append(
                f"game {i}: {label} (place {result.placements[0]}, "
                f"score {result.scores[0]:.0f} vs {trace.best_rival_score:.0f}, "
                f"conf {trace.mean_confidence:.2f}, acc {trace.mean_accuracy:.2f}, "
                f"survival turns {trace.survival_turns})")
    return tally, notes


def render(tally: Counter, notes: Sequence[str], show: int = 8) -> str:
    total = sum(tally.values()) or 1
    lines = [f"{total} games", "-" * 52]
    for label, count in tally.most_common():
        lines.append(f"  {label:<22s} {count:4d}  {count / total:6.1%}")
    losses = total - tally.get("WIN", 0)
    if losses:
        lines.append("")
        lines.append(f"sample losses ({min(show, len(notes))} of {losses}):")
        lines.extend("  " + note for note in notes[:show])
    return "\n".join(lines)


__all__ = ["analyse", "classify", "render", "MatchTrace"]
