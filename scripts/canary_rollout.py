#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gate.burn_rate import WindowMetrics, evaluate_gate
from gate.prometheus import PrometheusClient, PrometheusConfig
from gate.slo import GateThresholds, ServiceSLO


LOCK_FILE = Path(os.getenv("ROLLBACK_LOCK_FILE", "runtime/rollback.lock"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote or roll back a canary using SLO burn-rate checks.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prometheus-url", help="Prometheus base URL.")
    source.add_argument("--sample-file", help="Deterministic canary metrics JSON for tests or demos.")
    parser.add_argument("--router-url", default=os.getenv("ROUTER_URL", "http://localhost:8080"))
    parser.add_argument("--weights", default="10,50,100", help="Comma-separated canary weights.")
    parser.add_argument("--window", default="5m", help="Canary analysis window.")
    parser.add_argument("--job-regex", default="app-canary", help="Prometheus job regex for canary metrics.")
    parser.add_argument("--availability-target", type=float, default=0.999)
    parser.add_argument("--latency-success-target", type=float, default=0.95)
    parser.add_argument("--latency-threshold-seconds", type=float, default=0.300)
    parser.add_argument("--burn-threshold", type=float, default=2.0)
    parser.add_argument("--max-staleness-seconds", type=int, default=300)
    parser.add_argument("--proof-log", default="docs/proof/canary.log")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def log(path: str, message: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    line = f"{timestamp} {message}"
    print(line)
    proof_path = Path(path)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def post_json(router_url: str, path: str, payload: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, **payload}
    response = requests.post(f"{router_url.rstrip('/')}{path}", json=payload, timeout=5)
    response.raise_for_status()
    return response.json()


def set_canary_weight(router_url: str, weight: int, dry_run: bool) -> dict[str, Any]:
    active_version = "canary" if weight == 100 else "stable"
    return post_json(
        router_url,
        "/admin/traffic",
        {"canary_weight": weight, "active_version": active_version},
        dry_run,
    )


def mark(router_url: str, event: str, dry_run: bool) -> None:
    post_json(router_url, "/admin/mark", {"event": event, "version": "canary"}, dry_run)


def rollback(router_url: str, proof_log: str, reason: str, dry_run: bool) -> None:
    set_canary_weight(router_url, 0, dry_run)
    mark(router_url, "rollback", dry_run)
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(reason + "\n", encoding="utf-8")
    log(proof_log, f"ROLLBACK_TRIGGERED reason={reason!r} canary_weight=0")


def decision_from_sample_step(step: dict[str, Any], args: argparse.Namespace):
    slo = ServiceSLO(
        availability_target=args.availability_target,
        latency_success_target=args.latency_success_target,
        latency_threshold_seconds=args.latency_threshold_seconds,
    )
    thresholds = GateThresholds(
        short_burn_rate=args.burn_threshold,
        long_burn_rate=args.burn_threshold,
        max_metric_staleness_seconds=args.max_staleness_seconds,
    )
    metrics = WindowMetrics.from_counts(
        window=step.get("window", args.window),
        requests=float(step["requests"]),
        errors=float(step["errors"]),
        slow_requests=float(step.get("slow_requests", 0)),
        p95_latency_seconds=float(step.get("p95_latency_seconds", 0)),
    )
    return evaluate_gate(
        metrics,
        metrics,
        slo=slo,
        thresholds=thresholds,
        stale_seconds=float(step.get("stale_seconds", 0)),
        metadata={"source": "sample", "weight": step.get("weight")},
    )


def decision_from_prometheus(args: argparse.Namespace):
    slo = ServiceSLO(
        availability_target=args.availability_target,
        latency_success_target=args.latency_success_target,
        latency_threshold_seconds=args.latency_threshold_seconds,
    )
    thresholds = GateThresholds(
        short_burn_rate=args.burn_threshold,
        long_burn_rate=args.burn_threshold,
        max_metric_staleness_seconds=args.max_staleness_seconds,
    )
    prometheus = PrometheusClient(
        PrometheusConfig(
            base_url=args.prometheus_url,
            job_regex=args.job_regex,
            latency_threshold_seconds=args.latency_threshold_seconds,
        )
    )
    metrics = prometheus.window_metrics(args.window)
    return evaluate_gate(
        metrics,
        metrics,
        slo=slo,
        thresholds=thresholds,
        stale_seconds=prometheus.metric_staleness_seconds(),
        metadata={"source": "prometheus", "job_regex": args.job_regex},
    )


def main() -> int:
    args = parse_args()
    weights = [int(value.strip()) for value in args.weights.split(",") if value.strip()]
    sample_steps: list[dict[str, Any]] = []
    if args.sample_file:
        with Path(args.sample_file).open("r", encoding="utf-8") as handle:
            sample_steps = json.load(handle)["steps"]

    if LOCK_FILE.exists():
        log(args.proof_log, f"CANARY_BLOCKED rollback_lock={LOCK_FILE}")
        return 1

    mark(args.router_url, "canary_start", args.dry_run)
    log(args.proof_log, f"CANARY_STARTED weights={weights}")

    for index, weight in enumerate(weights):
        set_canary_weight(args.router_url, weight, args.dry_run)
        log(args.proof_log, f"CANARY_WEIGHT_SET weight={weight}")

        if sample_steps:
            step = sample_steps[min(index, len(sample_steps) - 1)]
            decision = decision_from_sample_step(step, args)
        else:
            decision = decision_from_prometheus(args)

        decision_payload = json.dumps(decision.to_dict(), sort_keys=True)
        log(args.proof_log, f"CANARY_ANALYSIS weight={weight} decision={decision_payload}")
        if not decision.passed:
            rollback(args.router_url, args.proof_log, "; ".join(decision.reasons), args.dry_run)
            return 1

    mark(args.router_url, "promote", args.dry_run)
    log(args.proof_log, "CANARY_PROMOTED canary_weight=100")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
