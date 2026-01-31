# Cost Optimization Guide

## Overview

This guide helps you minimize AWS costs for the infra-fleet platform while maintaining a production-like learning environment.

**Current Cost Target**: $45-55/month (with ALB + t3.large, disciplined manual destruction)
**Previous Target**: $35-40/month (before ALB and t3.large upgrade)
**Worst Case**: $95/month (if relying on scheduled destruction with ALB)

**December 2025 Infrastructure Changes**:
- ALB deployed for distributed load testing (+~$6/month)
- Instance upgraded from t3.medium to t3.large (+~$3/month)

---

## Your Usage Pattern (GMT Timezone)

- **Start Time**: 10 AM GMT (manual rebuild)
- **End Time**: 7-8 PM GMT (manual destroy)
- **Failsafe**: 8 PM GMT (scheduled destroy if manual forgotten)
- **Frequency**: Variable (daily to few times per week)

---

## December 2025 Cost Optimization Wins

On 2025-12-01, we identified and eliminated **$18/month in unnecessary costs** through systematic auditing:

### 1. Orphaned Elastic IPs - Saved $10.80/month
**Problem**: 3 unattached Elastic IPs were billing at $3.60/month each
**Detection**: Created `scripts/audit-ec2-costs.sh` to scan for orphaned resources
**Fix**: Deleted all 3 EIPs via AWS CLI

### 2. VPC Endpoint Misconfiguration - Saved $7.20/month
**Problem**: S3 endpoint configured as Interface endpoint instead of Gateway (free)
**Root Cause**: terraform-aws-modules/vpc/aws//modules/vpc-endpoints module creates Interface endpoints when `subnet_ids` and `security_group_ids` are provided, even with `vpc_endpoint_type = "Gateway"`
**Fix**: Removed S3 endpoint entirely - NAT Gateway already provides S3 access

### Cost Audit Script

We created `scripts/audit-ec2-costs.sh` to proactively identify cost inefficiencies:

```bash
# Run comprehensive EC2 cost audit
./scripts/audit-ec2-costs.sh eu-west-2 staging

# Checks for:
# - EBS volumes (active and orphaned)
# - EBS snapshots
# - Unattached Elastic IPs ($3.60/month each)
# - NAT Gateways ($32.40/month base)
# - VPC Endpoints (Interface: $7.20/month, Gateway: free)
# - Application Load Balancers ($16.20/month base)
```

**Best Practice**: Run this script monthly to catch orphaned resources early.

### Updated Cost Trajectory

| Month | Cost | Notes |
|-------|------|-------|
| November 2025 | $41.52 | Before December optimizations |
| December 2025 (forecast) | $15-20 | After $18/month savings + nightly destroy at 8 PM |

---

## Cost Breakdown by Component

### Current Configuration (t3.large + ALB)

| Component | Hourly Rate | Daily (10hrs) | Monthly (220hrs) | Notes |
|-----------|-------------|---------------|------------------|-------|
| EKS Control Plane | $0.10/hr | $1.00 | $22.00 | Cannot be reduced |
| Tax (20%) | 20% of EKS | $0.20 | $4.40 | VAT on EKS charges |
| NAT Gateway | $0.045/hr | $0.45 | $9.90 | Required for internet access |
| EC2 Spot (t3.large) | $0.031/hr | $0.31 | $6.82 | 70% cheaper than on-demand |
| ALB (base + LCU) | $0.029/hr | $0.29 | $6.42 | Base $0.0252 + ~$0.004 LCU |
| Miscellaneous | ~$0.006/hr | $0.06 | $0.18 | CloudWatch, etc. |
| **Daily Total** | **$0.219/hr** | **$2.19** | **$48.22** | **Weekday pattern (220hrs/month)** |

### Variable Costs

| Component | Monthly Cost | Notes |
|-----------|--------------|-------|
| EBS Volumes (PVCs) | $0.10/GB/month | Persistent - must delete manually |
| Data Transfer | ~$0.09/GB | Minimal for dev/learning |
| ALB LCU (high traffic) | +$3-5/month | During load testing |

---

## Cost Scenarios

### Scenario 1: Best Case (Manual Discipline ✅)

**Pattern**: Manual rebuild at 10 AM, manual destroy at 8 PM, 5 days/week

```
Uptime: 10 hours/day × 22 days = 220 hours/month

Monthly Cost:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EKS + Tax:        $26.40
NAT Gateway:      $9.90
EC2 Spot:         $1.36
Others:           $0.18
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:            $37.84/month
```

**Savings vs worst case**: $39.38/month (51% reduction)

---

