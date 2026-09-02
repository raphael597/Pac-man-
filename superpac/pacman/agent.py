"""The brain behind ``ThoresT``.

Per turn: read the board, learn what every rival just did, predict what they
will do next, then search our own action sequences and play the best one.

The search is a beam over ``(position, facing, strength)`` states.  Three
things make this game's search different from a normal grid bot's:

* **Turning costs a whole turn.**  ``TurnOrMoveOrStill`` turns *or* moves, so
  facing is part of the state and a change of heading is a real expense.  A
  long straight run through cabbage is worth far more than the shortest path
  to anywhere.
* **There are no walls**, so there is no pathfinding.  Distances are
  toroidal Manhattan, and the search is about *sequencing*, not routing.
* **Fights are probabilistic and the angle decides them.**  Nodes therefore
  carry ``P(alive)`` and an expected strength, and a branch that dies still
  contributes the score it had banked - because in this engine dying keeps
  your strength, it only stops you earning more.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, fields, replace
from typing import Dict, List, Optional, Sequence, Tuple

from .model import RivalRegistry
from .perception import RivalView, Snapshot, observe
from .rules import (ACTION_NAMES, DELTAS, DIRECTION_NAMES, EAST, MOVE,
                    N_ACTIONS, OPPOSITE, STILL, TURN_TO, UNREACHABLE,
                    defence_factor, distance, distance_field, is_turn,
                    neighbourhood, step, win_probability)


@dataclass
class Weights:
    """Everything tunable, in one place so the optimiser can search it."""

    run_ahead: float = 1.0
    """Weight on the cabbage lying in an unbroken line in front of us.

    Scaled so it trades against realised strength, and *discounted by how many
    turns away each cabbage is* - see ``run_discount``. Getting this wrong is
    subtle and expensive: with a flat weight above 1.0, a cabbage still on the
    ground was worth more than the same cabbage eaten, so standing still
    outscored moving forward by a hair and the bot procrastinated. It spent a
    quarter of its turns motionless."""
    run_discount: float = 0.88
    """Per-step discount inside the run.

    The ``i``-th cabbage ahead is ``i`` turns away, so it is worth
    ``run_discount ** i``. This is what makes eating now strictly better than
    planning to eat later."""
    density: float = 0.09
    """Cabbage in the neighbourhood - a tie-break when no run is available."""
    hunt: float = 0.85
    """Weight on expected strength from a kill.

    In strength units, so it trades directly against cabbage: 1.0 would mean
    "a kill worth 30 strength is exactly as attractive as 30 cabbages"."""
    hunt_decay: float = 0.86
    """Per-step decay of a distant target's pull.

    Must be gentle. The first version used 0.45 over a four-cell radius, which
    made anything further than a couple of steps worth nothing and left the
    bot with no reason to move at all once the cabbage ran out."""
    exposure: float = 6.0
    """Penalty for standing where a rival can profitably hit us."""
    facing_discipline: float = 0.0
    """Penalty for ending a turn with our back to a nearby threat.

    ``danger`` only prices rivals *already* lined up on us, because only those
    can strike next turn. But a rival two steps away needs one turn to aim and
    one to move - and our facing when it arrives is what sets its odds. Turned
    the wrong way that is 91% for it; turned to meet it, 50%.

    Off by default: it is a hypothesis, and the A/B at 900 matches a side is
    what decides whether it ships.
    """
    survival_bonus: float = 8.0
    """Flat bonus for still being alive at the horizon.

    Insurance: the engine prints dead players' strengths, so death may not
    zero the score, but a ranking that puts survivors first is just as
    plausible. This keeps us from trading life for a marginal pellet under
    either reading."""
    discount: float = 0.97
    beam_width: int = 26
    depth: int = 9
    attack_margin: float = 1.0
    """Scales the ``F < a/f`` attack threshold. Above 1 is bolder."""
    harvest_rate: float = 0.85
    """Cabbage per turn we expect to collect while alive - feeds ``F``."""
    phase_exposure: float = 0.0
    """Wie sich die Vorsicht ueber die Partie veraendert.

    Jagd und Angriff sind bereits phasenabhaengig, und zwar stetig: beide
    haengen an ``future_value``, das mit dem Kohl auf dem Brett faellt.
    Die *Vorsicht* dagegen war ueber die ganze Partie konstant, obwohl die
    Lage sich vollstaendig aendert - am Anfang stehen sechs gleich schwache
    Spieler auf einem vollen Brett, am Ende zwei ungleiche auf einem leeren.

    Wirkt als ``exposure * (1 + phase_exposure * verbraucht)``, wobei
    ``verbraucht`` von 0 auf 1 laeuft, waehrend das Brett leergefressen
    wird. Positiv heisst spaeter vorsichtiger, negativ spaeter mutiger.

    0.0 als Vorgabe, also unveraendert. Welche Richtung richtig ist, ist
    eine offene Frage - und genau deshalb ein A/B und keine Meinung.
    """
    facing_trust: float = 1.0
    """How long we believe a rival keeps looking the way it looks now.

    The hunt field prices a target eight steps away with the angle it offers
    *today*, and the search then plans up to fourteen plies on that price. A
    rival that simply turns to meet us makes the fight head-on - 50% instead
    of 91% - and the plan was worth a fraction of what it looked like.

    Trust decays as ``facing_trust ** distance``: at 1.0 the old behaviour
    (its facing is treated as fixed forever), below 1.0 the value slides
    toward the head-on price as the target gets further away. 1.0 by default
    because it is a hypothesis and the A/B decides, not the argument.
    """
    wall_aware: int = 1
    """Measure distances along walkable paths (1) or straight through walls (0).

    Only a switch so the two can be played against each other on identical
    boards; on a board without walls both give the same numbers. Kept after
    the measurement because it records which way the question was settled,
    and because it is the one knob that turns off the whole BFS if a host
    ever makes it too expensive.
    """

    def __post_init__(self) -> None:
        # ``beam_width`` and ``depth`` end up in ``range()``.  Weights reach us
        # from three directions - defaults, ``from_vector`` and a JSON dict
        # written by a tuning run - and only ``from_vector`` used to coerce.
        # A float that slipped through the other two raised inside ``_search``
        # every single turn, which the fault handler swallowed into the
        # fallback route, so the bot kept playing and nothing looked broken.
        # Coercing here closes all three doors at once.
        for f in fields(self):
            if f.type == "int" and not isinstance(getattr(self, f.name), int):
                object.__setattr__(self, f.name, int(round(getattr(self, f.name))))

    def as_vector(self) -> List[float]:
        return [float(getattr(self, f.name)) for f in fields(self)]

    @classmethod
    def from_vector(cls, vector: Sequence[float]) -> "Weights":
        names = [f.name for f in fields(cls)]
        if len(vector) != len(names):
            raise ValueError(f"expected {len(names)} weights, got {len(vector)}")
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


DEFAULT_WEIGHTS = Weights()

#: How far ahead the run-length scan looks.  Beyond this the discount has
#: made further cabbage irrelevant anyway.
RUN_CAP = 12


class TurnFields:
    """Per-turn lookup tables.

    Profiling the first working version put 80% of the run time in four
    helpers that were being called once per search node - roughly a thousand
    times a turn - even though every one of them depends only on the board,
    which does not change while we think.  Computing them once and reading
    them back turns the inner loop into array indexing.
    """

    __slots__ = ("size", "density", "pressure", "hunt", "_run", "snapshot",
                 "run_value", "back_turned")

    def __init__(self, snapshot: Snapshot, weights: "Weights",
                 move_probability: Dict[str, float],
                 future: float = 0.0, verbraucht: float = 0.0) -> None:
        size = snapshot.size
        self.size = size
        self.snapshot = snapshot
        n = size * size
        cabbage = snapshot.cabbage

        # --- cabbage density, radius 3 ---------------------------------
        # Reachable within three steps, not "three steps as the crow flies":
        # cabbage behind a wall is not food, it is scenery.  The neighbour
        # lists depend only on the walls, which never move, so they are built
        # once per board and cached.
        blocked = (snapshot.blocked
                   if snapshot.has_walls and weights.wall_aware else None)
        near = neighbourhood(size, blocked, 3)
        density = [0.0] * n
        for cell in range(n):
            total = 1 if cabbage[cell] else 0
            for other, _ in near[cell]:
                if cabbage[other]:
                    total += 1
            density[cell] = float(total)
        self.density = density

        # --- proximity pressure: stamped outward from each rival -------
        # Along the paths a rival can actually walk.  With Manhattan distance
        # a rival one step away through a wall looked like maximum danger, so
        # the bot fled from a threat that needed four turns to reach it - and
        # walls are exactly where it is worth standing still and eating.
        rival_distance = [distance_field(size, blocked, r.x, r.y)
                          for r in snapshot.rivals]
        pressure = [0.0] * n
        # Der Phasenfaktor sitzt hier im Feld, nicht im Evaluator: so
        # kostet er einmal pro Zug statt einmal pro Suchknoten.
        phase = 1.0 + weights.phase_exposure * verbraucht
        for rival, dist in zip(snapshot.rivals, rival_distance):
            weight = min(3.0, rival.strength / 4.0 + 0.5) * phase
            for cell in range(n):
                d = dist[cell]
                if d <= 3:
                    pressure[cell] += (0.45 ** d) * weight
        self.pressure = pressure

        # --- hunting value per (facing, cell) --------------------------
        # This is the half of the game that a harvest-only bot loses.  On a
        # 15x15 board six players strip all 225 cabbages by about turn 55,
        # and from then on the *only* source of strength is killing someone.
        # A trace of a real match showed our first version parked at 25 for
        # the last 45 turns while a rival ate its way from 37 to 69.
        #
        # So the field has to reach across the whole board, not just the four
        # cells the first version covered: at 0.45 per step a target eight
        # cells away was worth 0.001 and produced no gradient at all.  Values
        # are in strength units so they trade directly against cabbage.
        strength = snapshot.strength
        decay = weights.hunt_decay

        # Gate the whole field by the same economics as the attack rule.
        # Chasing someone is only free once there is nothing left to harvest;
        # early on it costs every cabbage we do not collect while manoeuvring.
        # Ungated, this field pulled the bot into hunting from turn one and
        # cost it a third of its win rate against strong opponents - worse
        # than having no hunting at all.
        hunt_scale = 1.0 / (1.0 + future / max(1.0, strength))

        hunt = [[0.0] * n for _ in range(4)]
        for rival, rival_dist in zip(snapshot.rivals, rival_distance):
            best_gain = 0.0
            for facing in range(4):
                p = win_probability(strength, rival.strength, facing,
                                    rival.direction)
                # Losing keeps the strength we already banked, so the downside
                # is the harvest we forfeit - which late in the match is near
                # nothing.  That is what makes hunting correct then and wrong
                # early, and the search gets the same trade from ``future``.
                gain = p * rival.strength
                if gain > best_gain:
                    best_gain = gain
            if best_gain <= 0.0:
                continue
            best_gain *= hunt_scale
            # What the same fight is worth if the target turns to meet us:
            # head-on, so its full strength defends.
            head_on = (strength / max(1e-9, strength + rival.strength)
                       * rival.strength * hunt_scale)
            trust = weights.facing_trust
            for facing in range(4):
                row = hunt[facing]
                factor = defence_factor(facing, rival.direction)
                p = win_probability(strength, rival.strength, facing,
                                    rival.direction)
                immediate = p * rival.strength * hunt_scale
                for cell in range(n):
                    d = rival_dist[cell]
                    if d >= UNREACHABLE:
                        continue        # no path there: no gradient either
                    x = cell % size
                    y = cell // size
                    ax, ay = step(x, y, facing, size)
                    if (ax, ay) == (rival.x, rival.y):
                        value = immediate       # we can strike right now
                    elif trust >= 1.0:
                        value = best_gain * (decay ** d)
                    else:
                        # The further off, the less its current facing tells
                        # us, so the price slides toward the head-on one.
                        held = trust ** d
                        value = ((best_gain * held + head_on * (1.0 - held))
                                 * (decay ** d))
                    if value > row[cell]:
                        row[cell] = value
        self.hunt = hunt

        # --- what our facing costs us, per (facing, cell) --------------
        # Priced only when the weight is on, since it is four more passes
        # over the board and buys nothing when switched off.
        if weights.facing_discipline > 0:
            back = [[0.0] * n for _ in range(4)]
            for rival in snapshot.rivals:
                reach = 3
                for dx in range(-reach, reach + 1):
                    for dy in range(abs(dx) - reach, reach + 1 - abs(dx)):
                        d = abs(dx) + abs(dy)
                        if d == 0 or d > reach:
                            continue
                        x = (rival.x + dx) % size
                        y = (rival.y + dy) % size
                        cell = y * size + x
                        # How much easier we make it for this rival by
                        # facing each way, relative to meeting it head on.
                        for facing in range(4):
                            p = win_probability(rival.strength, strength,
                                                rival.direction, facing)
                            best = win_probability(rival.strength, strength,
                                                   rival.direction,
                                                   OPPOSITE[rival.direction])
                            excess = max(0.0, p - best) * (0.55 ** (d - 1))
                            if excess > back[facing][cell]:
                                back[facing][cell] = excess
            self.back_turned = back
        else:
            self.back_turned = None

        # --- run-ahead, memoised lazily per (facing, cell) -------------
        self._run: Dict[int, int] = {}
        # Geometric sums, so a run of length k is worth
        # ``gamma + gamma^2 + ... + gamma^k`` rather than k flat.
        gamma = weights.run_discount
        sums = [0.0] * (RUN_CAP + 1)
        for i in range(1, RUN_CAP + 1):
            sums[i] = sums[i - 1] + gamma ** i
        self.run_value = sums

    # ------------------------------------------------------------------
    def run_ahead(self, x: int, y: int, facing: int,
                  eaten: Tuple[Tuple[int, int], ...]) -> int:
        """Unbroken cabbage straight ahead.

        Memoised on ``(facing, cell)``.  ``eaten`` is handled by truncating at
        the first cell this branch has already taken, which is exact whenever
        the branch has not doubled back on itself - and a branch that doubles
        back is one the search is about to discard anyway.
        """
        key = facing * self.size * self.size + y * self.size + x
        cached = self._run.get(key)
        if cached is None:
            cached = self._compute_run(x, y, facing)
            self._run[key] = cached
        if not eaten or cached == 0:
            return cached
        snapshot = self.snapshot
        cx, cy = x, y
        for i in range(cached):
            cx, cy = step(cx, cy, facing, self.size)
            if (cx, cy) in eaten:
                return i
        return cached

    def _compute_run(self, x: int, y: int, facing: int) -> int:
        snapshot = self.snapshot
        size = self.size
        count = 0
        cx, cy = x, y
        for _ in range(RUN_CAP):
            cx, cy = step(cx, cy, facing, size)
            if not snapshot.cabbage[cy * size + cx]:
                break
            if (cx, cy) in snapshot.occupied or snapshot.blocked[cy * size + cx]:
                break
            count += 1
        return count


class Brain:
    """Chooses one action per turn.  One instance lives for a whole match."""

    def __init__(self, weights: Optional[Weights] = None,
                 total_turns: Optional[int] = None, debug: bool = False) -> None:
        self.weights = weights or DEFAULT_WEIGHTS
        self.registry = RivalRegistry()
        self.total_turns = total_turns
        self.debug = debug
        self.turn = 0
        self.faults = 0
        self.slowest_ms = 0.0
        self.total_ms = 0.0
        self.last_action: int = STILL
        self.last_scores: Dict[int, float] = {}
        self.log: List[str] = []
        self._snapshot: Optional[Snapshot] = None
        self._move_probability: Dict[str, float] = {}
        self._max_cabbage = 0

    # ------------------------------------------------------------------
    def decide(self, me) -> int:
        """Return the action to take.  Never raises."""
        start = time.perf_counter()
        try:
            snapshot = observe(me, self.turn)
            self._snapshot = snapshot
            self.registry.update(snapshot)
            self.registry.predict_all(snapshot)
            self._move_probability = {
                r.name: self.registry.model_for(r.name).move_probability()
                for r in snapshot.rivals}
            action = self._search(snapshot)
        except Exception:
            self.faults += 1
            action = self._fallback(me)
        self.turn += 1
        elapsed = (time.perf_counter() - start) * 1000.0
        self.total_ms += elapsed
        self.slowest_ms = max(self.slowest_ms, elapsed)
        self.last_action = action
        return action

    # ------------------------------------------------------------------
    # threat
    # ------------------------------------------------------------------
    def danger(self, snapshot: Snapshot, x: int, y: int, facing: int,
               strength: float, ignore: Optional[str] = None) -> float:
        """``P(we are killed)`` if we end our turn at ``(x, y)`` facing ``facing``.

        Only rivals already lined up on us can strike next turn, since they
        must spend a turn to change heading.  Our own facing is what sets
        their odds - turning to meet an attacker cuts them from 91% to 50% -
        so this is a function of ``facing``, not just of position.
        """
        risk = 0.0
        for rival in snapshot.rivals:
            if ignore is not None and rival.name == ignore:
                continue
            ahead = step(rival.x, rival.y, rival.direction, snapshot.size)
            if ahead != (x, y):
                continue
            p_move = self._move_probability.get(rival.name, 1.0 / 3.0)
            p_win = win_probability(rival.strength, strength,
                                    rival.direction, facing)
            risk = risk + p_move * p_win - risk * p_move * p_win
        return min(1.0, risk)

    def _proximity_pressure(self, snapshot: Snapshot, x: int, y: int) -> float:
        """Soft danger from rivals that are close but not yet aimed at us."""
        total = 0.0
        blocked = (snapshot.blocked
                   if snapshot.has_walls and self.weights.wall_aware else None)
        for rival in snapshot.rivals:
            if blocked is None:
                d = distance(x, y, rival.x, rival.y, snapshot.size)
            else:
                d = distance_field(snapshot.size, blocked, rival.x, rival.y,
                                   limit=3)[y * snapshot.size + x]
            if d <= 3:
                total += (0.45 ** d) * min(3.0, rival.strength / 4.0 + 0.5)
        return total

    # ------------------------------------------------------------------
    # positional value
    # ------------------------------------------------------------------
    def _scan_run(self, snapshot: Snapshot, x: int, y: int, facing: int) -> int:
        """Unbroken cabbage ahead - the direct scan, for the fallback path.

        The search uses :meth:`TurnFields.run_ahead` instead, which memoises
        this; the fallback must not depend on the field cache existing.
        """
        count = 0
        cx, cy = x, y
        for _ in range(RUN_CAP):
            cx, cy = step(cx, cy, facing, snapshot.size)
            if not snapshot.has_cabbage(cx, cy) or (cx, cy) in snapshot.occupied:
                break
            if snapshot.is_blocked(cx, cy):
                break
            count += 1
        return count

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------
    def future_value(self, snapshot: Snapshot) -> float:
        """``F``: strength we still expect to harvest if we stay alive.

        Feeds the ``F < a / f`` attack rule, so it is what decides whether a
        fight is worth taking. It shrinks as the board is stripped, which is
        exactly why the bot grows bolder as the match wears on.

        ``total_turns`` is ``None`` by default because the current engine has
        **no turn limit** - ``PacmanGame`` loops until one player is left. The
        board is then the only honest clock: what is left to harvest is the
        cabbage still on it, divided by how many of us are chasing it.

        A number may still be passed for a host that does cap the match, in
        which case the tighter of the two clocks wins. Even then we fall back
        on the board once the count runs out, rather than letting ``F`` pin to
        zero and make ``F < a/f`` true for every angle - which would send the
        bot charging into head-on fights with the board still covered.
        """
        available = snapshot.n_cabbage / max(1.0, 1.0 + len(snapshot.rivals))
        if self.total_turns is None:
            return available
        remaining = self.total_turns - snapshot.turn
        if remaining <= 0:
            return available
        return min(remaining * self.weights.harvest_rate, available)

    def _verbraucht(self, snapshot: Snapshot) -> float:
        """Wie viel des Bretts schon abgeerntet ist, von 0 bis 1.

        Der Ausgangsbestand wird nicht gerechnet, sondern beobachtet: das
        erste, was wir sehen, ist das vollste Brett, das wir je sehen
        werden. Das haelt auch, wenn der Lehrer die Feldgroesse oder die
        Waende aendert - eine gerechnete Formel taete das nicht.
        """
        if snapshot.n_cabbage > self._max_cabbage:
            self._max_cabbage = snapshot.n_cabbage
        if self._max_cabbage <= 0:
            return 1.0
        return 1.0 - snapshot.n_cabbage / self._max_cabbage

    def _search(self, snapshot: Snapshot) -> int:
        w = self.weights
        size = snapshot.size
        future = self.future_value(snapshot)

        fields = TurnFields(snapshot, w, self._move_probability, future,
                            self._verbraucht(snapshot))

        # node: (score, x, y, facing, strength, alive, banked, eaten, first)
        start = (0.0, snapshot.x, snapshot.y, snapshot.direction,
                 snapshot.strength, 1.0, 0.0, (), -1)
        frontier = [start]
        best_by_action: Dict[int, float] = {}

        for ply in range(w.depth):
            expanded: List[tuple] = []
            for (_, x, y, facing, strength, alive, banked, eaten, first) in frontier:
                for action in range(N_ACTIONS):
                    node = self._apply(snapshot, action, x, y, facing, strength,
                                       alive, banked, eaten, future)
                    if node is None:
                        continue
                    nx, ny, nfacing, nstrength, nalive, nbanked, neaten = node
                    node_first = first if first >= 0 else action
                    value = self._evaluate(fields, nx, ny, nfacing, nstrength,
                                           nalive, nbanked, neaten, ply)
                    expanded.append((value, nx, ny, nfacing, nstrength, nalive,
                                     nbanked, neaten, node_first))
            if not expanded:
                break
            expanded.sort(key=lambda n: -n[0])
            frontier = expanded[:w.beam_width]
            for node in frontier:
                first = node[8]
                if node[0] > best_by_action.get(first, float("-inf")):
                    best_by_action[first] = node[0]

        if not best_by_action:
            return self._greedy_action(snapshot)
        self.last_scores = best_by_action
        action = max(best_by_action, key=lambda a: best_by_action[a])
        if self.debug:
            self.log.append(self._explain(snapshot, action, best_by_action))
        return action

    # ------------------------------------------------------------------
    def _apply(self, snapshot: Snapshot, action: int, x: int, y: int,
               facing: int, strength: float, alive: float, banked: float,
               eaten: Tuple[Tuple[int, int], ...], future: float):
        """One action, then the rivals' reply.  ``None`` prunes the branch."""
        w = self.weights
        size = snapshot.size

        if is_turn(action):
            new_facing = action
            if new_facing == facing:
                return None  # turning to where we already look wastes the turn
            nx, ny = x, y
            nstrength = strength
            neaten = eaten
            nalive, nbanked = alive, banked
        elif action == STILL:
            new_facing = facing
            nx, ny = x, y
            nstrength = strength
            neaten = eaten
            nalive, nbanked = alive, banked
        else:  # MOVE
            new_facing = facing
            nx, ny = step(x, y, facing, size)
            neaten = eaten
            nstrength = strength
            nalive, nbanked = alive, banked
            if snapshot.has_walls and snapshot.is_blocked(nx, ny):
                # ``_Move`` returns without doing anything, so the turn is
                # simply lost. Modelling it as a move would leave the planner
                # believing it is somewhere it never went.
                nx, ny = x, y
            target = snapshot.rival_at(nx, ny)
            if target is not None:
                factor = defence_factor(facing, target.direction)
                if future >= strength / factor * w.attack_margin:
                    return None  # the F < a/f rule says decline this fight
                p = win_probability(strength, target.strength, facing,
                                    target.direction)
                # A loss keeps the strength we had and ends our participation.
                nbanked = banked + alive * (1.0 - p) * strength
                nalive = alive * p
                nstrength = strength + target.strength
            elif snapshot.has_cabbage(nx, ny) and (nx, ny) not in eaten:
                nstrength = strength + 1.0
                neaten = eaten + ((nx, ny),)

        # Now every rival takes its turn before we act again.
        risk = self.danger(snapshot, nx, ny, new_facing, nstrength)
        if risk > 0:
            nbanked = nbanked + nalive * risk * nstrength
            nalive = nalive * (1.0 - risk)
        return nx, ny, new_facing, nstrength, nalive, nbanked, neaten

    # ------------------------------------------------------------------
    def _evaluate(self, fields: "TurnFields", x: int, y: int, facing: int,
                  strength: float, alive: float, banked: float,
                  eaten: Tuple[Tuple[int, int], ...], ply: int) -> float:
        w = self.weights
        horizon = w.discount ** ply
        cell = y * fields.size + x

        positional = w.run_ahead * fields.run_value[
            fields.run_ahead(x, y, facing, eaten)]
        positional += w.density * fields.density[cell]
        positional += w.hunt * fields.hunt[facing][cell]
        positional -= w.exposure * fields.pressure[cell]
        if fields.back_turned is not None:
            positional -= w.facing_discipline * fields.back_turned[facing][cell]
        positional += w.survival_bonus

        return banked + alive * (strength + horizon * positional)

    # ------------------------------------------------------------------
    def _greedy_action(self, snapshot: Snapshot) -> int:
        """Cheap, always-sane policy: eat what is in front, else face the
        longest clear run."""
        ahead = step(snapshot.x, snapshot.y, snapshot.direction, snapshot.size)
        if snapshot.rival_at(ahead) is None and snapshot.has_cabbage(*ahead):
            return MOVE
        best_direction, best_run = snapshot.direction, -1
        for direction in range(4):
            run = self._scan_run(snapshot, snapshot.x, snapshot.y, direction)
            if run > best_run:
                best_direction, best_run = direction, run
        if best_direction == snapshot.direction:
            return MOVE if best_run > 0 else STILL
        return TURN_TO[best_direction]

    def _fallback(self, me) -> int:
        """Last resort - needs nothing but the engine objects themselves."""
        try:
            snapshot = observe(me, self.turn)
            return self._greedy_action(snapshot)
        except Exception:
            return MOVE

    # ------------------------------------------------------------------
    def _explain(self, snapshot: Snapshot, chosen: int,
                 scores: Dict[int, float]) -> str:  # pragma: no cover
        lines = [
            f"TURN {snapshot.turn}  ({snapshot.x},{snapshot.y}) "
            f"{DIRECTION_NAMES[snapshot.direction]}  strength={snapshot.strength:g}  "
            f"rank={snapshot.rank()}  cabbage={snapshot.n_cabbage}  F={self.future_value(snapshot):.0f}",
            "  actions:",
        ]
        for action in sorted(scores, key=lambda a: -scores[a]):
            mark = "  <-- chosen" if action == chosen else ""
            lines.append(f"    {ACTION_NAMES[action]:<7s} {scores[action]:9.2f}{mark}")
        risk = self.danger(snapshot, snapshot.x, snapshot.y, snapshot.direction,
                           snapshot.strength)
        lines.append(f"  danger where we stand: {risk:.1%}")
        lines.append("  rivals:")
        lines.append(self.registry.describe(snapshot))
        return "\n".join(lines)

    def timing_report(self) -> str:
        mean = self.total_ms / max(1, self.turn)
        return (f"turns={self.turn} mean={mean:.2f} ms "
                f"slowest={self.slowest_ms:.2f} ms faults={self.faults}")


__all__ = ["Brain", "Weights", "DEFAULT_WEIGHTS"]
