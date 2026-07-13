from __future__ import annotations

import unittest

from tests import BACKEND  # noqa: F401

from app.cruise_planner import CruisePlanningError, plan_cruise_route


class CruisePlannerTest(unittest.TestCase):
    def test_requires_at_least_three_waypoints(self) -> None:
        with self.assertRaises(CruisePlanningError):
            plan_cruise_route(
                {
                    "grid": {"width": 8, "height": 8},
                    "waypoints": [
                        {"id": "a", "x": 1, "y": 1},
                        {"id": "b", "x": 4, "y": 1},
                    ],
                }
            )

    def test_plans_out_and_back_route_for_three_points(self) -> None:
        plan = plan_cruise_route(
            {
                "grid": {"width": 12, "height": 12},
                "start_heading": "east",
                "waypoints": [
                    {"id": "a", "name": "A", "x": 1, "y": 1},
                    {"id": "b", "name": "B", "x": 6, "y": 1},
                    {"id": "c", "name": "C", "x": 6, "y": 5},
                ],
            }
        )

        self.assertTrue(plan["ok"])
        self.assertEqual(plan["route_mode"], "out_and_back")
        self.assertEqual(plan["totals"]["segments"], 4)
        self.assertEqual(plan["segments"][0]["from"]["id"], "a")
        self.assertEqual(plan["segments"][-1]["to"]["id"], "a")
        self.assertGreater(plan["totals"]["move_commands"], 0)
        self.assertEqual(plan["totals"]["arrivals"], 4)
        self.assertEqual(plan["totals"]["turnarounds"], 2)

    def test_obstacles_are_avoided(self) -> None:
        plan = plan_cruise_route(
            {
                "grid": {"width": 10, "height": 8},
                "start_heading": "east",
                "waypoints": [
                    {"id": "a", "x": 1, "y": 2},
                    {"id": "b", "x": 7, "y": 2},
                    {"id": "c", "x": 7, "y": 5},
                ],
                "obstacles": [{"x": x, "y": 2} for x in range(2, 7)],
            }
        )

        blocked = {(x, 2) for x in range(2, 7)}
        route = {(cell["x"], cell["y"]) for cell in plan["route"]}
        self.assertFalse(route & blocked)


if __name__ == "__main__":
    unittest.main()
