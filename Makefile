.PHONY: test gate-pass gate-fail up down traffic canary-success canary-rollback reset

test:
	python -m unittest discover -s tests -v

gate-pass:
	python -m gate.cli --sample-file examples/safe_metrics.json

gate-fail:
	python -m gate.cli --sample-file examples/unhealthy_metrics.json

up:
	docker compose up --build -d

down:
	docker compose down

traffic:
	python scripts/generate_traffic.py --requests 250 --concurrency 8

canary-success:
	rm -f runtime/rollback.lock
	python scripts/canary_rollout.py --sample-file examples/canary_success.json --dry-run

canary-rollback:
	rm -f runtime/rollback.lock
	python scripts/canary_rollout.py --sample-file examples/canary_rollback.json --dry-run

reset:
	rm -f runtime/rollback.lock
	python scripts/inject_failure.py --service-url http://localhost:8001 --reset || true
	python scripts/inject_failure.py --service-url http://localhost:8002 --reset || true

