from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass

from gate.burn_rate import WindowMetrics


@dataclass(frozen=True)
class PrometheusConfig:
    base_url: str
    job_regex: str = "app-stable|app-canary"
    latency_threshold_seconds: float = 0.300
    timeout_seconds: int = 10


class PrometheusClient:
    def __init__(self, config: PrometheusConfig):
        self.config = config
        self.base_url = config.base_url.rstrip("/")

    def query_scalar(self, query: str) -> float:
        params = urllib.parse.urlencode({"query": query})
        url = f"{self.base_url}/api/v1/query?{params}"
        with urllib.request.urlopen(url, timeout=self.config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        result = payload.get("data", {}).get("result", [])
        if not result:
            return 0.0
        value = float(result[0]["value"][1])
        return value if math.isfinite(value) else 0.0

    def window_metrics(self, window: str) -> WindowMetrics:
        selector = f'job=~"{self.config.job_regex}"'
        request_rate = self.query_scalar(f"sum(rate(request_count_total{{{selector}}}[{window}]))")
        error_rate = self.query_scalar(f"sum(rate(error_count_total{{{selector}}}[{window}]))")
        slow_ratio = self.query_scalar(
            "1 - ("
            f"sum(rate(request_latency_seconds_bucket{{{selector},le=\"{self.config.latency_threshold_seconds:g}\"}}[{window}])) "
            "/ "
            f"sum(rate(request_latency_seconds_bucket{{{selector},le=\"+Inf\"}}[{window}]))"
            ")"
        )
        p95_latency = self.query_scalar(
            "histogram_quantile(0.95, "
            f"sum by (le) (rate(request_latency_seconds_bucket{{{selector}}}[{window}])))"
        )
        return WindowMetrics(
            window=window,
            request_rate=max(request_rate, 0.0),
            error_rate=max(error_rate, 0.0) / request_rate if request_rate > 0 else 0.0,
            slow_rate=max(slow_ratio, 0.0),
            p95_latency_seconds=max(p95_latency, 0.0),
        )

    def metric_staleness_seconds(self) -> float:
        selector = f'job=~"{self.config.job_regex}"'
        return self.query_scalar(f"time() - max(timestamp(request_count_total{{{selector}}}))")
