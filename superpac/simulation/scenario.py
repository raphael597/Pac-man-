"""Procedural map generation and match configuration.

Maps are generated in the Pac-Man idiom rather than as plain mazes: heavily
*braided* (loops everywhere, few dead ends) and mirror-symmetric, so no seat
starts with a structural advantage.  A dead-end knob is exposed because trap
density is exactly the parameter SUPERPAC's survival logic must be robust to.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from ..game.map_model import MapGraph
from ..game.rules import DEFAULT_RULES, RuleSet
from ..game.state import GameState


@dataclass
class MapSpec:
    width: int = 21
    height: int = 15
    braid: float = 0.85
    """Fraction of dead ends opened back into loops.  1.0 = no dead ends."""
    food_density: float = 1.0
    open_rooms: int = 2
    symmetric: bool = True


def generate_map(spec: MapSpec, rng: random.Random,
                 rules: Optional[RuleSet] = None) -> MapGraph:
    """Carve a braided, symmetric maze and return it as a :class:`MapGraph`."""
    # Work on an odd-sized lattice so walls always sit between cells.
    w = spec.width if spec.width % 2 else spec.width + 1
    h = spec.height if spec.height % 2 else spec.height + 1
    grid = [[1] * w for _ in range(h)]

    # Only carve the left half when symmetric, then mirror.
    carve_w = (w + 1) // 2 if spec.symmetric else w

    def neighbours(cx: int, cy: int):
        for dx, dy in ((0, -2), (0, 2), (-2, 0), (2, 0)):
            nx, ny = cx + dx, cy + dy
            if 1 <= nx < carve_w - 0 and 1 <= ny < h - 1:
                yield nx, ny, cx + dx // 2, cy + dy // 2

    start = (1, 1)
    grid[1][1] = 0
    stack = [start]
    while stack:
        cx, cy = stack[-1]
        options = [n for n in neighbours(cx, cy) if grid[n[1]][n[0]] == 1]
        if not options:
            stack.pop()
            continue
        nx, ny, mx, my = rng.choice(options)
        grid[my][mx] = 0
        grid[ny][nx] = 0
        stack.append((nx, ny))

    # --- braid: open dead ends so the map plays like Pac-Man, not a maze --
    if spec.braid > 0:
        for y in range(1, h - 1):
            for x in range(1, carve_w):
                if grid[y][x] != 0:
                    continue
                open_n = sum(1 for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                             if 0 <= x + dx < w and 0 <= y + dy < h and grid[y + dy][x + dx] == 0)
                if open_n == 1 and rng.random() < spec.braid:
                    walls = [(x + dx, y + dy) for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0))
                             if 1 <= x + dx < carve_w and 1 <= y + dy < h - 1
                             and grid[y + dy][x + dx] == 1]
                    if walls:
                        wx, wy = rng.choice(walls)
                        grid[wy][wx] = 0

    # --- open rooms give the middle game somewhere to manoeuvre ----------
    for _ in range(spec.open_rooms):
        rw, rh = rng.randint(2, 4), rng.randint(2, 3)
        rx = rng.randint(1, max(1, carve_w - rw - 1))
        ry = rng.randint(1, max(1, h - rh - 1))
        for y in range(ry, min(h - 1, ry + rh)):
            for x in range(rx, min(carve_w, rx + rw)):
                grid[y][x] = 0

    if spec.symmetric:
        for y in range(h):
            for x in range(w // 2 + 1):
                grid[y][w - 1 - x] = grid[y][x]
        # Mirroring leaves two independent mazes; punch the centre column
        # through so the halves form one connected arena.
        mid = w // 2
        joinable = [y for y in range(1, h - 1)
                    if grid[y][mid - 1] == 0 and grid[y][mid + 1] == 0]
        if joinable:
            n_joins = max(2, len(joinable) // 3)
            for y in rng.sample(joinable, min(n_joins, len(joinable))):
                grid[y][mid] = 0
        else:
            # Nothing lines up - carve a full centre corridor rather than
            # shipping a map that is really two disjoint games.
            for y in range(1, h - 1):
                grid[y][mid] = 0

    passable = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            passable[y * w + x] = 0 if grid[y][x] else 1

    graph = MapGraph(w, h, passable, rules=rules or DEFAULT_RULES)
    return _largest_component_only(graph, rules)


def _largest_component_only(graph: MapGraph, rules: Optional[RuleSet]) -> MapGraph:
    """Wall off stranded pockets so every player can reach every pellet."""
    if len(graph.region_sizes) <= 1:
        return graph
    keep = max(range(len(graph.region_sizes)), key=lambda i: graph.region_sizes[i])
    passable = bytearray(graph.passable)
    for cell in graph.cells:
        if graph.region_of[cell] != keep:
            passable[cell] = 0
    return MapGraph(graph.width, graph.height, passable, rules=rules or DEFAULT_RULES)


def spawn_points(graph: MapGraph, n_players: int, rng: random.Random) -> List[int]:
    """Pick mutually distant start cells so nobody spawns on top of anyone.

    Farthest-point sampling: seed with a random cell, then repeatedly take the
    walkable cell whose nearest chosen spawn is furthest away.
    """
    cells = list(graph.cells)
    if not cells:
        raise ValueError("map has no walkable cells")
    chosen = [rng.choice(cells)]
    while len(chosen) < n_players:
        dist = graph.multi_source_distances(chosen)
        best = max(cells, key=lambda c: dist[c] if dist[c] < (1 << 20) else -1)
        if dist[best] <= 0:
            best = rng.choice(cells)
        chosen.append(best)
    return chosen[:n_players]


def make_state(graph: MapGraph, n_players: int, rng: random.Random,
               rules: Optional[RuleSet] = None, food_density: float = 1.0) -> GameState:
    """Assemble a fresh :class:`GameState` on ``graph``."""
    rules = rules or DEFAULT_RULES
    spawns = spawn_points(graph, n_players, rng)
    occupied = set(spawns)
    food: Set[int] = set()
    for cell in graph.cells:
        if cell in occupied:
            continue
        if food_density >= 1.0 or rng.random() < food_density:
            food.add(cell)
    return GameState(graph, food, spawns, me=0, turn=0, rules=rules, spawns=spawns)


@dataclass
class Scenario:
    """A fully specified, reproducible match setup."""

    seed: int
    spec: MapSpec
    rules: RuleSet
    n_players: int

    def build(self) -> Tuple[GameState, random.Random]:
        rng = random.Random(self.seed)
        graph = generate_map(self.spec, rng, self.rules)
        state = make_state(graph, self.n_players, rng, self.rules,
                           self.spec.food_density)
        return state, rng


def standard_scenarios(count: int, n_players: int = 4,
                       rules: Optional[RuleSet] = None,
                       base_seed: int = 1000) -> List[Scenario]:
    """A varied but *reproducible* battery of match setups."""
    rules = rules or DEFAULT_RULES
    out: List[Scenario] = []
    sizes = [(15, 11), (21, 15), (27, 17), (19, 19)]
    for i in range(count):
        rng = random.Random(base_seed + i)
        w, h = sizes[i % len(sizes)]
        spec = MapSpec(
            width=w, height=h,
            braid=rng.choice([0.6, 0.8, 0.95]),
            food_density=rng.choice([0.7, 0.9, 1.0]),
            open_rooms=rng.randint(0, 3),
        )
        out.append(Scenario(seed=base_seed + i, spec=spec, rules=rules,
                            n_players=n_players))
    return out


__all__ = ["MapSpec", "Scenario", "generate_map", "make_state", "spawn_points",
           "standard_scenarios"]