### Scenario 2: Worst Case (Rely on 1 AM Scheduled Destroy)

**Pattern**: Manual rebuild at 10 AM, forget to destroy, rely on 1 AM failsafe

```
Uptime: 15 hours/day × 30 days = 450 hours/month

Monthly Cost:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EKS + Tax:        $54.00
NAT Gateway:      $20.25
EC2 Spot:         $2.79
Others:           $0.18
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:            $77.22/month
```

**This is 2× the cost of manual discipline!**

---

### Scenario 3: Current (November Actual)

**Pattern**: ~9.2 hours/day average, mix of manual and scheduled destroy

```
Uptime: ~276 hours/month

Monthly Cost:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EKS + Tax:        $34.81
NAT Gateway:      $12.42
EC2 (on-demand):  $4.24  ← Before spot pricing (Nov 1-20)
EC2 (spot):       $0.45  ← After spot pricing (Nov 21-23)
Others:           $0.18
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:            $41.52  ✅ Actual November bill
```

---

### Scenario 4: Target (Realistic with Good Habits)

**Pattern**: Manual destroy 80% of time, scheduled destroy 20% of time

```
Average uptime: 11 hours/day × 25 days = 275 hours/month

Monthly Cost:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EKS + Tax:        $34.65
NAT Gateway:      $12.38
EC2 Spot:         $1.71
Others:           $0.18
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total:            $38.92/month
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Next month savings from full spot: -$2.77
Target:           ~$36-37/month
```

---

## How to Minimize Costs

### 1. Daily Discipline (Highest Impact)

**Every extra hour costs $0.172**

```bash
# Morning: Start work session (10 AM)
gh workflow run rebuild-stack.yml

# Wait ~25 minutes for cluster to be ready
# ... do your work ...

# Evening: End work session (7-8 PM) ⚠️ DON'T FORGET!
gh workflow run nightly-destroy.yml -f reason="End of work session"
```

**Pro tip**: Set a calendar reminder for 7:30 PM GMT to destroy the stack.

**Impact**: Saves ~$0.86/day per hour earlier you destroy (5 hours × $0.172 = $0.86)

---

### 2. Shell Aliases (Convenience)

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
# Infra-fleet cluster management
alias cluster-start='gh workflow run rebuild-stack.yml && echo "⏳ Cluster rebuilding... (~25 min)"'
alias cluster-stop='gh workflow run nightly-destroy.yml -f reason="End of work session" && echo "💰 Stack destroying... saving \$0.17/hour"'
alias cluster-status='gh run list --workflow=rebuild-stack.yml --limit 1 && gh run list --workflow=nightly-destroy.yml --limit 1'

# Cost tracking
alias cluster-cost='echo "Current hourly rate: \$0.172/hr" && echo "Daily cost (10hrs): \$1.72" && echo "Monthly cost (220hrs): \$37.84"'
```

**Usage**:
```bash
cluster-start   # Start your day
cluster-stop    # End your day
cluster-status  # Check what's running
cluster-cost    # Quick cost reference
```

---

### 3. Weekend Strategy

**If you don't work weekends**, you're already saving:
- Weekend hours: 48 hours/week × 4 weeks = 192 hours/month
- Savings: 192 × $0.172 = **$33.02/month** (not incurred!)

**Current schedule (1 AM nightly) works perfectly** - destroys Friday night, you rebuild Monday morning.

---

### 4. Monitor Your Patterns

Track your actual usage to identify optimization opportunities:

```bash
# Check how many hours cluster ran this month
gh api /repos/your-org/infra-fleet/actions/workflows/rebuild-stack.yml/runs \
  --jq '[.workflow_runs[] | select(.created_at | startswith("2025-11"))] | length'

# Check your discipline (manual destroys vs scheduled)
gh api /repos/your-org/infra-fleet/actions/workflows/nightly-destroy.yml/runs \
  --jq '[.workflow_runs[] | select(.created_at | startswith("2025-11"))] |
         group_by(.event) |
         map({event: .[0].event, count: length})'
```

---

### 5. Multi-Day Breaks (Manual Intervention)

**If you know you won't use the cluster for 2-3 days**:

```bash
# Before break
cluster-stop

