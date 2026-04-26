from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceSLO:
    """SLO definition used by the deployment gate.

    Availability target is the percentage of successful requests. Latency target
    is the percentage of requests that must complete under the p95 threshold.
    """

    availability_target: float = 0.999
    latency_success_target: float = 0.95
    latency_threshold_seconds: float = 0.300

    @property
    def allowed_error_rate(self) -> float:
        return 1.0 - self.availability_target

    @property
    def allowed_slow_rate(self) -> float:
        return 1.0 - self.latency_success_target


@dataclass(frozen=True)
class GateThresholds:
    """Conservative initial thresholds for deployment blocking.

    A 99.9% availability SLO has a 0.1% error budget. A short-window threshold
    of 4 blocks deploys around 0.4% errors over one hour. The long-window
    threshold catches slower but sustained degradation.
    """

    short_burn_rate: float = 4.0
    long_burn_rate: float = 2.0
    max_metric_staleness_seconds: int = 300

