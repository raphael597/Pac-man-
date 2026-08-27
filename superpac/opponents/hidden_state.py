"""Latent behavioural mode inference (brief section 16).

A small forward-filtering HMM over six explanatory modes.  These are *not*
claims about the rival's real internal variables - they are the coarsest
description that changes how we should play against it, which is all we need.

Emissions are how well each mode's canonical policy explained the move that
actually happened; transitions are sticky, so a single odd move does not flip
the diagnosis.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

from ..game.map_model import UNREACHABLE
from .context_model import ObservationContext

COLLECT, ATTACK, ESCAPE, EXPLORE, RANDOM, ENDGAME = range(6)
MODE_NAMES = ("COLLECT", "ATTACK", "ESCAPE", "EXPLORE", "RANDOM", "ENDGAME")


class ModeClassifier:
    """Sticky belief over the six modes, updated once per observed move."""

    def __init__(self, stickiness: float = 0.86) -> None:
        n = len(MODE_NAMES)
        self.belief: List[float] = [1.0 / n] * n
        self.stickiness = stickiness

    # ------------------------------------------------------------------
    def _emissions(self, ctx: ObservationContext, action: int) -> List[float]:
        legal = ctx.legal
        share = 1.0 / max(1, len(legal))
        hit = 0.80
        miss = (1.0 - hit) / max(1, len(legal))

        def score(preferred: int) -> float:
            if preferred not in legal:
                return share
            return hit + miss if action == preferred else miss

        collect = score(ctx.food_action) if ctx.food_dist < UNREACHABLE else share
        attack = score(ctx.enemy_action) if ctx.enemy_dist < UNREACHABLE else share
        escape = score(ctx.flee_action) if ctx.rival_dist is not None else share

        # EXPLORE: keeps moving and prefers open cells over cramped ones.
        graph = ctx.state.graph
        degrees = [graph.degree[graph.step(ctx.pos, a)] for a in legal]
        total_degree = sum(degrees) or 1
        explore = share
        for a, deg in zip(legal, degrees):
            if a == action:
                explore = 0.35 * share + 0.65 * deg / total_degree
                if action == 4:
                    explore *= 0.3  # standing still is not exploring
                break

        endgame = 0.5 * collect + 0.5 * escape
        return [collect, attack, escape, explore, share, endgame]

    # ------------------------------------------------------------------
    def observe(self, ctx: ObservationContext, action: int) -> None:
        n = len(self.belief)
        stay = self.stickiness
        leak = (1.0 - stay) / (n - 1)
        # transition
        moved = [stay * self.belief[i] + leak * (1.0 - self.belief[i])
                 for i in range(n)]
        # emission
        emissions = self._emissions(ctx, action)
        posterior = [moved[i] * emissions[i] for i in range(n)]
        total = sum(posterior)
        if total <= 0:
            self.belief = [1.0 / n] * n
        else:
            self.belief = [p / total for p in posterior]

    # ------------------------------------------------------------------
    def mode(self) -> int:
        return max(range(len(self.belief)), key=lambda i: self.belief[i])

    def mode_name(self) -> str:
        return MODE_NAMES[self.mode()]

    def certainty(self) -> float:
        return self.belief[self.mode()]

    def describe(self) -> str:  # pragma: no cover - diagnostics
        pairs = sorted(zip(MODE_NAMES, self.belief), key=lambda p: -p[1])[:3]
        return " ".join(f"{name}={value:.2f}" for name, value in pairs)


__all__ = ["ModeClassifier", "MODE_NAMES", "COLLECT", "ATTACK", "ESCAPE",
           "EXPLORE", "RANDOM", "ENDGAME"]
