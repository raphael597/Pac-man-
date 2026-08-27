"""Match and tournament drivers plus the statistics the benchmarks report on."""

from __future__ import annotations

import random
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..game.state import GameState
from .engine import Engine, MatchResult
from .scenario import Scenario

BotFactory = Callable[[], object]


def run_game(factories: Sequence[BotFactory], scenario: Scenario,
             collect_times: bool = True, max_turns: Optional[int] = None,
             on_turn: Optional[Callable[[GameState, List[int]], None]] = None,
             ) -> MatchResult:
    """Play one match to completion.

    Bots are handed the *same* state object each turn with ``state.me``
    retargeted, which is both fast and a realistic model of how these engines
    usually behave.  A bot that raises or overruns is not allowed to abort the
    match: it is charged a fault and given a legal fallback move, exactly as a
    tournament harness would.
    """
    state, rng = scenario.build()
    if max_turns is not None:
        state.rules = state.rules.with_(max_turns=max_turns)
    engine = Engine(state.rules, rng)
    n = state.n_players
    food_start = len(state.food)

    bots = []
    for pid, factory in enumerate(factories[:n]):
        bot = factory()
        try:
            bot.reset(state, pid)
        except Exception:
            pass
        bots.append(bot)

    times = [0.0] * n
    crashes = [0] * n
    timeouts = [0] * n
    limit = state.rules.time_limit_ms / 1000.0
    eliminated_on: List[Optional[int]] = [None] * n
    actions = [4] * n

    while not state.is_terminal():
        for pid in range(n):
            if not state.alive[pid]:
                actions[pid] = 4
                continue
            state.me = pid
            state._legal_cache = None
            legal = state.legal_actions(pid)
            start = time.perf_counter() if collect_times else 0.0
            try:
                action = bots[pid].act(state)
            except Exception:
                crashes[pid] += 1
                action = legal[0] if legal else 4
            if collect_times:
                elapsed = time.perf_counter() - start
                times[pid] += elapsed
                if elapsed > limit:
                    timeouts[pid] += 1
            if action not in legal:
                action = legal[0] if legal else 4
            actions[pid] = action

        was_alive = list(state.alive)
        engine.step(state, actions)
        for pid in range(n):
            if was_alive[pid] and not state.alive[pid]:
                eliminated_on[pid] = state.turn
        if on_turn is not None:
            on_turn(state, actions)

    state.me = 0
    result = engine.finalise(state, food_start)
    result.move_times = times
    result.crashes = crashes
    result.timeouts = timeouts
    result.eliminated_on = eliminated_on
    return result


# --------------------------------------------------------------------------
@dataclass
class BotStats:
    name: str
    games: int = 0
    wins: int = 0
    placement_sum: int = 0
    score_sum: float = 0.0
    survived: int = 0
    eliminated: int = 0
    food_sum: int = 0
    time_sum: float = 0.0
    turn_sum: int = 0
    crashes: int = 0
    timeouts: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def avg_placement(self) -> float:
        return self.placement_sum / self.games if self.games else 0.0

    @property
    def avg_score(self) -> float:
        return self.score_sum / self.games if self.games else 0.0

    @property
    def survival_rate(self) -> float:
        return self.survived / self.games if self.games else 0.0

    @property
    def ms_per_move(self) -> float:
        return 1000.0 * self.time_sum / self.turn_sum if self.turn_sum else 0.0

    def row(self) -> str:
        return (f"{self.name:<22s} games={self.games:<5d} win={self.win_rate:6.1%} "
                f"place={self.avg_placement:4.2f} score={self.avg_score:6.2f} "
                f"surv={self.survival_rate:6.1%} ms/mv={self.ms_per_move:6.2f} "
                f"crash={self.crashes} to={self.timeouts}")


@dataclass
class TournamentReport:
    stats: Dict[str, BotStats] = field(default_factory=dict)
    games_played: int = 0

    def get(self, name: str) -> BotStats:
        if name not in self.stats:
            self.stats[name] = BotStats(name)
        return self.stats[name]

    def ranked(self) -> List[BotStats]:
        return sorted(self.stats.values(),
                      key=lambda s: (-s.win_rate, s.avg_placement, -s.avg_score))

    def render(self) -> str:
        head = f"{self.games_played} games\n" + "-" * 96
        return head + "\n" + "\n".join(s.row() for s in self.ranked())


