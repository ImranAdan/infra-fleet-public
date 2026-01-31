# LoadHarness Dashboard - Design Document

## Overview

A web-based dashboard for the LoadHarness API that provides a visual interface for triggering synthetic load tests and observing system behavior. Built as an extension to the existing Flask application using HTMX for dynamic interactions.

**Goal**: Learn frontend development while building something useful for demonstrating Kubernetes autoscaling behavior.

## Problem Statement

Currently, interacting with LoadHarness requires:
- Direct API calls via curl/Postman
- Swagger UI (functional but not user-friendly)
- Grafana for metrics (requires cluster access)

A dedicated dashboard consolidates these into a single, accessible interface.

## Target Users

- **Platform engineers** demonstrating autoscaling capabilities
- **Developers** learning about Kubernetes resource behavior
- **Anyone** wanting to visualize load test impacts without Grafana access

## MVP Scope

### In Scope
- Trigger load tests via web forms
- Display test results
- Monitor active sustained jobs
- Show basic live metrics (CPU, memory, pod count)

### Out of Scope (Future)
- User authentication
- Test history persistence (database)
- Multi-tenant isolation
- External target load testing
- Custom test scenarios/scripting

---

## Architecture

### Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Backend | Flask (existing) | No new services to deploy |
| Templates | Jinja2 | Built into Flask |
| Interactivity | HTMX | Minimal JS, server-rendered |
| Styling | Tailwind CSS (CDN) | Utility-first, no build step, professional appearance |
| Charts | Chart.js | Lightweight, CDN-based, supports real-time updates |

### Why HTMX?

HTMX allows dynamic page updates without writing JavaScript. It works by:
1. Adding HTML attributes to elements
2. HTMX intercepts events (clicks, form submits)
3. Makes AJAX requests to server
4. Swaps returned HTML into the page

Example:
```html
<button hx-post="/load/cpu"
        hx-target="#result"
        hx-swap="innerHTML">
  Run CPU Test
</button>
<div id="result">Results appear here</div>
```

### Application Structure (Implemented)

```
applications/load-harness/
├── src/load_harness/
│   ├── app.py                    # Flask app factory with template config
│   ├── load_harness_service.py   # API endpoints (/load/*, /system/*)
│   ├── dashboard/                # Dashboard module
│   │   ├── __init__.py           # Blueprint import
│   │   └── routes.py             # Dashboard routes (/ui/*) with Prometheus helpers
│   └── templates/                # Jinja2 templates
│       ├── base.html             # Layout with Tailwind CSS & HTMX from CDN
│       ├── dashboard.html        # Main dashboard page with tabs
│       └── partials/             # HTMX partial responses
│           ├── result.html       # Test result display (success/error/loading)
│           ├── active_jobs.html  # Running CPU jobs list
│           └── live_metrics.html # Prometheus metrics display
└── docs/
    └── dashboard-design.md       # This design document
```

**Note**: No separate `metrics.py` - Prometheus query logic is integrated into `routes.py`. No static CSS files - all styling uses Tailwind CSS utility classes directly in templates.

---

## Screen Design

### Main Dashboard (`/ui`)

Single-page layout with the following sections:

