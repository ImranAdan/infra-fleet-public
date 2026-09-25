# Observability

Request rate, errors and latency are measured at the gateway for any app;
CPU, memory and restarts come from the kubelet. Dashboards, including the
advisor's Declared intent row, are provisioned from Git and survive restarts.

## Sub-features

- `golden-signals-exact` the gateway counters equal the requests sent.
- `app-visible` Prometheus sees the app's container.
- `dashboards-provisioned` Fleet Application, the app's dashboards and DORA
  exist without any import.
- `advisor-row` the Declared intent row returns the approved report's counts.

## How to get to it (user POV)

- Grafana: `./fleet access --profile local --service grafana`, dashboard
  **Fleet Application**.
- Prometheus: `./fleet access --profile local --service prometheus`.

## Driving it with kubectl, flux and hey

Preconditions:

- Doctor clean, canary not mid-analysis, node CPU below 70%.
- No other traffic test is running.

- **Golden signals are exact.** Run `.claude/skills/verify-fleet/ground-truth.sh 200`.
  It prints `requests sent: 200`, `prometheus counted: 200` and
  `verdict: exact`, and exits 0.
- **App visible.** Query
  `count(container_cpu_usage_seconds_total{namespace="applications",container="<APP_NAME>"}) > bool 0`
  through the API proxy. The value is `1`.
- **Dashboards provisioned.** Run `P=$(cat "$(git rev-parse --git-common-dir)/fleet/local/grafana-password")`,
  start `./fleet access --profile local --service grafana`, then
  `curl -s -u admin:$P "localhost:3000/api/search?type=dash-db"`. The titles
  include `Fleet Application`, `Load Testing Overview`,
  `Load Harness - Load Testing Dashboard` and `DORA Metrics`.
- **Advisor row.** POST each Declared intent panel's target to
  `localhost:3000/api/ds/query`. The counts equal those in the advisor's
  `reports/report.json` on `main`.
- **Proof.** Keep the ground-truth evidence directory and the query outputs.

## Gotchas

- Prefer raw counter values at two times over `increase()`, which extrapolates
  to the window edges (about 3% high in practice).
- `/metrics` of a multi-process server must aggregate its workers. A dashboard
  once showed half the real traffic because each scrape saw one gunicorn worker.
- AWS-only series (ingress-nginx, DORA) are empty locally by design.
- The advisor row needs outbound HTTPS from Grafana to GitHub.
