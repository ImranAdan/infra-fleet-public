# EKS access

The supported deployment is the `staging` cluster in `eu-west-2`.

Its Kubernetes API endpoint is public because GitHub-hosted runner addresses
are ephemeral. The endpoint also has private access enabled. A public network
path is not authentication: callers still need an allowed AWS IAM identity and
an EKS access entry. This is a learning-stack trade-off, not a production
network posture.

## Identities created by Terraform

The permanent `GitHubActions-InfraFleet` role is granted EKS cluster-admin so
the deployment, verification, and teardown workflows can operate the cluster.

No adopter-specific IAM user is hard-coded. To grant an operator access, set
the repository variable and matching Terraform value to a JSON array of IAM
role or user ARNs:

```dotenv
EKS_ADMIN_PRINCIPAL_ARNS_JSON='["arn:aws:iam::123456789012:role/PlatformOperator"]'
```

Prefer an IAM Identity Center role. Because access entries are created during
the staging apply, configure this value before the first rebuild.

## Connect as an operator

Authenticate to AWS as one of the configured principals, then run:

```bash
aws sts get-caller-identity
aws eks update-kubeconfig --name staging --region eu-west-2
kubectl auth can-i get pods --all-namespaces
kubectl get nodes
```

If `kubectl` reports `Unauthorized`, compare the ARN from
`aws sts get-caller-identity` with `EKS_ADMIN_PRINCIPAL_ARNS_JSON`, apply the
staging workspace through the supported workflow, and retry.

The disabled Session Manager jumpbox files are historical reference only; the
template does not deploy a jumpbox.
