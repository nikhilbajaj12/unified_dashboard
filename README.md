# Unified Dashboard

AI/ML observability dashboard integrating Temporal workflow metrics and Phoenix LLM tracing into Grafana.

---

## Access URLs

| Service | URL | Credentials |
|---|---|---|
| **Grafana** | http://localhost:3000 | admin / admin *(or value in `.env`)* |
| **Prometheus** | http://localhost:9090 | — |
| **unified_dash-app API** | http://localhost:8000 | — |
| **unified_dash-app Metrics** | http://localhost:8001/metrics | — |
| **Phoenix OSS UI** | http://localhost:6006 | — |
| **Phoenix OTLP (gRPC)** | http://localhost:4317 | — |
| **Temporal UI** | https://temporal-ui.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io | — |
| **Phoenix Remote** | https://zaf-phoenix.bravesky-d9f9eeb7.eastus2.azurecontainerapps.io | API key in `.env` |

---

## Start the Stack

### Prerequisites
- [Podman](https://podman.io/) + [podman-compose](https://github.com/containers/podman-compose)
- `.env` file present in project root (see [.env.example](#env-variables) below)

### Start all containers
```bash
podman-compose up -d --build
```

---


## Project Pipeline

```
External Services                    Local Stack
─────────────────                    ───────────
Temporal UI (Azure)  ──── HTTP ───►  unified_dash-app
Phoenix (Azure)      ──── HTTP ───►  unified_dash-app
                                           │
                                    exposes /metrics
                                           │
                                           ▼
                                       Prometheus
                                    (scrapes port 8001)
                                           │
                                           ▼
                                        Grafana
                                    (queries Prometheus
                                     + Infinity plugin)
                                           │
                                           ▼
                                    Dashboards (port 3000)

OTel Traces (app) ──── gRPC:4317 ──► Phoenix OSS
                                     (local container)
                                      backed by Postgres
```

### Services

| Container | Image | Role |
|---|---|---|
| `unified_dash-app` | custom (FastAPI) | Polls Temporal & Phoenix APIs every 30s, exposes Prometheus metrics on `:8001`, serves REST API on `:8000` |
| `prometheus` | prom/prometheus:v2.51.0 | Scrapes `unified_dash-app:8001`, stores time-series, retains 15 days |
| `grafana` | grafana/grafana-oss:10.4.0 | Reads from Prometheus, renders 8 pre-built dashboards |
| `phoenix-server` | arizephoenix/phoenix:latest | Local Phoenix OSS instance for OTel trace ingestion |
| `phoenix-db` | postgres:15-alpine | Postgres backend for local Phoenix |

### Metrics Collected

**From Temporal** (via `TEMPORAL_BASE_URL/api/v1/namespaces/{namespace}/workflows`):
- `temporal_workflow_active` — currently running workflows
- `temporal_workflow_completed_total` — completed workflows
- `temporal_workflow_failed_total` — failed workflows
- `temporal_workflow_timed_out_total` — timed-out workflows
- `temporal_workflow_canceled_total` — cancelled workflows

**From Phoenix** (via `POST PHOENIX_BASE_URL/v1/spans`):
- `phoenix_model_accuracy`, `precision`, `recall`, `f1_score`
- `phoenix_model_drift_score`, `calibration_error`
- `phoenix_feature_drift`, `phoenix_outlier_count`, `phoenix_bias_score`
- `phoenix_positive_feedback_count`, `phoenix_negative_feedback_count`, `phoenix_annotation_count`
- `phoenix_feature_importance`, `phoenix_counterfactual_count`, `phoenix_sensitive_feature_score`

**System** (via `psutil` inside the container):
- `system_cpu_usage_percent`, `system_memory_usage_percent`
- `system_memory_available_gb`, `system_disk_usage_percent`
- `system_network_bytes_sent_total`, `system_network_bytes_recv_total`

### Grafana Dashboards

| Dashboard | Data Source | What it shows |
|---|---|---|
| System Health | Prometheus | CPU, memory, disk, network |
| Model Performance | Prometheus | Accuracy, precision, recall, F1, drift |
| Data Quality | Prometheus | Feature drift, outliers, bias by slice |
| Explainability | Prometheus | Feature importance, sensitive feature scores |
| User Feedback | Prometheus | Annotation counts, positive/negative feedback |
| Workflow Execution | Prometheus | Temporal workflow status counts and failure rate |
| Costs & Efficiency | Prometheus | Workflow/activity latency histograms |
| Tracing | Prometheus | Span-level metrics |

---

## Project Structure

```
grafana_dashboard/
├── .env                        # Local secrets (never commit)
├── docker-compose.yml          # All container definitions
├── app/
│   ├── main.py                 # Entry point — starts all collectors
│   ├── observability/
│   │   ├── temporal.py         # Temporal metrics collector
│   │   ├── phoenix.py          # Phoenix metrics collector
│   │   ├── kpi_metrics.py      # System metrics collector
│   │   └── tracing.py          # OTel tracing setup
│   ├── api/routers/
│   │   └── observability.py    # REST API endpoints
│   ├── shared/
│   │   ├── config.py           # Settings (reads from .env)
│   │   └── logger.py           # Structured logger
│   └── config/
│       ├── prometheus.yml      # Prometheus scrape config
│       └── grafana/
│           └── provisioning/
│               ├── dashboards/ # 8 pre-built JSON dashboards
│               ├── datasources/
│               └── alerting/
```
