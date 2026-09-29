#!/usr/bin/env bash
# Prove the teardown scripts discover the current NLB ownership tag without
# reaching AWS or deleting anything.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
mkdir -p "$scratch/bin"
cat > "$scratch/bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$AWS_CLEANUP_TEST_DIR/calls"
case "$*" in
  'eks describe-cluster '*) exit 1 ;;
  'elbv2 delete-load-balancer '*) touch "$AWS_CLEANUP_TEST_DIR/deleted"; exit 99 ;;
  'elbv2 describe-load-balancers '*LoadBalancerArn*) printf '%s\n' 'arn:aws:elasticloadbalancing:eu-west-2:111122223333:loadbalancer/net/fleet/abc' ;;
  'elbv2 describe-load-balancers '*LoadBalancerName*) printf '%s\n' 'fleet-nlb' ;;
  'elbv2 describe-load-balancers '*DNSName*) printf '%s\n' 'fleet.example.invalid' ;;
  'elbv2 describe-load-balancers '*Type*) printf '%s\n' 'network' ;;
  'elbv2 describe-tags '*) printf '%s\n' 'staging' ;;
  'ec2 describe-vpcs '*) printf '%s\n' 'None' ;;
  'ec2 describe-network-interfaces '*|'ec2 describe-security-groups '*|'ec2 describe-volumes '*) ;;
  *) printf 'Unexpected aws call: %s\n' "$*" >&2; exit 98 ;;
esac
EOF
chmod +x "$scratch/bin/aws"

export AWS_CLEANUP_TEST_DIR=$scratch
export PATH="$scratch/bin:$PATH"

"$root/scripts/cleanup-k8s-resources-v2.sh" staging eu-west-2 dry-run > "$scratch/cleanup"
grep -Fq 'Found: fleet-nlb [network]' "$scratch/cleanup"
grep -Fq '[DRY RUN] Would delete load balancer:' "$scratch/cleanup"
[ ! -e "$scratch/deleted" ] || { echo 'Dry-run teardown called delete-load-balancer.' >&2; exit 1; }

"$root/scripts/verify-cleanup-resources.sh" staging eu-west-2 > "$scratch/verify"
grep -Fq 'fleet-nlb [network] (fleet.example.invalid)' "$scratch/verify"
grep -Fq 'Found: 1 load balancer(s) managed by Kubernetes' "$scratch/verify"
grep -Fq "Key=='elbv2.k8s.aws/cluster' && Value=='staging'" "$scratch/calls"

echo 'AWS cleanup NLB discovery contract passed (no external calls).'
