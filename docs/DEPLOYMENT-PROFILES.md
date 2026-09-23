# Run the fleet with a deployment profile

[Documentation index](README.md) · [Architecture decision](DEPLOYMENT-PROFILES-DDR.md)

Every profile exposes the same three lifecycle phases. `setup` prepares and
validates the target, `up` brings it to a ready state, and `down` removes what
that profile owns. Each phase reports its target before changing anything, is
safe to repeat, and ends either ready or with an actionable failure.

`./fleet` selects `local` or `aws-staging`. Both compose the same application
base and delivery controls. Their bootstrap, registry, networking and policies
are explicit profile resources under `k8s/profiles/` and `k8s/clusters/`.

## Local Kubernetes

Requires Docker, Git, curl, OpenSSL and a supported Linux or macOS amd64/arm64
workstation. `setup` installs checksum-verified kind 0.31.0, kubectl 1.35.0 and
Flux CLI 2.7.5 into checkout-owned state under `.git/fleet/local/bin`; it does
not change system packages. The pinned cluster is Kubernetes 1.35.0; allow
Docker at least 8 GiB of memory. No AWS or GitHub write credentials are needed.
Initial startup downloads controller images and Helm charts. The monitoring
storage is ephemeral.

Commit application or manifest changes before deployment. The local source
serves the committed snapshot through a read-only Git HTTP backend on the kind Docker
network; it does not publish the repository or create a GitHub deploy key.

```bash
./fleet render --profile local   # inspect effective resources; fixtures only
./fleet setup --profile local    # install pinned CLIs and prepare local state
./fleet up --profile local
./fleet status --profile local
./fleet test --profile local
```

In separate terminals, forward only the services you need:

```bash
./fleet access --profile local --service app         # http://localhost:8080/ui/
./fleet access --profile local --service prometheus  # http://localhost:9090
./fleet access --profile local --service grafana     # http://localhost:3000
./fleet credentials --profile local                 # explicitly display login credentials
```

Local application authentication is enabled. Use the application API key to log
in; Grafana's username is `admin`. The bootstrap generates runtime credentials
and retains them across repeated starts. Port forwarding binds to loopback.
The registry binds to `127.0.0.1:5001`; it is intended only for this lab.

After committing a change:

```bash
./fleet sync --profile local
# Or select a full commit SHA already present in this repository:
./fleet sync --profile local --revision FULL_40_CHARACTER_SHA
./fleet down --profile local
```

`sync` builds that exact Git snapshot and updates only the local Git source and
configuration. Flux then reconciles it. It never pushes to GitHub. Runtime state
under `.git/fleet/local` is shared across linked worktrees; teardown retains
the pinned CLI cache, registry data and local credentials. Compose volumes are
separate.

`test` temporarily commits promotion and fault-injection snapshots into the
local-only Git source, verifies outcomes, and restores the deployed source. It
does not commit to the working branch or change the AWS image version.

## AWS staging

Complete [configuration](../CONFIGURATION.md) first. Plan mode reads and
validates the selected AWS, HCP Terraform, and GitHub targets. Apply mode creates
the permanent OIDC/ECR foundation and configures the named repository. Later
commands always pass that repository explicitly to the GitHub CLI.

```bash
./fleet render --profile aws-staging
./fleet setup --profile aws-staging    # validate all targets and plan the OIDC foundation
./fleet setup --profile aws-staging --apply   # apply it and configure GitHub
./fleet up --profile aws-staging       # dispatch rebuild-stack.yml to the configured repo
./fleet status --profile aws-staging
./fleet down --profile aws-staging     # dispatch nightly-destroy.yml
```

AWS creates billable resources. Apply collects required values before the first
mutation, creates a missing `staging` Environment, and preserves protection on
an existing one. Required secret values travel to `gh secret set` over standard
input. Local verification uses fakes and does not provision or destroy AWS.
Existing `terraform-outputs` values are translated into the common
`fleet-config` contract by the AWS profile.

AWS keeps its current NGINX staging preview and related ingress metrics.
Local uses Envoy Gateway and canary application metrics. This local profile does
not certify AWS routing, IAM or production readiness.

## Verification boundary

The local profile has been exercised end to end with a real kind cluster. Its
acceptance suite verifies Flux reconciliation and drift repair, Kyverno
rejections, Calico isolation, Prometheus target discovery, healthy canary
promotion and forced-failure rollback. Operator smoke tests cover application
authentication, the UI, Grafana health and Prometheus.

Pull-request CI renders, schema-checks and policy-checks both profiles without
creating a cluster. Application tests, the container smoke test and the image
scan also remain ordinary PR checks. This is the fast feedback path.

The full local acceptance suite is a deployment workflow rather than a check on
every PR and subsequent `main` push. Dispatch **Local Kubernetes** against the
candidate branch when a group of changes is ready for final review:

```bash
gh workflow run local-kubernetes.yml --ref YOUR_CANDIDATE_BRANCH
```

GitHub binds `GITHUB_SHA` to the branch head at dispatch, checks out that exact
commit and records the job in the `local` GitHub Environment. The cluster is
ephemeral and is removed before the job completes; the deployment record is
evidence of the completed integration cycle, not an endpoint that remains
online. Runs are serialized because the workflow represents one logical target.
A weekly scheduled run applies the same proof to current `main` without delaying
ordinary pull requests.

The AWS profile maps to the existing `staging` GitHub Environment because that
name is part of its OIDC trust boundary. AWS remains limited to static PR
validation until a configured private copy runs the reviewed cloud lifecycle.
Local success is evidence for the shared contracts and local provider; it is not
evidence that AWS resources were created or destroyed successfully.

## Layout and checks

- `k8s/applications/`: shared application base, including hardened Gunicorn
  deployment, HPA, PodMonitor, network policy and canary thresholds.
- `k8s/infrastructure/`: reusable controllers and AWS infrastructure components.
- `k8s/profiles/local/`: local controllers, Gateway API, metrics and registry policy.
- `k8s/profiles/aws-staging/`: AWS configuration adapter, networking and ECR policy.
- `k8s/clusters/`: distinct Flux roots; local cannot reconcile the AWS root.
- `policies/`: common policies; `policies/aws/` supplies ECR restrictions.

Profile rendering is authoritative for Kubernetes CI. Raw base manifests do
not contain the selected image or all provider configuration. The current
advisor reads static files and does not render Kustomize or Helm; interpret its
report with that coverage limitation.
