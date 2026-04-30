# Unified Dashboard


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
