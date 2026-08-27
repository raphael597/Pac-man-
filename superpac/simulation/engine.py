"""Reference game engine implementing :class:`RuleSet` faithfully.

This is the development simulator: it is *not* the tournament engine, and it
does not pretend to be.  Its job is to give the benchmark and optimisation
loops a rule-parameterised world so we can prove SUPERPAC is strong across
every plausible reading of the unknown rules rather than tuned to one guess.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..game.map_model import MapGraph
from ..game.rules import DEFAULT_RULES, RuleSet
from ..game.state import GameState


@dataclass
class MatchResult:
    """Everything a benchmark could want from one completed game."""

    scores: List[float]
    placements: List[int]
    """``placements[p]`` is 0 for the winner, 1 for runner-up, ..."""
    winner: int
    survived: List[bool]
    turns: int
    food_taken: List[int]
    eliminated_on: List[Optional[int]]
    move_times: List[float] = field(default_factory=list)
    """Total seconds each player spent choosing moves."""
    crashes: List[int] = field(default_factory=list)
    timeouts: List[int] = field(default_factory=list)


class Engine:
    """Steps a :class:`GameState` forward according to a :class:`RuleSet`."""

    def __init__(self, rules: Optional[RuleSet] = None, rng: Optional[random.Random] = None) -> None:
        self.rules = rules or DEFAULT_RULES
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------
    def step(self, state: GameState, actions: Sequence[int]) -> GameState:
        """Advance one turn in place and return the same object.

        ``actions[p]`` is player ``p``'s chosen action; entries for dead
        players are ignored.
        """
        rules = self.rules
        graph = state.graph
        n = state.n_players

        movers = [p for p in range(n) if state.alive[p]]
        if rules.simultaneous:
            intended = self._intended_cells(state, actions, movers)
            self._resolve_simultaneous(state, movers, intended)
        else:
            order = movers[:]
            if rules.turn_order_random:
                self.rng.shuffle(order)
            self._resolve_sequential(state, order, actions)

        # --- economy -----------------------------------------------------
        if rules.step_cost:
            for p in movers:
                if state.alive[p] and actions[p] != 4:
                    state.scores[p] -= rules.step_cost
        if rules.survival_bonus:
            for p in range(n):
                if state.alive[p]:
                    state.scores[p] += rules.survival_bonus

        state.turn += 1
        state._legal_cache = None
        return state

    # ------------------------------------------------------------------
    def _intended_cells(self, state: GameState, actions: Sequence[int],
                        movers: Sequence[int]) -> Dict[int, int]:
        graph = state.graph
        out: Dict[int, int] = {}
        for p in movers:
            action = actions[p] if p < len(actions) else 4
            if action == 4 and not state.rules.allow_stay:
                action = 4  # staying is always physically possible
            out[p] = graph.step(state.positions[p], action)
        return out

    # ------------------------------------------------------------------
    def _resolve_simultaneous(self, state: GameState, movers: List[int],
                              intended: Dict[int, int]) -> None:
        rules = self.rules
        mode = rules.collision_mode

        if mode == "block":
            intended = self._apply_blocking(state, movers, intended)
        elif mode == "swap_block":
            intended = self._refuse_swaps(state, movers, intended)

        old = {p: state.positions[p] for p in movers}
        for p in movers:
            state.positions[p] = intended[p]

        if mode == "elimination":
            self._apply_eliminations(state, movers, old)

        self._consume_food(state, [p for p in movers if state.alive[p]])

    # ------------------------------------------------------------------
    def _apply_blocking(self, state: GameState, movers: List[int],
                        intended: Dict[int, int]) -> Dict[int, int]:
        """Refuse moves into cells that stay occupied; iterate to a fixpoint.

        A chain ``A -> B -> C -> empty`` should all succeed, so this repeats
        until nothing changes rather than resolving in one pass.
        """
        for _ in range(len(movers) + 1):
            # Stationary players claim their cell first: standing your ground
            # always beats walking in, whatever the seat order happens to be.
            occupied: Dict[int, int] = {}
            for p in movers:
                if intended[p] == state.positions[p]:
                    occupied[state.positions[p]] = p
            for p in movers:
                occupied.setdefault(intended[p], p)

            changed = False
            for p in movers:
                target = intended[p]
                if target == state.positions[p]:
                    continue
                holder = occupied.get(target)
                if holder is not None and holder != p:
                    intended[p] = state.positions[p]
                    changed = True
            if not changed:
                break
        return intended

    def _refuse_swaps(self, state: GameState, movers: List[int],
                      intended: Dict[int, int]) -> Dict[int, int]:
        for i, p in enumerate(movers):
            for q in movers[i + 1:]:
                if intended[p] == state.positions[q] and intended[q] == state.positions[p]:
                    intended[p] = state.positions[p]
                    intended[q] = state.positions[q]
        return intended

    # ------------------------------------------------------------------
    def _apply_eliminations(self, state: GameState, movers: List[int],
                            old: Dict[int, int]) -> None:
        """Kill players that share a cell or that crossed through each other."""
        rules = self.rules
        if rules.head_on_resolution == "none":
            return  # contact is harmless under this variant
        groups: Dict[int, List[int]] = {}
        for p in movers:
            if state.alive[p]:
                groups.setdefault(state.positions[p], []).append(p)

        clashes: List[List[int]] = [g for g in groups.values() if len(g) > 1]

        # Swaps: two players trading cells pass *through* one another.
        for i, p in enumerate(movers):
            for q in movers[i + 1:]:
                if state.positions[p] == old[q] and state.positions[q] == old[p] and old[p] != old[q]:
                    clashes.append([p, q])

        for group in clashes:
            group = [p for p in group if state.alive[p]]
            if len(group) < 2:
                continue
            survivor = self._pick_survivor(state, group, old)
            for p in group:
                if p != survivor:
                    self._eliminate(state, p)
                    if survivor is not None and rules.kill_bonus:
                        state.scores[survivor] += rules.kill_bonus

    def _pick_survivor(self, state: GameState, group: List[int],
                       old: Dict[int, int]) -> Optional[int]:
        mode = self.rules.head_on_resolution
        if mode == "both":
            return None  # everyone in the clash dies
        if mode == "higher_score":
            best = max(group, key=lambda p: (state.scores[p], -p))
            ties = [p for p in group if state.scores[p] == state.scores[best]]
            return best if len(ties) == 1 else None
        if mode == "mover":
            # Whoever stood still owns the cell; movers into it die.
            standers = [p for p in group if old[p] == state.positions[p]]
            if len(standers) == 1:
                return standers[0]
            return None
        return None

    def _eliminate(self, state: GameState, player: int) -> None:
        if self.rules.respawn:
            state.positions[player] = state.spawns[player]
            return
        state.alive[player] = False
        state.positions[player] = -1

    # ------------------------------------------------------------------
    def _resolve_sequential(self, state: GameState, order: List[int],
                            actions: Sequence[int]) -> None:
        graph = state.graph
        rules = self.rules
        for p in order:
            if not state.alive[p]:
                continue
            action = actions[p] if p < len(actions) else 4
            target = graph.step(state.positions[p], action)
            occupant = next(
                (q for q in range(state.n_players)
                 if q != p and state.alive[q] and state.positions[q] == target),
                None,
            )
            if occupant is not None:
                if rules.collision_mode == "block":
                    target = state.positions[p]
                elif rules.collision_mode == "elimination" and rules.head_on_resolution != "none":
                    was_at = state.positions[p]
                    state.positions[p] = target
                    # ``occupant`` stood still, ``p`` walked in - that
                    # distinction is what "mover" resolution turns on.
                    survivor = self._pick_survivor(
                        state, [p, occupant], {p: was_at, occupant: target})
                    for q in (p, occupant):
                        if q != survivor:
                            self._eliminate(state, q)
                    if survivor is not None and rules.kill_bonus:
                        state.scores[survivor] += rules.kill_bonus
                    if state.alive[p]:
                        self._consume_food(state, [p])
                    continue
            state.positions[p] = target
            self._consume_food(state, [p])

    # ------------------------------------------------------------------
    def _consume_food(self, state: GameState, players: Sequence[int]) -> None:
        rules = self.rules
        food = state.food
        arrivals: Dict[int, List[int]] = {}
        for p in players:
            cell = state.positions[p]
            if cell in food:
                arrivals.setdefault(cell, []).append(p)
        for cell, claimants in arrivals.items():
            if len(claimants) == 1:
                winner = claimants[0]
            elif rules.turn_order_random:
                winner = self.rng.choice(claimants)
            else:
                winner = min(claimants)
            state.scores[winner] += rules.food_value
            if not rules.food_respawn:
                food.discard(cell)

    # ------------------------------------------------------------------
    def finalise(self, state: GameState, food_start: int) -> MatchResult:
        """Rank players once the match has ended."""
        rules = self.rules
        n = state.n_players
        alive = list(state.alive)

        def rank_key(p: int):
            # A sole survivor outranks score under the Highlander rule.
            if rules.highlander_wins and rules.contact_is_lethal:
                return (1 if alive[p] else 0, state.scores[p])
            return (0, state.scores[p])

        order = sorted(range(n), key=rank_key, reverse=True)
        placements = [0] * n
        for place, p in enumerate(order):
            placements[p] = place
        return MatchResult(
            scores=list(state.scores),
            placements=placements,
            winner=order[0],
            survived=alive,
            turns=state.turn,
            food_taken=[int(round(s / max(1e-9, rules.food_value))) for s in state.scores],
            eliminated_on=[None] * n,
        )


__all__ = ["Engine", "MatchResult"]
