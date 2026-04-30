import asyncio
import os
import statistics
from dataclasses import dataclass, field

import httpx
from prometheus_client import Gauge

from app.shared.logger import logger

_COLLECTION_INTERVAL = 30
_SPANS_LIMIT = 200  # recent spans per project to evaluate

# Model performance
_accuracy = Gauge("phoenix_model_accuracy", "Model accuracy", ["model_name"])
_precision = Gauge("phoenix_model_precision", "Model precision", ["model_name"])
_recall = Gauge("phoenix_model_recall", "Model recall", ["model_name"])
_f1_score = Gauge("phoenix_model_f1_score", "Model F1 score", ["model_name"])
_drift_score = Gauge("phoenix_model_drift_score", "Model drift score", ["model_name"])
_calibration_error = Gauge("phoenix_model_calibration_error", "Model calibration error", ["model_name"])

# Data quality
_feature_drift = Gauge("phoenix_feature_drift", "Feature drift score", ["model_name", "feature"])
_outlier_count = Gauge("phoenix_outlier_count", "Outlier count", ["model_name"])
_bias_score = Gauge("phoenix_bias_score", "Bias score", ["model_name", "slice"])

# User feedback
_positive_feedback = Gauge("phoenix_positive_feedback_count", "Positive feedback count", ["model_name"])
_negative_feedback = Gauge("phoenix_negative_feedback_count", "Negative feedback count", ["model_name"])
_annotation_count = Gauge("phoenix_annotation_count", "Annotation count", ["model_name"])
_retraining_trigger_count = Gauge("phoenix_retraining_trigger_count", "Retraining trigger count", ["model_name"])

# Explainability
_feature_importance = Gauge("phoenix_feature_importance", "Feature importance score", ["model_name", "feature"])
_counterfactual_count = Gauge("phoenix_counterfactual_count", "Counterfactual count", ["model_name"])
_sensitive_feature_score = Gauge(
    "phoenix_sensitive_feature_score", "Sensitive feature score", ["model_name", "feature"]
)


@dataclass
class PhoenixConfig:
    base_url: str
    api_key: str = field(default="")

    @classmethod
    def from_env(cls) -> "PhoenixConfig":
        return cls(
            base_url=os.environ.get("PHOENIX_BASE_URL", "http://localhost:6006"),
            api_key=os.environ.get("PHOENIX_API_KEY", ""),
        )


