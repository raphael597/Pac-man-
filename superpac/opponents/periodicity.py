"""Periodicity and cycle detection (brief section 11).

Two independent detectors, because the two bots the brief describes are
structurally different:

``CycleDetector``
    Finds a period ``p`` where ``a[t] == a[t-p]`` holds often - catches an
    outright repeating script.

``AnomalyDetector``
    Finds a dominant action plus a roughly regular *interruption*, i.e.
    ``if turn % 15 == 0: random() else: right()``.  The interval is allowed
    to be noisy: the brief is explicit that a fixed period must not be a
    requirement, so this tracks mean and variance and reports a probability,
    never a certainty.
"""

from __future__ import annotations

import math
from collections import deque

from ..game.rules import ACTION_NAMES
from typing import Deque, List, Optional, Sequence, Tuple


class CycleDetector:
    """Autocorrelation over the action history to find a repeating period."""

    def __init__(self, max_period: int = 24, window: int = 90,
                 min_samples: int = 8) -> None:
        self.max_period = max_period
        self.window = window
        self.min_samples = min_samples
        self.history: Deque[int] = deque(maxlen=window)
        self.period: Optional[int] = None
        self.strength: float = 0.0

    def observe(self, action: int) -> None:
        self.history.append(action)
        if len(self.history) >= self.min_samples * 2:
            self._recompute()

    def _recompute(self) -> None:
        seq = list(self.history)
        n = len(seq)
        best_period, best_score = None, 0.0
        for period in range(2, min(self.max_period, n // 2) + 1):
            matches = comparisons = 0
            for i in range(period, n):
                comparisons += 1
                if seq[i] == seq[i - period]:
                    matches += 1
            if comparisons < self.min_samples:
                continue
            rate = matches / comparisons
            # Prefer short periods when two explain the data equally well:
            # period 12 is usually period 6 counted twice.
            score = rate - 0.012 * period
            if score > best_score:
                best_period, best_score = period, score
        if best_period is not None and best_score > 0.55:
            self.period, self.strength = best_period, best_score
        else:
            self.period, self.strength = None, max(0.0, best_score)

    def predict(self, legal: Sequence[int]) -> Optional[List[float]]:
        """Distribution implied by the cycle, or ``None`` if none was found."""
        if self.period is None or len(self.history) < self.period:
            return None
        recalled = self.history[len(self.history) - self.period]
        if recalled not in legal:
            return None
        confidence = min(0.95, self.strength)
        spread = (1.0 - confidence) / len(legal)
        return [(confidence if a == recalled else 0.0) + (spread if a in legal else 0.0)
                for a in range(5)]


class AnomalyDetector:
    """Dominant action plus a noisy-periodic interruption."""

    def __init__(self, window: int = 140) -> None:
        self.counts = [0.0] * 5
        self.gaps: Deque[int] = deque(maxlen=24)
        self.turns_since: int = 0
        self.last_anomaly_turn: Optional[int] = None
        self.observations = 0
        self.window = window
        self.dominant: int = -1
        self.dominant_share: float = 0.0

    # ------------------------------------------------------------------
    def observe(self, action: int, turn: int) -> None:
        self.observations += 1
        for i in range(5):
            self.counts[i] *= 0.995
        self.counts[action] += 1.0
        total = sum(self.counts)
        self.dominant = max(range(5), key=lambda a: self.counts[a])
        self.dominant_share = self.counts[self.dominant] / total if total else 0.0

        if self.observations < 4:
            self.turns_since += 1
            return
        if action != self.dominant and self.dominant_share > 0.5:
            if self.last_anomaly_turn is not None:
                gap = turn - self.last_anomaly_turn
                if 1 <= gap <= 120:
                    self._record_gap(gap)
            self.last_anomaly_turn = turn
            self.turns_since = 0
        else:
            self.turns_since += 1

    # ------------------------------------------------------------------
    def _record_gap(self, gap: int) -> None:
        self.gaps.append(gap)

    def interval_stats(self) -> Tuple[float, float, float]:
        """``(mean, stdev, confidence)`` of the anomaly interval."""
        if len(self.gaps) < 3:
            return 0.0, 0.0, 0.0
        gaps = list(self.gaps)

        # An anomaly that happens to pick the dominant action is invisible, so
        # an observed gap is always the true period times some integer - never
        # a fraction of it.  That makes the *smallest* observed gap the robust
        # period estimate, and lets every longer gap be folded back onto it.
        # Averaging the raw gaps instead reports 18 for a true period of 15.
        base = min(gaps)
        normalised: List[float] = []
        misfits = 0
        if base >= 2:
            for gap in gaps:
                k = max(1, int(round(gap / base)))
                if abs(gap - k * base) <= max(1.0, 0.30 * base):
                    normalised.append(gap / k)
                else:
                    misfits += 1
        if len(normalised) < 3:
            normalised, misfits = [float(g) for g in gaps], 0

        mean = sum(normalised) / len(normalised)
        var = sum((g - mean) ** 2 for g in normalised) / len(normalised)
        sd = math.sqrt(var)
        # Confidence rises with sample count, falls with relative spread, and
        # falls again when gaps refuse to fit the multiple structure at all.
        regularity = 1.0 / (1.0 + sd / max(1.0, mean) * 3.0)
        sample_conf = min(1.0, len(gaps) / 6.0)
        fit = 1.0 - misfits / max(1, len(gaps))
        return mean, sd, regularity * sample_conf * fit

    def anomaly_probability(self) -> float:
        """Chance the *next* action breaks the dominant pattern."""
        mean, sd, confidence = self.interval_stats()
        if confidence <= 0.0 or mean <= 0.0:
            return 0.0
        # A Gaussian bump around the expected interval, widened by the
        # observed spread so a jittery bot does not produce a spike.
        elapsed = self.turns_since + 1
        sigma = max(0.9, sd)
        z = (elapsed - mean) / sigma
        peak = math.exp(-0.5 * z * z)
        # Overdue is more suspicious than early, never less.
        if elapsed > mean:
            peak = max(peak, min(0.9, 0.45 + 0.1 * (elapsed - mean)))
        return min(0.95, peak * confidence)

    def predict(self, legal: Sequence[int]) -> Optional[List[float]]:
        if self.dominant_share < 0.5 or self.dominant not in legal:
            return None
        _, _, confidence = self.interval_stats()
        if confidence < 0.15:
            return None
        p_anomaly = self.anomaly_probability()
        out = [0.0] * 5
        others = [a for a in legal if a != self.dominant]
        out[self.dominant] = 1.0 - p_anomaly
        if others:
            for a in others:
                out[a] = p_anomaly / len(others)
        else:
            out[self.dominant] = 1.0
        total = sum(out)
        return [v / total for v in out] if total > 0 else None

    def describe(self) -> str:  # pragma: no cover - diagnostics
        mean, sd, conf = self.interval_stats()
        if conf <= 0:
            return "no periodic anomaly detected"
        return (f"dominant={ACTION_NAMES[self.dominant]} ({self.dominant_share:.0%}) "
                f"interval~{mean:.1f}+-{sd:.1f} since={self.turns_since} "
                f"P(anomaly next)={self.anomaly_probability():.0%} conf={conf:.2f}")


__all__ = ["CycleDetector", "AnomalyDetector"]
