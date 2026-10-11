import importlib.util
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mps = load("mps_math", "addons/deep_mps/services/math.py")
capacity = load("capacity_math", "addons/deep_capacity_planning/services/math.py")
quality = load("quality_math", "addons/deep_quality/services/evaluation.py")


class PlanningTests(unittest.TestCase):
    def test_consumed_forecast(self):
        self.assertEqual(mps.demand_total(60, 100, 0, 50, "consume"), (100, 60))

    def test_additive_forecast(self):
        self.assertEqual(mps.demand_total(60, 100, 5, 50, "add"), (165, 115))

    def test_month_boundary(self):
        self.assertEqual(mps.period_end(date(2028, 2, 1), "monthly"), date(2028, 2, 29))

    def test_roll_forward(self):
        self.assertEqual(mps.bucket(10, 20, 100, 5), (75, 5))

    def test_minimum_lot_carries_excess_forward(self):
        self.assertEqual(mps.bucket(10, 0, 30, 0, minimum=50), (50, 30))

    def test_lot_multiple_rounds_up(self):
        self.assertEqual(mps.bucket(0, 0, 23, 0, multiple=10), (30, 7))

    def test_minimum_then_multiple(self):
        self.assertEqual(mps.lot_size(12, minimum=25, multiple=10), 30)

    def test_no_order_when_covered(self):
        self.assertEqual(mps.bucket(100, 0, 30, 10, minimum=50, multiple=10), (0, 70))

    def test_fractional_multiple_has_no_float_drift(self):
        self.assertAlmostEqual(mps.lot_size(0.3, multiple=0.1), 0.3)

    def test_negative_lot_size_rejected(self):
        with self.assertRaises(ValueError):
            mps.lot_size(5, minimum=-1)

    def test_setup_and_cycle(self):
        self.assertEqual(capacity.operation_minutes(20, 12, 1, 100, 30, 0, 20), 270)

    def test_multiple_batches(self):
        self.assertEqual(capacity.operation_minutes(40, 12, 1, 100, 30, 0, 20), 540)

    def test_capacity_and_efficiency(self):
        self.assertEqual(capacity.operation_minutes(20, 12, 2, 50, 30, 0), 270)

    def test_no_negative(self):
        with self.assertRaises(ValueError):
            capacity.operation_minutes(-1, 12, 1, 100, 30, 0)

    def test_numeric_limits(self):
        self.assertTrue(quality.evaluate("numeric", 15, 10, 20))
        self.assertFalse(quality.evaluate("numeric", 9, 10, 20))

    def test_invalid_boolean(self):
        with self.assertRaises(ValueError):
            quality.evaluate("boolean", "false")

    def test_nonfinite(self):
        with self.assertRaises(ValueError):
            quality.evaluate("numeric", float("nan"), 10, 20)

    def test_selection(self):
        self.assertTrue(quality.evaluate("selection", "A", options=["A", "B"]))
        with self.assertRaises(ValueError):
            quality.evaluate("selection", "C", options=["A", "B"])