```
┌─────────────────────────────────────────────────────────────────┐
│  LoadHarness Dashboard                         [Environment: staging]
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─── Load Tests ──────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  [CPU Load]  [Memory Load]  [Cluster Load]    ← Tabs    │   │
│  │  ─────────────────────────────────────────────────────  │   │
│  │                                                          │   │
│  │  Duration (ms):  [=======●===] 500                      │   │
│  │  Complexity:     [===●======] 5                         │   │
│  │                                                          │   │
│  │  [▶ Run Test]                                           │   │
│  │                                                          │   │
│  │  Result:                                                 │   │
│  │  ┌────────────────────────────────────────────────────┐ │   │
│  │  │ ✓ Completed in 502.3ms                             │ │   │
│  │  │ Iterations: 45,230                                 │ │   │
│  │  │ Complexity: 5                                      │ │   │
│  │  └────────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Active Jobs ─────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  job_1733541234  │ 2 workers │ running │ 45s left │ [Stop] │
│  │  job_1733541100  │ 1 worker  │ completed │ ─        │      │
│  │                                                          │   │
│  │  [↻ Refresh]  Auto-refresh: [●] 5s                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─── Live Metrics ────────────────────────────────────────┐   │
│  │                                                          │   │
│  │  CPU Usage        Memory Usage       Pod Count          │   │
│  │  ████████░░ 78%   ███░░░░░░░ 32%    ●●●○○ 3/5          │   │
│  │                                                          │   │
│  │  Request Rate: 45 req/s    Avg Response: 125ms          │   │
│  │                                                          │   │
│  │  [↻ Refresh]  Auto-refresh: [●] 5s                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Details

### 1. Load Test Forms

Three tabs, each with appropriate form fields:

**CPU Load Tab**
| Field | Type | Range | Default |
|-------|------|-------|---------|
| Cores | Slider + input | 1-{system cores} | 1 |
| Duration (s) | Slider + input | 10-300 | 60 |
| Intensity | Slider + input | 1-10 | 5 |

**Memory Load Tab**
| Field | Type | Range | Default |
|-------|------|-------|---------|
| Size (MB) | Slider + input | 10-500 | 100 |
| Duration (ms) | Slider + input | 100-10000 | 2000 |

**Cluster Load Tab** (Distributed Testing)
| Field | Type | Range | Default |
|-------|------|-------|---------|
| Concurrency | Slider + input | 1-100 | 10 |
| Iterations | Slider + input | 1,000-10,000,000 | 500,000 |

### 2. Result Display

Shows the API response in a user-friendly format:

```html
<!-- Success state -->
<div class="result success">
  <span class="icon">✓</span>
  <h4>Completed</h4>
  <dl>
    <dt>Duration</dt><dd>502.3 ms</dd>
    <dt>Iterations</dt><dd>45,230</dd>
    <dt>Complexity</dt><dd>5</dd>
  </dl>
</div>

<!-- Error state -->
<div class="result error">
  <span class="icon">✗</span>
  <h4>Error</h4>
  <p>duration_ms must be between 1 and 10000</p>
</div>

<!-- Loading state -->
<div class="result loading">
  <span class="spinner"></span>
  <p>Running test...</p>
</div>
```

### 3. Active Jobs Panel

Polls `/load/cpu/sustained/status` to display running jobs:

| Column | Source |
|--------|--------|
| Job ID | `job_id` |
| Workers | `workers_active` / `workers_requested` |
| Status | `status` (running/completed/stopped) |
| Time Left | Calculate from `started_at` + `duration_seconds` |
| Actions | Stop button (if running) |

Auto-refresh via HTMX polling:
```html
<div hx-get="/ui/partials/jobs"
     hx-trigger="every 5s"
     hx-swap="innerHTML">
  <!-- Job list renders here -->
</div>
```

### 4. Live Metrics Panel

Queries Prometheus for real-time metrics. Requires the dashboard backend to query Prometheus.

**Metrics to display:**

| Metric | Prometheus Query | Display |
|--------|-----------------|---------|
| CPU Usage | `rate(process_cpu_seconds_total{...}[1m])` | Percentage bar |
| Memory Usage | `process_resident_memory_bytes{...}` | Percentage bar |
| Pod Count | `kube_deployment_status_replicas{deployment="load-harness"}` | Count with visual |
| Request Rate | `rate(flask_http_request_total{...}[1m])` | Requests/sec |
| Avg Response | `rate(flask_http_request_duration_seconds_sum[1m]) / rate(flask_http_request_duration_seconds_count[1m])` | Milliseconds |

**Note**: Prometheus URL is determined automatically based on the `ENVIRONMENT` variable:
- Local development: `http://localhost:9090` (requires port-forward via `ops/port-forward-prometheus.sh`)
- In-cluster: `http://kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090`

---

## API Routes (Dashboard) - Implemented

Routes under `/ui` prefix:

