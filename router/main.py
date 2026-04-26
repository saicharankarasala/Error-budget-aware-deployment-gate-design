from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field


TRAFFIC_CONFIG = Path(os.getenv("TRAFFIC_CONFIG", "/runtime/traffic.json"))
DEFAULT_STABLE_URL = os.getenv("STABLE_URL", "http://app-stable:8000")
DEFAULT_CANARY_URL = os.getenv("CANARY_URL", "http://app-canary:8000")

ROUTED_REQUESTS = Counter(
    "router_requests",
    "Requests routed by the local canary router.",
    ["target", "status_class"],
)
ROUTER_LATENCY = Histogram(
    "router_request_latency_seconds",
    "Latency added by the local canary router.",
    ["target"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
TRAFFIC_WEIGHT = Gauge("traffic_weight_percent", "Current traffic split percentage.", ["target"])
DEPLOYMENT_EVENTS = Counter(
    "deployment_events",
    "Deployment and rollback events emitted by rollout automation.",
    ["event", "version"],
)


class TrafficConfig(BaseModel):
    stable_url: str = DEFAULT_STABLE_URL
    canary_url: str = DEFAULT_CANARY_URL
    canary_weight: int = Field(default=0, ge=0, le=100)
    active_version: str = "stable"


class TrafficPatch(BaseModel):
    canary_weight: int | None = Field(default=None, ge=0, le=100)
    active_version: str | None = None


class DeploymentEvent(BaseModel):
    event: str
    version: str = "canary"


app = FastAPI(
    title="Local Weighted Canary Router",
    description="Small reverse proxy used to isolate canary traffic in the local demo.",
    version="1.0.0",
)


def _ensure_config() -> None:
    TRAFFIC_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if not TRAFFIC_CONFIG.exists():
        _write_config(TrafficConfig())


def _read_config() -> TrafficConfig:
    _ensure_config()
    with TRAFFIC_CONFIG.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    config = TrafficConfig(**payload)
    _publish_weights(config)
    return config


def _write_config(config: TrafficConfig) -> None:
    TRAFFIC_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    with TRAFFIC_CONFIG.open("w", encoding="utf-8") as handle:
        json.dump(config.model_dump(), handle, indent=2)
        handle.write("\n")
    _publish_weights(config)


def _publish_weights(config: TrafficConfig) -> None:
    TRAFFIC_WEIGHT.labels("canary").set(config.canary_weight)
    TRAFFIC_WEIGHT.labels("stable").set(100 - config.canary_weight)


def _choose_target(request: Request, config: TrafficConfig) -> tuple[str, str]:
    override = request.headers.get("x-canary", "").lower()
    if override in {"always", "true", "1"}:
        return "canary", config.canary_url
    if override in {"never", "false", "0"}:
        return "stable", config.stable_url
    if random.randint(1, 100) <= config.canary_weight:
        return "canary", config.canary_url
    return "stable", config.stable_url


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/admin/traffic", response_model=TrafficConfig)
def get_traffic() -> TrafficConfig:
    return _read_config()


@app.post("/admin/traffic", response_model=TrafficConfig)
def set_traffic(patch: TrafficPatch) -> TrafficConfig:
    config = _read_config()
    values = config.model_dump()
    for field_name, value in patch.model_dump(exclude_unset=True).items():
        values[field_name] = value
    updated = TrafficConfig(**values)
    _write_config(updated)
    return updated


@app.post("/admin/mark")
def mark_deployment(event: DeploymentEvent) -> dict[str, str]:
    DEPLOYMENT_EVENTS.labels(event.event, event.version).inc()
    return {"status": "recorded", "event": event.event, "version": event.version}


@app.get("/metrics")
def metrics() -> Response:
    _publish_weights(_read_config())
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request) -> Response:
    config = _read_config()
    target, upstream = _choose_target(request, config)
    upstream_url = f"{upstream.rstrip('/')}/{path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length", "connection"}
    }
    body = await request.body()
    started = time.perf_counter()

    try:
        upstream_response = requests.request(
            request.method,
            upstream_url,
            headers=headers,
            data=body,
            timeout=10,
        )
        status_class = f"{upstream_response.status_code // 100}xx"
        ROUTED_REQUESTS.labels(target, status_class).inc()
        ROUTER_LATENCY.labels(target).observe(time.perf_counter() - started)
        passthrough_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() in {"content-type", "cache-control"}
        }
        passthrough_headers["x-routed-target"] = target
        return Response(
            content=upstream_response.content,
            status_code=upstream_response.status_code,
            headers=passthrough_headers,
        )
    except requests.RequestException as exc:
        ROUTED_REQUESTS.labels(target, "5xx").inc()
        ROUTER_LATENCY.labels(target).observe(time.perf_counter() - started)
        return Response(
            content=json.dumps({"ok": False, "error": str(exc), "target": target}),
            status_code=502,
            media_type="application/json",
        )

