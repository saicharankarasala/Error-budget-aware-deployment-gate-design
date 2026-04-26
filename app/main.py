from __future__ import annotations

import os
import random
import time
from threading import Lock
from typing import Any

from fastapi import FastAPI, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, Field


APP_VERSION = os.getenv("APP_VERSION", "local")
APP_ROLE = os.getenv("APP_ROLE", "stable")
BASE_LATENCY_MS = int(os.getenv("BASE_LATENCY_MS", "40"))
DEFAULT_ERROR_RATE = float(os.getenv("ERROR_RATE", "0.0"))
DEFAULT_LATENCY_INJECTION_MS = int(os.getenv("LATENCY_INJECTION_MS", "0"))

REQUEST_COUNT = Counter(
    "request_count",
    "Total application requests.",
    ["app_version", "app_role", "route", "status_class"],
)
ERROR_COUNT = Counter(
    "error_count",
    "Total failed application requests.",
    ["app_version", "app_role", "route", "status_class"],
)
REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "Application request latency in seconds.",
    ["app_version", "app_role", "route"],
    buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
SERVICE_INFO = Gauge(
    "service_build_info",
    "Build metadata for the demo service.",
    ["app_version", "app_role"],
)
INJECTION_STATE = Gauge(
    "failure_injection_state",
    "Current failure injection settings.",
    ["app_version", "app_role", "setting"],
)

SERVICE_INFO.labels(APP_VERSION, APP_ROLE).set(1)


class InjectionConfig(BaseModel):
    error_rate: float = Field(DEFAULT_ERROR_RATE, ge=0.0, le=1.0)
    latency_ms: int = Field(DEFAULT_LATENCY_INJECTION_MS, ge=0, le=30000)
    force_status: int | None = Field(default=None, ge=100, le=599)


class InjectionPatch(BaseModel):
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    latency_ms: int | None = Field(default=None, ge=0, le=30000)
    force_status: int | None = Field(default=None, ge=100, le=599)


class WorkResponse(BaseModel):
    ok: bool
    version: str
    role: str
    latency_ms: int


app = FastAPI(
    title="SLO Demo Service",
    description="A tiny service that exposes Prometheus metrics and supports controlled failure injection.",
    version="1.0.0",
)

_state_lock = Lock()
_injection = InjectionConfig()


def _publish_injection_state() -> None:
    INJECTION_STATE.labels(APP_VERSION, APP_ROLE, "error_rate").set(_injection.error_rate)
    INJECTION_STATE.labels(APP_VERSION, APP_ROLE, "latency_ms").set(_injection.latency_ms)
    INJECTION_STATE.labels(APP_VERSION, APP_ROLE, "force_status").set(_injection.force_status or 0)


_publish_injection_state()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": APP_VERSION, "role": APP_ROLE}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    return {"status": "ready", "version": APP_VERSION, "role": APP_ROLE}


@app.get("/api/work", response_model=WorkResponse)
def do_work(response: Response) -> WorkResponse | dict[str, Any]:
    route = "/api/work"
    started = time.perf_counter()

    with _state_lock:
        injection = _injection.model_copy()

    jitter_ms = random.randint(0, 35)
    latency_ms = BASE_LATENCY_MS + injection.latency_ms + jitter_ms
    time.sleep(latency_ms / 1000)

    forced_failure = injection.force_status is not None and injection.force_status >= 500
    sampled_failure = random.random() < injection.error_rate
    failed = forced_failure or sampled_failure
    status_code = injection.force_status if injection.force_status is not None else 200
    if failed and status_code < 500:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR

    status_class = f"{status_code // 100}xx"
    elapsed = time.perf_counter() - started
    REQUEST_COUNT.labels(APP_VERSION, APP_ROLE, route, status_class).inc()
    REQUEST_LATENCY.labels(APP_VERSION, APP_ROLE, route).observe(elapsed)

    if status_code >= 500:
        ERROR_COUNT.labels(APP_VERSION, APP_ROLE, route, status_class).inc()
        response.status_code = status_code
        return {
            "ok": False,
            "version": APP_VERSION,
            "role": APP_ROLE,
            "latency_ms": latency_ms,
            "error": "failure injected for SLO validation",
        }

    response.status_code = status_code
    return WorkResponse(ok=True, version=APP_VERSION, role=APP_ROLE, latency_ms=latency_ms)


@app.get("/admin/injection", response_model=InjectionConfig)
def get_injection() -> InjectionConfig:
    with _state_lock:
        return _injection.model_copy()


@app.post("/admin/injection", response_model=InjectionConfig)
def set_injection(patch: InjectionPatch) -> InjectionConfig:
    global _injection
    with _state_lock:
        values = _injection.model_dump()
        for field_name, value in patch.model_dump(exclude_unset=True).items():
            values[field_name] = value
        _injection = InjectionConfig(**values)
        _publish_injection_state()
        return _injection.model_copy()


@app.post("/admin/injection/reset", response_model=InjectionConfig)
def reset_injection() -> InjectionConfig:
    global _injection
    with _state_lock:
        _injection = InjectionConfig(error_rate=0.0, latency_ms=0, force_status=None)
        _publish_injection_state()
        return _injection.model_copy()


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