| Route | Method | Purpose | Response |
|-------|--------|---------|----------|
| `/ui` | GET | Main dashboard page | Full HTML |
| `/ui/api/system-info` | GET | Proxy system info from backend | JSON |
| `/ui/partials/cpu-result` | POST | Execute CPU load test | Partial HTML |
| `/ui/partials/memory-result` | POST | Execute Memory load test | Partial HTML |
| `/ui/partials/cluster-result` | POST | Execute distributed cluster test | Partial HTML |
| `/ui/partials/active-jobs` | GET | Get running CPU jobs list | Partial HTML |
| `/ui/partials/live-metrics` | GET | Get Prometheus metrics | Partial HTML |

### Route Implementation Example

```python
# src/load_harness/dashboard/routes.py

from flask import Blueprint, render_template, request
import requests

dashboard = Blueprint('dashboard', __name__, url_prefix='/ui')

@dashboard.route('/')
def index():
    """Render main dashboard page."""
    return render_template('dashboard.html')

@dashboard.route('/partials/jobs')
def jobs_partial():
    """Return jobs list as HTML partial."""
    # Call existing API internally
    response = requests.get('http://localhost:5000/load/cpu/sustained/status')
    jobs = response.json()
    return render_template('partials/job_list.html', jobs=jobs)

@dashboard.route('/partials/metrics')
def metrics_partial():
    """Query Prometheus and return metrics as HTML partial."""
    prometheus_url = os.getenv('PROMETHEUS_URL', 'http://localhost:9090')
    # Query Prometheus...
    return render_template('partials/metrics.html', metrics=metrics)
```

---

## Data Flow

### System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REQUEST FLOWS                                      │
└─────────────────────────────────────────────────────────────────────────────┘

1. DASHBOARD PAGE LOAD
   ┌──────┐    ┌─────┐    ┌─────────────────┐    ┌─────────────────┐
   │ User │───▶│ ALB │───▶│ load-harness    │───▶│ Prometheus      │
   │      │    │     │    │ Pod (Flask)     │    │ (metrics query) │
   └──────┘    └─────┘    │                 │◀───┘                 │
                          │ GET /ui         │
                          └─────────────────┘

2. CPU/MEMORY LOAD TEST (single pod execution)
   ┌──────┐    ┌─────┐    ┌─────────────────┐
   │ User │───▶│ ALB │───▶│ load-harness    │
   │      │    │     │    │ Pod A           │
   └──────┘    └─────┘    │                 │
                          │ POST /ui/partials/cpu-result
                          │      │
                          │      ▼ (internal call to 127.0.0.1)
                          │ POST /load/cpu ─────┐
                          │      ▲              │
                          │      └──────────────┘
                          │ (same pod handles both)
                          └─────────────────┘

3. CLUSTER LOAD TEST (distributed across pods)
   ┌──────┐    ┌─────┐    ┌─────────────────┐    ┌─────────────────┐
   │ User │───▶│ ALB │───▶│ load-harness    │    │ K8s Service     │
   │      │    │     │    │ Pod A (origin)  │───▶│ (ClusterIP)     │
   └──────┘    └─────┘    │                 │    │                 │
                          │ POST /ui/partials/cluster-result      │
                          │                 │    │    load balances│
                          │ ThreadPool      │    │    requests to: │
                          │ sends N requests│    │    ┌──────────┐ │
                          │ to Service ─────┼───▶│───▶│ Pod A    │ │
                          │                 │    │    │ Pod B    │ │
                          │                 │    │    │ Pod C    │ │
                          │                 │◀───│◀───│ ...      │ │
                          │ aggregates      │    │    └──────────┘ │
                          │ results         │    └─────────────────┘
                          └─────────────────┘

4. LIVE METRICS POLLING (every 5s via HTMX)
   ┌─────────────────┐    ┌──────────────────────────────────────┐
   │ load-harness    │───▶│ kube-prometheus-stack-prometheus     │
   │ Pod             │    │ .observability.svc.cluster.local:9090│
   │                 │◀───│                                      │
   │ GET /ui/partials/live-metrics                               │
   │      │          │    │ PromQL queries:                      │
   │      ▼          │    │ - kube_pod_status_phase (pod count)  │
   │ _query_prometheus()  │ - container_cpu_usage_seconds_total  │
   │                 │    │ - container_memory_working_set_bytes │
   │                 │    │ - flask_http_request_total           │
   └─────────────────┘    └──────────────────────────────────────┘
