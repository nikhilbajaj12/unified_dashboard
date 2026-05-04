from fastapi import APIRouter
from pydantic import BaseModel

from app.observability.kpi_metrics import (
    _cpu_usage,
    _disk_usage,
    _memory_available_gb,
    _memory_usage,
)
from app.observability.phoenix import _drift_score
from app.shared.logger import logger

router = APIRouter(prefix="/observability", tags=["observability"])


class SystemHealthResponse(BaseModel):
    cpu_percent: float | None
    memory_percent: float | None
    memory_available_gb: float | None
    disk_percent: float | None


class MetricValue(BaseModel):
    name: str
    value: float
    labels: dict[str, str]


class MetricsResponse(BaseModel):
    system: list[MetricValue]


class AlertItem(BaseModel):
    name: str
    severity: str
    value: float
    threshold: float
    firing: bool


class AlertsResponse(BaseModel):
    alerts: list[AlertItem]


def _first_value(gauge) -> float | None:
    for family in gauge.collect():
        if family.samples:
            return family.samples[0].value
    return None


def _max_value(gauge) -> float:
    val = 0.0
    for family in gauge.collect():
        for sample in family.samples:
            val = max(val, sample.value)
    return val


@router.get("/health", response_model=SystemHealthResponse)
async def get_health() -> SystemHealthResponse:
    return SystemHealthResponse(
        cpu_percent=_first_value(_cpu_usage),
        memory_percent=_first_value(_memory_usage),
        memory_available_gb=_first_value(_memory_available_gb),
        disk_percent=_first_value(_disk_usage),
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    system_gauges = [_cpu_usage, _memory_usage, _memory_available_gb, _disk_usage]

    system_metrics: list[MetricValue] = []
    for gauge in system_gauges:
        for family in gauge.collect():
            for sample in family.samples:
                system_metrics.append(
                    MetricValue(
                        name=sample.name,
                        value=sample.value,
                        labels=dict(sample.labels),
                    )
                )

    return MetricsResponse(system=system_metrics)


@router.get("/alerts", response_model=AlertsResponse)
async def get_alerts() -> AlertsResponse:
    alerts: list[AlertItem] = [
        AlertItem(
            name="Model Drift",
            severity="warning",
            value=_max_value(_drift_score),
            threshold=0.05,
            firing=_max_value(_drift_score) > 0.05,
        ),
        AlertItem(
            name="CPU Usage",
            severity="critical",
            value=_max_value(_cpu_usage),
            threshold=85.0,
            firing=_max_value(_cpu_usage) > 85.0,
        ),
        AlertItem(
            name="Memory Usage",
            severity="critical",
            value=_max_value(_memory_usage),
            threshold=85.0,
            firing=_max_value(_memory_usage) > 85.0,
        ),
    ]

    return AlertsResponse(alerts=alerts)
