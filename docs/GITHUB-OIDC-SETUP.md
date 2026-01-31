# GitHub Actions OIDC Authentication Setup

## Overview

This project uses **OpenID Connect (OIDC)** to authenticate GitHub Actions workflows to AWS. This eliminates the need for long-lived AWS access keys, following AWS security best practices.

## Architecture

```
┌─────────────────────┐
│  GitHub Actions     │
│  Workflow           │
└──────────┬──────────┘
           │
           │ 1. Request OIDC token
           │    (includes repo info)
           ▼
┌─────────────────────┐
│  GitHub OIDC        │
│  Provider           │
└──────────┬──────────┘
           │
           │ 2. Issue signed JWT token
           │
           ▼
┌─────────────────────┐
│  AWS STS            │
│  (AssumeRoleWith    │
│   WebIdentity)      │
└──────────┬──────────┘
           │
           │ 3. Verify token against
           │    OIDC provider
           │
           ▼
┌─────────────────────┐
│  IAM Role           │
│  GitHubActions-     │
│  InfraFleet         │
└──────────┬──────────┘
           │
           │ 4. Return temporary
           │    credentials (valid 1hr)
           │
           ▼
┌─────────────────────┐
│  GitHub Actions     │
│  (authenticated)    │
└─────────────────────┘
```

## Benefits vs. Access Keys

| Feature | OIDC | Access Keys |
|---------|------|-------------|
| **Credential Lifetime** | 1 hour (temporary) | Permanent (until rotated) |
| **Storage Required** | None (just role ARN) | GitHub Secrets |
| **Rotation Needed** | Automatic | Manual |
| **Security** | ⭐⭐⭐⭐⭐ Best practice | ⭐⭐ Requires careful management |
| **Audit Trail** | Role assumption in CloudTrail | Access key usage |
| **Compromise Risk** | Limited (1hr window) | High (until detected) |

## Setup Instructions

### Step 1: Deploy Permanent Infrastructure (One-Time Setup)

The OIDC provider and IAM role are defined in `infrastructure/permanent/github-oidc.tf`.

**⚠️ IMPORTANT**: Deploy this **BEFORE** merging the PR or enabling nightly automation.

**Deploy the OIDC infrastructure:**

```bash
cd infrastructure/permanent
terraform init
terraform plan  # Review what will be created
terraform apply
```

**This infrastructure is PERMANENT and will NEVER be destroyed** by nightly automation.

### Why Separate Permanent Infrastructure?

```
clusters/
├── permanent/              # NEVER destroyed (costs ~$0)
│   └── github-oidc.tf     # GitHub Actions authentication
│
└── staging/               # Destroyed nightly at 2 AM UTC
    ├── eks.tf             # EKS cluster (~$72/month)
    ├── vpc.tf             # NAT Gateway (~$45/month)
    └── ...                # Other ephemeral resources
```

**Problem solved**: Without separation, nightly destruction would delete the OIDC role, preventing rebuild workflows from authenticating the next day (chicken-and-egg problem).

**With separation**: OIDC always exists, workflows always work, zero manual intervention needed.

This creates:
- ✅ AWS IAM OIDC Provider for GitHub
- ✅ IAM Role `GitHubActions-InfraFleet`
- ✅ IAM Policy with required permissions
- ✅ Trust relationship allowing your repository

**Expected output:**
```
github_actions_role_arn = "arn:aws:iam::123456789012:role/GitHubActions-InfraFleet"
github_oidc_provider_arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
```

### Step 2: Configure GitHub Secret

You only need **ONE** secret in GitHub (the role ARN):

1. Go to: https://github.com/your-org/infra-fleet/settings/secrets/actions
2. Click "New repository secret"
3. Add:
   - **Name**: `AWS_GITHUB_ACTIONS_ROLE_ARN`
   - **Value**: Copy the `github_actions_role_arn` output from Terraform

**That's it!** No AWS access keys needed.

### Step 3: Verify OIDC Setup (Recommended)

After deploying the permanent infrastructure and configuring the GitHub secret, verify everything is working:

**Verify AWS Resources:**

```bash
# Check OIDC provider exists
aws iam list-open-id-connect-providers --query 'OpenIDConnectProviderList[?contains(Arn, `token.actions.githubusercontent.com`)]'

# Check IAM role exists
aws iam get-role --role-name GitHubActions-InfraFleet

# Check trust policy is correct
aws iam get-role --role-name GitHubActions-InfraFleet --query 'Role.AssumeRolePolicyDocument.Statement[0].Condition'

# Check policy is attached
aws iam list-attached-role-policies --role-name GitHubActions-InfraFleet
```

**Expected Results:**
```
✅ OIDC Provider: arn:aws:iam::YOUR_ACCOUNT:oidc-provider/token.actions.githubusercontent.com
✅ IAM Role: GitHubActions-InfraFleet
✅ Trust Policy: Restricts to repo:your-org/infra-fleet:*
✅ Policy Attached: GitHubActions-InfraFleet-Policy
```

**Verify GitHub Secret:**

```bash
# List repository secrets
gh secret list

# Should show:
# AWS_GITHUB_ACTIONS_ROLE_ARN    <timestamp>
```