```

### Key Points

- **ALB (Application Load Balancer)** routes external traffic to any healthy pod via Ingress
- **CPU/Memory tests** execute on the pod that receives the request (calls itself via `127.0.0.1:5000`)
- **Cluster Load tests** fan out requests through the K8s Service, which distributes to all pods using round-robin
- **Prometheus** is only queried for metrics display, not involved in load generation
- **HTMX** handles all dynamic updates without requiring custom JavaScript

### HTMX Request/Response Cycle

```
User clicks "Run Test"
        │
        ▼
┌───────────────────┐
│ HTMX intercepts   │
│ form submit       │
└─────────┬─────────┘
          │ POST /ui/partials/cpu-result
          │ {cores: 1, duration_seconds: 60, intensity: 5}
          ▼
┌───────────────────┐
│ Dashboard route   │
│ calls internal    │──────► POST /load/cpu
│ API endpoint      │◄────── {status: started, job_id: ...}
└─────────┬─────────┘
          │
          │ Render partials/result.html
          │ with response data
          ▼
┌───────────────────┐
│ Return HTML       │
│ partial           │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│ HTMX swaps HTML   │
│ into #result div  │
└───────────────────┘
```

---

## Implementation Plan

### Phase 1: Project Foundation ✅ COMPLETE
**Goal**: Basic dashboard shell renders and serves from Flask

**Deliverables**:
- [x] Configure Jinja2 templates in Flask app factory
- [x] Create `src/load_harness/templates/` directory structure
- [x] Create `base.html` with Tailwind CSS, HTMX, Chart.js from CDN
- [x] Create dashboard Blueprint with `/ui` route
- [x] Create `dashboard.html` with placeholder sections (Load Tests, Jobs, Metrics)
- [x] Register Blueprint in `app.py`
- [x] Verify renders at `http://localhost:5000/ui`
- [x] Update docker-compose for template hot-reload

**Acceptance Criteria**: Dashboard shell loads with styled header showing "LoadHarness Dashboard" and environment name. ✅

---

### Phase 2: Load Test Forms ✅ COMPLETE
**Goal**: Users can trigger CPU, Memory, and Sustained load tests via the UI

**Deliverables**:
- [x] Create tabbed form component (CPU / Memory / Cluster Load tabs)
- [x] Implement CPU load form with cores, duration, and intensity sliders
- [x] Create `/ui/partials/cpu-result` route that calls internal API
- [x] Create `partials/result.html` template (success/error/loading states)
- [x] Wire HTMX form submission with result swap
- [x] Implement Memory load form with size and duration sliders
- [x] Implement Cluster Load form for distributed testing across pods
- [x] Add loading spinner during test execution (hx-indicator)

**Acceptance Criteria**: User can run all three test types and see formatted results without page reload. ✅

---

### Phase 3: Job Management Panel ✅ COMPLETE
**Goal**: Users can view and control sustained load jobs

**Deliverables**:
- [x] Create `/ui/partials/active-jobs` route calling `/load/cpu/status`
- [x] Create `partials/active_jobs.html` template with job cards
- [x] Display job_id, cores, intensity, status, time remaining
- [x] Calculate and display countdown for running jobs with progress bar
- [x] Implement auto-refresh polling (every 2s via hx-trigger)
- [x] Handle empty state (no active jobs)

**Note**: Stop button was not implemented as CPU jobs are fire-and-forget background tasks.

**Acceptance Criteria**: Jobs panel shows running/completed jobs and updates automatically. ✅

---

### Phase 4: Live Metrics ✅ COMPLETE
**Goal**: Real-time visualization of system metrics from Prometheus

