#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import time
from dataclasses import dataclass

import requests


@dataclass
class Result:
    ok: int = 0
    failed: int = 0


def hit(url: str, canary: str | None, timeout: float) -> bool:
    headers = {}
    if canary:
        headers["x-canary"] = canary
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
        return response.status_code < 500
    except requests.RequestException:
        return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate demo traffic for Prometheus metrics.")
    parser.add_argument("--url", default="http://localhost:8080/api/work")
    parser.add_argument("--requests", type=int, default=250)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--delay-ms", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--canary", choices=("always", "never"), default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = Result()
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = []
        for _ in range(args.requests):
            futures.append(executor.submit(hit, args.url, args.canary, args.timeout))
            if args.delay_ms:
                time.sleep(args.delay_ms / 1000)
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                result.ok += 1
            else:
                result.failed += 1

    elapsed = time.perf_counter() - started
    print(
        f"traffic complete url={args.url} ok={result.ok} failed={result.failed} "
        f"elapsed={elapsed:.1f}s"
    )
    return 0 if result.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

