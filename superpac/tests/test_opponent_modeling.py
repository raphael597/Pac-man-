"""Opponent modelling: prediction, periodicity, confidence calibration."""
from __future__ import annotations

import random
import unittest

from superpac.game.map_model import graph_from_lines
from superpac.game.rules import EAST, NORTH, SOUTH, STAY, WEST
from superpac.game.state import GameState
from superpac.opponents.context_model import ContextPolicyModel, ObservationContext, bucket
from superpac.opponents.hidden_state import ModeClassifier
from superpac.opponents.model import OpponentModel, OpponentRegistry
from superpac.opponents.pattern_detector import OscillationDetector, PredictionScorer
from superpac.opponents.periodicity import AnomalyDetector, CycleDetector
from superpac.opponents.predictor import HypothesisEnsemble
from superpac.opponents.sequence_model import NGramModel

OPEN = ["#######", "#.....#", "#.....#", "#.....#", "#######"]
ALL_ACTIONS = (0, 1, 2, 3, 4)


class TestNGram(unittest.TestCase):
    def test_learns_a_repeating_script(self):
        script = [EAST, EAST, NORTH, EAST, EAST, SOUTH]
        model = NGramModel(3)
        for i in range(120):
            model.observe(script[i % len(script)])
        # After E,E the script always says NORTH or SOUTH depending on phase;
        # after N the script always says EAST.
        model.history.clear()
        for a in (SOUTH, EAST, EAST):
            model.history.append(a)
        prediction = model.predict(ALL_ACTIONS)
        self.assertEqual(max(range(5), key=lambda a: prediction[a]), NORTH)
        self.assertGreater(model.determinism(), 0.9)

    def test_distribution_is_normalised_over_legal_actions(self):
        model = NGramModel(2)
        for a in (EAST, NORTH, EAST):
            model.observe(a)
        legal = (EAST, NORTH)
        prediction = model.predict(legal)
        self.assertAlmostEqual(sum(prediction), 1.0, places=6)
        self.assertEqual(prediction[SOUTH], 0.0)
        self.assertEqual(prediction[WEST], 0.0)


class TestPeriodicity(unittest.TestCase):
    def test_cycle_detector_finds_the_period(self):
        script = [EAST, EAST, NORTH]
        detector = CycleDetector()
        for i in range(90):
            detector.observe(script[i % 3])
        self.assertEqual(detector.period, 3)
        self.assertGreater(detector.strength, 0.8)

    def test_anomaly_interval_recovered_despite_hidden_anomalies(self):
        # A third of anomalies coincide with the dominant action and are
        # invisible; the estimate must still be 15, not a multiple of it.
        rng = random.Random(4)
        detector = AnomalyDetector()
        for turn in range(240):
            action = rng.choice([NORTH, SOUTH, WEST]) if turn % 15 == 0 else EAST
            detector.observe(action, turn)
        mean, sd, confidence = detector.interval_stats()
        self.assertAlmostEqual(mean, 15.0, delta=1.0)
        self.assertGreater(confidence, 0.6)

    def test_non_periodic_stream_stays_unconfident(self):
        rng = random.Random(2)
        detector = AnomalyDetector()
        for turn in range(240):
            detector.observe(rng.choice([EAST, EAST, EAST, NORTH, SOUTH]), turn)
        _, _, confidence = detector.interval_stats()
        self.assertLess(confidence, 0.45)


class TestContextModel(unittest.TestCase):
    def test_buckets_are_monotonic(self):
        self.assertEqual(bucket(0), 0)
        self.assertEqual(bucket(1), 0)
        self.assertEqual(bucket(3), 1)
        self.assertEqual(bucket(6), 2)
        self.assertEqual(bucket(99), 3)

    def test_backoff_answers_before_the_specific_table_fills(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(4, 1)], [g.index(1, 1), g.index(3, 3)])
        ctx = ObservationContext(st, 1)
        model = ContextPolicyModel()
        model.observe(ctx, EAST)
        prediction = model.predict(ctx)
        self.assertAlmostEqual(sum(prediction), 1.0, places=6)
        self.assertGreater(prediction[EAST], 0.0)

    def test_prediction_only_covers_legal_actions(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [], [g.index(1, 1), g.index(1, 1)])
        ctx = ObservationContext(st, 0)
        model = ContextPolicyModel()
        prediction = model.predict(ctx)
        for action in range(5):
            if action not in ctx.legal:
                self.assertEqual(prediction[action], 0.0)


