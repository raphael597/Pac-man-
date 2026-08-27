"""One adaptive model per opponent, and the registry that owns them all.

Brief section 8 is emphatic that opponents must not share a model, and it is
right: in a four-player game the three rivals are usually three *different*
programs, and averaging them produces a prediction that describes none of
them.  Each :class:`OpponentModel` therefore owns its own hypothesis
ensemble, mode belief, scorer and history.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE
from ..game.rules import ACTION_NAMES, delta_to_action
from ..game.state import GameState
from .context_model import ObservationContext
from .hidden_state import ModeClassifier
from .pattern_detector import OscillationDetector, PredictionScorer
from .predictor import HypothesisEnsemble


class OpponentModel:
    """Everything SUPERPAC believes about one rival."""

    __slots__ = ("player", "ensemble", "modes", "scorer", "oscillation",
                 "actions", "positions", "last_context", "last_prediction",
                 "observations", "_forecast_cache", "_forecast_turn")

    def __init__(self, player: int, history: int = 200) -> None:
        self.player = player
        self.ensemble = HypothesisEnsemble()
        self.modes = ModeClassifier()
        self.scorer = PredictionScorer()
        self.oscillation = OscillationDetector()
        self.actions: Deque[int] = deque(maxlen=history)
        self.positions: Deque[int] = deque(maxlen=history)
        self.last_context: Optional[ObservationContext] = None
        self.last_prediction: Optional[List[float]] = None
        self.observations = 0
        self._forecast_cache: Optional[List[Dict[int, float]]] = None
        self._forecast_turn: int = -1

    # ------------------------------------------------------------------
    def observe_transition(self, state: GameState, previous_cell: int,
                           current_cell: int) -> None:
        """Infer the action that produced an observed move and learn from it.

        We never see a rival's chosen action, only the displacement it caused,
        so the action is recovered from the geometry.  A move that is not a
        single legal step (a respawn, a teleport, an engine quirk) is dropped
        rather than fed to the models as a bogus observation.
        """
        graph = state.graph
        if previous_cell < 0 or current_cell < 0:
            return
        if previous_cell == current_cell:
            action = 4
        else:
            action = graph.action_between(previous_cell, current_cell)
            if action == 4:
                return  # not an adjacent step - do not corrupt the model
        ctx = self.last_context
        if ctx is None:
            self.actions.append(action)
            self.positions.append(current_cell)
            self.oscillation.observe(current_cell)
            return

        if self.last_prediction is not None:
            self.scorer.record(self.last_prediction, action, ctx.legal)
        self.ensemble.observe(ctx, action)
        self.modes.observe(ctx, action)
        self.actions.append(action)
        self.positions.append(current_cell)
        self.oscillation.observe(current_cell)
        self.observations += 1
        self.last_prediction = None
        self._forecast_cache = None

    # ------------------------------------------------------------------
    def predict(self, state: GameState) -> List[float]:
        """Distribution over this rival's *next* action."""
        last_action = self.actions[-1] if self.actions else 4
        ctx = ObservationContext(state, self.player, last_action)
        self.last_context = ctx
        distribution = self.ensemble.predict(ctx)
        self.last_prediction = distribution
        return distribution

    # ------------------------------------------------------------------
    def confidence(self) -> float:
        """Blend of measured accuracy and how settled the hypothesis mix is."""
        measured = self.scorer.confidence()
        settled = self.ensemble.concentration()
        return max(0.0, min(1.0, 0.75 * measured + 0.25 * settled * min(1.0, self.observations / 15.0)))

    def is_erratic(self) -> bool:
        return self.scorer.is_erratic()

    # ------------------------------------------------------------------
    def forecast(self, state: GameState, horizon: int = 4,
                 top_k: int = 3, min_mass: float = 0.02,
                 ) -> List[Dict[int, float]]:
        """Probabilistic position maps for turns ``t+1 .. t+horizon``.

        Propagates the current action distribution forward, re-predicting the
        *shape* of behaviour at each step from the rival's own position.  The
        beam is pruned two ways - keep the ``top_k`` branches per cell and drop
        anything under ``min_mass`` - because the full tree is 5^horizon and
        almost all of it is noise.

        Note the deliberate approximation: food and other players are held
        fixed across the horizon.  Re-deriving them per branch would multiply
        the cost by the beam width for a forecast that is already dominated by
        model error at depth 3+.
        """
        if self._forecast_cache is not None and self._forecast_turn == state.turn:
            return self._forecast_cache

        graph = state.graph
        pos = state.positions[self.player]
        if pos < 0 or not state.alive[self.player]:
            return [dict() for _ in range(horizon)]

        distribution = self.predict(state)
        confidence = self.confidence()

        # A rival we cannot predict is forecast as a diffusion, not a plan:
        # blending toward uniform is what stops the threat map from being
        # confidently wrong about an erratic bot.
        legal = graph.legal_actions(pos, state.rules.allow_stay)
        if confidence < 0.5:
            flat = 1.0 / len(legal)
            mix = 0.45 + 0.55 * (confidence / 0.5)
            distribution = [
                (mix * distribution[a] + (1.0 - mix) * flat) if a in legal else 0.0
                for a in range(5)
            ]
            total = sum(distribution) or 1.0
            distribution = [v / total for v in distribution]

        frames: List[Dict[int, float]] = []
        belief: Dict[int, float] = {pos: 1.0}
        step_dist = distribution

        for step in range(horizon):
            nxt: Dict[int, float] = {}
            for cell, mass in belief.items():
                if mass < min_mass:
                    continue
                if step == 0:
                    moves = step_dist
                else:
                    # Beyond the first step we no longer know the rival's
                    # action history, so fall back to a mobility-weighted
                    # spread that still respects walls.
                    moves = self._diffuse(state, cell, confidence)
                ranked = sorted(range(5), key=lambda a: -moves[a])[:top_k]
                sub_total = sum(moves[a] for a in ranked) or 1.0
                for action in ranked:
                    p = moves[action] / sub_total
                    if p <= 0:
                        continue
                    target = graph.step(cell, action)
                    nxt[target] = nxt.get(target, 0.0) + mass * p
            total = sum(nxt.values())
            if total <= 0:
                nxt = dict(belief)
                total = sum(nxt.values()) or 1.0
            belief = {c: m / total for c, m in nxt.items() if m / total >= min_mass * 0.5}
            total = sum(belief.values()) or 1.0
            belief = {c: m / total for c, m in belief.items()}
            frames.append(dict(belief))

        self._forecast_cache = frames
        self._forecast_turn = state.turn
        return frames

    def _diffuse(self, state: GameState, cell: int, confidence: float) -> List[float]:
        """Cheap forward model for steps beyond the first."""
        graph = state.graph
        legal = graph.legal_actions(cell, state.rules.allow_stay)
        out = [0.0] * 5
        if not legal:
            out[4] = 1.0
            return out
        # Rivals overwhelmingly keep moving rather than doubling back, so
        # weight by the openness of the destination and starve STAY.
        weights = []
        for action in legal:
            target = graph.step(cell, action)
            w = 1.0 + 0.35 * graph.degree[target]
            if action == 4:
                w *= 0.25
            weights.append(w)
        total = sum(weights)
        for action, w in zip(legal, weights):
            out[action] = w / total
        return out

    # ------------------------------------------------------------------
    def describe(self, state: Optional[GameState] = None) -> str:
        """The human-readable opponent view from brief section 59."""
        name, weight = self.ensemble.best()
        lines = [
            f"OPPONENT {self.player}",
            f"  likely policy      : {name} (w={weight:.2f})",
            f"  hypothesis mix     : " + ", ".join(
                f"{n}={w:.2f}" for n, w, _ in self.ensemble.ranked(4)),
            f"  behavioural mode   : {self.modes.mode_name()} ({self.modes.certainty():.0%})",
            f"  prediction quality : {self.scorer.describe()}",
            f"  confidence         : {self.confidence():.2f}"
            + ("   [ERRATIC - plan robustly]" if self.is_erratic() else ""),
        ]
        escape = self.ensemble.get("greedy_escape")
        if escape is not None and getattr(escape, "samples", 0) > 8:
            threshold, p = escape.best_threshold()      # type: ignore[attr-defined]
            lines.append(f"  escape threshold   : d<={threshold} (p={p:.2f})")
        periodic = self.ensemble.get("periodic")
        if periodic is not None:
            desc = periodic.describe()
            if "no periodic" not in desc:
                lines.append(f"  periodicity        : {desc}")
        cycle = self.ensemble.get("cycle")
        if cycle is not None and getattr(cycle, "model", None) is not None:
            if cycle.model.period:                       # type: ignore[attr-defined]
                lines.append(f"  action cycle       : {cycle.describe()}")
        if self.oscillation.is_oscillating():
            lines.append("  note               : oscillating in place")
        if state is not None and self.last_prediction:
            ranked = sorted(range(5), key=lambda a: -self.last_prediction[a])[:4]
            preds = ", ".join(f"{ACTION_NAMES[a]} {self.last_prediction[a]:.0%}"
                              for a in ranked if self.last_prediction[a] > 0.01)
            lines.append(f"  next action        : {preds}")
        return "\n".join(lines)


