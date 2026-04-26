#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Roll back the canary to stable traffic.")
    parser.add_argument("--router-url", default=os.getenv("ROUTER_URL", "http://localhost:8080"))
    parser.add_argument("--reason", default="canary failed SLO guardrail")
    parser.add_argument("--proof-log", default="docs/proof/rollback.log")
    parser.add_argument("--aws", action="store_true", help="Also trigger ECS service rollback when AWS env vars are set.")
    return parser.parse_args()


def write_log(path: str, line: str) -> None:
    proof_path = Path(path)
    proof_path.parent.mkdir(parents=True, exist_ok=True)
    with proof_path.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def rollback_router(router_url: str) -> dict[str, object]:
    response = requests.post(
        f"{router_url.rstrip('/')}/admin/traffic",
        json={"canary_weight": 0, "active_version": "stable"},
        timeout=5,
    )
    response.raise_for_status()
    requests.post(
        f"{router_url.rstrip('/')}/admin/mark",
        json={"event": "rollback", "version": "canary"},
        timeout=5,
    ).raise_for_status()
    return response.json()


def rollback_ecs() -> None:
    cluster = os.getenv("ECS_CLUSTER")
    service = os.getenv("ECS_SERVICE")
    task_definition = os.getenv("STABLE_TASK_DEFINITION")
    if not (cluster and service and task_definition):
        print("AWS rollback skipped: ECS_CLUSTER, ECS_SERVICE, or STABLE_TASK_DEFINITION is not set")
        return
    subprocess.run(
        [
            "aws",
            "ecs",
            "update-service",
            "--cluster",
            cluster,
            "--service",
            service,
            "--task-definition",
            task_definition,
            "--force-new-deployment",
        ],
        check=True,
    )


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        traffic = rollback_router(args.router_url)
        if args.aws:
            rollback_ecs()
        line = (
            f"{timestamp} ROLLBACK_TRIGGERED reason={args.reason!r} "
            f"traffic={json.dumps(traffic, sort_keys=True)}"
        )
        print(line)
        write_log(args.proof_log, line)
        return 0
    except Exception as exc:
        line = f"{timestamp} ROLLBACK_FAILED error={exc!r}"
        print(line, file=sys.stderr)
        write_log(args.proof_log, line)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

