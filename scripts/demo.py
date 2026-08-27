#!/usr/bin/env python3
"""Watch SUPERPAC think.

Plays one match with diagnostics enabled and prints the decision trace: the
strategy in force, every action's score with its risk and information terms,
the principal variation, the threat map, and what SUPERPAC currently believes
about each rival - its likely policy, the competing hypotheses, the inferred
hidden parameters, and how well it has actually been predicting.

    python scripts/demo.py --turns 3 --board
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.superpac import SuperPac
from superpac.bots.patterned import PeriodicBot
from superpac.bots.reactive import GreedyEscapeBot
from superpac.bots.simple import GreedyFoodBot, RandomBot
from superpac.game.rules import ACTION_NAMES
from superpac.simulation.scenario import standard_scenarios
from superpac.simulation.tournament import run_game

HOLDER = {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=3, help="how many traces to print")
    ap.add_argument("--seed", type=int, default=4242)
    ap.add_argument("--board", action="store_true", help="also render the map")
    ap.add_argument("--opponents", default="greedy_escape,periodic,random")
    args = ap.parse_args()

    catalogue = {
        "greedy": lambda: GreedyFoodBot(2),
        "greedy_escape": lambda: GreedyEscapeBot(3, threshold=3),
        "periodic": lambda: PeriodicBot(4, period=11),
        "random": lambda: RandomBot(5),
    }
    chosen = [catalogue[name.strip()] for name in args.opponents.split(",")
              if name.strip() in catalogue]

    def make():
        agent = SuperPac(seed=1, debug=True)
        HOLDER["agent"] = agent
        return agent

    boards = []
    result = run_game([make] + chosen,
                      standard_scenarios(1, 1 + len(chosen), base_seed=args.seed)[0],
                      on_turn=lambda st, acts: boards.append(st.render())
                      if args.board else None)

    agent = HOLDER["agent"]
    traces = agent._log[-args.turns:]
    for i, trace in enumerate(traces):
        print("=" * 74)
        print(trace)
        if args.board and boards:
            index = len(boards) - len(traces) + i
            if 0 <= index < len(boards):
                print("\nboard (0 = SUPERPAC, . = food):")
                print(boards[index])
        print()

    print("=" * 74)
    print("MATCH RESULT")
    print(f"  placements : {result.placements}   (0 = winner)")
    print(f"  scores     : {[int(s) for s in result.scores]}")
    print(f"  survived   : {result.survived}")
    print(f"  turns      : {result.turns}")
    print(f"  SUPERPAC   : {agent.timing_report()}")


if __name__ == "__main__":
    main()
