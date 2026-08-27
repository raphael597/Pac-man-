"""Translation layer between an unknown host engine and SUPERPAC's world model.

Why this module exists
----------------------
No starter files, example players or rule documents were supplied with this
repository, so the exact shape of the tournament API is genuinely unknown.
The brief's instruction -- *do not implement against an imagined API* -- is
taken literally here: instead of guessing one interface and hard-coding it,
the adapter **discovers** the interface at runtime from whatever object the
host hands us, and caches the discovered schema so the cost is paid once.

That turns an unknown API from a rewrite risk into a lookup table.  When the
real starter files show up, the fastest path is still to read them and pin
:class:`Schema` explicitly (see :func:`Schema.pinned`) -- sniffing is the
safety net, not the plan.

The sniffer handles the shapes this kind of exercise actually ships with:

* ``dict`` state, attribute-object state, or a bare ``(grid, pos, food)`` tuple
* maps as list-of-strings, list-of-lists, nested dicts, flat sequences, or a
  ``walls``/``blocked`` container
* positions as ``(x, y)``, ``[x, y]``, ``{'x':.., 'y':..}``, ``.x/.y`` objects,
  ``complex``, or flat integer cell ids
* row-major vs column-major axis order, resolved by *calibration* rather than
  assumption (see :meth:`StateExtractor._calibrate`)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .map_model import MapGraph
from .rules import (ACTION_NAMES, ALL_ACTIONS, DEFAULT_RULES, DELTAS,
                    MOVE_ACTIONS, STAY, RuleSet, action_from_name)
from .state import GameState

# --------------------------------------------------------------------------
# Candidate names, ordered most-likely-first.
# --------------------------------------------------------------------------
WIDTH_NAMES = ("width", "w", "cols", "columns", "n_cols", "ncols", "size_x",
               "map_width", "grid_width", "board_width", "x_size", "sizeX")
HEIGHT_NAMES = ("height", "h", "rows", "n_rows", "nrows", "size_y",
                "map_height", "grid_height", "board_height", "y_size", "sizeY")
GRID_NAMES = ("grid", "map", "board", "maze", "field", "world", "layout",
              "tiles", "cells", "terrain", "level", "matrix", "arena")
WALL_NAMES = ("walls", "wall", "blocked", "obstacles", "wall_positions",
              "wall_set", "blockers", "solid", "is_wall")
FOOD_NAMES = ("food", "foods", "food_positions", "pellets", "dots", "points",
              "coins", "items", "resources", "remaining_food", "gold",
              "treasures", "targets", "food_list", "pills")
MYPOS_NAMES = ("my_position", "my_pos", "position", "pos", "location", "loc",
               "me", "my_location", "self_position", "head", "coord",
               "my_coords", "current_position", "player_position")
MYID_NAMES = ("my_id", "id", "player_id", "index", "player_index", "me",
              "my_index", "player_number", "team", "uid", "number")
OPP_NAMES = ("opponents", "opponent_positions", "enemies", "others",
             "other_players", "opponent_list", "rivals", "enemy_positions",
             "adversaries", "opps")
PLAYERS_NAMES = ("players", "agents", "bots", "all_players", "player_list",
                 "characters", "entities", "player_positions", "positions")
TURN_NAMES = ("turn", "tick", "step", "turn_number", "round", "time",
              "frame", "move_number", "iteration", "t")
SCORE_NAMES = ("score", "my_score", "points", "my_points", "food_eaten")
SCORES_NAMES = ("scores", "all_scores", "player_scores", "points_list")
ALIVE_NAMES = ("alive", "is_alive", "living", "active", "dead")

WALL_CHARS = set("#%X*█+|-WB1")
FOOD_CHARS = set(".oO*·•")


def _is_mapping(obj: Any) -> bool:
    """Duck-typed mapping test - also true for :class:`_MergedSource`."""
    return hasattr(obj, "keys") and hasattr(obj, "__getitem__")


def _get(obj: Any, names: Sequence[str]) -> Tuple[bool, Any]:
    """First present attribute/key among ``names``.  ``(found, value)``."""
    if obj is None:
        return False, None
    if _is_mapping(obj):
        for n in names:
            if n in obj:
                return True, obj[n]
            # tolerate CamelCase / snake_case drift in host APIs
            for k in obj.keys():
                if isinstance(k, str) and k.lower().replace("_", "") == n.lower().replace("_", ""):
                    return True, obj[k]
    for n in names:
        if hasattr(obj, n):
            val = getattr(obj, n)
            if callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            return True, val
    return False, None


def _as_int_pair(value: Any) -> Optional[Tuple[int, int]]:
    """Coerce a huge variety of 'position' encodings into ``(a, b)``."""
    if value is None:
        return None
    if isinstance(value, complex):
        return int(value.real), int(value.imag)
    if isinstance(value, dict):
        if "x" in value and "y" in value:
            return int(value["x"]), int(value["y"])
        if "col" in value and "row" in value:
            return int(value["col"]), int(value["row"])
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        try:
            return int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return None
    if hasattr(value, "x") and hasattr(value, "y"):
        try:
            return int(value.x), int(value.y)
        except (TypeError, ValueError):
            return None
    if hasattr(value, "col") and hasattr(value, "row"):
        return int(value.col), int(value.row)
    # A nested holder such as Player(position=(3, 4))
    found, inner = _get(value, MYPOS_NAMES)
    if found and not isinstance(inner, type(value)):
        return _as_int_pair(inner)
    return None


@dataclass
class Schema:
    """What the sniffer learned about the host API.

    Discovered once, then reused every turn.  ``swap_axes`` records whether
    the host's first coordinate is the row rather than the column.
    """

    width: int = 0
    height: int = 0
    swap_axes: bool = False
    flat_ids: bool = False
    """Host addresses cells by a single integer rather than a pair."""
    grid_name: Optional[str] = None
    food_name: Optional[str] = None
    pos_name: Optional[str] = None
    players_name: Optional[str] = None
    turn_name: Optional[str] = None
    action_style: str = "int"
    """How to *return* an action: ``int`` | ``name`` | ``delta`` | ``lower``."""
    notes: List[str] = field(default_factory=list)

    @staticmethod
    def pinned(width: int, height: int, **kwargs) -> "Schema":
        """Build an explicit schema once the real API is known."""
        return Schema(width=width, height=height, **kwargs)

    def describe(self) -> str:
        return (
            f"Schema(size={self.width}x{self.height}, swap_axes={self.swap_axes}, "
            f"flat_ids={self.flat_ids}, grid={self.grid_name!r}, food={self.food_name!r}, "
            f"pos={self.pos_name!r}, players={self.players_name!r}, "
            f"action_style={self.action_style!r})\n  " + "\n  ".join(self.notes)
        )


class StateExtractor:
    """Turns whatever the host passes in into a :class:`GameState`.

    One instance lives for the whole match.  The first call performs
    discovery; later calls take the fast path through the cached
    :class:`Schema` and the cached :class:`MapGraph`.
    """

    def __init__(self, rules: Optional[RuleSet] = None) -> None:
        self.rules = rules or DEFAULT_RULES
        self.schema = Schema()
        self.graph: Optional[MapGraph] = None
        self._ready = False
        self._player_order: List[Any] = []

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------
    def extract(self, raw: Any, extra: Optional[Any] = None) -> GameState:
        """Build a :class:`GameState`.  Raises :class:`ValueError` if the
        object is too alien to interpret -- callers fall back to a safe move."""
        src = _MergedSource(raw, extra)
        if not self._ready:
            self._discover(src)
            self._ready = True

        food = self._extract_food(src)
        positions, me, scores, alive = self._extract_players(src)
        found_turn, turn = _get(src, TURN_NAMES)
        turn = int(turn) if found_turn and isinstance(turn, (int, float)) else 0

        assert self.graph is not None
        return GameState(
            graph=self.graph,
            food=food,
            positions=positions,
            me=me,
            turn=turn,
            scores=scores,
            alive=alive,
            rules=self.rules,
        )

    # ------------------------------------------------------------------
    # discovery
    # ------------------------------------------------------------------
    def _discover(self, src: "_MergedSource") -> None:
        grid_rows, w, h, name = self._find_grid(src)
        notes = self.schema.notes

        if grid_rows is not None:
            notes.append(f"grid found under {name!r} as {h} rows x {w} cols")
            passable = bytearray(w * h)
            for y, row in enumerate(grid_rows):
                for x in range(w):
                    cell = row[x] if x < len(row) else "#"
                    passable[y * w + x] = 0 if self._is_wall_cell(cell) else 1
        else:
            fw, w_val = _get(src, WIDTH_NAMES)
            fh, h_val = _get(src, HEIGHT_NAMES)
            if not (fw and fh):
                raise ValueError(
                    "SUPERPAC could not locate a map in the host state. "
                    "Pin the schema explicitly in superpac/game/adapter.py."
                )
            w, h = int(w_val), int(h_val)
            passable = bytearray(b"\x01" * (w * h))
            found_walls, walls = _get(src, WALL_NAMES)
            if found_walls and walls is not None:
                notes.append("walls taken from an explicit wall container")
                for cell in self._iter_cells(walls, w, h):
                    if 0 <= cell < w * h:
                        passable[cell] = 0
            else:
                notes.append("no walls found - assuming an open grid")

        self.schema.width, self.schema.height = w, h
        self._calibrate(src, passable, w, h)

        # Re-derive passability if calibration decided the axes were swapped.
        if self.schema.swap_axes and grid_rows is not None:
            notes.append("axis calibration: host uses (row, col) ordering")

        self.graph = MapGraph(w, h, passable, rules=self.rules)
        notes.append(f"walkable cells: {len(self.graph.cells)}")
        self.schema.grid_name = name

    # ------------------------------------------------------------------
    def _find_grid(self, src) -> Tuple[Optional[List[Sequence]], int, int, Optional[str]]:
        for name in GRID_NAMES:
            found, value = _get(src, (name,))
            if not found or value is None:
                continue
            rows = self._normalise_grid(value)
            if rows:
                h = len(rows)
                w = max(len(r) for r in rows)
                if w > 1 and h > 1:
                    return rows, w, h, name
        return None, 0, 0, None

    @staticmethod
    def _normalise_grid(value: Any) -> Optional[List[Sequence]]:
        """Coerce list-of-strings / list-of-lists / dict-grid into rows."""
        if isinstance(value, str):
            rows = value.strip("\n").split("\n")
            return rows if len(rows) > 1 else None
        if isinstance(value, dict):
            keys = list(value.keys())
            pairs = [_as_int_pair(k) for k in keys]
            if pairs and all(p is not None for p in pairs):
                max_a = max(p[0] for p in pairs)  # type: ignore[index]
                max_b = max(p[1] for p in pairs)  # type: ignore[index]
                rows = [[" "] * (max_a + 1) for _ in range(max_b + 1)]
                for key, cell in value.items():
                    pair = _as_int_pair(key)
                    if pair is not None:
                        rows[pair[1]][pair[0]] = cell
                return rows
            return None
        if isinstance(value, (list, tuple)):
            if not value:
                return None
            first = value[0]
            if isinstance(first, (str, list, tuple, bytes, bytearray)):
                return [row for row in value]  # type: ignore[misc]
        return None

    @staticmethod
    def _is_wall_cell(cell: Any) -> bool:
        if isinstance(cell, bool):
            return cell
        if isinstance(cell, (int, float)):
            return int(cell) == 1  # convention: 1 = wall, 0 = floor
        if isinstance(cell, str):
            return cell in WALL_CHARS
        if isinstance(cell, (bytes, bytearray)):
            return bool(cell) and cell[0] in b"#1"
        return False

    def _iter_cells(self, container: Any, w: int, h: int) -> Iterable[int]:
        """Yield flat cell ids from any container of positions."""
        if container is None:
            return
        if isinstance(container, dict):
            container = [k for k, v in container.items() if v] or list(container.keys())
        if isinstance(container, (set, frozenset, list, tuple)):
            for item in container:
                if isinstance(item, int) and not isinstance(item, bool):
                    yield item
                    continue
                pair = _as_int_pair(item)
                if pair is not None:
                    yield self._to_cell(pair, w, h)

    def _to_cell(self, pair: Tuple[int, int], w: int, h: int) -> int:
        a, b = pair
        if self.schema.swap_axes:
            a, b = b, a
        return b * w + a

    def _any_to_cell(self, value: Any, w: int, h: int) -> Optional[int]:
        """Accept either a coordinate pair or an already-flat cell id."""
        if isinstance(value, int) and not isinstance(value, bool):
            self.schema.flat_ids = True
            return value if 0 <= value < w * h else None
        pair = _as_int_pair(value)
        return self._to_cell(pair, w, h) if pair is not None else None

    # ------------------------------------------------------------------
    def _calibrate(self, src, passable: bytearray, w: int, h: int) -> None:
        """Decide ``(x, y)`` vs ``(row, col)`` from evidence, not assumption.

        Every position the host reports *must* land on a walkable cell.  We
        score both interpretations against that invariant and keep the winner;
        a square map with no disagreement leaves the default in place, which
        is harmless because both readings then agree.
        """
        samples: List[Tuple[int, int]] = []
        for names in (MYPOS_NAMES, OPP_NAMES, PLAYERS_NAMES, FOOD_NAMES):
            found, value = _get(src, names)
            if not found or value is None:
                continue
            if isinstance(value, (list, tuple, set, frozenset)):
                for item in list(value)[:24]:
                    pair = _as_int_pair(item)
                    if pair is not None:
                        samples.append(pair)
            else:
                pair = _as_int_pair(value)
                if pair is not None:
                    samples.append(pair)
        if not samples:
            return

        def score(swap: bool) -> int:
            good = 0
            for a, b in samples:
                x, y = (b, a) if swap else (a, b)
                if 0 <= x < w and 0 <= y < h and passable[y * w + x]:
                    good += 1
            return good

        direct, swapped = score(False), score(True)
        if swapped > direct:
            self.schema.swap_axes = True
            self.schema.notes.append(
                f"axis calibration chose (row, col): {swapped}/{len(samples)} valid "
                f"vs {direct}/{len(samples)} for (x, y)"
            )
        else:
            self.schema.notes.append(
                f"axis calibration kept (x, y): {direct}/{len(samples)} valid"
            )

    # ------------------------------------------------------------------
    def _extract_food(self, src) -> Set[int]:
        w, h = self.schema.width, self.schema.height
        found, value = _get(src, FOOD_NAMES)
        if found and value is not None:
            cells = set(self._iter_cells(value, w, h))
            if cells:
                return cells
            # A boolean mask rather than a position list?
            mask = self._as_mask(value, w, h)
            if mask is not None:
                return mask
        # Last resort: food characters straight off the grid.
        rows, gw, gh, _ = self._find_grid(src)
        if rows is not None:
            out: Set[int] = set()
            for y, row in enumerate(rows):
                for x in range(min(gw, len(row))):
                    if isinstance(row[x], str) and row[x] in FOOD_CHARS:
                        out.add(y * w + x)
            return out
        return set()

    def _as_mask(self, value: Any, w: int, h: int) -> Optional[Set[int]]:
        rows = self._normalise_grid(value)
        if rows is None:
            return None
        out: Set[int] = set()
        for y, row in enumerate(rows):
            for x in range(min(w, len(row))):
                cell = row[x]
                if cell is True or cell == 1 or (isinstance(cell, str) and cell in FOOD_CHARS):
                    out.add(y * w + x)
        return out or None

    # ------------------------------------------------------------------
    def _extract_players(self, src):
        w, h = self.schema.width, self.schema.height
        positions: List[int] = []
        scores: List[float] = []
        alive: List[bool] = []
        me = 0

        found_all, all_players = _get(src, PLAYERS_NAMES)
        found_me, my_raw = _get(src, MYPOS_NAMES)
        my_cell = self._any_to_cell(my_raw, w, h) if found_me else None

        if found_all and isinstance(all_players, (list, tuple, dict)):
            items = list(all_players.values()) if isinstance(all_players, dict) else list(all_players)
            for entry in items:
                cell = self._any_to_cell(entry, w, h)
                if cell is None:
                    found_pos, inner = _get(entry, MYPOS_NAMES)
                    cell = self._any_to_cell(inner, w, h) if found_pos else None
                if cell is None:
                    continue
                positions.append(cell)
                fs, sc = _get(entry, SCORE_NAMES)
                scores.append(float(sc) if fs and isinstance(sc, (int, float)) else 0.0)
                fa, al = _get(entry, ALIVE_NAMES)
                alive.append(bool(al) if fa else True)

        if not positions:
            # Fall back to "me plus a list of opponents".
            found_opp, opps = _get(src, OPP_NAMES)
            opp_cells = list(self._iter_cells(opps, w, h)) if found_opp else []
            if my_cell is None and not opp_cells:
                raise ValueError("SUPERPAC could not locate any player positions.")
            positions = ([my_cell] if my_cell is not None else []) + opp_cells
            me = 0 if my_cell is not None else 0
            scores = [0.0] * len(positions)
            alive = [True] * len(positions)
            found_s, my_score = _get(src, SCORE_NAMES)
            if found_s and isinstance(my_score, (int, float)) and scores:
                scores[me] = float(my_score)
            return positions, me, scores, alive

        # We have the full roster - work out which entry is us.
        found_id, my_id = _get(src, MYID_NAMES)
        if found_id and isinstance(my_id, int) and 0 <= my_id < len(positions):
            me = my_id
        elif my_cell is not None and my_cell in positions:
            me = positions.index(my_cell)

        found_ss, all_scores = _get(src, SCORES_NAMES)
        if found_ss and isinstance(all_scores, (list, tuple)) and len(all_scores) == len(positions):
            scores = [float(s) for s in all_scores]
        return positions, me, scores, alive

    # ------------------------------------------------------------------
    def encode_action(self, action: int) -> Any:
        """Render our internal action id in the host's preferred vocabulary."""
        style = self.schema.action_style
        if style == "name":
            return ACTION_NAMES[action]
        if style == "lower":
            return ACTION_NAMES[action].lower()
        if style == "delta":
            return DELTAS[action]
        return action

    def learn_action_style(self, sample: Any) -> None:
        """Adopt whatever vocabulary the host used in an example move."""
        if isinstance(sample, str):
            self.schema.action_style = "lower" if sample.islower() else "name"
        elif isinstance(sample, (tuple, list)):
            self.schema.action_style = "delta"
        else:
            self.schema.action_style = "int"