**Deliverables**:
- [x] Implement `_query_prometheus()` helper function in routes.py
- [x] Implement error handling for Prometheus unavailable/timeout
- [x] Create `/ui/partials/live-metrics` route returning HTML partial
- [x] Define PromQL queries for: CPU usage, memory usage, request rate, pod count
- [x] Display pod count with HPA scaling indicator
- [x] Display CPU and memory usage as percentage bars
- [x] Display request rate as requests/second
- [x] Wire HTMX polling to update metrics every 5 seconds
- [x] Environment-aware Prometheus URL (local vs in-cluster)
- [x] Create error state UI when Prometheus unavailable ("Waiting for Prometheus connection...")

**Note**: Decided against Chart.js rolling window charts in favor of simple metric cards with progress bars. This provides a cleaner UX and avoids complexity.

**Acceptance Criteria**: Metrics display live values, update automatically, and gracefully handle Prometheus being down. ✅

---

### Phase 4.5: Cluster Load (Distributed Testing) ✅ COMPLETE
**Goal**: Demonstrate Kubernetes load distribution across multiple pods

This feature was added beyond the original MVP scope to showcase how Kubernetes Service load balancing distributes requests across scaled pods.

**Deliverables**:
- [x] Create Cluster Load tab in the dashboard
- [x] Implement `/ui/partials/cluster-result` route for distributed testing
- [x] Create `_get_k8s_service_url()` helper for in-cluster vs local routing
- [x] Use ThreadPoolExecutor for concurrent request distribution
- [x] Display results showing which pods handled requests
- [x] Show pod distribution breakdown with request counts per pod
- [x] Add validation for concurrency (1-100) and iterations (1K-10M)
- [x] Handle all-requests-failed error scenario with informative message

**Form Fields**:
| Field | Type | Range | Default |
|-------|------|-------|---------|
| Concurrency | Slider + input | 1-100 | 10 |
| Iterations | Slider + input | 1,000-10,000,000 | 500,000 |

**Result Display**:
- Total requests sent
- Successful vs failed count
- Average duration per request
- Number of unique pods used
- Load distribution breakdown showing request count per pod

**Acceptance Criteria**: User can send concurrent requests that distribute across all available pods, demonstrating Kubernetes load balancing. ✅

---

### Phase 5: Polish & Error Handling
**Goal**: Production-ready UI with comprehensive error handling

**Deliverables**:
- [ ] Add error boundaries for all HTMX requests (hx-on::error)
- [ ] Implement timeout handling with "Taking longer than expected" message
- [ ] Add responsive breakpoints for tablet/mobile
- [ ] Ensure forms are usable on mobile devices
- [ ] Add keyboard shortcuts for common actions (optional)
- [ ] Implement dark mode toggle with Tailwind dark: classes (optional)
- [ ] Add favicon and page title
- [ ] Test all error scenarios (API down, Prometheus down, network timeout)
- [ ] Update README with dashboard usage instructions

**Acceptance Criteria**: Dashboard works on mobile, handles all error states gracefully, looks professional.

---

## Deployment Considerations

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `ENVIRONMENT` | Controls Prometheus URL selection and UI header display | `local` |
| `PORT` | Flask server port (for internal API calls) | `5000` |

**Prometheus URL Logic** (in `routes.py`):
- When `ENVIRONMENT=local`: Uses `http://localhost:9090` (port-forwarded Prometheus)
- When `ENVIRONMENT=production` or `ENVIRONMENT=staging`: Uses `http://kube-prometheus-stack-prometheus.observability.svc.cluster.local:9090`

**Kubernetes Service URLs** (for Cluster Load):
- Local: Uses `http://127.0.0.1:{PORT}` for API calls
- In-cluster: Uses `http://load-harness.applications.svc.cluster.local` for distributed load across pods

### Kubernetes Changes

No new deployments needed. The dashboard is part of the existing load-harness pod.

May need to update:
- ConfigMap with `PROMETHEUS_URL`
- ServiceMonitor if adding dashboard-specific metrics

### Resource Impact

Minimal - dashboard adds:
- ~500KB static assets (CSS, HTMX)
- Slight increase in memory for template rendering
- Additional HTTP requests for polling (lightweight)

---

## Future Enhancements

After MVP is stable, consider:

