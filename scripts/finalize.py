#!/usr/bin/env python3
"""Final integration: verify the tuned weights, then build the submission.

Refuses to ship weights that are not actually better than the hand-set
defaults.  An optimiser that ran is not the same thing as an optimiser that
helped, and the whole point of the promotion gate is that the difference gets
checked rather than assumed.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from superpac.ai.evaluator import Weights
from superpac.training.optimize_weights import load_weights
from superpac.training.self_play import accept_challenger, render_duel, version_duel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="results/weights_champion.json")
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--margin", type=float, default=0.03)
    ap.add_argument("--force", action="store_true",
                    help="ship the tuned weights even if the duel says no")
    args = ap.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, args.weights)
    if not os.path.exists(path):
        print(f"no tuned weights at {args.weights}; building with defaults")
        subprocess.run([sys.executable, "scripts/build_submission.py"], cwd=root)
        return

    defaults = Weights()
    tuned = load_weights(path)

    print("tuned vs hand-set defaults, identical scenarios, both in every seat")
    print("(tie-breaking randomness disabled on both sides)\n")
    start = time.perf_counter()
    result = version_duel(defaults, tuned, games=args.games)
    print(render_duel(result))
    print(f"[{time.perf_counter() - start:.0f}s]\n")

    promote = accept_challenger(result, margin=args.margin) or args.force
    if promote:
        print("-> shipping the TUNED weights")
        build = [sys.executable, "scripts/build_submission.py",
                 "--weights", args.weights]
    else:
        print("-> tuned weights did not clear the promotion margin; "
              "shipping the DEFAULTS")
        build = [sys.executable, "scripts/build_submission.py",
                 "--weights", "results/__nonexistent__.json"]

    subprocess.run(build, cwd=root, check=True)
    subprocess.run([sys.executable, "submission/superpac.py"], cwd=root, check=True)

    changed = [(name, getattr(defaults, name), getattr(tuned, name))
               for name in Weights.names()
               if abs(float(getattr(defaults, name)) - float(getattr(tuned, name))) > 1e-6]
    if changed:
        print(f"\nwhat the optimiser changed ({len(changed)} of {len(Weights.names())}):")
        for name, old, new in sorted(changed, key=lambda c: -abs(c[2] - c[1]) / max(1e-6, abs(c[1]))):
            direction = "up" if new > old else "down"
            print(f"  {name:<22s} {old:>8.3f} -> {new:>8.3f}  ({direction})")


if __name__ == "__main__":
    main()
