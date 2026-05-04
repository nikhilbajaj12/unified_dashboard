"""
Temporal metrics collector.

Polls the unauthenticated Temporal UI HTTP API (TEMPORAL_BASE_URL) for the
configured namespace and exposes workflow execution counts as Prometheus gauges.

Endpoint: GET /api/v1/namespaces/{namespace}/workflows?query=ExecutionStatus='...'
"""
import asyncio
import os
from dataclasses import dataclass

import httpx
from prometheus_client import Gauge

from app.shared.logger import logger

_COLLECTION_INTERVAL = 30
_PAGE_SIZE = 1000

# Prometheus metric names match what the Grafana dashboards query
_workflow_active = Gauge("temporal_workflow_active", "Running workflows", ["namespace"])
_workflow_completed = Gauge("temporal_workflow_completed_total", "Completed workflows", ["namespace"])
_workflow_failed = Gauge("temporal_workflow_failed_total", "Failed workflows", ["namespace"])
_workflow_timed_out = Gauge("temporal_workflow_timed_out_total", "Timed-out workflows", ["namespace"])
_workflow_canceled = Gauge("temporal_workflow_canceled_total", "Cancelled workflows", ["namespace"])
_activity_task_error = Gauge(
    "temporal_activity_task_error_total",
    "Activity task errors",
    ["namespace", "activity_type"],
)


@dataclass
class TemporalConfig:
    base_url: str
    namespaces: list[str]

    @classmethod
    def from_env(cls) -> "TemporalConfig":
        namespaces_str = os.environ.get("TEMPORAL_NAMESPACES", "default")
        namespaces = [ns.strip() for ns in namespaces_str.split(",") if ns.strip()]
        return cls(
            base_url=os.environ.get("TEMPORAL_BASE_URL", "").rstrip("/"),
            namespaces=namespaces,
        )


class TemporalMetricsCollector:
    def __init__(self, config: TemporalConfig) -> None:
        self._base_url = config.base_url
        self._namespaces = config.namespaces

    async def _get(self, client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict | None:
        try:
            response = await client.get(
                f"{self._base_url}{path}",
                params=params,
                timeout=15.0,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Temporal API call failed: %s — %s", path, exc)
            return None

    async def _count_status(self, client: httpx.AsyncClient, namespace: str, status: str) -> int:
        data = await self._get(
            client,
            f"/api/v1/namespaces/{namespace}/workflows",
            params={"pageSize": _PAGE_SIZE, "query": f"ExecutionStatus='{status}'"},
        )
        if data is None:
            return 0
        return len(data.get("executions", []))

    async def collect(self) -> None:
        if not self._base_url:
            logger.debug("Temporal: TEMPORAL_BASE_URL not configured, skipping")
            return

        async with httpx.AsyncClient() as client:
            for ns in self._namespaces:
                running, completed, failed, timed_out, canceled = await asyncio.gather(
                    self._count_status(client, ns, "Running"),
                    self._count_status(client, ns, "Completed"),
                    self._count_status(client, ns, "Failed"),
                    self._count_status(client, ns, "TimedOut"),
                    self._count_status(client, ns, "Canceled"),
                )

                _workflow_active.labels(namespace=ns).set(running)
                _workflow_completed.labels(namespace=ns).set(completed)
                _workflow_failed.labels(namespace=ns).set(failed)
                _workflow_timed_out.labels(namespace=ns).set(timed_out)
                _workflow_canceled.labels(namespace=ns).set(canceled)

                logger.debug(
                    "Temporal [%s] running=%d completed=%d failed=%d timedout=%d canceled=%d",
                    ns, running, completed, failed, timed_out, canceled,
                )


async def _collection_loop(collector: TemporalMetricsCollector) -> None:
    while True:
        try:
            await collector.collect()
        except Exception as exc:
            logger.error("Temporal metrics collection error: %s", exc)
        await asyncio.sleep(_COLLECTION_INTERVAL)