**Verification Checklist:**
- [ ] OIDC provider exists in AWS
- [ ] IAM role `GitHubActions-InfraFleet` exists
- [ ] Trust policy restricts to your repository
- [ ] IAM policy is attached to role
- [ ] GitHub secret `AWS_GITHUB_ACTIONS_ROLE_ARN` is configured
- [ ] Role ARN matches between AWS and GitHub secret

If all checks pass, your OIDC authentication is ready! ✅

### Step 4: Review Workflows

The workflows are already configured to use OIDC:

**`.github/workflows/nightly-destroy.yml`:**
```yaml
permissions:
  id-token: write   # Required for OIDC
  contents: read

steps:
  - name: Configure AWS credentials via OIDC
    uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: ${{ secrets.AWS_GITHUB_ACTIONS_ROLE_ARN }}
      role-session-name: GitHubActions-NightlyDestroy-${{ github.run_id }}
      aws-region: eu-west-2
```

## Security Features

### Repository Restriction

The IAM role trust policy restricts access to your specific repository:

```json
"Condition": {
  "StringLike": {
    "token.actions.githubusercontent.com:sub": "repo:your-org/infra-fleet:*"
  }
}
```

This means:
- ✅ Only workflows from `your-org/infra-fleet` can assume the role
- ❌ Other repositories cannot use this role
- ❌ Even if someone gets the role ARN, they can't use it from another repo

### Session Naming

Each workflow run has a unique session name:
```
GitHubActions-NightlyDestroy-123456789
```

This appears in CloudTrail for audit purposes:
- Who: `GitHubActions-InfraFleet`
- What: `AssumeRoleWithWebIdentity`
- When: Timestamp
- Context: Workflow run ID

### Temporary Credentials

Credentials expire after 1 hour:
- Can't be reused after workflow completes
- Automatically invalidated
- No cleanup required

## IAM Permissions

The role has permissions to manage:

- **EKS**: Full cluster management
- **EC2**: VPC, instances, security groups (for EKS nodes)
- **IAM**: Create/manage service roles for EKS
- **Auto Scaling**: For EKS node groups
- **CloudWatch Logs**: For EKS logging
- **SSM**: For Session Manager jumpbox
- **S3/DynamoDB**: For Terraform state (if used)

**Least Privilege**: Permissions are scoped to infrastructure management only.

## Troubleshooting

### Error: "Not authorized to perform sts:AssumeRoleWithWebIdentity"

**Cause**: OIDC provider not created or trust policy misconfigured

**Solution**:
```bash
cd clusters/staging
terraform apply  # Ensure OIDC provider exists
```

### Error: "No OIDC provider found"

**Cause**: OIDC provider wasn't created in AWS

**Solution**:
1. Check AWS IAM Console → Identity providers
2. Should see: `token.actions.githubusercontent.com`
3. If missing, run `terraform apply` in `clusters/staging`

### Error: "Access denied" during workflow

**Cause**: IAM role doesn't have required permissions

**Solution**:
1. Check CloudTrail for specific denied action
2. Update IAM policy in `github-oidc.tf`
3. Run `terraform apply`

### Error: "GitHub secret not found"

**Cause**: `AWS_GITHUB_ACTIONS_ROLE_ARN` secret not configured

**Solution**:
1. Get role ARN: `terraform output github_actions_role_arn`
2. Add secret to GitHub repository settings
3. Re-run workflow

## Testing OIDC Authentication

### Test with Workflow

1. Manually trigger the rebuild workflow:
   ```bash
   gh workflow run rebuild-stack.yml
   ```

2. Check workflow logs for successful authentication:
   ```
   ✅ Configure AWS credentials via OIDC
   ```

3. Verify in CloudTrail:
   - Event: `AssumeRoleWithWebIdentity`
   - User: `GitHubActions-InfraFleet`
   - Source: `token.actions.githubusercontent.com`

### Test Locally (Limited)

**Note**: OIDC authentication cannot be fully tested with `act` locally because:
- `act` doesn't have access to GitHub's OIDC provider
- OIDC tokens are GitHub-specific

For local testing, you can still use access keys with `act` via `.secrets` file.

## Maintenance

### No Maintenance Required! 🎉

With OIDC:
- ✅ No key rotation needed
- ✅ No expiration warnings
- ✅ No secret management
- ✅ Automatically secure

### Optional: Monitor Usage

Monitor role usage in CloudTrail:
```bash
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=GitHubActions-InfraFleet \
  --max-results 10
```

## Comparison: Before & After

### Before (Access Keys)
```yaml
steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}      # ❌ Long-lived
      aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }} # ❌ Permanent
      aws-region: eu-west-2
```

**Required Secrets**: 2
**Security Risk**: High (permanent credentials)
**Maintenance**: Manual rotation needed

### After (OIDC)
```yaml
permissions:
  id-token: write

steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: ${{ secrets.AWS_GITHUB_ACTIONS_ROLE_ARN }} # ✅ Just role ARN
      role-session-name: GitHubActions-${{ github.run_id }}
      aws-region: eu-west-2
```

