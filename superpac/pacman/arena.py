"""Run matches on the teacher's *actual* engine (version 2).

Not a re-implementation: this imports ``Pacman.py`` and drives the real
``Field``.  What it controls is which classes fill the seats, so different
players can be compared on identical boards.

The second version of the exercise changed the shape of a match in ways that
matter more than they look:

* ``Field(fieldsize, pacmanlist, walls)`` - players arrive from outside as
  ``[class, name]`` pairs, so a player is now its own file rather than a stub
  inside the engine.
* **Walls are real.**  ``buildWall`` lays them out from a spec.
* ``PacmanGame`` reshuffles the acting order every round with
  ``random.sample``, so nobody moves last by default any more.
* There is **no turn limit**.  The loop runs while more than one player is
  alive, which makes survival the win condition rather than a tiebreak.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

#: The wall layout from the teacher's ``PacmanGame.py``.  Resolved lazily
#: because it needs the engine's ``Direction`` constants.
def default_walls():
    from Pacman import Direction
    return [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
            [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
            [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]


#: A match that never resolves would hang the benchmark, so cap it.  Reaching
#: the cap is reported rather than hidden - it means nobody could finish the
#: others off, which is itself a result worth seeing.
SAFETY_CAP = 1500


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
    survivors: int = 0
    sole_survivor: bool = False
    kills: int = 0
    faults: int = 0
    ms_per_turn: float = 0.0
    hit_cap: bool = False

    @property
    def won(self) -> bool:
        """Last one standing.

        The engine's own loop stops once a single player is left, so that is
        the natural reading of a win. Strength is reported alongside because
        a match that hits the safety cap has no sole survivor.
        """
        return self.sole_survivor


def _rank_of(name: str, strengths: Dict[str, float]) -> int:
    mine = strengths[name]
    return sum(1 for other, value in strengths.items()
               if other != name and value > mine)


def play(subject_class: Optional[Callable] = None,
         fillers: Optional[Sequence[Tuple[Callable, str]]] = None,
         seed: int = 0, fieldsize: int = 15, walls: Optional[list] = None,
         subject_name: str = "ThoresT",
         max_turns: int = SAFETY_CAP,
         shuffle_order: bool = True) -> MatchResult:
    """One match on the real engine.

    ``fillers`` is a list of ``(class, name)``; ``None`` uses the teacher's
    own line-up from ``PacmanGame.py`` (three default Pacmen and two TRex).
    """
    import Pacman

    random.seed(seed)
    if walls is None:
        walls = default_walls()
    if fillers is None:
        from TRex import TRex
        fillers = [(Pacman.Pacman, "Pacman1"), (Pacman.Pacman, "Pacman2"),
                   (Pacman.Pacman, "Pacman3"), (TRex, "Trex1"), (TRex, "Trex2")]

    roster = [[cls, name] for cls, name in fillers]
    if subject_class is not None:
        roster.append([subject_class, subject_name])

    board = Pacman.Field(fieldsize, roster, walls)
    subject = next((p for p in board.pacmans if p.name == subject_name), None)

    turn = 0
    alive = sum(1 for p in board.pacmans if p.alive)
    while alive > 1 and turn < max_turns:
        order = (random.sample(board.pacmans, len(board.pacmans))
                 if shuffle_order else list(board.pacmans))
        for pacman in order:
            if pacman.alive:
                pacman.TurnOrMoveOrStill()
        alive = sum(1 for p in board.pacmans if p.alive)
        turn += 1

    strengths = {p.name: float(p.strength) for p in board.pacmans}
    alive_map = {p.name: bool(p.alive) for p in board.pacmans}
    survivors = sum(alive_map.values())
    brain = getattr(subject, "brain", None) if subject is not None else None

    return MatchResult(
        strengths=strengths, alive=alive_map, turns=turn,
        subject=subject_name if subject is not None else "",
        subject_strength=float(subject.strength) if subject else 0.0,
        subject_alive=bool(subject.alive) if subject else False,
        subject_rank=_rank_of(subject_name, strengths) if subject else 99,
        survivors=survivors,
        sole_survivor=bool(subject and subject.alive and survivors == 1),
        kills=sum(1 for p in board.pacmans if p is not subject and not p.alive),
        faults=getattr(brain, "faults", 0),
        ms_per_turn=(brain.total_ms / max(1, brain.turn)) if brain else 0.0,
        hit_cap=turn >= max_turns,
    )


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
    turn_sum: int = 0
    capped: int = 0
    rival_best_sum: float = 0.0
    strongest: int = 0

    def add(self, result: MatchResult) -> None:
        self.games += 1
        self.wins += 1 if result.won else 0
        self.strength_sum += result.subject_strength
        self.survived += 1 if result.subject_alive else 0
        self.rank_sum += result.subject_rank
        self.strongest += 1 if result.subject_rank == 0 else 0
        self.kills += result.kills
        self.faults += result.faults
        self.ms_sum += result.ms_per_turn
        self.turn_sum += result.turns
        self.capped += 1 if result.hit_cap else 0
        rivals = [v for k, v in result.strengths.items() if k != result.subject]
        self.rival_best_sum += max(rivals) if rivals else 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def strongest_rate(self) -> float:
        return self.strongest / self.games if self.games else 0.0

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
        p = self.win_rate
        ci = 1.96 * math.sqrt(max(1e-9, p * (1 - p)) / max(1, self.games))
        return (f"{self.label:<22s} allein-uebrig={p:6.1%} +-{ci:4.1%}  "
                f"staerkster={self.strongest_rate:5.0%}  "
                f"staerke={self.mean_strength:6.1f} (bester Gegner "
                f"{self.mean_best_rival:5.1f})  lebt={self.survival_rate:5.0%}  "
                f"zuege={self.turn_sum / max(1, self.games):5.0f}  "
                f"ms={self.ms_sum / max(1, self.games):5.2f}"
                + (f"  CAP={self.capped}" if self.capped else "")
                + (f"  FEHLER={self.faults}" if self.faults else ""))


def evaluate(subject_class: Optional[Callable], games: int = 40,
             fieldsize: int = 15, base_seed: int = 1000,
             label: str = "subject",
             fillers: Optional[Sequence[Tuple[Callable, str]]] = None,
             walls: Optional[list] = None,
             max_turns: int = SAFETY_CAP) -> Report:
    """Play ``games`` matches on identical, reproducible boards.

    The seed drives spawn placement, wall layout, the acting order *and* the
    engine's combat rolls, so two subjects run with the same ``base_seed``
    face the same games.
    """
    report = Report(label)
    for i in range(games):
        report.add(play(subject_class, fillers=fillers, seed=base_seed + i,
                        fieldsize=fieldsize, walls=walls, max_turns=max_turns))
    return report


__all__ = ["play", "evaluate", "MatchResult", "Report", "default_walls",
           "SAFETY_CAP"]