class PhoenixMetricsCollector:
    def __init__(self, config: PhoenixConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._headers: dict[str, str] = {}
        if config.api_key:
            self._headers["Authorization"] = f"Bearer {config.api_key}"

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict | None = None,
        extra_headers: dict | None = None,
    ) -> dict | list | None:
        try:
            headers = {**self._headers, **(extra_headers or {})}
            response = await client.get(
                f"{self._base_url}{path}",
                params=params,
                headers=headers,
                timeout=10.0,
            )
            if not response.is_success:
                logger.warning("Phoenix %s on %s — detail: %s", response.status_code, path, response.text[:300])
                return None
            return response.json()
        except Exception as exc:
            logger.warning("Phoenix API call failed: %s — %s", path, exc)
            return None

    async def _post(
        self,
        client: httpx.AsyncClient,
        path: str,
        body: dict,
    ) -> dict | list | None:
        try:
            response = await client.post(
                f"{self._base_url}{path}",
                json=body,
                headers=self._headers,
                timeout=10.0,
            )
            if not response.is_success:
                logger.warning("Phoenix %s on POST %s — detail: %s", response.status_code, path, response.text[:300])
                return None
            return response.json()
        except Exception as exc:
            logger.warning("Phoenix POST failed: %s — %s", path, exc)
            return None

    async def collect(self) -> None:
        async with httpx.AsyncClient() as client:
            projects = await self._get(client, "/v1/projects")
            if not isinstance(projects, dict):
                return

            project_list = projects.get("data", [])
            if not project_list:
                logger.debug("Phoenix: no projects found")
                return

            for project in project_list:
                project_name: str = project.get("name", "unknown")
                await self._collect_project_metrics(client, project_name)

    async def _collect_project_metrics(self, client: httpx.AsyncClient, project_name: str) -> None:
        # POST /v1/spans with JSON body — Phoenix REST API requires a request body
        data = await self._post(
            client,
            "/v1/spans",
            body={"queries": [{"project_name": project_name, "limit": _SPANS_LIMIT}]},
        )
        if not isinstance(data, dict):
            return

        spans: list[dict] = data.get("data", [])
        if not spans:
            return

        attrs_list = [s.get("attributes", {}) for s in spans]
        statuses = [s.get("status_code", s.get("attributes", {}).get("openinference.span.kind", "")) for s in spans]

        # --- Model performance ---
        total = len(spans)
        ok_count = sum(1 for s in spans if s.get("status_code", "").upper() not in ("ERROR", "UNSET"))
        error_count = total - ok_count

        accuracy = ok_count / total if total else 0.0

        # precision / recall derived from evaluation score attributes when available
        eval_scores = [
            float(a["eval.score"])
            for a in attrs_list
            if "eval.score" in a and a["eval.score"] is not None
        ]
        if eval_scores:
            mean_score = statistics.mean(eval_scores)
            precision = mean_score
            recall = mean_score
        else:
            precision = accuracy
            recall = accuracy

        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        # drift = coefficient of variation of latency_ms
        latencies = [
            float(a["latency_ms"])
            for a in attrs_list
            if "latency_ms" in a and a["latency_ms"] is not None
        ]
        if len(latencies) >= 2:
            mean_lat = statistics.mean(latencies)
            stdev_lat = statistics.stdev(latencies)
            drift = (stdev_lat / mean_lat) if mean_lat > 0 else 0.0
        else:
            drift = 0.0

        # calibration error: mean absolute deviation of eval scores from 0.5
        calibration_error = (
            statistics.mean(abs(s - 0.5) for s in eval_scores) if eval_scores else 0.0
        )

        _accuracy.labels(model_name=project_name).set(accuracy)
        _precision.labels(model_name=project_name).set(precision)
        _recall.labels(model_name=project_name).set(recall)
        _f1_score.labels(model_name=project_name).set(f1)
        _drift_score.labels(model_name=project_name).set(drift)
        _calibration_error.labels(model_name=project_name).set(calibration_error)

        # --- Data quality ---
        if latencies:
            mean_lat = statistics.mean(latencies)
            stdev_lat = statistics.stdev(latencies) if len(latencies) >= 2 else 0.0
            threshold = mean_lat + 3 * stdev_lat
            outliers = sum(1 for lat in latencies if lat > threshold)
        else:
            outliers = 0

        _outlier_count.labels(model_name=project_name).set(outliers)

        # token count drift as a feature drift proxy
        token_counts = [
            float(a["llm.token_count.total"])
            for a in attrs_list
            if "llm.token_count.total" in a and a["llm.token_count.total"] is not None
        ]
        if len(token_counts) >= 2:
            mean_tok = statistics.mean(token_counts)
            stdev_tok = statistics.stdev(token_counts)
            token_drift = (stdev_tok / mean_tok) if mean_tok > 0 else 0.0
        else:
            token_drift = 0.0
        _feature_drift.labels(model_name=project_name, feature="token_count").set(token_drift)
        _feature_drift.labels(model_name=project_name, feature="latency_ms").set(drift)

        # bias: error rate by span kind
        span_kinds: dict[str, list[bool]] = {}
        for s in spans:
            kind = s.get("attributes", {}).get("openinference.span.kind", "UNKNOWN")
            is_ok = s.get("status_code", "").upper() not in ("ERROR", "UNSET")
            span_kinds.setdefault(kind, []).append(is_ok)
        for kind, results in span_kinds.items():
            error_rate = 1.0 - (sum(results) / len(results))
            _bias_score.labels(model_name=project_name, slice=kind).set(error_rate)

        # --- User feedback (annotations) ---
        annotations = [
            s for s in spans
            if s.get("attributes", {}).get("annotation.label") is not None
        ]
        positive = sum(
            1 for s in annotations
            if str(s["attributes"].get("annotation.label", "")).lower() in ("correct", "positive", "thumbs_up", "1")
        )
        negative = len(annotations) - positive

        _annotation_count.labels(model_name=project_name).set(len(annotations))
        _positive_feedback.labels(model_name=project_name).set(positive)
        _negative_feedback.labels(model_name=project_name).set(negative)
        _retraining_trigger_count.labels(model_name=project_name).set(
            sum(1 for s in spans if s.get("attributes", {}).get("retraining.trigger") == "true")
        )

        # --- Explainability ---
        # feature importance from token contribution attributes
        token_prompt = sum(
            float(a.get("llm.token_count.prompt", 0))
            for a in attrs_list
            if "llm.token_count.prompt" in a
        )
        token_completion = sum(
            float(a.get("llm.token_count.completion", 0))
            for a in attrs_list
            if "llm.token_count.completion" in a
        )
        total_tokens = token_prompt + token_completion
        _feature_importance.labels(model_name=project_name, feature="prompt_tokens").set(
            token_prompt / total_tokens if total_tokens > 0 else 0.0
        )
        _feature_importance.labels(model_name=project_name, feature="completion_tokens").set(
            token_completion / total_tokens if total_tokens > 0 else 0.0
        )
        _counterfactual_count.labels(model_name=project_name).set(error_count)
        _sensitive_feature_score.labels(model_name=project_name, feature="latency").set(drift)


async def _collection_loop(collector: PhoenixMetricsCollector) -> None:
    while True:
        try:
            await collector.collect()
        except Exception as exc:
            logger.error("Phoenix metrics collection error: %s", exc)
        await asyncio.sleep(_COLLECTION_INTERVAL)


