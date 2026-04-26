from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gate.burn_rate import decision_from_sample, evaluate_gate
from gate.prometheus import PrometheusClient, PrometheusConfig
from gate.slo import GateThresholds, ServiceSLO


def _format_text(decision: object) -> str:
    data = decision.to_dict()  # type: ignore[attr-defined]
    lines = [
        f"Deployment gate: {data['status']}",
        (
            "short window: "
            f"availability burn={data['short']['availability_burn_rate']:.2f}x, "
            f"latency burn={data['short']['latency_burn_rate']:.2f}x, "
            f"p95={data['short']['p95_latency_seconds']:.3f}s"
        ),
        (
            "long window: "
            f"availability burn={data['long']['availability_burn_rate']:.2f}x, "
            f"latency burn={data['long']['latency_burn_rate']:.2f}x, "
            f"p95={data['long']['p95_latency_seconds']:.3f}s"
        ),
    ]
    if data["reasons"]:
        lines.append("reasons:")
        lines.extend(f"- {reason}" for reason in data["reasons"])
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SLO burn-rate deployment gate.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prometheus-url", help="Prometheus base URL, for example http://localhost:9090")
    source.add_argument("--sample-file", help="Read deterministic metrics from a JSON file.")
    parser.add_argument("--job-regex", default="app-stable|app-canary", help="Prometheus job regex to evaluate.")
    parser.add_argument("--short-window", default="1h", help="Short burn-rate window.")
    parser.add_argument("--long-window", default="6h", help="Long burn-rate window.")
    parser.add_argument("--availability-target", type=float, default=0.999)
    parser.add_argument("--latency-success-target", type=float, default=0.95)
    parser.add_argument("--latency-threshold-seconds", type=float, default=0.300)
    parser.add_argument("--short-burn-threshold", type=float, default=4.0)
    parser.add_argument("--long-burn-threshold", type=float, default=2.0)
    parser.add_argument("--max-staleness-seconds", type=int, default=300)
    parser.add_argument("--output", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.sample_file:
        with Path(args.sample_file).open("r", encoding="utf-8") as handle:
            decision = decision_from_sample(json.load(handle))
    else:
        slo = ServiceSLO(
            availability_target=args.availability_target,
            latency_success_target=args.latency_success_target,
            latency_threshold_seconds=args.latency_threshold_seconds,
        )
        thresholds = GateThresholds(
            short_burn_rate=args.short_burn_threshold,
            long_burn_rate=args.long_burn_threshold,
            max_metric_staleness_seconds=args.max_staleness_seconds,
        )
        prometheus = PrometheusClient(
            PrometheusConfig(
                base_url=args.prometheus_url,
                job_regex=args.job_regex,
                latency_threshold_seconds=args.latency_threshold_seconds,
            )
        )
        decision = evaluate_gate(
            prometheus.window_metrics(args.short_window),
            prometheus.window_metrics(args.long_window),
            slo=slo,
            thresholds=thresholds,
            stale_seconds=prometheus.metric_staleness_seconds(),
            metadata={"source": "prometheus", "job_regex": args.job_regex},
        )

    if args.output == "json":
        print(json.dumps(decision.to_dict(), indent=2, sort_keys=True))
    else:
        print(_format_text(decision))
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

