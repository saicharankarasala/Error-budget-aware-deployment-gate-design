from __future__ import annotations

import json
import unittest
from argparse import Namespace
from pathlib import Path

from scripts.canary_rollout import decision_from_sample_step


ROOT = Path(__file__).resolve().parents[1]


def args() -> Namespace:
    return Namespace(
        availability_target=0.999,
        latency_success_target=0.95,
        latency_threshold_seconds=0.300,
        burn_threshold=2.0,
        max_staleness_seconds=300,
        window="5m",
    )


class CanaryDecisionTests(unittest.TestCase):
    def test_canary_success_steps_pass(self) -> None:
        payload = json.loads((ROOT / "examples/canary_success.json").read_text(encoding="utf-8"))

        decisions = [decision_from_sample_step(step, args()) for step in payload["steps"]]

        self.assertTrue(all(decision.passed for decision in decisions))

    def test_canary_rollback_step_fails(self) -> None:
        payload = json.loads((ROOT / "examples/canary_rollback.json").read_text(encoding="utf-8"))

        decision = decision_from_sample_step(payload["steps"][0], args())

        self.assertFalse(decision.passed)
        self.assertTrue(any("availability burn" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()

