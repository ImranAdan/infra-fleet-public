# EKS Cluster Build Guide

This guide provides step-by-step instructions for deploying an EKS cluster with public endpoint access and GitOps integration.

**Important Notes**:
- **Session Manager jumpbox**: Disabled for cost optimization (~$10-15/month savings)
- **Nightly destruction**: Stack automatically destroyed at 8 PM UTC daily (GitHub Actions)
- **Cost optimization**: Spot instances + nightly destroy pattern = ~$36-41/month actual costs
- See [docs/EKS-ACCESS.md](../../docs/EKS-ACCESS.md) for current access methods
- See [docs/COST-OPTIMIZATION-GUIDE.md](../../docs/COST-OPTIMIZATION-GUIDE.md) for comprehensive cost analysis

## 1. Prerequisites

Before you begin, ensure you have:

* An AWS Account with necessary permissions for VPCs, EKS clusters, IAM roles, and related resources
* [Terraform](https://learn.hashicorp.com/tutorials/terraform/install-cli) (v1.12.2+) installed on your local machine
* The [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-install.html) (v2) installed and configured with your AWS credentials
* [`kubectl`](https://kubernetes.io/docs/tasks/tools/install-kubectl/) installed on your local machine

## 2. Configuration Overview

The infrastructure is defined in the `infrastructure/staging/` directory with these key files:

### `main.tf`
- Defines required providers: `aws` (>= 6.15.0, < 7.0.0) and `random` (~> 3.1)
- Configures AWS provider region (`eu-west-2`)

### `vpc.tf`
- VPC with `10.0.0.0/16` CIDR block
- Two AZ setup: `eu-west-2a`, `eu-west-2b` (EKS requirement)
- Private subnets: `10.0.1.0/24`, `10.0.2.0/24` (EKS workers)
- Public subnet: `10.0.101.0/24` (Session Manager, ALB)
- NAT Gateway for internet access from private subnets
- S3 VPC Gateway Endpoint for cost optimization

### `eks.tf`
- EKS cluster with public endpoint (`0.0.0.0/0` for Terraform Cloud/GitHub Actions access)
- **Staged Add-ons** to prevent dependency issues:
  - **Stage 1**: `vpc-cni`, `kube-proxy` (critical for node health)
  - **Stage 2**: `coredns`, `eks-pod-identity-agent` (deployed after nodes ready)
- EKS Access Entries for GitHub Actions IAM role

### `session-manager.tf.disabled`
- **DISABLED** for cost optimization (~$10-15/month savings)
- EKS access managed via temporary IP whitelisting + kubectl
- Can be re-enabled if needed: rename to `session-manager.tf` and uncomment references in `eks.tf`
- See [docs/EKS-ACCESS.md](../../docs/EKS-ACCESS.md) for current access methods and re-enabling instructions

### `s3.tf`
- Commented out for cost optimization
- Can be uncommented if S3 storage needed

## 3. Deployment Steps

1. **Navigate to the staging directory:**
   ```bash
   cd infrastructure/staging
   ```

2. **Initialize Terraform:**
   ```bash
   terraform init
   ```

3. **Apply the configuration:**
   ```bash
   terraform apply
   ```
   Review the plan and type `yes` when prompted.

   **Expected Timeline:**
   - VPC and networking: ~3 minutes
   - EKS cluster: ~12 minutes
   - Critical add-ons (VPC CNI, kube-proxy): ~3 minutes
   - Node group: ~6 minutes
   - Non-critical add-ons (CoreDNS, Pod Identity): ~3 minutes
   - **Total: ~25-30 minutes**

## 4. Post-Deployment: GitOps with Flux

After infrastructure deployment, Flux automatically:
- Bootstraps itself into the cluster
- Syncs manifests from `k8s/` directory
- Deploys infrastructure components (AWS Load Balancer Controller)
- Deploys applications (load-harness)

**Flux Components** (slim deployment for cost optimization):
- `source-controller` - Monitors Git repository
- `kustomize-controller` - Applies Kustomize manifests
- `helm-controller` - Manages Helm releases

See `infrastructure/staging/flux.tf` for bootstrap configuration.

## 5. Verification Steps

**Note**: With Session Manager disabled, kubectl access requires temporary IP whitelisting. See [docs/EKS-ACCESS.md](../../docs/EKS-ACCESS.md) for detailed instructions.

1. **Add your IP to EKS endpoint (via AWS Console):**
   ```bash
   # Get your current IP
   curl -s ifconfig.me

   # AWS Console: EKS → staging → Networking → Manage networking
   # Add your IP to "Public access endpoint CIDRs" (e.g., 203.0.113.42/32)
   # Wait 2-3 minutes for changes to apply
   ```

2. **Configure kubectl locally:**
   ```bash
   aws eks update-kubeconfig --name staging --region eu-west-2
   ```

3. **Verify Node Status:**
   ```bash
   kubectl get nodes
   ```
   Expected output:
   ```
   NAME                                         STATUS   ROLES    AGE   VERSION
   ip-10-0-1-25.eu-west-2.compute.internal    Ready    <none>   5m    v1.29.15-eks-c39b1d0
   ```

5. **Verify System Pods:**
   ```bash
   kubectl get pods -n kube-system
   ```
   Expected pods: `aws-node`, `coredns` (x2), `kube-proxy`, `eks-pod-identity-agent` in `Running` state.

6. **Verify Flux Deployment:**
   ```bash
   kubectl get pods -n flux-system
   ```
   Expected pods: `source-controller`, `kustomize-controller`, `helm-controller` in `Running` state.

7. **Verify ALB Controller:**
   ```bash
   kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-load-balancer-controller
   ```
   Expected: ALB controller pod in `Running` state.

## 6. Basic Troubleshooting

### Issue: Add-on Dependency Problems
If add-ons fail to create properly:

**Symptoms:** Terraform hangs during add-on creation, nodes show `NotReady` status

**Solution:** The configuration uses staged dependencies to prevent this:
- **Critical add-ons** (vpc-cni, kube-proxy) deploy first
- **Non-critical add-ons** (coredns, pod-identity-agent) wait for node group completion

### Issue: Terraform Validation Errors
Always run before applying:
```bash
terraform validate
```

### Issue: Resource State Problems
For targeted resource recreation:
```bash
terraform destroy -target='resource.name' -auto-approve
terraform apply
```

## 7. Final Verification Checklist

- [ ] Node status: `kubectl get nodes` shows `Ready`
- [ ] System pods: All pods in `kube-system` namespace are `Running`
- [ ] Flux pods: All pods in `flux-system` namespace are `Running`
- [ ] ALB controller: Pod running in `kube-system` namespace
- [ ] DNS resolution works within cluster
- [ ] Internet access from worker nodes (can pull external images)

## 8. Cost Overview

**Actual Costs** (November 2025 with nightly destruction):
- **Monthly**: ~$36-41/month (38% uptime pattern)
- **Hourly**: $0.172/hour when running
- **Annual savings**: $1,656/year (Kubernetes 1.32 vs extended support)

**Cost Breakdown** (when running):

| Component | Cost | Notes |
|-----------|------|-------|
| EKS Cluster | $72/month | Control plane (prorated when destroyed) |
| EC2 t3.small (Worker) | ~$5/month | Spot instance (~70% savings), prorated |
| NAT Gateway | ~$10-12/month | Prorated by uptime |
| S3 VPC Endpoint | $0 | Gateway type (free) |
| **Actual Total** | **~$36-41/month** | With 38% uptime + spot pricing |

**Key Cost Optimizations**:
1. **Nightly destruction** (8 PM UTC) - Reduces uptime to ~38%
2. **Spot instances** - 70% savings on EC2 costs
3. **Session Manager disabled** - Saves ~$10-15/month
4. **Kubernetes 1.32** - Avoids $1,656/year extended support fees
5. **Slim Flux deployment** - Minimal resource footprint

See [docs/COST-OPTIMIZATION-GUIDE.md](../../docs/COST-OPTIMIZATION-GUIDE.md) for comprehensive cost analysis and optimization strategies.

## 9. Automated Stack Management

**Nightly Destruction**:
- Scheduled: 8 PM UTC daily (GitHub Actions)
- Workflow: `.github/workflows/nightly-destroy.yml`
- Manual trigger: `gh workflow run nightly-destroy.yml -f reason="reason"`

**Stack Rebuild**:
- Manual: `gh workflow run rebuild-stack.yml`
- Duration: ~25-30 minutes
- Fully automated via Terraform + Flux

See [docs/STACK-AUTOMATION.md](../../docs/STACK-AUTOMATION.md) for details.

---

**Next Steps:** See `Design-Considerations.md` for architectural decisions, cost optimization strategies, and lessons learned during development.