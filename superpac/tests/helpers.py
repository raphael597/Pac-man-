"""Shared setup for the engine tests.

``Field`` now takes the roster and the wall layout from outside, so building
a board is no longer a one-liner.  Centralising it here keeps the tests
readable and means the next signature change is one edit.
"""
from __future__ import annotations

import random
from typing import List, Optional, Sequence, Tuple


def teacher_walls():
    """The wall layout from the teacher's ``PacmanGame.py``."""
    from Pacman import Direction
    return [[[5, 3], Direction.east, 8], [[5, 4], Direction.south, 3],
            [[12, 4], Direction.south, 3], [[2, 12], Direction.east, 8],
            [[2, 11], Direction.north, 3], [[9, 11], Direction.north, 3]]


def make_board(seed: int = 1, size: int = 15, rivals: int = 5,
               subject=None, subject_name: str = "T",
               walls: Optional[list] = None):
    """Build a board and hand back ``(board, subject)``.

    The subject is appended last, so ``board.pacmans[-1]`` is ours - the same
    position the old engine hard-coded for ``ThoresT``.
    """
    import Pacman

    random.seed(seed)
    if walls is None:
        walls = []
    roster = [[Pacman.Pacman, f"Pacman{i}"] for i in range(1, rivals + 1)]
    roster.append([subject or Pacman.Pacman, subject_name])
    board = Pacman.Field(size, roster, walls)
    me = next(p for p in board.pacmans if p.name == subject_name)
    return board, me


def step_rivals(board, me) -> None:
    """Let everyone except ``me`` take a turn."""
    for pacman in board.pacmans:
        if pacman is not me and pacman.alive:
            pacman.TurnOrMoveOrStill()


def wall_off(board, every: int = 3) -> int:
    """Turn a grid of cabbage cells into walls; returns how many."""
    import Pacman

    size = Pacman.Position.fieldsize
    built = 0
    for x in range(size):
        for y in range(size):
            position = Pacman.Position(x, y)
            if x % every == 1 and y % every == 1 and isinstance(
                    board.field[position], Pacman.Cabbage):
                del board.field[position]
                board.field[position] = Pacman.Wall(position)
                built += 1
    return built


__all__ = ["make_board", "step_rivals", "wall_off", "teacher_walls"]
