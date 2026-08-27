"""The modular evaluation function and the per-turn fields it reads.

Brief section 33 asks for a weighted sum of strategic components, and section
42 insists the weights be *measured* rather than guessed.  They live in one
:class:`Weights` dataclass so the optimiser can treat SUPERPAC as a function
of a vector, and so the tournament build can embed the tuned numbers verbatim.

The performance idea here is that almost nothing is computed per *candidate
move*.  Once per turn we build a handful of dense fields over the map; the
search then scores a position with a few array lookups, which is what lets the
planner visit thousands of nodes inside a 100 ms budget.
"""

from __future__ import annotations

import math
from array import array
from dataclasses import asdict, dataclass, fields, replace
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import UNREACHABLE, MapGraph
from ..game.state import GameState
from .territory import TerritoryAnalysis
from .threat import ThreatMap


@dataclass
class Weights:
    """Every tunable number in one place.

    Defaults are a reasonable hand-set starting point, *not* the final
    answer: :mod:`superpac.training.optimize_weights` searches this space and
    the tournament build embeds whatever it finds.
    """

    # --- reward ---------------------------------------------------------
    food: float = 12.0
    """Immediate pellet under our feet."""
    food_potential: float = 5.5
    """Discounted value of the best food-collecting walk from a cell."""
    territory: float = 0.5
    """How deep inside our own uncontested region a cell sits.

    Distinct from ``food_potential`` (which values food regardless of who
    owns the ground) and from ``danger`` (which prices immediate collision,
    not regional control).  This is the "find a quiet corner and harvest in
    peace" term from section 32.
    """
    cluster: float = 0.3
    mobility: float = 2.6
    """Escape routes.  Cheap insurance that repeatedly pays for itself."""
    # Note on ``cluster``/``territory``/``intercept``: hand-picked values for
    # these measured *worse* than switching them off (see docs/RESULTS.md), so
    # they start small and the optimiser decides whether they earn their keep.
    # Intuition is not evidence - section 42 of the brief is explicit about it.
    open_space: float = 0.9
    denial: float = 0.8
    """Value of taking food a rival wanted."""
    intercept: float = 0.0
    """Deliberately zero by default - see the benchmark note in the README."""
    information: float = 0.35
    """Active-learning bonus, annealed away as the game gets decisive."""

    # --- risk -----------------------------------------------------------
    death: float = 260.0
    """Elimination is close to terminal under Highlander scoring, so this
    dominates everything else by design."""
    danger: float = 9.0
    contest: float = 1.1
    dead_end: float = 4.2
    trap: float = 7.0
    stagnation: float = 1.3
    """Penalty for revisiting recent cells - breaks oscillation loops."""

    # --- planner behaviour ----------------------------------------------
    discount: float = 0.88
    """Per-step discount inside the search."""
    potential_discount: float = 0.80
    """Decay of the food-potential field per step of distance."""
    risk_aversion: float = 0.55
    """How hard to penalise the bad tail across scenarios (section 20)."""
    territory_softness: float = 1.4
    beam_width: int = 12
    max_depth: int = 6
    forecast_horizon: int = 4
    scenario_count: int = 6
    explore_epsilon: float = 0.035
    """Controlled tie-breaking randomness (section 48)."""

    def as_vector(self) -> List[float]:
        return [float(getattr(self, f.name)) for f in fields(self)]

    @classmethod
    def from_vector(cls, vector: Sequence[float]) -> "Weights":
        names = [f.name for f in fields(cls)]
        if len(vector) != len(names):
            # zip() would silently truncate and hand back a plausible-looking
            # but wrong weight set - exactly the sort of bug that surfaces as
            # "the tuned version is somehow worse than the defaults".
            raise ValueError(
                f"weight vector has {len(vector)} entries, expected {len(names)}; "
                "it was probably saved by an older build - re-run the optimiser")
        kwargs = {}
        for name, value in zip(names, vector):
            declared = cls.__dataclass_fields__[name].type
            kwargs[name] = int(round(value)) if declared == "int" else float(value)
        return cls(**kwargs)

    @classmethod
    def names(cls) -> List[str]:
        return [f.name for f in fields(cls)]

    def with_(self, **kwargs) -> "Weights":
        return replace(self, **kwargs)

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


DEFAULT_WEIGHTS = Weights()

#: Minimum value of a pellet in the potential field, however contested.  Keeps
#: a gradient toward food alive when every pellet looks lost - see the comment
#: in :meth:`TurnFields._build_potential`.
FOOD_REWARD_FLOOR = 0.06


