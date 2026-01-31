# Permanent Infrastructure

## Purpose

This directory contains Terraform configuration for **permanent infrastructure** that should **never be destroyed**.

These resources persist across nightly destroy/rebuild cycles and provide foundational authentication and security capabilities.

## ⚠️ CRITICAL WARNING

**DO NOT run `terraform destroy` in this directory!**

Destroying these resources will break all GitHub Actions automation and require manual recovery. If you need to modify resources, use `terraform apply` to update them in place.

## Current Resources

### GitHub Actions OIDC Authentication
- **File**: `github-oidc.tf`
- **Status**: ✅ Deployed (2025-11-19)
- **Resources**:
  - AWS IAM OIDC Provider for GitHub Actions
  - IAM Role: `GitHubActions-InfraFleet`
  - IAM Policy with least-privilege permissions
  - Trust policy restricting to `your-org/infra-fleet` repository
- **Cost**: $0/month

### Why Permanent?

The OIDC infrastructure must remain persistent because:
1. **Authentication Dependency**: GitHub Actions workflows need this role to authenticate
2. **Chicken-and-Egg Problem**: Can't rebuild infrastructure without authentication
3. **Zero-Downtime**: Workflows always have access to AWS
4. **Cost**: ~$0 (IAM roles are free)

## Future Resources (Under Consideration)

### DNS (Route53 Hosted Zone)
- **Status**: 🔄 Planning (see ai/DECISIONS-NEEDED.md)
- **When to add**: If using custom domain for applications
- **Reason for permanent**:
  - DNS records should persist across stack rebuilds
  - Required for ACM certificate validation
  - Prevents domain configuration loss
- **Cost**: $0.50/month
- **File**: `dns.tf` (when implemented)

### SSL Certificates (ACM)
- **Status**: 🔄 Planning (see ai/DECISIONS-NEEDED.md)
- **When to add**: If using AWS Certificate Manager with Route53
- **Reason for permanent**:
  - Certificate validation creates DNS records
  - Auto-renewal depends on persistent validation
  - Prevents certificate recreation delays
- **Cost**: $0/month (ACM is free)
- **File**: `acm.tf` (when implemented)
- **Alternative**: Keep in staging/ if using Let's Encrypt (app-managed)

## Deployment

### One-Time Setup (Deploy Once)

```bash
cd infrastructure/permanent
terraform init
terraform apply
```

**Outputs:**
- `github_actions_role_arn` - Copy this to GitHub Secrets

### GitHub Secret Configuration

After deploying, configure the GitHub repository secret:

1. Get role ARN:
   ```bash
   terraform output github_actions_role_arn
   ```

2. Add to GitHub:
   - Go to: https://github.com/your-org/infra-fleet/settings/secrets/actions
   - Name: `AWS_GITHUB_ACTIONS_ROLE_ARN`
   - Value: (paste ARN from above)

### Subsequent Operations

**You should NEVER need to run Terraform here again** unless:
- Updating IAM policy permissions
- Changing trust policy
- Adding new OIDC providers

## Decision Framework: Permanent vs Ephemeral

### Add to `infrastructure/permanent/` if:

- ✅ Required for GitHub Actions authentication
- ✅ Breaking it breaks the entire automation chain
- ✅ Recreation would require manual intervention
- ✅ Cost is $0 or negligible (<$1/month)
- ✅ Doesn't change frequently
- ✅ Other infrastructure depends on it

### Keep in `infrastructure/staging/` if:

- ✅ Application-specific (EKS cluster, apps, databases)
- ✅ Can be recreated automatically by workflows
- ✅ Has significant monthly cost (benefits from nightly destroy)
- ✅ Changes frequently during development
- ✅ Can be destroyed without breaking automation

**Example**: EKS cluster costs ~$88/month and can be rebuilt automatically → stays in `staging/`

**Example**: Route53 hosted zone costs $0.50/month but recreation requires manual DNS reconfiguration → should go in `permanent/`

## Separation from Ephemeral Infrastructure

```
infrastructure/
├── permanent/              # NEVER destroyed
│   ├── github-oidc.tf     # GitHub Actions authentication
│   ├── main.tf            # Provider configuration
│   ├── dns.tf             # (Future) Route53 hosted zone
│   ├── acm.tf             # (Future) SSL certificates
│   └── README.md          # This file
│
└── staging/               # Destroyed nightly at 1 AM UTC
    ├── eks.tf             # EKS cluster
    ├── vpc.tf             # Networking
    ├── session-manager.tf # Jumpbox
    ├── flux.tf            # GitOps automation
    └── ...                # All ephemeral resources
```

## Workflow Integration

### Nightly Destroy Workflow
- Runs: `cd infrastructure/staging && terraform destroy`
- **Does NOT touch** `infrastructure/permanent/`
- Schedule: 1 AM UTC daily
- Manual trigger: `gh workflow run nightly-destroy.yml`