class OpponentRegistry:
    """Owns one :class:`OpponentModel` per rival and drives their updates."""

    def __init__(self) -> None:
        self.models: Dict[int, OpponentModel] = {}
        self._last_positions: Dict[int, int] = {}

    def model_for(self, player: int) -> OpponentModel:
        model = self.models.get(player)
        if model is None:
            model = OpponentModel(player)
            self.models[player] = model
        return model

    # ------------------------------------------------------------------
    def update(self, state: GameState) -> None:
        """Feed every rival's observed displacement into its own model."""
        for player in range(state.n_players):
            if player == state.me:
                continue
            current = state.positions[player]
            previous = self._last_positions.get(player)
            if not state.alive[player]:
                self._last_positions.pop(player, None)
                continue
            model = self.model_for(player)
            if previous is not None:
                model.observe_transition(state, previous, current)
            self._last_positions[player] = current

    # ------------------------------------------------------------------
    def predict_all(self, state: GameState) -> Dict[int, List[float]]:
        return {p: self.model_for(p).predict(state) for p in state.opponents()}

    def forecast_all(self, state: GameState, horizon: int = 4
                     ) -> Dict[int, List[Dict[int, float]]]:
        return {p: self.model_for(p).forecast(state, horizon)
                for p in state.opponents()}

    def mean_confidence(self, state: GameState) -> float:
        opponents = state.opponents()
        if not opponents:
            return 1.0
        return sum(self.model_for(p).confidence() for p in opponents) / len(opponents)

    def describe(self, state: GameState) -> str:
        return "\n".join(self.model_for(p).describe(state) for p in state.opponents())


__all__ = ["OpponentModel", "OpponentRegistry"]
