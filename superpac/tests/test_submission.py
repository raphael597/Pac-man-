"""The shipped single-file build is the actual deliverable, so it gets tests.

Everything else in this repository can be perfect and it will not matter if
the bundle fails to import on the tournament machine.  These tests build it
from scratch and exercise it the way an unknown host would: through the
adapter, with no package on the path.
"""
from __future__ import annotations

import importlib.util
import os
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ARENA = ["###########",
         "#....#....#",
         "#.##.#.##.#",
         "#....#....#",
         "#.##...##.#",
         "#.........#",
         "###########"]
WIDTH = len(ARENA[0])
WALKABLE = [(x, y) for y, row in enumerate(ARENA)
            for x, ch in enumerate(row) if ch != "#"]
DELTAS = ((0, -1), (0, 1), (-1, 0), (1, 0), (0, 0))


def _build(target: str) -> None:
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "build_submission.py"),
         "--out", target],
        cwd=ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"build failed:\n{result.stdout}\n{result.stderr}")


class TestSubmissionBundle(unittest.TestCase):
    module = None
    path = None
    tmpdir = None

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmpdir.name, "superpac_build.py")
        _build(cls.path)
        # Loaded WITHOUT registering in sys.modules first, which is the case
        # that used to crash dataclasses at import time.
        spec = importlib.util.spec_from_file_location("superpac_build", cls.path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    @classmethod
    def tearDownClass(cls):
        if cls.tmpdir:
            cls.tmpdir.cleanup()

    # ------------------------------------------------------------------
    def test_bundle_is_standard_library_only(self):
        with open(self.path) as fh:
            source = fh.read()
        self.assertNotIn("from superpac", source)
        self.assertNotIn("import superpac", source)
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("from .") or stripped.startswith("from .."):
                self.fail(f"relative import survived the flattening: {stripped}")

    def test_every_entry_point_exists(self):
        for name in ("SuperPacPlayer", "Player", "Bot", "Agent", "AI",
                     "get_move", "choose_action", "move", "next_move",
                     "reset", "inspect_api", "WEIGHTS", "TUNED_WEIGHTS"):
            self.assertTrue(hasattr(self.module, name), f"missing {name}")

    def test_embedded_weights_match_the_dataclass(self):
        from superpac.ai.evaluator import Weights
        self.assertEqual(set(self.module.TUNED_WEIGHTS), set(Weights.names()),
                         "embedded weights drifted from the Weights dataclass")

    # ------------------------------------------------------------------
    def _play(self, dialect: str, turns: int = 40):
        player = self.module.SuperPacPlayer()
        me = (1, 1)
        rivals = [(9, 5), (5, 3)]
        food = {c for c in WALKABLE if c != me and c not in rivals}
        rng = random.Random(1)
        for turn in range(turns):
            if not food:
                break
            if dialect == "dict_xy":
                state = {"grid": ARENA, "food": sorted(food), "my_position": me,
                         "opponents": rivals, "turn": turn}
            elif dialect == "rowcol":
                state = {"board": [[1 if ch == "#" else 0 for ch in row] for row in ARENA],
                         "pellets": [(y, x) for (x, y) in sorted(food)],
                         "pos": (me[1], me[0]),
                         "enemies": [(y, x) for (x, y) in rivals], "step": turn}
            else:
                state = {"maze": ARENA,
                         "food": sorted(y * WIDTH + x for x, y in food),
                         "position": me[1] * WIDTH + me[0],
                         "others": [y * WIDTH + x for x, y in rivals], "turn": turn}
            action = player.get_move(state)
            self.assertIsInstance(action, int)
            self.assertIn(action, range(5))
            dx, dy = DELTAS[action]
            nxt = (me[0] + dx, me[1] + dy)
            self.assertIn(nxt, WALKABLE,
                          f"{dialect}: illegal move {me} -> {nxt} (action {action})")
            me = nxt
            food.discard(me)
            rivals = [rng.choice([p for p in
                                  [(r[0] + u, r[1] + v) for u, v in DELTAS[:4]]
                                  if p in WALKABLE] or [r]) for r in rivals]
        return player

    def test_plays_legally_through_an_xy_dict_host(self):
        player = self._play("dict_xy")
        self.assertEqual(player.brain.faults, 0)
        self.assertFalse(player.extractor.schema.swap_axes)

    def test_plays_legally_through_a_row_col_host(self):
        player = self._play("rowcol")
        self.assertEqual(player.brain.faults, 0)
        self.assertTrue(player.extractor.schema.swap_axes,
                        "axis order should have been calibrated, not assumed")

    def test_plays_legally_through_a_flat_cell_id_host(self):
        player = self._play("flat")
        self.assertEqual(player.brain.faults, 0)
        self.assertTrue(player.extractor.schema.flat_ids)

    # ------------------------------------------------------------------
    def test_a_garbage_state_still_yields_an_action(self):
        player = self.module.SuperPacPlayer()
        for junk in ({}, {"nonsense": 1}, None, [1, 2, 3], "hello"):
            action = player.get_move(junk)
            self.assertIn(action, range(5),
                          "the host is owed a move even when the state is unreadable")

    def test_module_level_functions_work(self):
        state = {"grid": ARENA, "food": [(2, 1)], "my_position": (1, 1),
                 "opponents": [(9, 5)], "turn": 0}
        for fn in (self.module.get_move, self.module.choose_action,
                   self.module.move, self.module.next_move):
            self.assertIn(fn(state), range(5))
        self.module.reset()

    def test_self_test_passes(self):
        result = subprocess.run([sys.executable, self.path],
                                capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0,
                         f"self-test failed:\n{result.stdout}\n{result.stderr}")
        self.assertIn("no faults", result.stdout)


if __name__ == "__main__":
    unittest.main()