# --------------------------------------------------------------------------
class TurnFields:
    """Dense per-turn maps that make position scoring a lookup.

    Built once per move request.  Everything the search asks about a cell is
    answered from one of these arrays.
    """

    __slots__ = ("state", "graph", "weights", "territory", "threat",
                 "food_potential", "food_dist", "recent", "n_food",
                 "opponent_potential", "_score_cache", "cluster_field",
                 "intercept_field")

    def __init__(self, state: GameState, territory: TerritoryAnalysis,
                 threat: ThreatMap, weights: Weights,
                 recent: Optional[Dict[int, int]] = None) -> None:
        self.state = state
        self.graph = state.graph
        self.weights = weights
        self.territory = territory
        self.threat = threat
        self.recent = recent or {}
        self.n_food = len(state.food)
        # The beam re-scores the same (cell, depth) pairs thousands of times
        # per turn while sorting.  Profiling put 2.0 s of a 11 s run in this
        # one function; memoising it per turn removed almost all of that.
        # The cache is per-TurnFields and TurnFields is rebuilt every turn, so
        # it can never go stale.
        self._score_cache: Dict[int, float] = {}
        self.food_potential = self._build_potential(weights.potential_discount)
        self.food_dist = (state.graph.multi_source_distances(state.food)
                          if state.food else None)
        self.cluster_field = (self._build_cluster_field()
                              if weights.cluster > 0 else None)
        self.intercept_field = (self._build_intercept_field()
                                if weights.intercept > 0 else None)

    # ------------------------------------------------------------------
    def _build_potential(self, gamma: float) -> array:
        """Value-iterate a discounted "best food walk" field over the map.

        ``V[c] = reward[c] + gamma * max(V[n] for n in neighbours(c))``

        Each pellet is worth its *win probability*, so food a rival will
        clearly reach first barely raises the field.  This is a heuristic
        potential, not an exact value function: because the recurrence has no
        memory of what has already been eaten, a two-cell back-and-forth can
        count the same pellet more than once.  With ``gamma`` around 0.8 the
        inflation is small and, more importantly, near-uniform across cells -
        and only the *ranking* of cells feeds the planner.  Exact evaluation
        would need the food set in the state, which is precisely the cost this
        field exists to avoid.
        """
        graph = self.graph
        n = graph.n_cells
        reward = [0.0] * n
        for cell in self.state.food:
            # A pellet a rival will probably reach first is worth little - but
            # never literally nothing.  Rivals do not play optimally, which is
            # the same reasoning that made ``win_probability`` a soft logistic
            # rather than a hard comparison; a hard zero here contradicts it.
            #
            # It also matters concretely at the end of a match.  With every
            # remaining pellet nominally "denied", a zero reward flattens this
            # field completely, the planner finds no gradient anywhere, and
            # SUPERPAC idles out the clock while trailing - observed at turn
            # 169 of a real match, bouncing between two cells with two pellets
            # still on the board.  Losing by one while contesting is no worse
            # than losing by one while standing still, and it might not lose.
            reward[cell] = max(FOOD_REWARD_FLOOR,
                               self.territory.win_probability(cell))

        values = array("f", bytes(4 * n))
        for cell in graph.cells:
            values[cell] = reward[cell]

        neighbors = graph.neighbors
        cells = graph.cells
        # Enough sweeps for influence to travel ~2/(1-gamma) cells, which is
        # where the discount has made further propagation irrelevant anyway.
        sweeps = min(24, int(2.0 / max(0.05, 1.0 - gamma)))
        for _ in range(sweeps):
            changed = 0.0
            for cell in cells:
                best = 0.0
                for nb in neighbors[cell]:
                    v = values[nb]
                    if v > best:
                        best = v
                new = reward[cell] + gamma * best
                if new > values[cell]:
                    changed += new - values[cell]
                    values[cell] = new
            if changed < 1e-3:
                break
        return values

    # ------------------------------------------------------------------
    def _build_cluster_field(self):
        """Pull toward dense, winnable pockets of food (brief section 7).

        The food-potential field values the best *walk*; this values the best
        *destination*.  They differ where a long corridor of single pellets
        scores about the same as a tight pocket worth several - the cluster
        field breaks that tie toward the pocket, which pays off because a
        pocket is collected with fewer wasted steps.

        One cached BFS per cluster centre over a handful of clusters, so it
        stays affordable.
        """
        clusters = self.territory.clusters()
        if not clusters:
            return None
        n = self.graph.n_cells
        field = array("f", bytes(4 * n))
        for cluster in clusters[:5]:
            row = self.graph.distances_from(cluster.centre)
            value = cluster.value
            for cell in self.graph.cells:
                d = row[cell]
                if d >= UNREACHABLE:
                    continue
                contribution = value * (0.86 ** d)
                if contribution > field[cell]:
                    field[cell] = contribution
        return field

    def _build_intercept_field(self):
        """Value of standing where a rival is predicted to arrive (section 24).

        Under the default Highlander reading, contact kills *both* parties, so
        body-blocking is mutual destruction: this field is correctly empty
        there, because the danger term already prices those cells and adding a
        reward on top would simply cancel it out.  Interception is only worth
        anything where we would survive the exchange - a ``higher_score``
        ruleset while we are ahead, or a ruleset where contact is harmless and
        blocking is pure denial.

        Whether that narrow case earns a weight at all is a question for the
        benchmark rather than for intuition, which is why the term exists and
        the weight starts at zero instead of being hard-coded either way.
        """
        rules = self.state.rules
        survivable = (not rules.contact_is_lethal) or (
            rules.head_on_resolution == "higher_score"
            and self.state.score_gap() > 0)
        if not survivable:
            return None
        n = self.graph.n_cells
        field = array("f", bytes(4 * n))
        for frames in self.threat.opponent_frames.values():
            for t, frame in enumerate(frames):
                decay = 0.75 ** t
                for cell, p in frame.items():
                    contribution = p * decay
                    if contribution > field[cell]:
                        field[cell] = contribution
        return field

    def positional_score(self, cell: int, depth: int = 0) -> float:
        """Static desirability of standing on ``cell`` (no food reward here).

        Food collected along a path is credited by the planner as it happens;
        this is the *positional* half of the evaluation.
        """
        key = cell * 16 + (depth if depth < 15 else 15)
        cached = self._score_cache.get(key)
        if cached is not None:
            return cached
        value = self._positional_score(cell, depth)
        self._score_cache[key] = value
        return value

    def _positional_score(self, cell: int, depth: int) -> float:
        w = self.weights
        graph = self.graph
        score = 0.0

        score += w.food_potential * self.food_potential[cell]
        # Regional control: how far the nearest rival is from this cell, as a
        # proxy for how much of the surrounding ground is uncontested.  Capped
        # because beyond a dozen steps "safe" stops getting meaningfully safer.
        rival_reach = self.territory.opp_min[cell]
        if rival_reach < UNREACHABLE:
            score += w.territory * min(rival_reach, 12) * 0.08
        else:
            score += w.territory * 0.96
        if self.cluster_field is not None:
            score += w.cluster * self.cluster_field[cell]
        if self.intercept_field is not None:
            score += w.intercept * self.intercept_field[cell]
        score += w.mobility * _mobility_value(graph, cell)
        score += w.open_space * min(4, graph.degree[cell]) * 0.25

        # Threat, discounted by how far ahead we are looking.
        t = min(depth, max(0, len(self.threat.frames) - 1))
        score -= w.danger * self.threat.at(cell, t)
        score -= w.contest * self.territory.contest_score(cell)

        # Dead ends cost by how deep the pocket is and how much pressure is
        # on it; the trap term below prices the thing that actually kills you.
        depth_penalty = graph.dead_end_depth[cell]
        if depth_penalty:
            exposure = 1.0 + 2.0 * self.threat.pressure(cell)
            score -= w.dead_end * math.log1p(depth_penalty) * exposure
            score -= w.trap * self.trap_risk(cell, depth)

        if cell in self.recent:
            score -= w.stagnation * self.recent[cell]
        return score

    # ------------------------------------------------------------------
    def trap_risk(self, cell: int, depth: int = 0) -> float:
        """Probability that entering ``cell`` gets us sealed in (section 31).

        Pocket depth alone is the wrong signal - a ten-cell pocket with every
        rival on the far side of the map is perfectly safe, and a two-cell one
        with a rival at its mouth is fatal.  What matters is the *race*: we
        must travel ``escape_distance`` to get back to the mouth, and a rival
        must travel however far it is from that same mouth.  Lose the race and
        we are choosing between walking into it and starving in the pocket.

        ``depth`` is how many plies into the search this cell sits, which is
        also how many steps the rivals have had to close in - so their head
        start shrinks as we look further ahead.
        """
        graph = self.graph
        if not graph.is_dead_end[cell]:
            return 0.0
        mouth = graph.pocket_mouth[cell]
        if mouth < 0:
            return 0.0
        rival_time = self.territory.opp_min[mouth]
        if rival_time >= UNREACHABLE:
            return 0.0
        my_time = graph.escape_distance[cell]
        # Rivals have already spent ``depth`` steps closing while we searched.
        margin = (rival_time - depth) - my_time
        if margin > 6:
            return 0.0
        if margin < -6:
            return 1.0
        return 1.0 / (1.0 + math.exp(margin / 1.5))

    def step_reward(self, cell: int, eaten: frozenset) -> float:
        """Reward for arriving at ``cell`` given what we already ate."""
        if cell in self.state.food and cell not in eaten:
            w = self.weights
            bonus = w.food
            # Taking a pellet a rival was closing on is worth more than one
            # nobody wanted: the swing is two-sided.
            bonus += w.denial * self.territory.contest_score(cell)
            return bonus
        return 0.0


def _mobility_value(graph: MapGraph, cell: int) -> float:
    """Diminishing returns on escape routes; being cornered is what hurts."""
    degree = graph.degree[cell]
    if degree <= 1:
        return -1.0
    if degree == 2:
        return 0.35
    if degree == 3:
        return 0.85
    return 1.0


__all__ = ["Weights", "DEFAULT_WEIGHTS", "TurnFields"]
