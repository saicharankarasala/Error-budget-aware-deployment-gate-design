from __future__ import annotations

import json
import unittest
from pathlib import Path

from gate.burn_rate import WindowMetrics, calculate_burn_rate, decision_from_sample, evaluate_gate
from gate.slo import GateThresholds, ServiceSLO


ROOT = Path(__file__).resolve().parents[1]


class BurnRateTests(unittest.TestCase):
    def test_burn_rate_uses_allowed_error_rate(self) -> None:
        slo = ServiceSLO(availability_target=0.999)
        metrics = WindowMetrics.from_counts("1h", requests=100_000, errors=200, slow_requests=0, p95_latency_seconds=0.1)

        result = calculate_burn_rate(metrics, slo)

        self.assertAlmostEqual(result.error_rate, 0.002)
        self.assertAlmostEqual(result.availability_burn_rate, 2.0)

    def test_gate_passes_healthy_metrics(self) -> None:
        payload = json.loads((ROOT / "examples/safe_metrics.json").read_text(encoding="utf-8"))

        decision = decision_from_sample(payload)

        self.assertTrue(decision.passed, decision.reasons)

    def test_gate_blocks_high_short_window_burn(self) -> None:
        payload = json.loads((ROOT / "examples/unhealthy_metrics.json").read_text(encoding="utf-8"))

        decision = decision_from_sample(payload)

        self.assertFalse(decision.passed)
        self.assertTrue(any("1h availability burn" in reason for reason in decision.reasons))
        self.assertTrue(any("p95 latency" in reason for reason in decision.reasons))

    def test_gate_fails_closed_when_metrics_are_stale(self) -> None:
        metrics = WindowMetrics.from_counts("1h", requests=10_000, errors=0, slow_requests=0, p95_latency_seconds=0.1)

        decision = evaluate_gate(
            metrics,
            metrics,
            thresholds=GateThresholds(max_metric_staleness_seconds=300),
            stale_seconds=900,
        )

        self.assertFalse(decision.passed)
        self.assertTrue(any("stale" in reason for reason in decision.reasons))


if __name__ == "__main__":
    unittest.main()

