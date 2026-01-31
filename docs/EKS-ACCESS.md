# EKS Cluster Access Guide

## Overview

The EKS cluster has a **public endpoint** with `publicAccessCidrs = ["0.0.0.0/0"]` to allow:
- GitHub Actions workflows (for Terraform apply)
- Terraform Cloud workers (for Flux bootstrap)

**Security:** Network access alone is not sufficient - you must have valid AWS IAM credentials.

---

## Session Manager Jumpbox (Disabled)

The Session Manager jumpbox is **currently disabled** to reduce costs (~$10-15/month).

**To re-enable:**
1. Rename `clusters/staging/session-manager.tf.disabled` → `session-manager.tf`
2. Uncomment session manager resources in `clusters/staging/eks.tf`:
   - `access_entries.session_manager`
   - `security_group_additional_rules.allow_jumpbox_https`
3. Run `terraform apply`

---

## Accessing the Cluster (Without Jumpbox)

### Method 1: Temporary IP Whitelist (Recommended)

When you need kubectl access:

**Step 1: Add Your IP via AWS Console**

```bash
# Get your current IP
curl -s ifconfig.me

# AWS Console steps:
# 1. Go to: EKS → Clusters → staging → Networking
# 2. Click "Manage networking"
# 3. Add your IP to "Public access endpoint CIDRs"
#    Example: 203.0.113.42/32
# 4. Click "Update" (takes 2-3 minutes to apply)
```

**Step 2: Configure kubectl**

```bash
# Update kubeconfig
aws eks update-kubeconfig --name staging --region eu-west-2

# Test connection
kubectl get nodes
kubectl get pods -A
```

**Step 3: (Optional) Remove Your IP**

When done, go back to AWS Console and remove your IP from the CIDR list.

---

### Method 2: Use IAM User Access Entry

Your IAM user already has an access entry (created manually during testing):

```bash
# Verify your AWS identity
aws sts get-caller-identity

# If you see: arn:aws:iam::123456789012:user/imran
# Then you already have cluster access configured

# Just update kubeconfig and connect
aws eks update-kubeconfig --name staging --region eu-west-2
kubectl get nodes
```

**Note:** This requires your IP to be in the `publicAccessCidrs` list (see Method 1).

---

## GitHub Actions Access

GitHub Actions workflows have permanent access via:
- **IAM Role:** `GitHubActions-InfraFleet` (OIDC-based)
- **EKS Access Entry:** Configured with `AmazonEKSClusterAdminPolicy`
- **No IP restriction needed:** GitHub Actions IPs are unpredictable

This is how Terraform and Flux operations work in CI/CD.

---

## Security Considerations

### Current Security Posture

**Network Layer:**
- Public endpoint: `0.0.0.0/0` (no IP restrictions)
- Private endpoint: Enabled (for future use if jumpbox re-enabled)

**Authentication Layer:**
- AWS IAM required (token-based or OIDC)
- Must have valid AWS credentials
- Must have EKS access entry or aws-auth ConfigMap entry

**Attack Surface:**
Attacker needs BOTH:
1. ✅ Network access (easy - public endpoint)
2. ❌ Valid AWS credentials (hard - requires compromised IAM)

**Verdict:** Acceptable for staging/dev, especially with nightly rebuilds

### When to Improve Security

Consider one of these options before going to production:

