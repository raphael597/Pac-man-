"""Competing explanations of an opponent's policy, mixed by evidence.

Brief sections 13, 14 and 27.  Rather than committing to one theory of what a
rival is doing, SUPERPAC keeps a handful of *hypotheses* alive at once, scores
each one on how well it predicted what actually happened, and blends them by
those scores.

The two design decisions that make this work:

**Fixed-share weight updating.**  A plain Bayesian product collapses onto one
hypothesis and can never recover, which is fatal against a bot that switches
strategy at turn 40 (:class:`ModeSwitchBot` does exactly that).  After each
multiplicative update a small share of the total weight is redistributed
uniformly, so a hypothesis that has been wrong for fifty turns can climb back
within a few observations.  This is the standard tracking-the-best-expert
trick and it is the difference between adapting and being stuck.

**An honest ignorance hypothesis.**  ``UniformHypothesis`` is always in the
mix.  When nothing explains a rival, the mixture correctly flattens out
instead of manufacturing false confidence - which is what lets the planner
switch to robust play rather than exploitation.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE
from ..game.rules import ACTION_NAMES, ALL_ACTIONS, OPPOSITE
from .context_model import ContextPolicyModel, ObservationContext
from .periodicity import AnomalyDetector, CycleDetector
from .sequence_model import NGramModel

EPS = 1e-9


def _normalise(dist: List[float], legal: Sequence[int]) -> List[float]:
    out = [0.0] * 5
    total = 0.0
    for a in legal:
        v = dist[a]
        if v > 0:
            out[a] = v
            total += v
    if total <= 0:
        share = 1.0 / max(1, len(legal))
        return [share if a in legal else 0.0 for a in range(5)]
    return [v / total for v in out]


def _peaked(action: int, legal: Sequence[int], confidence: float) -> List[float]:
    """A distribution spiking on ``action`` with the rest spread over legals."""
    if action not in legal:
        share = 1.0 / max(1, len(legal))
        return [share if a in legal else 0.0 for a in range(5)]
    rest = (1.0 - confidence) / max(1, len(legal))
    return [(confidence if a == action else 0.0) + (rest if a in legal else 0.0)
            for a in range(5)]


# --------------------------------------------------------------------------
# Hypotheses
# --------------------------------------------------------------------------
class Hypothesis:
    """One theory about how a rival picks its moves."""

    name = "hypothesis"

    def predict(self, ctx: ObservationContext) -> Optional[List[float]]:
        raise NotImplementedError

    def observe(self, ctx: ObservationContext, action: int) -> None:
        """Learning hypotheses update here; fixed ones ignore it."""

    def describe(self) -> str:
        return self.name


class UniformHypothesis(Hypothesis):
    """"I have no idea."  Its job is to win when nothing else deserves to."""

    name = "random"

    def predict(self, ctx):
        share = 1.0 / max(1, len(ctx.legal))
        return [share if a in ctx.legal else 0.0 for a in range(5)]


class GreedyFoodHypothesis(Hypothesis):
    """Beelines for the nearest pellet, ignoring everyone else."""

    name = "greedy_food"

    def __init__(self, sharpness: float = 0.82) -> None:
        self.sharpness = sharpness

    def predict(self, ctx):
        if ctx.food_dist >= UNREACHABLE:
            return None
        return _peaked(ctx.food_action, ctx.legal, self.sharpness)


class MomentumHypothesis(Hypothesis):
    """Keeps going the way it was going - corridors make this common."""

    name = "momentum"

    def predict(self, ctx):
        if ctx.last_action == 4 or ctx.last_action not in ctx.legal:
            return None
        return _peaked(ctx.last_action, ctx.legal, 0.70)


class HunterHypothesis(Hypothesis):
    """Closes on the nearest rival once inside an engagement range."""

    name = "hunter"

    def __init__(self, engage: int = 8) -> None:
        self.engage = engage

    def predict(self, ctx):
        if ctx.enemy_dist >= UNREACHABLE or ctx.enemy_dist > self.engage:
            return None
        return _peaked(ctx.enemy_action, ctx.legal, 0.72)


class AvoiderHypothesis(Hypothesis):
    """Always runs, whether or not anything is actually close."""

    name = "avoider"

    def predict(self, ctx):
        if ctx.rival_dist is None:
            return None
        return _peaked(ctx.flee_action, ctx.legal, 0.68)


class EscapeThresholdHypothesis(Hypothesis):
    """Greedy until a rival comes within ``threshold``, then flees.

    The threshold is not assumed - a posterior over candidate values is
    maintained and updated by how well each one explained the last move.  That
    is what lets SUPERPAC report "estimated escape threshold: distance <= 3"
    (brief section 59) and then deliberately sit just outside it.
    """

    name = "greedy_escape"
    CANDIDATES = (1, 2, 3, 4, 5, 6, 8)

    def __init__(self) -> None:
        n = len(self.CANDIDATES)
        self.posterior: List[float] = [1.0 / n] * n
        self.samples = 0

    # -- per-threshold policy -------------------------------------------
    def _policy(self, ctx: ObservationContext, threshold: int) -> Optional[List[float]]:
        if ctx.enemy_dist <= threshold and ctx.rival_dist is not None:
            return _peaked(ctx.flee_action, ctx.legal, 0.76)
        if ctx.food_dist >= UNREACHABLE:
            return None
        return _peaked(ctx.food_action, ctx.legal, 0.78)

    def predict(self, ctx):
        blended = [0.0] * 5
        total = 0.0
        for weight, threshold in zip(self.posterior, self.CANDIDATES):
            sub = self._policy(ctx, threshold)
            if sub is None:
                continue
            for a in range(5):
                blended[a] += weight * sub[a]
            total += weight
        if total <= 0:
            return None
        return _normalise([v / total for v in blended], ctx.legal)

    def observe(self, ctx, action):
        likelihoods: List[float] = []
        for threshold in self.CANDIDATES:
            sub = self._policy(ctx, threshold)
            likelihoods.append(sub[action] if sub else 0.2)
        total = 0.0
        for i, lik in enumerate(likelihoods):
            self.posterior[i] *= (lik + 0.05)
            total += self.posterior[i]
        if total > 0:
            # Floor every candidate: a threshold ruled out early must be able
            # to come back if the rival's behaviour changes.
            n = len(self.CANDIDATES)
            for i in range(n):
                self.posterior[i] = 0.97 * self.posterior[i] / total + 0.03 / n
        self.samples += 1

    def best_threshold(self) -> Tuple[int, float]:
        idx = max(range(len(self.CANDIDATES)), key=lambda i: self.posterior[i])
        return self.CANDIDATES[idx], self.posterior[idx]

    def describe(self):
        threshold, confidence = self.best_threshold()
        return f"greedy_escape(flee at d<={threshold}, p={confidence:.2f})"


class PriorityHypothesis(Hypothesis):
    """Learns a fixed directional preference order from what it picks.

    Counts each action's wins *relative to how often it was even available*,
    so a bot in a map full of eastward corridors is not mistaken for one with
    an EAST preference.
    """

    name = "fixed_priority"

    def __init__(self) -> None:
        self.chosen = [0.0] * 5
        self.available = [0.0] * 5

    def observe(self, ctx, action):
        for a in ctx.legal:
            self.available[a] += 1.0
        self.chosen[action] += 1.0

    def predict(self, ctx):
        if sum(self.chosen) < 6:
            return None
        rates = [self.chosen[a] / self.available[a] if self.available[a] > 0 else 0.0
                 for a in range(5)]
        legal_rates = [(rates[a], a) for a in ctx.legal]
        if not legal_rates:
            return None
        top_rate = max(r for r, _ in legal_rates)
        if top_rate < 0.55:
            return None  # no real preference to speak of
        best = max(legal_rates)[1]
        return _peaked(best, ctx.legal, min(0.88, top_rate))

    def order(self) -> List[int]:
        rates = [(self.chosen[a] / self.available[a] if self.available[a] else 0.0, a)
                 for a in range(5)]
        return [a for _, a in sorted(rates, reverse=True)]

    def describe(self):
        return "priority(" + ">".join(ACTION_NAMES[a][0] for a in self.order()) + ")"


class ContextHypothesis(Hypothesis):
    """Wraps the learned state-conditioned frequency tables."""

    name = "context"

    def __init__(self) -> None:
        self.model = ContextPolicyModel()

    def predict(self, ctx):
        if self.model.observations < 6:
            return None
        return self.model.predict(ctx)

    def observe(self, ctx, action):
        self.model.observe(ctx, action)

    def describe(self):
        return f"context({self.model.observations} obs, {self.model.size()} rows)"


class SequenceHypothesis(Hypothesis):
    """Wraps the backed-off n-gram over the raw action stream."""

    name = "ngram"

    def __init__(self, order: int = 3) -> None:
        self.model = NGramModel(order)

    def predict(self, ctx):
        if self.model.observations < 5:
            return None
        return self.model.predict(ctx.legal)

    def observe(self, ctx, action):
        self.model.observe(action)

    def describe(self):
        return f"ngram(det={self.model.determinism():.2f})"


class CycleHypothesis(Hypothesis):
    name = "cycle"

    def __init__(self) -> None:
        self.model = CycleDetector()

    def predict(self, ctx):
        return self.model.predict(ctx.legal)

    def observe(self, ctx, action):
        self.model.observe(action)

    def describe(self):
        return f"cycle(period={self.model.period}, s={self.model.strength:.2f})"


class PeriodicHypothesis(Hypothesis):
    name = "periodic"

    def __init__(self) -> None:
        self.model = AnomalyDetector()

    def predict(self, ctx):
        return self.model.predict(ctx.legal)

    def observe(self, ctx, action):
        self.model.observe(action, ctx.turn)

    def describe(self):
        return self.model.describe()


# --------------------------------------------------------------------------
# The ensemble
# --------------------------------------------------------------------------
class HypothesisEnsemble:
    """Weighted mixture over hypotheses with fixed-share tracking."""

    def __init__(self, share: float = 0.035, floor: float = 0.004) -> None:
        self.hypotheses: List[Hypothesis] = [
            UniformHypothesis(),
            GreedyFoodHypothesis(),
            EscapeThresholdHypothesis(),
            MomentumHypothesis(),
            HunterHypothesis(),
            AvoiderHypothesis(),
            PriorityHypothesis(),
            ContextHypothesis(),
            SequenceHypothesis(),
            CycleHypothesis(),
            PeriodicHypothesis(),
        ]
        n = len(self.hypotheses)
        self.weights: List[float] = [1.0 / n] * n
        self.share = share
        self.floor = floor
        self._last_predictions: Optional[List[Optional[List[float]]]] = None

    # ------------------------------------------------------------------
    def predict(self, ctx: ObservationContext) -> List[float]:
        blended = [0.0] * 5
        total = 0.0
        preds: List[Optional[List[float]]] = []
        for hyp, weight in zip(self.hypotheses, self.weights):
            try:
                dist = hyp.predict(ctx)
            except Exception:
                dist = None
            preds.append(dist)
            if dist is None:
                continue
            for a in range(5):
                blended[a] += weight * dist[a]
            total += weight
        self._last_predictions = preds
        if total <= 0:
            share = 1.0 / max(1, len(ctx.legal))
            return [share if a in ctx.legal else 0.0 for a in range(5)]
        return _normalise([v / total for v in blended], ctx.legal)

    # ------------------------------------------------------------------
    def observe(self, ctx: ObservationContext, action: int) -> None:
        """Score each hypothesis on the move that actually happened, then learn."""
        preds = self._last_predictions
        if preds is None:
            preds = []
            for hyp in self.hypotheses:
                try:
                    preds.append(hyp.predict(ctx))
                except Exception:
                    preds.append(None)

        n = len(self.hypotheses)
        total = 0.0
        for i, dist in enumerate(preds):
            # A hypothesis that declined to predict is neither rewarded nor
            # punished: it gets the mixture's own average likelihood.
            likelihood = dist[action] if dist is not None else 1.0 / max(1, len(ctx.legal))
            self.weights[i] *= (likelihood + self.floor)
            total += self.weights[i]

        if total <= 0:
            self.weights = [1.0 / n] * n
        else:
            share = self.share
            for i in range(n):
                self.weights[i] = (1.0 - share) * self.weights[i] / total + share / n

        for hyp in self.hypotheses:
            try:
                hyp.observe(ctx, action)
            except Exception:
                pass
        self._last_predictions = None

    # ------------------------------------------------------------------
    def ranked(self, top: int = 4) -> List[Tuple[str, float, str]]:
        pairs = sorted(zip(self.hypotheses, self.weights),
                       key=lambda hw: -hw[1])[:top]
        return [(h.name, w, h.describe()) for h, w in pairs]

    def best(self) -> Tuple[str, float]:
        idx = max(range(len(self.weights)), key=lambda i: self.weights[i])
        return self.hypotheses[idx].name, self.weights[idx]

    def get(self, name: str) -> Optional[Hypothesis]:
        for hyp in self.hypotheses:
            if hyp.name == name:
                return hyp
        return None

    def concentration(self) -> float:
        """1 - normalised entropy of the weights: how settled the theory is."""
        n = len(self.weights)
        entropy = -sum(w * math.log(w + EPS) for w in self.weights if w > 0)
        return 1.0 - entropy / math.log(n)


__all__ = ["HypothesisEnsemble", "Hypothesis", "UniformHypothesis",
           "GreedyFoodHypothesis", "EscapeThresholdHypothesis",
           "PriorityHypothesis", "ContextHypothesis", "SequenceHypothesis",
           "CycleHypothesis", "PeriodicHypothesis", "HunterHypothesis",
           "AvoiderHypothesis", "MomentumHypothesis"]
