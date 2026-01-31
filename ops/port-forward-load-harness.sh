#!/bin/bash
# Port-forward Load Harness from cluster to localhost
# This is a convenience wrapper for ./port-forward.sh load-harness

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/port-forward.sh" load-harness
