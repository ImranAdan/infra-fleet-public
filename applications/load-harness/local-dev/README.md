# Local Development

This directory contains everything needed for local development of the Load Harness application with full observability stack.

## Quick Start

```bash
# From load-harness/ directory:

# 1. Start the full stack (app + Prometheus + Grafana)
./local-dev/dev.sh up-full

# 2. Setup Grafana (imports dashboard automatically)
./local-dev/dev.sh setup

# 3. Open Grafana and view metrics
open http://localhost:3000
# Login: admin / admin
```

## Directory Contents

```
local-dev/
├── docker-compose.yml    # Docker Compose configuration
├── prometheus.yml        # Prometheus scrape configuration
├── setup-grafana.sh      # Grafana setup automation
├── dev.sh                # Developer convenience script
└── README.md             # This file
```

## Usage

### Start Services

```bash
# App only (no observability)
./local-dev/dev.sh up

# Full stack (app + Prometheus + Grafana)
./local-dev/dev.sh up-full

# View logs
./local-dev/dev.sh logs           # Flask app logs
./local-dev/dev.sh logs prometheus # Prometheus logs
./local-dev/dev.sh logs grafana    # Grafana logs
```

### Stop Services

```bash
./local-dev/dev.sh down
```

### Run Tests

```bash
./local-dev/dev.sh test
```

### Setup Grafana

After starting with `up-full`, run:

```bash
./local-dev/dev.sh setup
```

This automatically:
- Adds Prometheus as a datasource
- Imports the Flask dashboard from `../monitoring/grafana-dashboard.json`

## Services

| Service | Port | URL |
|---------|------|-----|
| Flask App | 8080 | http://localhost:8080 |
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3000 | http://localhost:3000 |

### Endpoints

**Flask App:**
- `/` - Application Info
- `/health` - Health check
- `/metrics` - Prometheus metrics
- `/ui` - Web Dashboard
- `/apidocs` - Interactive Swagger UI
- `/load/cpu` (POST) - Start background CPU load job
- `/load/cpu/work` (POST) - Synchronous CPU work (for distributed testing)
- `/load/cpu/status` (GET) - Get CPU job statuses
- `/load/cpu/stop` (POST) - Stop CPU jobs
- `/load/memory` (POST) - Start background memory load job
- `/load/memory/status` (GET) - Get memory job statuses
- `/load/memory/stop` (POST) - Stop memory jobs

**Prometheus:**
- Query metrics and explore data
- Validate scraping is working

**Grafana:**
- View pre-built dashboard
- Create custom visualizations
- Login: `admin` / `admin`

## Development Workflow

### 1. Make Code Changes

Edit files in `../src/`:
```bash
vim ../src/load_harness/app.py
```

Changes are automatically reloaded (hot reload enabled).

### 2. Run Tests

```bash
./local-dev/dev.sh test
```

### 3. View Metrics

1. Generate traffic: `curl http://localhost:8080/`
2. View in Grafana: http://localhost:3000
3. Query in Prometheus: http://localhost:9090

### 4. Update Dashboard

1. Edit dashboard in Grafana UI
2. Export JSON via Share → Export → Save to file
3. Save to `../monitoring/grafana-dashboard.json`
4. Commit changes

## Docker Compose Profiles

Services are organized by profile:

```yaml
# No profile - always runs
- load-harness

# --profile observability
- prometheus
- grafana

# --profile test
- test
```

### Manual Docker Compose

If you prefer not to use `dev.sh`:

```bash
# App only
docker-compose -f local-dev/docker-compose.yml up

# With observability
docker-compose -f local-dev/docker-compose.yml --profile observability up

# Run tests
docker-compose -f local-dev/docker-compose.yml --profile test run test
```

## Troubleshooting

### Grafana dashboard not showing data

1. Check Prometheus is scraping:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```
   Should show `load-harness:8080` as UP

2. Generate traffic:
   ```bash
   for i in {1..100}; do curl http://localhost:8080/; done
   ```

3. Refresh Grafana dashboard

### Permission denied on dev.sh

```bash
chmod +x local-dev/dev.sh
```

### Port already in use

Stop conflicting services:
```bash
# Find what's using port 8080
lsof -i :8080

# Kill it or stop your services first
./local-dev/dev.sh down
```

## File Structure

```
load-harness/
├── src/load_harness/       # Application code
│   ├── app.py              # Flask app factory
│   ├── constants.py        # Centralized configuration
│   ├── load_harness_service.py
│   ├── services/           # Service layer (JobManager, Prometheus, Metrics)
│   ├── workers/            # Background workers (CPU, Memory)
│   ├── middleware/         # Auth, Chaos, Security headers
│   ├── dashboard/          # Dashboard routes
│   ├── static/js/          # Frontend JavaScript
│   └── templates/          # Jinja2 templates
├── tests/                  # Test suite (104 tests)
│   ├── conftest.py         # Shared fixtures
│   ├── test_app.py
│   ├── test_security_headers.py
│   └── test_services.py
├── monitoring/             # Grafana dashboards
├── local-dev/              # Local development (THIS DIR)
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   ├── setup-grafana.sh
│   ├── dev.sh
│   └── README.md
├── Dockerfile              # Production image
└── requirements.txt        # Python dependencies
```

## Next Steps

- Add more endpoints to the Flask app
- Create custom Grafana dashboards
- Add alerting rules in Prometheus
- Explore PromQL queries

## Related Documentation

- Main README: `../README.md`
- Grafana dashboards: `../monitoring/`
- K8s deployment: `../../k8s/applications/load-harness/`
