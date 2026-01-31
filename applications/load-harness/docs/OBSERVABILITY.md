# Local Observability Stack

Simple Prometheus + Grafana setup for local development and testing.

## Quick Start

```bash
# Start Flask app + Prometheus + Grafana
docker-compose --profile observability up

# Or start them separately
docker-compose up load-harness         # Just the app
docker-compose --profile observability up prometheus grafana  # Add observability
```

## Access

- **Flask App**: http://localhost:8080
- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (login: `admin` / `admin`)

## Flask Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Application info |
| `/health` | GET | Health check |
| `/metrics` | GET | Prometheus metrics |
| `/load/cpu` | POST | Blocking CPU load |
| `/load/memory` | POST | Memory allocation load |
| `/load/cpu/sustained` | POST | Non-blocking background CPU load |
| `/load/cpu/sustained/status` | GET | Check sustained load job status |
| `/load/cpu/sustained/stop` | POST | Stop sustained load workers |
| `/apidocs` | GET | Interactive Swagger UI |
| `/apispec.json` | GET | OpenAPI specification |

## Grafana Setup (One-Time)

1. Open http://localhost:3000
2. Login with `admin` / `admin`
3. Go to **Configuration** → **Data Sources** → **Add data source**
4. Select **Prometheus**
5. Set URL to: `http://prometheus:9090`
6. Click **Save & Test**

## Creating Dashboards

### Option 1: Import Pre-Built Dashboard (Recommended)
1. Go to **Dashboards** → **Import**
2. Click **Upload JSON file**
3. Select `grafana-dashboard.json` from this directory
4. Select **Prometheus** as the datasource
5. Click **Import**

This dashboard includes:
- Request Rate (req/s)
- Response Time
- Total Requests
- HTTP Status Codes
- CPU Load Endpoint Usage
- Python Memory Usage

### Option 2: Import Community Dashboard
1. Go to **Dashboards** → **Import**
2. Enter dashboard ID: `10924` (Flask Prometheus Exporter)
3. Select Prometheus datasource
4. Click **Import**

### Option 3: Build Your Own
1. Go to **Dashboards** → **New** → **New Dashboard**
2. Click **Add visualization**
3. Select **Prometheus** datasource
4. Add panels with PromQL queries:
   - Request rate: `rate(flask_http_request_total[1m])`
   - Response time: `rate(flask_http_request_duration_seconds_sum[1m]) / rate(flask_http_request_duration_seconds_count[1m])`
   - Error rate: `rate(flask_http_request_total{status=~"5.."}[5m])`
   - Total requests: `sum(flask_http_request_total)`

## Testing

```bash
# Generate some traffic
curl http://localhost:8080/

# Generate CPU load (blocking)
curl -X POST http://localhost:8080/load/cpu \
  -H "Content-Type: application/json" \
  -d '{"duration_ms": 1000, "complexity": 5}'

# Generate memory load
curl -X POST http://localhost:8080/load/memory \
  -H "Content-Type: application/json" \
  -d '{"size_mb": 100, "duration_ms": 2000}'

# Start sustained CPU load (non-blocking)
curl -X POST http://localhost:8080/load/cpu/sustained \
  -H "Content-Type: application/json" \
  -d '{"workers": 2, "duration_seconds": 60, "complexity": 5}'

# Check sustained load status
curl http://localhost:8080/load/cpu/sustained/status

# Stop sustained load workers
curl -X POST http://localhost:8080/load/cpu/sustained/stop \
  -H "Content-Type: application/json" \
  -d '{}'

# Check metrics are being collected
curl http://localhost:8080/metrics

# View interactive API docs
# Open http://localhost:8080/apidocs

# View in Prometheus
# Open http://localhost:9090/targets - should see load-harness as UP

# View in Grafana
# Create dashboards using the metrics above
```

## Prometheus Configuration

See `prometheus.yml` - minimal config that scrapes Flask app's `/metrics` endpoint every 15 seconds.

## Data Persistence

Metrics and Grafana config are persisted in Docker volumes:
- `prometheus-data` - Prometheus time-series database
- `grafana-data` - Grafana dashboards and settings

```bash
# Clear all data and start fresh
docker-compose down -v
```

## Production Deployment

For EKS deployment, see Phase 2b plan in `APPLICATION-ROADMAP.md`.