1. **Test Presets** - Save common test configurations
2. **Results History** - Add SQLite/PostgreSQL for persistence
3. **Comparison View** - Compare results across test runs
4. **Export** - Download results as JSON/CSV
5. **Alerts** - Visual alerts when metrics exceed thresholds
6. **HPA Visualization** - Show autoscaling events timeline
7. **Multi-target** - Evolve to test external endpoints (Option B)

---

## Design Decisions

### Styling: Tailwind CSS

**Decision**: Use Tailwind CSS via CDN for styling.

**Rationale**:
- More control over appearance than classless frameworks
- Utility-first approach is intuitive once learned
- Excellent documentation with examples
- CDN version requires no build step
- Better for creating polished, professional-looking interfaces

**Implementation**:
```html
<!-- In base.html head -->
<script src="https://cdn.tailwindcss.com"></script>
```

### Charts: Chart.js with Real-Time Updates

**Decision**: Include Chart.js for live visualizations that update over time.

**Rationale**:
- Users should see metrics changing as load tests run
- Visual feedback is more intuitive than numbers alone
- Chart.js is lightweight, well-documented, CDN-available
- Supports streaming/real-time data updates

**Charts to Include**:

1. **CPU Usage Timeline** - Line chart showing CPU % over last 60 seconds
2. **Memory Usage Timeline** - Line chart showing memory over last 60 seconds
3. **Request Rate** - Line chart showing requests/second
4. **Pod Count** - Simple gauge or number with scaling indicator

**Real-Time Implementation**:
```javascript
// Minimal JS needed for Chart.js updates
// HTMX fetches new data, we update the chart

document.body.addEventListener('htmx:afterSwap', function(event) {
    if (event.detail.target.id === 'metrics-data') {
        // Parse new data from hidden element and update chart
        const data = JSON.parse(document.getElementById('metrics-json').textContent);
        updateCharts(data);
    }
});
```

### Error States: Graceful Degradation

**Decision**: Dashboard remains functional even when Prometheus is unavailable.

**Error Scenarios**:

| Scenario | User Experience |
|----------|-----------------|
| Prometheus unreachable | Metrics panel shows "Metrics unavailable - Prometheus not connected" with retry button |
| Prometheus query fails | Specific metric shows "─" with tooltip explaining the error |
| API endpoint fails | Form shows error message, doesn't break page |
| Network timeout | Loading state with "Taking longer than expected..." message |

**Error State Templates**:

```html
<!-- Prometheus unavailable -->
<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
  <div class="flex items-center gap-2 text-yellow-800">
    <svg class="w-5 h-5"><!-- warning icon --></svg>
    <span class="font-medium">Metrics Unavailable</span>
  </div>
  <p class="text-yellow-700 text-sm mt-1">
    Cannot connect to Prometheus at {{ prometheus_url }}
  </p>
  <button hx-get="/ui/partials/metrics"
          hx-target="#metrics-panel"
          class="mt-2 text-sm text-yellow-800 underline">
    Retry
  </button>
</div>

<!-- API error -->
<div class="bg-red-50 border border-red-200 rounded-lg p-4">
  <div class="flex items-center gap-2 text-red-800">
    <svg class="w-5 h-5"><!-- error icon --></svg>
    <span class="font-medium">Test Failed</span>
  </div>
  <p class="text-red-700 text-sm mt-1">{{ error_message }}</p>
</div>
```

**Backend Error Handling**:

```python
# src/load_harness/dashboard/metrics.py

import requests
from requests.exceptions import ConnectionError, Timeout

class PrometheusClient:
    def __init__(self, url: str, timeout: int = 5):
        self.url = url
        self.timeout = timeout

    def query(self, promql: str) -> dict:
        """Execute PromQL query with error handling."""
        try:
            response = requests.get(
                f"{self.url}/api/v1/query",
                params={"query": promql},
                timeout=self.timeout
            )
            response.raise_for_status()
            return {"status": "success", "data": response.json()["data"]}
        except ConnectionError:
            return {"status": "error", "error": "prometheus_unreachable"}
        except Timeout:
            return {"status": "error", "error": "prometheus_timeout"}
        except Exception as e:
            return {"status": "error", "error": str(e)}
```

---

## Real-Time Updates Architecture

### Update Frequency