**Required Secrets**: 1 (just the role ARN)
**Security Risk**: Minimal (temporary, scoped credentials)
**Maintenance**: None

## Troubleshooting

### Common Issues During Initial Testing

#### Permission Errors During Terraform Apply

**Symptom**: Workflow fails with "not authorized to perform: [action]" errors

**Cause**: IAM policy missing required permissions for EKS infrastructure

**Solution**: Update IAM policy in `infrastructure/permanent/github-oidc.tf` and apply:
```bash
cd infrastructure/permanent
terraform apply
```

**Common Missing Permissions for EKS**:
- `iam:ListRolePolicies`, `GetRolePolicy`, `PutRolePolicy`, `DeleteRolePolicy`
- `iam:CreateOpenIDConnectProvider` (for EKS pod identity OIDC)
- `kms:ListAliases`, `kms:ListKeys` (critical for KMS key management)
- `logs:ListTagsForResource`, `logs:TagResource` (for log group management)

#### Orphaned Resources from Failed Runs

**Symptom**: "EntityAlreadyExists" or "ResourceAlreadyExists" errors

**Cause**: Previous failed Terraform run left partial resources

**Solution**: Clean up orphaned resources before retrying:
```bash
# Delete IAM roles (remove policies/instance profiles first)
aws iam delete-role --role-name <role-name>

# Delete CloudWatch log groups
aws logs delete-log-group --log-group-name <log-group-name> --region eu-west-2

# Delete KMS keys (schedules deletion, 7-day wait)
aws kms schedule-key-deletion --key-id <key-id> --pending-window-in-days 7 --region eu-west-2

# Delete OIDC providers
aws iam delete-open-id-connect-provider --open-id-connect-provider-arn <arn>
```

#### Two OIDC Providers - Don't Get Confused!

**Important**: This setup uses TWO different OIDC providers:

1. **GitHub OIDC** (permanent, in `infrastructure/permanent/`):
   - Provider: `token.actions.githubusercontent.com`
   - Purpose: GitHub Actions authenticates to AWS
   - IAM Role: `GitHubActions-InfraFleet`
   - Never destroyed

2. **EKS OIDC** (ephemeral, created by terraform-aws-modules/eks):
   - Provider: `oidc.eks.{region}.amazonaws.com/id/{cluster-id}`
   - Purpose: Kubernetes pods authenticate to AWS (IRSA - IAM Roles for Service Accounts)
   - Destroyed nightly with cluster
   - Recreated on rebuild

Don't delete the GitHub OIDC provider - it's permanent infrastructure!

### Permission Discovery Strategy

**Educational Approach** (used in this project):
- Start with minimal permissions
- Add permissions as errors occur
- Understand exactly what each permission does
- ⚠️ Requires multiple iterations

**Production Approach** (recommended):
1. Start with broad permissions (e.g., `PowerUserAccess` + specific IAM permissions)
2. Deploy successfully
3. Enable CloudTrail logging
4. Review CloudTrail to see which permissions were actually used
5. Create least-privilege policy based on actual usage
6. Test with restricted policy
7. Document final permission set

**Quick Start Approach**:
- Use the complete permission set documented in `infrastructure/permanent/github-oidc.tf`
- This includes all permissions discovered during testing
- Suitable for terraform-aws-modules/eks deployments

## Additional Resources

- [AWS Blog: OIDC for GitHub Actions](https://aws.amazon.com/blogs/security/use-iam-roles-to-connect-github-actions-to-actions-in-aws/)
- [GitHub Docs: OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [aws-actions/configure-aws-credentials](https://github.com/aws-actions/configure-aws-credentials)
- [Terraform AWS EKS Module](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest)

## Lessons Learned (2025-11-19 Testing)

### Critical Permissions Often Missed

These permissions are frequently overlooked but critical for EKS deployment:

1. **`iam:ListRolePolicies`**: Terraform reads inline policies to manage state
2. **`kms:ListAliases`**: Terraform verifies KMS alias existence before creation
3. **`logs:ListTagsForResource`**: Terraform manages CloudWatch log group tags
4. **`iam:CreateOpenIDConnectProvider`**: Required for EKS pod identity (IRSA)

### Testing Recommendations

1. **Test in Non-Production First**: Use a separate AWS account or isolated environment
2. **Monitor CloudTrail**: Enable detailed logging during first deployment
3. **Expect Iterations**: First-time OIDC setup typically requires 2-4 permission adjustments
4. **Document Changes**: Track which permissions were added and why
5. **Clean Up Orphaned Resources**: Failed runs leave partial infrastructure

### Performance Notes

- **Terraform Apply Time**: ~25-30 minutes for full EKS cluster
- **Permission Updates**: Take effect immediately (no waiting)
- **Orphaned Resource Cleanup**: 1-2 minutes
- **Total Testing Time**: ~2-3 hours (including 4 rebuild attempts)

---

**Last Updated**: 2025-11-19
**Managed By**: Terraform (`infrastructure/permanent/github-oidc.tf`)
**Security Level**: ⭐⭐⭐⭐⭐ Best Practice
**Status**: Production-ready with comprehensive permissions
