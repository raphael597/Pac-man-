"""Static map intelligence: graph, distances, corridors, dead ends, regions.

Everything in here depends only on the *walls*, never on food or players, so
it is computed exactly once per match and then read from cheap lookups.  That
split is the single most important performance decision in the project: the
per-turn hot loop must never run a fresh BFS for a question whose answer
cannot have changed.

Cells are integers (``y * width + x``).  Adjacency, degrees, corridor
classification and dead-end depths are dense tuples/arrays indexed by cell id.
"""

from __future__ import annotations

from array import array
from collections import deque
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .rules import DEFAULT_RULES, DELTAS, MOVE_ACTIONS, RuleSet

#: Sentinel for "unreachable" in distance arrays.  Large but still small
#: enough that ``dist_a + dist_b`` cannot overflow a signed 32-bit int.
UNREACHABLE: int = 1 << 20

#: Above this many walkable cells we stop building the full all-pairs table
#: and fall back to memoised single-source BFS.  1400 cells => ~2M entries
#: (~8 MB as an 'i' array) and roughly a quarter second to build, which is a
#: fair trade for O(1) distance lookups for the rest of the match.
APSP_CELL_LIMIT: int = 1400


class MapGraph:
    """Immutable, precomputed view of the walkable structure of a map.

    Parameters
    ----------
    width, height:
        Grid dimensions.
    passable:
        Length ``width * height`` sequence of truthy values, one per cell.
    rules:
        Consulted only for wrap-around; everything else is geometry.
    build_apsp:
        ``None`` auto-decides from :data:`APSP_CELL_LIMIT`.
    """

    __slots__ = (
        "width", "height", "n_cells", "rules",
        "passable", "cells", "neighbors", "neighbor_actions", "degree",
        "_apsp", "_apsp_rows", "_bfs_cache", "_bfs_order",
        "dead_end_depth", "pocket_size", "escape_distance", "pocket_mouth",
        "is_junction", "is_corridor", "is_dead_end", "is_terminal",
        "region_of", "region_sizes", "articulation", "_max_bfs_cache",
    )

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------
    def __init__(
        self,
        width: int,
        height: int,
        passable: Sequence[object],
        rules: Optional[RuleSet] = None,
        build_apsp: Optional[bool] = None,
        max_bfs_cache: int = 256,
    ) -> None:
        self.width = width
        self.height = height
        self.n_cells = width * height
        self.rules = rules or DEFAULT_RULES
        self.passable = bytes(1 if p else 0 for p in passable)
        self.cells: Tuple[int, ...] = tuple(i for i in range(self.n_cells) if self.passable[i])

        self._build_adjacency()
        self._classify_topology()
        self._label_regions()
        self._find_articulation_points()

        self._bfs_cache: Dict[int, array] = {}
        self._bfs_order: deque = deque()
        self._max_bfs_cache = max_bfs_cache
        self._apsp: Optional[array] = None
        self._apsp_rows: int = 0

        if build_apsp is None:
            build_apsp = len(self.cells) <= APSP_CELL_LIMIT
        if build_apsp:
            self.build_all_pairs()

    # ------------------------------------------------------------------
    def _build_adjacency(self) -> None:
        """Precompute neighbour lists and the action that reaches each one."""
        w, h, n = self.width, self.height, self.n_cells
        wrap_x, wrap_y = self.rules.wrap_x, self.rules.wrap_y
        passable = self.passable

        neighbors: List[Tuple[int, ...]] = [()] * n
        neighbor_actions: List[Tuple[int, ...]] = [()] * n
        degree = array("b", bytes(n))

        for idx in range(n):
            if not passable[idx]:
                continue
            x, y = idx % w, idx // w
            nbrs: List[int] = []
            acts: List[int] = []
            for act in MOVE_ACTIONS:
                dx, dy = DELTAS[act]
                nx, ny = x + dx, y + dy
                if wrap_x:
                    nx %= w
                elif not (0 <= nx < w):
                    continue
                if wrap_y:
                    ny %= h
                elif not (0 <= ny < h):
                    continue
                nidx = ny * w + nx
                if passable[nidx]:
                    nbrs.append(nidx)
                    acts.append(act)
            neighbors[idx] = tuple(nbrs)
            neighbor_actions[idx] = tuple(acts)
            degree[idx] = len(nbrs)

        self.neighbors: Tuple[Tuple[int, ...], ...] = tuple(neighbors)
        self.neighbor_actions: Tuple[Tuple[int, ...], ...] = tuple(neighbor_actions)
        self.degree = degree

    # ------------------------------------------------------------------
    def _classify_topology(self) -> None:
        """Peel the walkable graph to find pockets you commit to by entering.

        Repeatedly removing degree-1 cells strips every tree-like tail from
        the map and leaves the 2-connected core untouched.  For each cell we
        record what entering it costs you:

        ``dead_end_depth[c]``
            Length of the longest tail hanging off ``c``.  Walk in and this
            is how many steps you may have to retrace to get out again.
        ``pocket_size[c]``
            Number of cells that sit *behind* ``c`` in the peel - the amount
            of room in the trap.  A deep pocket with lots of food may still
            be worth entering; a deep pocket with none never is.
        ``escape_distance[c]``
            Steps to the nearest genuine junction (degree >= 3), i.e. how
            long you are committed before you have a real choice again.

        Cells on a cycle survive the peel and get depth/pocket 0: entering
        them commits you to nothing.  O(V + E).
        """
        n = self.n_cells
        degree = self.degree
        neighbors = self.neighbors

        depth = array("i", bytes(4 * n))
        pocket = array("i", bytes(4 * n))
        remaining = array("b", degree)
        peeled = bytearray(n)
        queue = deque(c for c in self.cells if remaining[c] == 1)

        while queue:
            cell = queue.popleft()
            if peeled[cell] or remaining[cell] != 1:
                continue
            peeled[cell] = 1
            depth[cell] = depth[cell] + 1 if depth[cell] else 1
            pocket[cell] += 1
            for nb in neighbors[cell]:
                if peeled[nb]:
                    continue
                # ``nb`` inherits the worst tail and the total room behind it.
                if depth[nb] < depth[cell]:
                    depth[nb] = depth[cell]
                pocket[nb] += pocket[cell]
                remaining[nb] -= 1
                if remaining[nb] == 1:
                    queue.append(nb)

        # Survivors of the peel lie on a cycle: entering them traps nobody.
        for cell in self.cells:
            if not peeled[cell]:
                depth[cell] = 0
                pocket[cell] = 0

        self.dead_end_depth = depth
        self.pocket_size = pocket
        self.is_terminal = bytes(1 if degree[c] == 1 else 0 for c in range(n))
        self.is_junction = bytes(1 if degree[c] >= 3 else 0 for c in range(n))
        self.is_corridor = bytes(1 if degree[c] == 2 else 0 for c in range(n))
        self.is_dead_end = bytes(peeled)

        junctions = [c for c in self.cells if degree[c] >= 3]
        if junctions:
            self.escape_distance = self.multi_source_distances(junctions)
        else:
            # No junction anywhere (pure corridor / ring map): nothing to
            # escape *to*, so treat every cell as equally committed.
            self.escape_distance = array("i", bytes(4 * n))

        self.pocket_mouth = self._label_pocket_mouths(peeled)

    # ------------------------------------------------------------------
    def _label_pocket_mouths(self, peeled: bytearray) -> array:
        """For each dead-end cell, the core cell you must come back out through.

        Knowing the *depth* of a pocket is not enough to judge the risk of
        entering one: what matters is whether a rival can reach the mouth
        before you can get back to it.  A multi-source BFS from the
        2-connected core into the peeled tails carries that mouth's id down
        every branch in O(V).

        ``-1`` means there is no core to return to - the whole component is a
        tree - in which case there is no sealable mouth to reason about.
        """
        n = self.n_cells
        degree = self.degree
        mouth = array("i", [-1]) * n
        frontier: List[int] = []
        for cell in self.cells:
            # Seed from the 2-connected core *and* from junctions.  On a map
            # that is entirely a tree nothing survives the peel, and seeding
            # only from the core would name the tree's centre as every cell's
            # mouth - far from the branch point you would actually escape
            # through.  A junction is a real choice point either way.
            if not peeled[cell] or degree[cell] >= 3:
                mouth[cell] = cell
                frontier.append(cell)
        neighbors = self.neighbors
        while frontier:
            nxt: List[int] = []
            for cell in frontier:
                label = mouth[cell]
                for nb in neighbors[cell]:
                    if mouth[nb] == -1:
                        mouth[nb] = label
                        nxt.append(nb)
            frontier = nxt
        return mouth

    def _label_regions(self) -> None:
        """Connected-component label per cell (maps may be disjoint)."""
        n = self.n_cells
        region = array("i", [-1]) * n
        sizes: List[int] = []
        label = 0
        for start in self.cells:
            if region[start] != -1:
                continue
            size = 0
            stack = [start]
            region[start] = label
            while stack:
                cell = stack.pop()
                size += 1
                for nb in self.neighbors[cell]:
                    if region[nb] == -1:
                        region[nb] = label
                        stack.append(nb)
            sizes.append(size)
            label += 1
        self.region_of = region
        self.region_sizes = tuple(sizes)

    # ------------------------------------------------------------------
    def _find_articulation_points(self) -> None:
        """Iterative Tarjan: cells whose removal disconnects the map.

        These are the chokepoints an opponent can seal to trap us, and the
        chokepoints *we* can seal to deny a region.  Recursion is avoided so
        big maps cannot blow the interpreter stack.
        """
        n = self.n_cells
        disc = array("i", [0]) * n
        low = array("i", [0]) * n
        art = bytearray(n)
        visited = bytearray(n)
        timer = 1

        for root in self.cells:
            if visited[root]:
                continue
            root_children = 0
            visited[root] = 1
            disc[root] = low[root] = timer
            timer += 1
            # stack frames: (cell, parent, iterator index)
            stack: List[Tuple[int, int, int]] = [(root, -1, 0)]
            while stack:
                cell, parent, ptr = stack[-1]
                nbrs = self.neighbors[cell]
                if ptr < len(nbrs):
                    stack[-1] = (cell, parent, ptr + 1)
                    nb = nbrs[ptr]
                    if nb == parent:
                        continue
                    if visited[nb]:
                        if disc[nb] < low[cell]:
                            low[cell] = disc[nb]
                    else:
                        visited[nb] = 1
                        disc[nb] = low[nb] = timer
                        timer += 1
                        if cell == root:
                            root_children += 1
                        stack.append((nb, cell, 0))
                else:
                    stack.pop()
                    if stack:
                        pcell = stack[-1][0]
                        if low[cell] < low[pcell]:
                            low[pcell] = low[cell]
                        if pcell != root and low[cell] >= disc[pcell]:
                            art[pcell] = 1
            if root_children > 1:
                art[root] = 1
        self.articulation = bytes(art)

    # ------------------------------------------------------------------
    # distances
    # ------------------------------------------------------------------
    def bfs(self, source: int, out: Optional[array] = None) -> array:
        """Unweighted single-source shortest paths from ``source``.

        Returns an ``array('i')`` of length ``n_cells`` with
        :data:`UNREACHABLE` for cells that cannot be reached.
        """
        dist = out if out is not None else array("i", [UNREACHABLE]) * self.n_cells
        if out is not None:
            for i in range(self.n_cells):
                dist[i] = UNREACHABLE
        if not self.passable[source]:
            return dist
        neighbors = self.neighbors
        dist[source] = 0
        frontier = [source]
        d = 0
        while frontier:
            d += 1
            nxt: List[int] = []
            append = nxt.append
            for cell in frontier:
                for nb in neighbors[cell]:
                    if dist[nb] == UNREACHABLE:
                        dist[nb] = d
                        append(nb)
            frontier = nxt
        return dist

    def distances_from(self, source: int) -> array:
        """Cached :meth:`bfs`.  O(1) when the all-pairs table exists."""
        if self._apsp is not None:
            base = source * self.n_cells
            return self._apsp[base: base + self.n_cells]
        cached = self._bfs_cache.get(source)
        if cached is not None:
            return cached
        dist = self.bfs(source)
        self._bfs_cache[source] = dist
        self._bfs_order.append(source)
        if len(self._bfs_order) > self._max_bfs_cache:
            self._bfs_cache.pop(self._bfs_order.popleft(), None)
        return dist

    def build_all_pairs(self) -> None:
        """Materialise the dense distance table.  Memory: 4 * n_cells^2 bytes."""
        n = self.n_cells
        table = array("i", [UNREACHABLE]) * (n * n)
        for source in self.cells:
            row = self.bfs(source)
            base = source * n
            table[base: base + n] = row
        self._apsp = table
        self._apsp_rows = n

    def distance(self, a: int, b: int) -> int:
        """Shortest walking distance between two cells."""
        if a == b:
            return 0
        if self._apsp is not None:
            return self._apsp[a * self.n_cells + b]
        return self.distances_from(a)[b]

    def multi_source_distances(self, sources: Iterable[int]) -> array:
        """Distance to the *nearest* of several sources (one BFS, not k)."""
        dist = array("i", [UNREACHABLE]) * self.n_cells
        frontier: List[int] = []
        for src in sources:
            if self.passable[src] and dist[src] != 0:
                dist[src] = 0
                frontier.append(src)
        neighbors = self.neighbors
        d = 0
        while frontier:
            d += 1
            nxt: List[int] = []
            append = nxt.append
            for cell in frontier:
                for nb in neighbors[cell]:
                    if dist[nb] == UNREACHABLE:
                        dist[nb] = d
                        append(nb)
            frontier = nxt
        return dist

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def step(self, cell: int, action: int) -> int:
        """Resulting cell after ``action``; the same cell if it is illegal."""
        if action == 4:
            return cell
        acts = self.neighbor_actions[cell]
        for i, a in enumerate(acts):
            if a == action:
                return self.neighbors[cell][i]
        return cell

    def action_between(self, src: int, dst: int) -> int:
        """The action moving ``src`` -> ``dst`` for adjacent cells, else STAY."""
        for i, nb in enumerate(self.neighbors[src]):
            if nb == dst:
                return self.neighbor_actions[src][i]
        return 4

    def legal_actions(self, cell: int, allow_stay: bool = True) -> Tuple[int, ...]:
        acts = self.neighbor_actions[cell]
        return acts + (4,) if allow_stay else acts

    def first_step_towards(self, src: int, dst: int) -> int:
        """Greedy first action along a shortest path from ``src`` to ``dst``.

        Uses the *destination's* distance field so a single BFS answers the
        query for every source, which is what the fallback policy needs.
        """
        if src == dst:
            return 4
        dist = self.distances_from(dst)
        best_d = dist[src]
        if best_d >= UNREACHABLE:
            return 4
        for i, nb in enumerate(self.neighbors[src]):
            if dist[nb] == best_d - 1:
                return self.neighbor_actions[src][i]
        return 4

    def nearest_target(self, src: int, targets) -> Tuple[int, int, int]:
        """One BFS answering "closest target, how far, which way first?".

        Returns ``(cell, distance, first_action)`` or ``(-1, UNREACHABLE, 4)``
        when nothing is reachable.  Tagging each frontier cell with the action
        that *started* its branch means the caller gets a move for free
        instead of running a second BFS back from the target.
        """
        if not targets:
            return -1, UNREACHABLE, 4
        target_set = targets if isinstance(targets, (set, frozenset)) else set(targets)
        if src in target_set:
            return src, 0, 4
        neighbors = self.neighbors
        seen = bytearray(self.n_cells)
        seen[src] = 1
        frontier: List[Tuple[int, int]] = []
        for i, nb in enumerate(neighbors[src]):
            act = self.neighbor_actions[src][i]
            if nb in target_set:
                return nb, 1, act
            seen[nb] = 1
            frontier.append((nb, act))
        d = 1
        while frontier:
            d += 1
            nxt: List[Tuple[int, int]] = []
            append = nxt.append
            for cell, act in frontier:
                for nb in neighbors[cell]:
                    if seen[nb]:
                        continue
                    if nb in target_set:
                        return nb, d, act
                    seen[nb] = 1
                    append((nb, act))
            frontier = nxt
        return -1, UNREACHABLE, 4

    def xy(self, cell: int) -> Tuple[int, int]:
        return cell % self.width, cell // self.width

    def index(self, x: int, y: int) -> int:
        return y * self.width + x

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<MapGraph {self.width}x{self.height} walkable={len(self.cells)} "
            f"apsp={'yes' if self._apsp is not None else 'no'}>"
        )


def graph_from_lines(lines: Sequence[str], wall_chars: str = "#%X|-+", rules=None) -> MapGraph:
    """Build a :class:`MapGraph` from an ASCII map (test/simulator helper)."""
    height = len(lines)
    width = max(len(line) for line in lines)
    passable = bytearray(width * height)
    for y, line in enumerate(lines):
        for x in range(width):
            ch = line[x] if x < len(line) else wall_chars[0]
            passable[y * width + x] = 0 if ch in wall_chars else 1
    return MapGraph(width, height, passable, rules=rules)


__all__ = ["MapGraph", "UNREACHABLE", "APSP_CELL_LIMIT", "graph_from_lines"]