# When you return
cluster-start
```

**Savings**: 2 days × 24 hours × $0.172 = **$8.26 saved**

---

## Cost Comparison Table

| Work Pattern | Hours/Month | Monthly Cost | vs Current | Best Case Savings |
|--------------|-------------|--------------|------------|-------------------|
| **Best**: Manual discipline, weekdays only | 220 | $37.84 | -$3.68 | Baseline |
| **Target**: 80% manual, 20% forget | 275 | $38.92 | -$2.60 | -$1.08 |
| **Current**: November actual (mixed) | 276 | $41.52 | Baseline | -$3.68 |
| **Acceptable**: Forget often, rely on 1 AM | 360 | $62.00 | +$20.48 | -$24.16 |
| **Worst**: Daily usage, always to 1 AM | 450 | $77.22 | +$35.70 | -$39.38 |

---

## Instance Type Analysis (December 2025)

### Why t3.large is Required

**Current Pod Count (baseline):** 16 pods
- Flux controllers: 5 pods
- Observability stack: 5 pods
- AWS LB Controller: 1 pod
- Load-harness: 1 pod
- System pods: 4 pods

**With HPA scaling (max):** 23 pods (load-harness scales to 8 replicas)

### Instance Comparison (eu-west-2 Spot Pricing)

| Instance | Max Pods | Memory | Spot/hr | Monthly (220hrs) | Viable? |
|----------|----------|--------|---------|------------------|---------|
| t3.small | 11 | 2 GiB | $0.006 | $1.32 | NO - only 11 pods |
| t3.medium | 17 | 4 GiB | $0.013 | $2.86 | NO - 16 baseline, 1 margin |
| **t3.large** | 35 | 8 GiB | $0.031 | $6.82 | YES - 12 pod margin |
| t3a.large (AMD) | 35 | 8 GiB | $0.041 | $9.02 | NO - more expensive |
| t4g.large (ARM) | 35 | 8 GiB | $0.033 | $7.26 | MAYBE - needs ARM images |

**Key Finding**: t3a (AMD) is NOT cheaper for spot instances in eu-west-2. T3 (Intel) has better spot pricing.

**T4g (Graviton)** could save ~$0.44/month but requires multi-arch Docker builds - not worth the complexity.

---

## Regional Cost Arbitrage

### Is Changing Regions Cheaper?

**Yes, but savings are modest (~6%)** for this workload. US regions are generally cheaper than European regions.

### Component-by-Component Comparison

| Component | eu-west-2 (London) | us-east-1 (Virginia) | Difference |
|-----------|-------------------|---------------------|------------|
| EKS Control Plane | $0.10/hr | $0.10/hr | Same |
| NAT Gateway | $0.048/hr | $0.045/hr | +6.7% |
| ALB | $0.0252/hr | $0.0225/hr | +12% |
| t3.large Spot | ~$0.031/hr | ~$0.025/hr | +24% |

### Estimated Monthly Savings (220hrs)

| Component | eu-west-2 | us-east-1 | Savings |
|-----------|-----------|-----------|---------|
| EKS | $22.00 | $22.00 | $0 |
| NAT Gateway | $10.56 | $9.90 | $0.66 |
| ALB | $5.54 | $4.95 | $0.59 |
| EC2 Spot | $6.82 | $5.50 | $1.32 |
| **Total** | **$44.92** | **$42.35** | **~$2.57/month** |

### Regional Pricing Tiers

| Region | Relative Cost | Notes |
|--------|---------------|-------|
| us-east-1, us-east-2, us-west-2 | Cheapest | ~6% cheaper than London |
| eu-west-1 (Ireland) | Mid-tier | Similar to London |
| eu-west-2 (London) | Mid-tier | Current deployment |
| ap-northeast-1 (Tokyo) | Expensive | ~15-20% more than US |
| sa-east-1 (São Paulo) | Most expensive | ~35% more than US |

### Trade-offs of Region Migration

**Pros:**
- ~$2.57/month savings (~$31/year)
- US regions have larger spot capacity (less interruption risk)

**Cons:**
- +70-100ms latency from UK to Virginia
- Migration effort (new Terraform state, ECR registry, IAM roles)
- Time zone mismatch for scheduled jobs (1 AM UTC vs 8 PM EST)

### Verdict

**Not recommended for this project.** The ~6% savings (~$31/year) doesn't justify:
- Migration complexity
- Latency increase for UK-based development
- Reconfiguring all GitHub Actions workflows

**When regional arbitrage IS worth it:**
- Large-scale production workloads (savings compound)
- Latency-insensitive batch processing
- Multi-region deployments (pick cheapest for non-latency-sensitive components)

---

### Orphaned Resource Prevention

**⚠️ Costs that persist after cluster destruction**:

1. **EBS Volumes (PVCs)**: $0.10/GB/month
   - Created by StatefulSets or manual PVCs
   - Must be deleted manually or via cleanup script
   - **Check monthly**: `aws ec2 describe-volumes --region eu-west-2 --query 'Volumes[?State==\`available\`]'`

2. **Elastic IPs**: $0.005/hour if not attached ($3.60/month)
   - Rare, but can happen with manual testing
   - **Check monthly**: `aws ec2 describe-addresses --region eu-west-2 --query 'Addresses[?AssociationId==null]'`

3. **Load Balancers**: $16-21/month each
   - Hybrid cleanup script handles these ✅
   - Kubernetes-native cleanup (delete Ingress) + AWS tag-based fallback
   - Flux suspension prevents recreation during destroy ✅

**Current protection**:
- Hybrid cleanup approach (v2 script in `scripts/cleanup-k8s-resources-v2.sh`)
- Handles both healthy clusters (kubectl) and destroyed clusters (AWS API)
- Pre/post verification prevents silent failures
- See `docs/implementation-summary-hybrid-cleanup.md` for details

---

## Cost Monitoring Commands

### Check Current Month Spend

```bash
# Via AWS CLI (requires aws-cli)
aws ce get-cost-and-usage \
  --time-period Start=2025-11-01,End=2025-11-30 \
  --granularity MONTHLY \
  --metrics BlendedCost \
  --group-by Type=SERVICE \
  --query 'ResultsByTime[0].Groups' \
  --output table
