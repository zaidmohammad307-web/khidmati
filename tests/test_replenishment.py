import importlib.util
import math
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "replenishment_math",
    Path(__file__).resolve().parents[1] / "addons/deep_planning_plus/services/statistics.py",
)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


class ReplenishmentTests(unittest.TestCase):
    def test_zero_history_does_not_invent_demand(self):
        values = policy.reorder_policy([0] * 90, 14, 30, 1.65)
        self.assertEqual(values["maximum_qty"], 0)
        self.assertEqual(values["safety_qty"], 0)

    def test_constant_consumption_reorder_and_maximum(self):
        values = policy.reorder_policy([3] * 30, 7, 10, 1.65)
        self.assertEqual(values["daily_mean"], 3)
        self.assertEqual(values["safety_qty"], 0)
        self.assertEqual(values["reorder_qty"], 21)
        self.assertEqual(values["maximum_qty"], 51)

    def test_zero_consumption_days_affect_variability(self):
        values = policy.reorder_policy([0, 10], 4, 2, 1)
        self.assertEqual(values["daily_mean"], 5)
        self.assertEqual(values["daily_std"], 5)
        self.assertEqual(values["safety_qty"], 10)
        self.assertEqual(values["reorder_qty"], 30)
        self.assertEqual(values["maximum_qty"], 40)

    def test_uom_rounding_is_upward(self):
        values = policy.reorder_policy([0.1, 0.2], 2.5, 4, 1, 0.25)
        self.assertEqual(values["reorder_qty"] % 0.25, 0)
        self.assertGreaterEqual(values["maximum_qty"], values["reorder_qty"])

    def test_invalid_series_rejected(self):
        for daily in ([], [-1], [math.nan], [math.inf]):
            with self.subTest(daily=daily), self.assertRaises(ValueError):
                policy.reorder_policy(daily, 1, 1, 1)

    def test_invalid_policy_inputs_rejected(self):
        for inputs in (
            (-1, 10, 1, 1),
            (1, 0, 1, 1),
            (1, 10, -1, 1),
            (1, 10, 1, 0),
            (math.nan, 10, 1, 1),
        ):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                policy.reorder_policy([1], *inputs)