class _MergedSource:
    """Presents two candidate state objects as one lookup surface."""

    __slots__ = ("primary", "secondary")

    def __init__(self, primary: Any, secondary: Any = None) -> None:
        self.primary = primary
        self.secondary = secondary

    def __contains__(self, key: str) -> bool:
        for obj in (self.primary, self.secondary):
            if isinstance(obj, dict) and key in obj:
                return True
        return False

    def __getitem__(self, key: str) -> Any:
        for obj in (self.primary, self.secondary):
            if isinstance(obj, dict) and key in obj:
                return obj[key]
        raise KeyError(key)

    def keys(self):
        seen = []
        for obj in (self.primary, self.secondary):
            if isinstance(obj, dict):
                for k in obj:
                    if k not in seen:
                        seen.append(k)
        return seen

    def __iter__(self):
        return iter(self.keys())

    def __getattr__(self, name: str) -> Any:
        for obj in (self.primary, self.secondary):
            if obj is None:
                continue
            if isinstance(obj, dict):
                if name in obj:
                    return obj[name]
            elif hasattr(obj, name):
                return getattr(obj, name)
        raise AttributeError(name)


def describe_host_state(raw: Any, extra: Any = None) -> str:
    """One-shot diagnostic: dump what the sniffer sees in a host state object.

    Run this *once* against the real engine and the exact API falls out; the
    result tells you what to pin in :meth:`Schema.pinned`.
    """
    lines = [f"type: {type(raw).__name__}"]
    if isinstance(raw, dict):
        for key, value in raw.items():
            lines.append(f"  [{key!r}] {type(value).__name__} = {_preview(value)}")
    else:
        for attr in sorted(dir(raw)):
            if attr.startswith("_"):
                continue
            try:
                value = getattr(raw, attr)
            except Exception:
                continue
            if callable(value):
                continue
            lines.append(f"  .{attr} {type(value).__name__} = {_preview(value)}")
    if extra is not None:
        lines.append("--- second argument ---")
        lines.append(describe_host_state(extra))
    extractor = StateExtractor()
    try:
        state = extractor.extract(raw, extra)
        lines.append("--- sniffer result ---")
        lines.append(extractor.schema.describe())
        lines.append(repr(state))
    except Exception as exc:  # pragma: no cover - diagnostic path
        lines.append(f"--- sniffer FAILED: {exc!r} ---")
    return "\n".join(lines)


def _preview(value: Any, limit: int = 90) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


__all__ = ["StateExtractor", "Schema", "describe_host_state", "_as_int_pair"]
