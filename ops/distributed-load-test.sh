#!/bin/bash
# Distributed CPU Load Test
# Uses 'hey' via Docker to hammer the /load/cpu/work endpoint
#
# Usage: ./distributed-load-test.sh [duration] [concurrency] [iterations]
#   duration    - Test duration (default: 15m)
#   concurrency - Concurrent requests (default: 4)
#   iterations  - CPU iterations per request (default: 1000000)
#
# Recommended settings for sustained load without killing health probes:
#   - 4 concurrent (matches 2 workers x 2 pods)
#   - 1M iterations (~2s per request)
#   - 15m duration for meaningful test
#
# Example: ./distributed-load-test.sh 15m 4 1000000

set -e

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# Parameters with defaults (tuned for sustained load)
DURATION="${1:-15m}"
CONCURRENCY="${2:-4}"
ITERATIONS="${3:-1000000}"

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  Distributed CPU Load Test${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# Try to get ALB DNS from Ingress
echo -e "${CYAN}Fetching ALB endpoint from Ingress...${NC}"
ALB_DNS=$(kubectl get ingress load-harness -n applications -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "")

if [ -n "$ALB_DNS" ]; then
    TARGET_URL="http://${ALB_DNS}/load/cpu/work"
    echo -e "${GREEN}Found ALB: ${ALB_DNS}${NC}"
    echo -e "${GREEN}Using distributed load via ALB${NC}"
else
    echo -e "${YELLOW}No ALB found, falling back to port-forward (single pod)${NC}"
    TARGET_URL="http://host.docker.internal:8080/load/cpu/work"
fi

echo ""
echo -e "  Duration:     ${GREEN}${DURATION}${NC}"
echo -e "  Concurrency:  ${GREEN}${CONCURRENCY}${NC} concurrent requests"
echo -e "  Iterations:   ${GREEN}${ITERATIONS}${NC} per request"
echo -e "  Target:       ${GREEN}${TARGET_URL}${NC}"
echo ""
echo -e "${YELLOW}Starting load test...${NC}"
echo ""

# Run hey via Docker
# --add-host allows Docker to reach host's localhost (for port-forward fallback)
docker run --rm --add-host=host.docker.internal:host-gateway \
    williamyeh/hey:latest \
    -z "${DURATION}" \
    -c "${CONCURRENCY}" \
    -m POST \
    -H "Content-Type: application/json" \
    -d "{\"iterations\": ${ITERATIONS}}" \
    "${TARGET_URL}"

echo ""
echo -e "${GREEN}Load test complete!${NC}"
echo -e "${CYAN}Check Grafana at http://localhost:3000 for metrics${NC}"
