"""Per-rival behaviour models for the real game's action space.

The engine gives us something unusually good: **a rival's action is exactly
recoverable from the board.** Each player takes one action per round, and the
three kinds leave distinguishable traces:

* position changed  -> it called ``_Move``
* facing changed    -> it turned
* neither           -> it stood still

A surviving Pacman is never displaced by anyone else (the loser of a fight
dies, the winner advances), so a position change can only be its own move.
That makes the observation exact rather than inferred, which is a much better
starting point than the position-only observations the general engine had.

Three models are mixed by fixed-share weighting, so a rival that changes
strategy mid-match can be tracked instead of averaged away:

``FrequencyModel``   what it does overall
``SequenceModel``    what it does given its last two actions
``ContextModel``     what it does given the situation in front of it

The teacher's own ``Pacman`` is uniform 1/3 turn, 1/3 move, 1/3 still, and
the frequency model locks onto that within a couple of dozen turns.  Other
students' bots will not be, which is the point of keeping the other two.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from .perception import RivalView, Snapshot
from .rules import (ACTION_NAMES, DELTAS, MOVE, N_ACTIONS, STILL, TURN_TO,
                    is_turn, step)

EPS = 1e-9


def infer_action(previous: RivalView, current: RivalView) -> int:
    """Which of the six actions turned ``previous`` into ``current``?"""
    if (current.x, current.y) != (previous.x, previous.y):
        return MOVE
    if current.direction != previous.direction:
        return TURN_TO[current.direction]
    return STILL


def _normalise(weights: Sequence[float]) -> List[float]:
    total = sum(weights)
    if total <= 0:
        return [1.0 / N_ACTIONS] * N_ACTIONS
    return [w / total for w in weights]


class FrequencyModel:
    """Decayed marginal over the six actions."""

    name = "frequency"

    def __init__(self, decay: float = 0.985, prior: float = 0.6) -> None:
        self.counts = [prior] * N_ACTIONS
        self.decay = decay
        self.observations = 0

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        for i in range(N_ACTIONS):
            self.counts[i] *= self.decay
        self.counts[action] += 1.0
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        if self.observations < 3:
            return None
        return _normalise(self.counts)

    def describe(self) -> str:
        p = _normalise(self.counts)
        return " ".join(f"{ACTION_NAMES[i]}={p[i]:.2f}" for i in range(N_ACTIONS))


class SequenceModel:
    """Order-1/2 n-gram over the rival's own action stream."""

    name = "sequence"

    def __init__(self, decay: float = 0.99, prior: float = 0.4) -> None:
        self.tables: List[Dict[Tuple[int, ...], List[float]]] = [{}, {}, {}]
        self.history: Deque[int] = deque(maxlen=2)
        self.prior = prior
        self.decay = decay
        self.observations = 0

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        history = tuple(self.history)
        for order in range(min(len(history), 2) + 1):
            key = history[len(history) - order:] if order else ()
            row = self.tables[order].setdefault(key, [self.prior] * N_ACTIONS)
            for i in range(N_ACTIONS):
                row[i] *= self.decay
            row[action] += 1.0
        self.history.append(action)
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        if self.observations < 6:
            return None
        history = tuple(self.history)
        blended = [0.0] * N_ACTIONS
        total_weight = 0.0
        for order in range(min(len(history), 2), -1, -1):
            key = history[len(history) - order:] if order else ()
            row = self.tables[order].get(key)
            if not row:
                continue
            mass = sum(row)
            trust = min(1.0, mass / (3.0 + 2.0 * order))
            weight = trust * (5.0 ** order)
            for i in range(N_ACTIONS):
                blended[i] += weight * row[i] / mass
            total_weight += weight
        if total_weight <= 0:
            return None
        return _normalise(blended)

    def determinism(self) -> float:
        table = self.tables[2]
        if not table:
            return 0.0
        peak = mass = 0.0
        for row in table.values():
            row_mass = sum(row)
            if row_mass < 2.0:
                continue
            mass += row_mass
            peak += max(row)
        return peak / mass if mass > 0 else 0.0

    def describe(self) -> str:
        return f"order-2 determinism {self.determinism():.2f}"