| Component | Update Method | Frequency |
|-----------|--------------|-----------|
| Metrics charts | HTMX polling | Every 5 seconds |
| Active jobs list | HTMX polling | Every 5 seconds |
| Test result | On-demand (after submit) | N/A |
| Pod count | HTMX polling | Every 10 seconds |

### Chart Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ Browser                                                         │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Chart.js instance (in memory)                               │ │
│ │ - Maintains last 60 data points                             │ │
│ │ - Animates smoothly between updates                         │ │
│ └──────────────────────────▲──────────────────────────────────┘ │
│                            │ updateChart(newData)               │
│ ┌──────────────────────────┴──────────────────────────────────┐ │
│ │ <div id="metrics-data"                                      │ │
│ │      hx-get="/ui/partials/metrics-data"                     │ │
│ │      hx-trigger="every 5s"                                  │ │
│ │      hx-swap="innerHTML">                                   │ │
│ │   <script id="metrics-json" type="application/json">        │ │
│ │     {"cpu": 45.2, "memory": 128, "pods": 2, "rps": 12}     │ │
│ │   </script>                                                 │ │
│ │ </div>                                                      │ │
│ └──────────────────────────▲──────────────────────────────────┘ │
└────────────────────────────│────────────────────────────────────┘
                             │ HTML partial with JSON
                             │
┌────────────────────────────┴────────────────────────────────────┐
│ Flask Dashboard Route                                           │
│                                                                 │
│ @dashboard.route('/partials/metrics-data')                      │
│ def metrics_data():                                             │
│     metrics = prometheus_client.get_current_metrics()           │
│     return render_template('partials/metrics_data.html',        │
│                            metrics=metrics)                     │
└────────────────────────────▲────────────────────────────────────┘
                             │ PromQL queries
                             │
┌────────────────────────────┴────────────────────────────────────┐
│ Prometheus                                                      │
│ - process_cpu_seconds_total                                     │
│ - process_resident_memory_bytes                                 │
│ - flask_http_request_total                                      │
│ - kube_deployment_status_replicas                               │
└─────────────────────────────────────────────────────────────────┘
```

### Chart Configuration

```javascript
// Included in base.html or separate dashboard.js

const chartConfig = {
    type: 'line',
    options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: {
            duration: 300  // Smooth transitions
        },
        scales: {
            x: {
                type: 'time',
                time: {
                    unit: 'second',
                    displayFormats: {
                        second: 'HH:mm:ss'
                    }
                }
            },
            y: {
                beginAtZero: true
            }
        },
        plugins: {
            legend: {
                display: false
            }
        }
    }
};

// CPU chart with 60-second window
const cpuChart = new Chart(document.getElementById('cpu-chart'), {
    ...chartConfig,
    data: {
        datasets: [{
            label: 'CPU %',
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            fill: true,
            data: []  // {x: timestamp, y: value}
        }]
    }
});

// Update function called after HTMX swap
function updateCharts(metrics) {
    const now = new Date();

    // Add new point
    cpuChart.data.datasets[0].data.push({
        x: now,
        y: metrics.cpu
    });

    // Remove points older than 60 seconds
    const cutoff = new Date(now - 60000);
    cpuChart.data.datasets[0].data = cpuChart.data.datasets[0].data
        .filter(point => point.x > cutoff);

    cpuChart.update('none');  // Update without animation for smooth feel
}
```

---

## Decision Summary

| Question | Decision |
|----------|----------|
| Styling framework | Tailwind CSS (via CDN) |
| Charts | Chart.js with 60-second rolling window |
| Real-time updates | HTMX polling every 5 seconds |
| Error handling | Graceful degradation with clear error states |
| Prometheus unavailable | Show warning, allow retry, don't break dashboard |

---

## References

- [HTMX Documentation](https://htmx.org/docs/)
- [Tailwind CSS](https://tailwindcss.com/docs/)
- [Chart.js Documentation](https://www.chartjs.org/docs/)
- [Flask Templates](https://flask.palletsprojects.com/en/3.0.x/templating/)
- [Prometheus HTTP API](https://prometheus.io/docs/prometheus/latest/querying/api/)
