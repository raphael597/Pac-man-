"""Run matches on the teacher's *actual* engine.

Not a re-implementation: this imports ``Pacman.py`` and drives the real
``Field``, so anything measured here is measured against the code that will
run in the tournament.  The only thing it changes is *which* class fills the
last seat, so different bots can be compared on identical boards.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field as dataclass_field
from typing import Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class MatchResult:
    strengths: Dict[str, float]
    alive: Dict[str, bool]
    turns: int
    subject: str
    subject_strength: float = 0.0
    subject_alive: bool = True
    subject_rank: int = 0
    """0 = highest strength on the board."""
    kills: int = 0
    faults: int = 0
    ms_per_turn: float = 0.0

    @property
    def won(self) -> bool:
        return self.subject_rank == 0


def _rank_of(name: str, strengths: Dict[str, float]) -> int:
    mine = strengths[name]
    return sum(1 for other, value in strengths.items()
               if other != name and value > mine)


def play(subject_factory: Optional[Callable] = None, seed: int = 0,
         fieldsize: int = 15, turns: int = 100,
         subject_name: str = "T",
         fillers: Optional[Sequence[Callable]] = None) -> MatchResult:
    """One match on the real engine.

    ``subject_factory(position, name, field)`` builds the player under test.
    Passing ``None`` leaves whatever ``Pacman.ThoresT`` currently is - which
    in this repository is the shipped bot, since ``Pacman.py`` *is* the
    deliverable. To benchmark a different player, pass its class.

    ``fillers`` replaces the five default random bots, cycled over the seats.
    The replacements are swapped in *after* ``Field.__init__`` has run, at the
    same positions - rather than by patching ``Pacman.Pacman``, which would
    break the engine's own ``isinstance`` checks during combat and silently
    stop fights from resolving at all.
    """
    import Pacman

    random.seed(seed)
    original = Pacman.ThoresT
    if subject_factory is not None:
        Pacman.ThoresT = subject_factory
    try:
        board = Pacman.Field(fieldsize)
        subject = board.pacmans[-1]
        if fillers:
            for i, existing in enumerate(board.pacmans[:-1]):
                factory = fillers[i % len(fillers)]
                if factory is None or factory is Pacman.Pacman:
                    continue
                replacement = factory(existing.position, existing.name,
                                      board.field)
                board.field[existing.position] = replacement
                board.pacmans[i] = replacement

        for _ in range(turns):
            for pacman in board.pacmans:
                if pacman.alive:
                    pacman.TurnOrMoveOrStill()

        strengths = {p.name: float(p.strength) for p in board.pacmans}
        alive = {p.name: bool(p.alive) for p in board.pacmans}
        brain = getattr(subject, "brain", None)
        dead_rivals = sum(1 for p in board.pacmans
                          if p is not subject and not p.alive)
        return MatchResult(
            strengths=strengths, alive=alive, turns=turns,
            subject=subject.name,
            subject_strength=float(subject.strength),
            subject_alive=bool(subject.alive),
            subject_rank=_rank_of(subject.name, strengths),
            kills=dead_rivals,
            faults=getattr(brain, "faults", 0),
            ms_per_turn=(brain.total_ms / max(1, brain.turn)) if brain else 0.0,
        )
    finally:
        Pacman.ThoresT = original


@dataclass
class Report:
    label: str
    games: int = 0
    wins: int = 0
    strength_sum: float = 0.0
    survived: int = 0
    rank_sum: int = 0
    kills: int = 0
    faults: int = 0
    ms_sum: float = 0.0
    best: float = 0.0
    worst: float = 1e9
    rival_best_sum: float = 0.0

    def add(self, result: MatchResult) -> None:
        self.games += 1
        self.wins += 1 if result.won else 0
        self.strength_sum += result.subject_strength
        self.survived += 1 if result.subject_alive else 0
        self.rank_sum += result.subject_rank
        self.kills += result.kills
        self.faults += result.faults
        self.ms_sum += result.ms_per_turn
        self.best = max(self.best, result.subject_strength)
        self.worst = min(self.worst, result.subject_strength)
        rivals = [v for k, v in result.strengths.items() if k != result.subject]
        self.rival_best_sum += max(rivals) if rivals else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def mean_strength(self) -> float:
        return self.strength_sum / self.games if self.games else 0.0

    @property
    def mean_best_rival(self) -> float:
        return self.rival_best_sum / self.games if self.games else 0.0

    @property
    def survival_rate(self) -> float:
        return self.survived / self.games if self.games else 0.0

    @property
    def mean_rank(self) -> float:
        return self.rank_sum / self.games if self.games else 0.0

    def row(self) -> str:
        import math
        p = self.win_rate
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / max(1, self.games))
        return (f"{self.label:<22s} win={p:6.1%} +-{ci:4.1%}  "
                f"strength={self.mean_strength:6.1f} (best rival "
                f"{self.mean_best_rival:5.1f})  surv={self.survival_rate:5.0%}  "
                f"rank={self.mean_rank:4.2f}  kills={self.kills / max(1, self.games):4.2f}  "
                f"ms={self.ms_sum / max(1, self.games):5.2f}"
                + (f"  FAULTS={self.faults}" if self.faults else ""))


def evaluate(subject_factory: Optional[Callable], games: int = 40,
             fieldsize: int = 15, turns: int = 100, base_seed: int = 1000,
             label: str = "subject",
             fillers: Optional[Sequence[Callable]] = None) -> Report:
    """Play ``games`` matches on identical, reproducible boards.

    The seed drives ``Field``'s spawn placement *and* the engine's combat
    rolls, so two subjects evaluated with the same ``base_seed`` face the same
    boards - which is what makes the comparison worth reading.
    """
    report = Report(label)
    for i in range(games):
        report.add(play(subject_factory, seed=base_seed + i,
                        fieldsize=fieldsize, turns=turns, fillers=fillers))
    return report


__all__ = ["play", "evaluate", "MatchResult", "Report"]