class ContextModel:
    """What it does given what is in front of it.

    Discretised as ``(cabbage ahead?, player ahead?, cabbage under foot?)``,
    which is coarse on purpose - a fine context fragments the counts far more
    than it sharpens the prediction over a hundred-turn match.
    """

    name = "context"

    def __init__(self, decay: float = 0.99, prior: float = 0.5) -> None:
        self.table: Dict[Tuple[int, int, int], List[float]] = {}
        self.decay = decay
        self.prior = prior
        self.observations = 0

    @staticmethod
    def key(snapshot: Snapshot, rival: RivalView) -> Tuple[int, int, int]:
        ax, ay = step(rival.x, rival.y, rival.direction, snapshot.size)
        ahead_rival = snapshot.rival_at(ax, ay)
        return (1 if snapshot.has_cabbage(ax, ay) else 0,
                1 if ahead_rival is not None else 0,
                1 if snapshot.has_cabbage(rival.x, rival.y) else 0)

    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        row = self.table.setdefault(self.key(snapshot, rival),
                                    [self.prior] * N_ACTIONS)
        for i in range(N_ACTIONS):
            row[i] *= self.decay
        row[action] += 1.0
        self.observations += 1

    def predict(self, snapshot: Snapshot, rival: RivalView) -> Optional[List[float]]:
        row = self.table.get(self.key(snapshot, rival))
        if not row or sum(row) < 3.0:
            return None
        return _normalise(row)

    def describe(self) -> str:
        return f"{len(self.table)} contexts"


class RivalModel:
    """One rival's ensemble, its accuracy record, and its forecast."""

    def __init__(self, name: str, share: float = 0.04, floor: float = 0.005) -> None:
        self.name = name
        self.models = [FrequencyModel(), SequenceModel(), ContextModel()]
        self.weights = [1.0 / len(self.models)] * len(self.models)
        self.share = share
        self.floor = floor
        self.previous: Optional[RivalView] = None
        self.last_prediction: Optional[List[float]] = None
        self.hits: Deque[int] = deque(maxlen=40)
        self.log_losses: Deque[float] = deque(maxlen=60)
        self.observations = 0
        self.actions: Deque[int] = deque(maxlen=120)

    # ------------------------------------------------------------------
    def predict(self, snapshot: Snapshot, rival: RivalView) -> List[float]:
        blended = [0.0] * N_ACTIONS
        total = 0.0
        cache: List[Optional[List[float]]] = []
        for model, weight in zip(self.models, self.weights):
            try:
                distribution = model.predict(snapshot, rival)
            except Exception:
                distribution = None
            cache.append(distribution)
            if distribution is None:
                continue
            for i in range(N_ACTIONS):
                blended[i] += weight * distribution[i]
            total += weight
        self._cache = cache
        if total <= 0:
            # Before any evidence, assume the engine's own default bot: it is
            # what five of the six players on the board actually run.
            prior = [1.0 / 12.0] * 4 + [1.0 / 3.0, 1.0 / 3.0]
            self.last_prediction = prior
            return prior
        prediction = _normalise(blended)
        self.last_prediction = prediction
        return prediction

    # ------------------------------------------------------------------
    def observe(self, snapshot: Snapshot, rival: RivalView, action: int) -> None:
        cache = getattr(self, "_cache", None)
        if cache is None:
            cache = [m.predict(snapshot, rival) for m in self.models]

        if self.last_prediction is not None:
            top = max(range(N_ACTIONS), key=lambda a: self.last_prediction[a])
            self.hits.append(1 if top == action else 0)
            self.log_losses.append(-math.log(max(EPS, self.last_prediction[action])))

        total = 0.0
        for i, distribution in enumerate(cache):
            likelihood = (distribution[action] if distribution is not None
                          else 1.0 / N_ACTIONS)
            self.weights[i] *= (likelihood + self.floor)
            total += self.weights[i]
        n = len(self.models)
        if total <= 0:
            self.weights = [1.0 / n] * n
        else:
            # Fixed share: any model can climb back after a strategy change.
            self.weights = [(1.0 - self.share) * w / total + self.share / n
                            for w in self.weights]

        for model in self.models:
            try:
                model.observe(snapshot, rival, action)
            except Exception:
                pass
        self.actions.append(action)
        self.observations += 1
        self._cache = None

    # ------------------------------------------------------------------
    @property
    def accuracy(self) -> float:
        return sum(self.hits) / len(self.hits) if self.hits else 0.0

    @property
    def log_loss(self) -> float:
        return (sum(self.log_losses) / len(self.log_losses)
                if self.log_losses else math.log(N_ACTIONS))

    def confidence(self) -> float:
        """How much the planner should trust this model."""
        if self.observations < 4:
            return 0.0
        sample = min(1.0, self.observations / 15.0)
        calibration = max(0.0, 1.0 - self.log_loss / math.log(N_ACTIONS))
        return max(0.0, min(1.0, (0.55 * self.accuracy + 0.45 * calibration) * sample))

    def move_probability(self) -> float:
        """``P(this rival advances next turn)`` - the number the threat map needs."""
        if self.last_prediction is None:
            return 1.0 / 3.0
        return self.last_prediction[MOVE]

    def describe(self) -> str:  # pragma: no cover - diagnostics
        best = max(range(len(self.models)), key=lambda i: self.weights[i])
        prediction = self.last_prediction or [0.0] * N_ACTIONS
        top = sorted(range(N_ACTIONS), key=lambda a: -prediction[a])[:3]
        return (f"{self.name}: {self.models[best].name} (w={self.weights[best]:.2f}) "
                f"acc={self.accuracy:.0%} logloss={self.log_loss:.2f} "
                f"conf={self.confidence():.2f} | "
                + ", ".join(f"{ACTION_NAMES[a]} {prediction[a]:.0%}" for a in top))