```

### Estimate This Month's Cost (Based on Uptime)

```bash
# Count workflow runs this month
RUNS=$(gh api /repos/your-org/infra-fleet/actions/workflows/rebuild-stack.yml/runs \
  --jq '[.workflow_runs[] | select(.created_at | startswith("2025-11"))] | length')

echo "Rebuild runs this month: $RUNS"
echo "Estimated hours: $(($RUNS * 11)) hours"
echo "Estimated cost: \$$(echo "scale=2; $RUNS * 11 * 0.172" | bc)"
```

---

## Decision Framework: When to Destroy

### ✅ Destroy Immediately When:
- Finished testing for the day
- Going to lunch/meetings (>2 hours away)
- End of work session
- Before weekends (if not working)
- Before holidays/vacation

### ⚠️ Keep Running When:
- Actively developing/testing
- Waiting for long builds (>15 min)
- Debugging issues
- Running load tests

### 💰 Cost of "Just in Case" Running

**Common thought**: "I might need it later, keep it running"

**Reality check**:
- Rebuild time: 25 minutes
- Cost per hour: $0.172
- Break-even: 2.5 hours (25 min rebuild ≈ $0.07 cost vs $0.172/hr running)

**Conclusion**: If you won't use cluster for >2.5 hours, destroy it!

---

## Optimization Recommendations

### ✅ Already Implemented (Good!)
- Spot instances (70% EC2 savings)
- Single NAT Gateway (vs multi-AZ)
- Session Manager disabled (saves $10-15/month)
- Nightly destruction failsafe (prevents runaway costs)
- Flux (5 controllers: source, kustomize, helm, image-automation, image-reflector)
- t3.large with best spot pricing for region

### ⚠️ ALB Cost Reduction Options

**Option A: Disable ALB when not load testing**
- Savings: ~$6/month
- Implementation: Comment out Ingress in GitOps
- Trade-off: Must use port-forwarding for access

**Option B: Reduce HPA max replicas**
- Current: maxReplicas: 8
- Proposed: maxReplicas: 4
- Impact: Reduces max pod count, maintains stability

### ❌ Not Recommended

| Option | Why Not |
|--------|---------|
| Downgrade to t3.medium | Only 17 pods max, 16 baseline = no margin |
| Switch to t3a (AMD) | Spot price higher ($0.041 vs $0.031) |
| Switch to T4g (Graviton) | Requires multi-arch Docker builds, minimal savings |
| VPC endpoints | Requires rearchitecture |
| Fargate | Minimal savings, added complexity |

---

## Summary

**Your current setup is optimized for the workload**. The main optimization lever is **discipline with manual destruction**.

**Key Takeaways**:
1. **Every hour costs $0.219** - destroy when done!
2. **t3.large is required** - 16 baseline pods, need headroom for HPA scaling
3. **t3a (AMD) is NOT cheaper** - spot pricing is higher in eu-west-2
4. **ALB adds ~$6/month** - justified for distributed load testing
5. **Target: $45-55/month** with good destruction discipline
6. **Worst case: $95/month** if always relying on scheduled failsafe

**Best practices**:
- Set a daily reminder to destroy at end of session
- Use shell aliases for convenience
- Check AWS billing dashboard weekly
- Verify no orphaned resources monthly

---

**Last Updated**: 2025-12-08
**Next Review**: After January billing (to validate new cost structure)