class TestEnsemble(unittest.TestCase):
    def test_weights_stay_normalised_and_floored(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(4, 1)], [g.index(1, 1), g.index(3, 3)])
        ensemble = HypothesisEnsemble()
        for _ in range(40):
            ctx = ObservationContext(st, 1)
            ensemble.predict(ctx)
            ensemble.observe(ctx, EAST)
        self.assertAlmostEqual(sum(ensemble.weights), 1.0, places=6)
        self.assertTrue(all(w > 0 for w in ensemble.weights),
                        "fixed-share must keep every hypothesis recoverable")

    def test_a_consistently_wrong_hypothesis_loses_weight(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(5, 1)], [g.index(1, 1), g.index(3, 3)])
        ensemble = HypothesisEnsemble()
        uniform_index = [h.name for h in ensemble.hypotheses].index("random")
        greedy_index = [h.name for h in ensemble.hypotheses].index("greedy_food")
        for _ in range(60):
            ctx = ObservationContext(st, 1)
            ensemble.predict(ctx)
            ensemble.observe(ctx, ctx.food_action)
        self.assertGreater(ensemble.weights[greedy_index],
                           ensemble.weights[uniform_index])


class TestScorer(unittest.TestCase):
    def test_perfect_prediction_scores_high(self):
        scorer = PredictionScorer()
        for _ in range(40):
            scorer.record([0.0, 0.0, 0.0, 1.0, 0.0], EAST, (0, 1, 2, 3))
        self.assertAlmostEqual(scorer.short_accuracy, 1.0)
        self.assertGreater(scorer.confidence(), 0.85)
        self.assertFalse(scorer.is_erratic())

    def test_uniform_prediction_of_noise_is_flagged_erratic(self):
        rng = random.Random(0)
        scorer = PredictionScorer()
        for _ in range(60):
            scorer.record([0.25, 0.25, 0.25, 0.25, 0.0],
                          rng.choice((0, 1, 2, 3)), (0, 1, 2, 3))
        self.assertLess(scorer.confidence(), 0.3)
        self.assertTrue(scorer.is_erratic())

    def test_confidently_wrong_scores_worse_than_honest_uncertainty(self):
        confident = PredictionScorer()
        honest = PredictionScorer()
        for _ in range(30):
            confident.record([0.0, 0.0, 0.0, 0.97, 0.03], NORTH, (0, 1, 2, 3))
            honest.record([0.25, 0.25, 0.25, 0.25, 0.0], NORTH, (0, 1, 2, 3))
        self.assertGreater(confident.log_loss, honest.log_loss)


class TestOscillation(unittest.TestCase):
    def test_two_cell_bounce_is_detected(self):
        detector = OscillationDetector()
        for i in range(12):
            detector.observe(10 if i % 2 else 11)
        self.assertTrue(detector.is_oscillating())

    def test_steady_travel_is_not(self):
        detector = OscillationDetector()
        for i in range(12):
            detector.observe(i)
        self.assertFalse(detector.is_oscillating())


class TestRegistry(unittest.TestCase):
    def test_illegal_teleports_do_not_corrupt_the_model(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [], [g.index(1, 1), g.index(1, 2)])
        model = OpponentModel(1)
        model.observe_transition(st, g.index(1, 2), g.index(5, 3))
        self.assertEqual(model.observations, 0)

    def test_registry_keeps_models_separate(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(4, 1)],
                       [g.index(1, 1), g.index(2, 2), g.index(4, 3)])
        registry = OpponentRegistry()
        registry.update(st)
        self.assertIsNot(registry.model_for(1), registry.model_for(2))

    def test_forecast_conserves_probability_mass(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(4, 1)], [g.index(1, 1), g.index(3, 2)])
        registry = OpponentRegistry()
        registry.update(st)
        for frame in registry.model_for(1).forecast(st, horizon=4):
            self.assertAlmostEqual(sum(frame.values()), 1.0, places=5)

    def test_forecast_only_lands_on_walkable_cells(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(4, 1)], [g.index(1, 1), g.index(3, 2)])
        registry = OpponentRegistry()
        registry.update(st)
        for frame in registry.model_for(1).forecast(st, horizon=4):
            for cell in frame:
                self.assertTrue(g.passable[cell])


class TestModes(unittest.TestCase):
    def test_belief_is_a_distribution(self):
        g = graph_from_lines(OPEN)
        st = GameState(g, [g.index(5, 1)], [g.index(1, 1), g.index(3, 2)])
        classifier = ModeClassifier()
        for _ in range(20):
            ctx = ObservationContext(st, 1)
            classifier.observe(ctx, ctx.food_action)
        self.assertAlmostEqual(sum(classifier.belief), 1.0, places=6)
        self.assertEqual(classifier.mode_name(), "COLLECT")


if __name__ == "__main__":
    unittest.main()