### Rebuild Workflow
- Runs: `cd infrastructure/staging && terraform apply`
- **Does NOT touch** `infrastructure/permanent/`
- Manual trigger: `gh workflow run rebuild-stack.yml`

The permanent infrastructure remains available for authentication throughout all destroy/rebuild cycles.

## Cost Analysis

### Current Cost (Deployed Resources)
- **IAM OIDC Provider**: $0.00
- **IAM Role**: $0.00
- **IAM Policy**: $0.00

**Current Total**: $0.00/month

### Future Cost (If All Planned Resources Added)
- **IAM OIDC Provider**: $0.00
- **IAM Role**: $0.00
- **Route53 Hosted Zone**: $0.50/month
- **ACM Certificate**: $0.00

**Future Total**: $0.50/month

### Cost vs Benefit
Even with all future resources, permanent infrastructure costs less than 1% of ephemeral infrastructure (~$88/month when running). The persistent nature prevents manual configuration, reduces rebuild time, and enables automation.

## Security

### Trust Policy
Only workflows from `your-org/infra-fleet` can assume this role.

### Least Privilege
The IAM policy grants only permissions needed for infrastructure management:
- EKS cluster operations
- EC2/VPC management for EKS nodes
- IAM for EKS service roles
- Terraform state access (if using S3/DynamoDB)

### Audit Trail
All role assumptions logged in CloudTrail with:
- Repository information
- Workflow run ID
- Timestamp

## Troubleshooting

### "Role not found" in workflows
- Ensure permanent infrastructure is deployed: `cd infrastructure/permanent && terraform apply`
- Check GitHub secret is configured: `AWS_GITHUB_ACTIONS_ROLE_ARN`
- Verify role exists: `aws iam get-role --role-name GitHubActions-InfraFleet`

### Need to update IAM permissions
```bash
cd infrastructure/permanent
# Edit github-oidc.tf to update IAM policy
terraform plan
terraform apply
```

### Need to verify OIDC configuration
```bash
# Check OIDC provider exists
aws iam list-open-id-connect-providers

# Check role trust policy
aws iam get-role --role-name GitHubActions-InfraFleet --query 'Role.AssumeRolePolicyDocument'

# Check attached policies
aws iam list-attached-role-policies --role-name GitHubActions-InfraFleet
```

## Disaster Recovery

### If Permanent Infrastructure Accidentally Destroyed

**Impact Severity**: 🔴 Critical - All GitHub Actions workflows will fail

**Symptoms**:
- Rebuild workflow fails with "AssumeRole" errors
- Nightly destroy workflow fails (though manual destroy may still work)
- All automation broken until recovery

**Recovery Steps**:

1. **Immediate**: Redeploy permanent infrastructure
   ```bash
   cd infrastructure/permanent
   terraform init
   terraform apply
   ```

2. **Verify**: Check role ARN matches GitHub secret
   ```bash
   terraform output github_actions_role_arn
   gh secret list | grep AWS_GITHUB_ACTIONS_ROLE_ARN
   ```

3. **Update GitHub Secret** (if ARN changed):
   ```bash
   # Get new ARN
   NEW_ARN=$(terraform output -raw github_actions_role_arn)

   # Update secret
   gh secret set AWS_GITHUB_ACTIONS_ROLE_ARN --body "$NEW_ARN"
   ```

4. **Test**: Trigger rebuild workflow
   ```bash
   gh workflow run rebuild-stack.yml
   ```

**Time to Recovery**: ~5-10 minutes

**Data Loss**: None (IAM resources are configuration, not data)

**Prevention**: Never run `terraform destroy` in this directory!

## State Management

### Terraform State
- **Backend**: Local state file (future: consider S3 + DynamoDB)
- **Location**: `infrastructure/permanent/terraform.tfstate`
- **Criticality**: Loss requires redeployment, but state can be recovered via `terraform import`

### Backup Recommendations
1. Commit `terraform.tfstate` to git (if not using remote backend)
2. Or use S3 backend with versioning enabled
3. State is easily reconstructible via Terraform import if lost

## Safeguards

### Current Protections
1. **Workflow Isolation**: GitHub Actions workflows only destroy `infrastructure/staging/`
2. **Manual Review**: All changes to this directory should go through PR review
3. **Documentation**: This README warns against destructive operations

### Recommended Future Enhancements
1. **Terraform Backend**: Use S3 with deletion protection and versioning
2. **State Locking**: Use DynamoDB to prevent concurrent modifications
3. **IAM Restrictions**: Limit who can modify permanent infrastructure
4. **Terraform Cloud**: Consider workspace with deletion protection enabled

---

## Summary

**Current Status**: ✅ Deployed and operational
**Resources**: GitHub OIDC authentication only
**Cost**: $0.00/month
**Maintenance**: None required (update permissions as needed)
**Recovery Time**: <10 minutes if accidentally destroyed
**Next Additions**: DNS + ACM when user decides on HTTPS approach (see ai/DECISIONS-NEEDED.md)
