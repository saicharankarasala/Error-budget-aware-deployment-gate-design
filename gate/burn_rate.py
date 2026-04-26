from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gate.slo import GateThresholds, ServiceSLO


@dataclass(frozen=True)
class WindowMetrics:
    window: str
    request_rate: float
    error_rate: float
    slow_rate: float
    p95_latency_seconds: float

    @classmethod
    def from_counts(
        cls,
        window: str,
        requests: float,
        errors: float,
        slow_requests: float,
        p95_latency_seconds: float,
    ) -> "WindowMetrics":
        request_rate = max(requests, 0.0)
        if request_rate <= 0:
            return cls(window, 0.0, 0.0, 0.0, p95_latency_seconds)
        return cls(
            window=window,
            request_rate=request_rate,
            error_rate=max(errors, 0.0) / request_rate,
            slow_rate=max(slow_requests, 0.0) / request_rate,
            p95_latency_seconds=p95_latency_seconds,
        )


@dataclass(frozen=True)
class BurnRateResult:
    window: str
    availability_burn_rate: float
    latency_burn_rate: float
    error_rate: float
    slow_rate: float
    p95_latency_seconds: float
    request_rate: float


@dataclass(frozen=True)
class GateDecision:
    status: str
    reasons: tuple[str, ...]
    short: BurnRateResult
    long: BurnRateResult
    stale_seconds: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": list(self.reasons),
            "stale_seconds": self.stale_seconds,
            "short": self.short.__dict__,
            "long": self.long.__dict__,
            "metadata": self.metadata,
        }


def calculate_burn_rate(metrics: WindowMetrics, slo: ServiceSLO) -> BurnRateResult:
    allowed_error_rate = max(slo.allowed_error_rate, 1e-12)
    allowed_slow_rate = max(slo.allowed_slow_rate, 1e-12)
    return BurnRateResult(
        window=metrics.window,
        availability_burn_rate=metrics.error_rate / allowed_error_rate,
        latency_burn_rate=metrics.slow_rate / allowed_slow_rate,
        error_rate=metrics.error_rate,
        slow_rate=metrics.slow_rate,
        p95_latency_seconds=metrics.p95_latency_seconds,
        request_rate=metrics.request_rate,
    )


def evaluate_gate(
    short_metrics: WindowMetrics,
    long_metrics: WindowMetrics,
    slo: ServiceSLO | None = None,
    thresholds: GateThresholds | None = None,
    stale_seconds: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> GateDecision:
    slo = slo or ServiceSLO()
    thresholds = thresholds or GateThresholds()
    short = calculate_burn_rate(short_metrics, slo)
    long = calculate_burn_rate(long_metrics, slo)
    reasons: list[str] = []

    if stale_seconds is None:
        reasons.append("metric freshness could not be verified")
    elif stale_seconds > thresholds.max_metric_staleness_seconds:
        reasons.append(
            f"metrics are stale: {stale_seconds:.0f}s old "
            f"(limit {thresholds.max_metric_staleness_seconds}s)"
        )

    if short.request_rate <= 0 and long.request_rate <= 0:
        reasons.append("no request traffic found for SLO evaluation")

    if short.availability_burn_rate > thresholds.short_burn_rate:
        reasons.append(
            f"{short.window} availability burn {short.availability_burn_rate:.2f}x exceeds "
            f"{thresholds.short_burn_rate:.2f}x"
        )
    same_window = short.window == long.window
    if not same_window and long.availability_burn_rate > thresholds.long_burn_rate:
        reasons.append(
            f"{long.window} availability burn {long.availability_burn_rate:.2f}x exceeds "
            f"{thresholds.long_burn_rate:.2f}x"
        )
    if short.latency_burn_rate > thresholds.short_burn_rate:
        reasons.append(
            f"{short.window} latency burn {short.latency_burn_rate:.2f}x exceeds "
            f"{thresholds.short_burn_rate:.2f}x"
        )
    if not same_window and long.latency_burn_rate > thresholds.long_burn_rate:
        reasons.append(
            f"{long.window} latency burn {long.latency_burn_rate:.2f}x exceeds "
            f"{thresholds.long_burn_rate:.2f}x"
        )
    if short.p95_latency_seconds > slo.latency_threshold_seconds:
        reasons.append(
            f"{short.window} p95 latency {short.p95_latency_seconds:.3f}s exceeds "
            f"{slo.latency_threshold_seconds:.3f}s"
        )
    if not same_window and long.p95_latency_seconds > slo.latency_threshold_seconds:
        reasons.append(
            f"{long.window} p95 latency {long.p95_latency_seconds:.3f}s exceeds "
            f"{slo.latency_threshold_seconds:.3f}s"
        )

    return GateDecision(
        status="FAIL" if reasons else "PASS",
        reasons=tuple(reasons),
        short=short,
        long=long,
        stale_seconds=stale_seconds,
        metadata=metadata or {},
    )


def decision_from_sample(payload: dict[str, Any]) -> GateDecision:
    slo_payload = payload.get("slo", {})
    threshold_payload = payload.get("thresholds", {})
    slo = ServiceSLO(
        availability_target=float(slo_payload.get("availability_target", 0.999)),
        latency_success_target=float(slo_payload.get("latency_success_target", 0.95)),
        latency_threshold_seconds=float(slo_payload.get("latency_threshold_seconds", 0.300)),
    )
    thresholds = GateThresholds(
        short_burn_rate=float(threshold_payload.get("short_burn_rate", 4.0)),
        long_burn_rate=float(threshold_payload.get("long_burn_rate", 2.0)),
        max_metric_staleness_seconds=int(threshold_payload.get("max_metric_staleness_seconds", 300)),
    )
    windows = payload["windows"]
    short = WindowMetrics.from_counts(
        window=windows["short"].get("window", "1h"),
        requests=float(windows["short"]["requests"]),
        errors=float(windows["short"]["errors"]),
        slow_requests=float(windows["short"].get("slow_requests", 0)),
        p95_latency_seconds=float(windows["short"].get("p95_latency_seconds", 0)),
    )
    long = WindowMetrics.from_counts(
        window=windows["long"].get("window", "6h"),
        requests=float(windows["long"]["requests"]),
        errors=float(windows["long"]["errors"]),
        slow_requests=float(windows["long"].get("slow_requests", 0)),
        p95_latency_seconds=float(windows["long"].get("p95_latency_seconds", 0)),
    )
    stale_seconds = payload.get("stale_seconds")
    return evaluate_gate(
        short,
        long,
        slo=slo,
        thresholds=thresholds,
        stale_seconds=None if stale_seconds is None else float(stale_seconds),
        metadata=payload.get("metadata", {}),
    )
