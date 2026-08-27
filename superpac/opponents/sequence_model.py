"""Backed-off n-gram model over an opponent's action sequence (section 10).

Catches scripted behaviour that no state-conditioned model sees, e.g. the
``R R U R R U`` loop of :class:`PatternBot`: given the last two actions the
next one is certain, but the marginal distribution looks like plain noise.
"""

from __future__ import annotations

from collections import deque
from typing import Deque, Dict, List, Optional, Sequence, Tuple


class NGramModel:
    """Orders 1..``max_order`` with stupid-backoff style interpolation."""

    def __init__(self, max_order: int = 3, decay: float = 0.995,
                 prior: float = 0.30) -> None:
        self.max_order = max_order
        self.decay = decay
        self.prior = prior
        # tables[k] maps a k-length action tuple -> counts over next actions
        self.tables: List[Dict[Tuple[int, ...], List[float]]] = [
            {} for _ in range(max_order + 1)
        ]
        self.history: Deque[int] = deque(maxlen=max_order)
        self.observations = 0

    # ------------------------------------------------------------------
    def observe(self, action: int) -> None:
        hist = tuple(self.history)
        for order in range(min(len(hist), self.max_order) + 1):
            key = hist[len(hist) - order:] if order else ()
            table = self.tables[order]
            row = table.get(key)
            if row is None:
                row = [0.0] * 5
                table[key] = row
            if self.decay < 1.0:
                for i in range(5):
                    row[i] *= self.decay
            row[action] += 1.0
        self.history.append(action)
        self.observations += 1

    # ------------------------------------------------------------------
    def predict(self, legal: Sequence[int]) -> List[float]:
        hist = tuple(self.history)
        blended = [0.0] * 5
        weight_total = 0.0
        # Longest context first; a long context that fires is far more
        # informative than the marginal, hence the steep weight.
        for order in range(min(len(hist), self.max_order), -1, -1):
            key = hist[len(hist) - order:] if order else ()
            row = self.tables[order].get(key)
            if row is None:
                continue
            mass = sum(row)
            if mass < 1.0:
                continue
            trust = min(1.0, mass / (2.0 + order))
            weight = trust * (4.0 ** order)
            for i in range(5):
                blended[i] += weight * row[i] / mass
            weight_total += weight

        out = [0.0] * 5
        for action in legal:
            base = blended[action] / weight_total if weight_total > 0 else 0.0
            out[action] = base + self.prior / len(legal)
        total = sum(out)
        if total <= 0:
            share = 1.0 / len(legal)
            return [share if a in legal else 0.0 for a in range(5)]
        return [v / total for v in out]

    # ------------------------------------------------------------------
    def determinism(self) -> float:
        """How close the longest-context table is to being a lookup table.

        1.0 means "given the last ``max_order`` actions, the next one is
        fixed" - the signature of a scripted bot.
        """
        table = self.tables[self.max_order]
        if not table:
            return 0.0
        total_mass = 0.0
        peak_mass = 0.0
        for row in table.values():
            mass = sum(row)
            if mass < 2.0:
                continue
            total_mass += mass
            peak_mass += max(row)
        return peak_mass / total_mass if total_mass > 0 else 0.0

    def prune(self, max_rows: int = 700) -> None:
        for order in range(self.max_order + 1):
            table = self.tables[order]
            if len(table) <= max_rows:
                continue
            ordered = sorted(table.items(), key=lambda kv: sum(kv[1]))
            for key, _ in ordered[: len(table) - max_rows]:
                del table[key]


__all__ = ["NGramModel"]