class RivalRegistry:
    """One :class:`RivalModel` per rival, updated from consecutive snapshots."""

    def __init__(self) -> None:
        self.models: Dict[str, RivalModel] = {}
        self._previous: Dict[str, RivalView] = {}
        self._previous_snapshot: Optional[Snapshot] = None

    def model_for(self, name: str) -> RivalModel:
        model = self.models.get(name)
        if model is None:
            model = RivalModel(name)
            self.models[name] = model
        return model

    # ------------------------------------------------------------------
    def update(self, snapshot: Snapshot) -> None:
        """Learn from what every rival did since our last turn."""
        previous_snapshot = self._previous_snapshot
        seen = set()
        for rival in snapshot.rivals:
            seen.add(rival.name)
            before = self._previous.get(rival.name)
            if before is not None and previous_snapshot is not None:
                action = infer_action(before, rival)
                self.model_for(rival.name).observe(previous_snapshot, before, action)
            self._previous[rival.name] = rival
        for gone in set(self._previous) - seen:
            del self._previous[gone]
        self._previous_snapshot = snapshot

    def predict_all(self, snapshot: Snapshot) -> Dict[str, List[float]]:
        return {r.name: self.model_for(r.name).predict(snapshot, r)
                for r in snapshot.rivals}

    def mean_confidence(self, snapshot: Snapshot) -> float:
        if not snapshot.rivals:
            return 1.0
        return sum(self.model_for(r.name).confidence()
                   for r in snapshot.rivals) / len(snapshot.rivals)

    def describe(self, snapshot: Snapshot) -> str:  # pragma: no cover
        return "\n".join("  " + self.model_for(r.name).describe()
                         for r in snapshot.rivals)


__all__ = ["RivalModel", "RivalRegistry", "infer_action", "FrequencyModel",
           "SequenceModel", "ContextModel"]
