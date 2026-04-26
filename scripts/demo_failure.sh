#!/usr/bin/env bash
set -euo pipefail

echo "1. Generate healthy baseline traffic"
python scripts/generate_traffic.py --requests 150 --concurrency 8

echo "2. Healthy gate should pass"
python -m gate.cli --prometheus-url http://localhost:9090 --short-window 5m --long-window 15m

echo "3. Inject 8% errors into the canary"
python scripts/inject_failure.py --service-url http://localhost:8002 --error-rate 0.08
python scripts/generate_traffic.py --requests 150 --concurrency 8 --canary always || true

echo "4. Gate should fail and canary should roll back"
python scripts/canary_rollout.py --prometheus-url http://localhost:9090 --weights 10 --window 5m || true

