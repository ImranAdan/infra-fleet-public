#!/bin/bash
# Port-forward Prometheus from cluster to localhost
# This is a convenience wrapper for ./port-forward.sh prometheus

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/port-forward.sh" prometheus