1. **GitHub Actions Workflow for Flux** (Issue #17, Option B)
   - Restrict EKS endpoint to GitHub Actions IPs only
   - Bootstrap Flux via GitHub Actions instead of Terraform
   - Best balance of security and automation

2. **Terraform Cloud Agents** (Issue #17, Option A)
   - Deploy TFC agent in VPC
   - Fully private EKS endpoint
   - Requires TFC Plus/Business tier

3. **Re-enable Session Manager + Private Endpoint**
   - Remove public endpoint entirely
   - Access only via jumpbox in VPC
   - Highest security but manual Flux bootstrap

---

## Troubleshooting

### "Unauthorized" Error

```
Error: You must be logged in to the server (Unauthorized)
```

**Cause:** Your IAM identity doesn't have an EKS access entry

**Fix:**
```bash
# Check your identity
aws sts get-caller-identity

# Add access entry (replace with your IAM ARN)
aws eks create-access-entry \
  --cluster-name staging \
  --region eu-west-2 \
  --principal-arn arn:aws:iam::123456789012:user/YOUR_USER \
  --type STANDARD

# Associate admin policy
aws eks associate-access-policy \
  --cluster-name staging \
  --region eu-west-2 \
  --principal-arn arn:aws:iam::123456789012:user/YOUR_USER \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
```

### "Connection Timeout" Error

**Cause:** Your IP is not in `publicAccessCidrs`

**Fix:** Add your IP via AWS Console (see Method 1 above)

### "Token Expired" Error

**Cause:** EKS auth token expired (valid for 15 minutes)

**Fix:**
```bash
# Refresh kubeconfig
aws eks update-kubeconfig --name staging --region eu-west-2

# Try again
kubectl get nodes
```

### Node and Add-on Issues

#### `KubeletNotReady` and `cni plugin not initialized`

**Symptoms:**
```
Ready False  KubeletNotReady  Network plugin returns error: cni plugin not initialized
```

**Cause:** The `aws-node` (VPC CNI) DaemonSet could not start because there were no nodes or insufficient pod capacity.

**Fix:**
- Ensure a managed node group is deployed
- Use at least `t3.large` instance type (35 pods max)
- Verify: `kubectl get daemonset -n kube-system aws-node` — all replicas must be `READY`

#### `InsufficientNumberOfReplicas` for Add-ons

**Symptoms:**
```
The add-on is unhealthy because all deployments have all pods unscheduled — no nodes available.
```

**Cause:** EKS add-ons were applied before nodes were available.

**Fix:**
- Wait for nodes to be ready, or trigger a rebuild
- Re-apply add-ons after node creation (if needed)

#### Node has limited pod capacity

**Symptoms:**
```bash
Capacity:
  pods: 4
Allocatable:
  pods: 4
```

**Cause:** Using a small instance type (t3.micro/t3.small) limits available pods.

**Fix:** Use `t3.large` (35 pods max) or larger. Current cluster uses t3.large spot instances.

#### CoreDNS Service Not Found

**Symptoms:**
```bash
Error from server (NotFound): services "coredns" not found
```

**Cause:** The DNS service in EKS is called `kube-dns`, not `coredns`.

**Fix:**
```bash
kubectl get svc,endpoints -n kube-system kube-dns
```

### Maintenance Tips

- **Confirm all system pods healthy:**
  ```bash
  kubectl get pods -n kube-system
  ```

- **Check node status:**
  ```bash
  kubectl get nodes -o wide
  ```

- **Test DNS resolution:**
  ```bash
  kubectl run -it dns-test --image=busybox:1.36 --restart=Never -- nslookup kubernetes.default
  ```

---

## Cost Impact

**With Session Manager Disabled:**
- Savings: ~$10-15/month (t3.micro instance + EBS volume)
- Total cluster cost impact:
  - November 2025 actual: $36-41/month (with nightly destroy + spot instances)
  - Previous estimates: $144/month (24/7 on-demand)
  - **Achieved savings**: 73% cost reduction

**Trade-off:**
- Manual IP whitelisting when you need access
- Suitable for staging/dev with infrequent human access
- GitHub Actions always has access via OIDC (0.0.0.0/0 endpoint)
- Can re-enable anytime for dedicated jumpbox access

---

## Related Documentation

- **Issue #17:** Secure EKS API Access discussion
- **Issue #18:** Flux bootstrap authentication resolution
- **DDR:** `docs/TERRAFORM-CLOUD-EKS-DDR.md` - Terraform Cloud constraints

---

**Last Updated:** 2025-12-23
