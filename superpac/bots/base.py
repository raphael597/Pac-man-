"""The bot interface every player in the simulator implements."""

from __future__ import annotations

import random
from typing import Optional

from ..game.state import GameState


class Bot:
    """Minimal contract: see a state, return a legal action.

    Bots are long-lived objects - one instance plays a whole match - which
    mirrors the usual shape of this exercise and is what lets SUPERPAC carry
    opponent models across turns.
    """

    name: str = "bot"

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rng = random.Random(seed)
        self.player_id: int = 0

    def reset(self, state: GameState, player_id: int) -> None:
        """Called once before the first move of a match."""
        self.player_id = player_id

    def act(self, state: GameState) -> int:
        raise NotImplementedError

    # -- helpers shared by the simple bots -----------------------------
    def legal(self, state: GameState):
        return state.legal_actions(state.me)

    def random_legal(self, state: GameState) -> int:
        return self.rng.choice(self.legal(state))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.name}>"


class BotFactory:
    """Picklable ``() -> Bot`` factory.

    The benchmarks and the optimiser fan out across processes, and a lambda
    cannot cross a process boundary.  This is the smallest thing that can.
    """

    __slots__ = ("cls", "kwargs", "label")

    def __init__(self, cls, label: Optional[str] = None, **kwargs) -> None:
        self.cls = cls
        self.kwargs = kwargs
        self.label = label or getattr(cls, "name", cls.__name__)

    def __call__(self):
        return self.cls(**self.kwargs)

    def entry(self):
        """``(name, factory)`` pair as the tournament helpers expect."""
        return (self.label, self)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BotFactory {self.label}>"


__all__ = ["Bot", "BotFactory"]
