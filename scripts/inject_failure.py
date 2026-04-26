#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inject 5xx errors or latency into a demo service.")
    parser.add_argument("--service-url", default="http://localhost:8000")
    parser.add_argument("--error-rate", type=float, default=None)
    parser.add_argument("--latency-ms", type=int, default=None)
    parser.add_argument("--force-status", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.reset:
        response = requests.post(f"{args.service_url.rstrip('/')}/admin/injection/reset", timeout=5)
    else:
        payload = {
            key: value
            for key, value in {
                "error_rate": args.error_rate,
                "latency_ms": args.latency_ms,
                "force_status": args.force_status,
            }.items()
            if value is not None
        }
        response = requests.post(
            f"{args.service_url.rstrip('/')}/admin/injection",
            json=payload,
            timeout=5,
        )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