def run_tournament(entries: Sequence[Tuple[str, BotFactory]],
                   scenarios: Sequence[Scenario],
                   n_players: int = 4,
                   repeats: int = 1,
                   rotate_seats: bool = True,
                   seed: int = 0,
                   progress: Optional[Callable[[int, int], None]] = None,
                   ) -> TournamentReport:
    """Round-robin style tournament over a fixed scenario battery.

    Seats are rotated so no entrant benefits from a favourable spawn, and
    every entrant meets the same scenario set - the two things that make
    version-vs-version comparisons trustworthy.
    """
    report = TournamentReport()
    rng = random.Random(seed)
    names = [e[0] for e in entries]
    total = len(scenarios) * repeats
    done = 0

    for scenario in scenarios:
        for rep in range(repeats):
            if len(entries) <= n_players:
                table = list(range(len(entries)))
            else:
                table = rng.sample(range(len(entries)), n_players)
            while len(table) < n_players:
                table.append(rng.randrange(len(entries)))

            rotation = rep % n_players if rotate_seats else 0
            table = table[rotation:] + table[:rotation]

            scen = Scenario(scenario.seed + rep * 7919, scenario.spec,
                            scenario.rules, n_players)
            result = run_game([entries[i][1] for i in table], scen)

            for seat, entry_idx in enumerate(table):
                st = report.get(names[entry_idx])
                st.games += 1
                st.placement_sum += result.placements[seat]
                st.score_sum += result.scores[seat]
                st.food_sum += result.food_taken[seat]
                st.turn_sum += result.turns
                st.time_sum += result.move_times[seat] if result.move_times else 0.0
                st.crashes += result.crashes[seat] if result.crashes else 0
                st.timeouts += result.timeouts[seat] if result.timeouts else 0
                if result.survived[seat]:
                    st.survived += 1
                else:
                    st.eliminated += 1
                if result.winner == seat:
                    st.wins += 1
            report.games_played += 1
            done += 1
            if progress is not None and done % 25 == 0:
                progress(done, total)
    return report


def head_to_head(a: Tuple[str, BotFactory], b: Tuple[str, BotFactory],
                 scenarios: Sequence[Scenario], fillers: Sequence[Tuple[str, BotFactory]] = (),
                 n_players: int = 4, seed: int = 0) -> TournamentReport:
    """A vs B on identical scenarios with identical filler opponents.

    Both entrants play *every* scenario from *every* seat, which removes seat
    and map luck from the comparison - the point of section 41 of the brief.
    """
    report = TournamentReport()
    rng = random.Random(seed)
    pool = list(fillers)
    for scenario in scenarios:
        for seat_a in range(n_players):
            table: List[Tuple[str, BotFactory]] = [None] * n_players  # type: ignore
            seat_b = (seat_a + 1) % n_players
            table[seat_a] = a
            table[seat_b] = b
            spare = [i for i in range(n_players) if i not in (seat_a, seat_b)]
            for i, s in enumerate(spare):
                table[s] = pool[i % len(pool)] if pool else a
            scen = Scenario(scenario.seed, scenario.spec, scenario.rules, n_players)
            result = run_game([t[1] for t in table], scen)
            for seat, (name, _) in enumerate(table):
                st = report.get(name)
                st.games += 1
                st.placement_sum += result.placements[seat]
                st.score_sum += result.scores[seat]
                st.turn_sum += result.turns
                st.time_sum += result.move_times[seat] if result.move_times else 0.0
                st.crashes += result.crashes[seat] if result.crashes else 0
                st.timeouts += result.timeouts[seat] if result.timeouts else 0
                if result.survived[seat]:
                    st.survived += 1
                if result.winner == seat:
                    st.wins += 1
            report.games_played += 1
    return report


__all__ = ["run_game", "run_tournament", "head_to_head", "BotStats",
           "TournamentReport"]
