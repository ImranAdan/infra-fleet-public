# AWS Cost Controls

The local profile uses the workstation's Docker and kind resources. The AWS
staging profile creates billable resources in the adopter's account. Prices
change by region and over time, so this guide describes the resource model and
controls rather than publishing a monthly estimate.

Use the [AWS Pricing Calculator](https://calculator.aws/) before deployment and
AWS Cost Explorer after deployment. Configure an account budget and billing
alerts independently of this repository.

## Resource lifetime

The AWS profile has two Terraform stacks with different lifetimes.

| Stack | Resources | Lifetime |
|---|---|---|
| `infrastructure/permanent` | GitHub OIDC/IAM foundation and the application ECR repository | Kept across staging rebuilds |
| `infrastructure/staging` | VPC, EKS, worker group, NAT gateway, public load balancer support, controller IAM and related resources | Exists until explicitly destroyed |

The permanent ECR repository keeps at most ten images through its lifecycle
policy. Staging resources carry `Environment`, `Service` and `Owner` cost
allocation tags where AWS supports them.

## Costs while staging exists

The main cost-bearing resources are:

- the EKS control plane;
- a single NAT gateway and its data processing;
- an internet-facing Network Load Balancer provisioned for Envoy Gateway;
- up to three `t3.large` Spot workers and their storage;
- public IPv4 addresses, CloudWatch logs and data transfer; and
- ECR image storage and transfer in the permanent stack.

Spot capacity and scheduled worker release reduce compute usage. They do not
stop control-plane, NAT gateway, load-balancer, address, log or storage charges.

## Worker usage window

Terraform installs two Auto Scaling scheduled actions:

| Time (`Europe/London`) | Weekdays | Result |
|---|---|---|
| 08:00 | Monday to Friday | Restore one worker; allow scaling to three |
| 20:00 | Monday to Friday | Release every worker |

The defaults live in `infrastructure/staging/variables.tf` as
`usage_window_start`, `usage_window_stop` and `usage_window_time_zone`. A worker
release leaves the EKS control plane and networking in place. Workloads return
when the next worker starts and Flux reconciles them. Inside the window,
cluster-autoscaler (`k8s/infrastructure/cluster-autoscaler/`, IAM in
`infrastructure/staging/cluster-autoscaler.tf`) adds workers up to three when
pods are pending and removes idle ones.

To work outside the window, change the Auto Scaling group temporarily. The next
scheduled action still applies:

```bash
aws autoscaling update-auto-scaling-group \
  --auto-scaling-group-name "$(aws autoscaling describe-auto-scaling-groups \
    --filters Name=tag-key,Values=k8s.io/cluster-autoscaler/staging \
    --query 'AutoScalingGroups[0].AutoScalingGroupName' --output text)" \
  --min-size 1 --desired-capacity 1
```

## Stop all staging charges

Destroy staging when it will not be used. From an onboarded clone:

```bash
./fleet down --profile aws-staging
```

The command names the target repository and environment, requires the exact
confirmation `destroy staging`, and dispatches the teardown workflow from the
configured deployment branch. The workflow removes Kubernetes-managed AWS
resources before destroying the staging Terraform stack, then checks for
leftovers. It retains the permanent OIDC/IAM and ECR foundation.

For non-interactive operation, the caller must provide the same confirmation
explicitly:

```bash
FLEET_CONFIRM_DESTROY='destroy staging' ./fleet down --profile aws-staging
```

There is no implicit nightly stack destroy. The weekday schedule stops workers;
only the explicit teardown removes the control plane and network resources.

## Audit the account

The inventory script reports relevant resources in a region without embedding
price assumptions:

```bash
./scripts/audit-ec2-costs.sh eu-west-2 staging
```

Review the output for resources that outlive their expected stack, especially
load balancers, NAT gateways, unattached volumes, Elastic IP addresses and
network interfaces. The script is an inventory aid; verify ownership by tags
before deleting anything.

Use AWS billing tools for the amount charged. Filter by the cost allocation
tags where available:

- `Service=infra-fleet`
- `Environment=staging` or `Environment=shared`
- `Owner=<configured cost_owner>`

## Cost review checklist

Before `./fleet up --profile aws-staging`:

- estimate the current regional resource prices;
- confirm billing alerts and a budget exist in the target account;
- confirm the selected `cost_owner` tag identifies the adopter; and
- decide when the staging stack will be destroyed.

While it is running:

- watch Spot interruptions and pending pods before changing node capacity;
- keep the worker usage window aligned with actual working hours;
- avoid retaining application data in an ephemeral staging cluster; and
- use Cost Explorer to investigate unexpected service or region usage.

After teardown:

- confirm the destroy workflow's final verification passed;
- run the inventory script if any cleanup phase warned or failed; and
- inspect the permanent ECR repository separately, because teardown preserves
  it by design.
