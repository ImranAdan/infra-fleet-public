#!/bin/bash
# Port-forward Grafana from cluster to localhost
# This is a convenience wrapper for ./port-forward.sh grafana

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/port-forward.sh" grafana
