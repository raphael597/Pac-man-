"""Predictability measurement (brief sections 14 and 27).

The single most important output of the modelling layer is not a prediction -
it is an honest answer to *"how much should the planner trust this
prediction?"*.  A bot that treats a coin flip as a certainty will walk into
the coin flip.

Three complementary signals are tracked and fused:

* **Accuracy** - rolling top-1 hit rate, short and long window.
* **Calibration** - rolling log loss and Brier score against the full
  predicted distribution, which punishes confident wrongness far harder than
  hit rate does.
* **Entropy** - how peaked our own predictions are.  Sharp *and* accurate is
  exploitable; sharp and wrong is dangerous; flat is simply unknown.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Deque, List, Optional, Sequence, Tuple

EPS = 1e-9


class PredictionScorer:
    """Rolling accuracy, log loss and Brier score over one opponent."""

    def __init__(self, short_window: int = 20, long_window: int = 120) -> None:
        self.short: Deque[int] = deque(maxlen=short_window)
        self.long: Deque[int] = deque(maxlen=long_window)
        self.log_losses: Deque[float] = deque(maxlen=long_window)
        self.briers: Deque[float] = deque(maxlen=long_window)
        self.entropies: Deque[float] = deque(maxlen=long_window)
        self.total = 0

    # ------------------------------------------------------------------
    def record(self, predicted: Sequence[float], action: int,
               legal: Sequence[int]) -> None:
        self.total += 1
        top = max(range(5), key=lambda a: predicted[a])
        hit = 1 if top == action else 0
        self.short.append(hit)
        self.long.append(hit)

        p = max(EPS, min(1.0, predicted[action]))
        self.log_losses.append(-math.log(p))

        brier = sum((predicted[a] - (1.0 if a == action else 0.0)) ** 2
                    for a in range(5))
        self.briers.append(brier)

        entropy = -sum(predicted[a] * math.log(predicted[a] + EPS)
                       for a in range(5) if predicted[a] > 0)
        max_entropy = math.log(max(2, len(legal)))
        self.entropies.append(entropy / max_entropy if max_entropy > 0 else 1.0)

    # ------------------------------------------------------------------
    @property
    def short_accuracy(self) -> float:
        return sum(self.short) / len(self.short) if self.short else 0.0

    @property
    def long_accuracy(self) -> float:
        return sum(self.long) / len(self.long) if self.long else 0.0

    @property
    def log_loss(self) -> float:
        return sum(self.log_losses) / len(self.log_losses) if self.log_losses else 1.6

    @property
    def brier(self) -> float:
        return sum(self.briers) / len(self.briers) if self.briers else 1.0

    @property
    def mean_entropy(self) -> float:
        return sum(self.entropies) / len(self.entropies) if self.entropies else 1.0

    # ------------------------------------------------------------------
    def confidence(self) -> float:
        """One number in ``[0, 1]`` for "how much to trust this model".

        Deliberately conservative early: with fewer than eight observations
        the sample-size term dominates and confidence stays low no matter how
        good the hit rate looks, because three-for-three means nothing.
        """
        if self.total < 3:
            return 0.0
        sample = min(1.0, self.total / 12.0)
        # Recent behaviour matters more than ancient history, but not so much
        # that a two-move fluke rewrites the assessment.
        accuracy = 0.62 * self.short_accuracy + 0.38 * self.long_accuracy
        # Log loss of ln(4)~1.386 is "no better than guessing among 4".
        calibration = max(0.0, 1.0 - self.log_loss / 1.386)
        sharpness = 1.0 - self.mean_entropy
        raw = 0.45 * accuracy + 0.35 * calibration + 0.20 * sharpness
        return max(0.0, min(1.0, raw * sample))

    def is_erratic(self) -> bool:
        """True when this rival should be planned *around*, not predicted."""
        return self.total >= 10 and self.confidence() < 0.28

    def describe(self) -> str:  # pragma: no cover - diagnostics
        return (f"acc {self.short_accuracy:.0%}/{self.long_accuracy:.0%} "
                f"logloss {self.log_loss:.2f} brier {self.brier:.2f} "
                f"conf {self.confidence():.2f}")


class OscillationDetector:
    """Spots a rival bouncing between two cells - a stuck or trapped bot.

    Worth knowing about: an oscillating rival is both harmless (it is going
    nowhere) and a free kill (its next cell is nearly certain).
    """

    def __init__(self, window: int = 12) -> None:
        self.positions: Deque[int] = deque(maxlen=window)

    def observe(self, cell: int) -> None:
        self.positions.append(cell)

    def score(self) -> float:
        if len(self.positions) < 6:
            return 0.0
        unique = len(set(self.positions))
        return max(0.0, 1.0 - (unique - 1) / (len(self.positions) / 2.0))

    def is_oscillating(self) -> bool:
        return self.score() > 0.6


__all__ = ["PredictionScorer", "OscillationDetector"]
