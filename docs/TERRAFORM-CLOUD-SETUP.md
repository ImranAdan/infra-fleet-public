# HCP Terraform setup

HCP Terraform is the state backend for both stacks. The supplied workflows use
**Local execution**: HCP stores and locks state, while Terraform and AWS calls
run on the operator's machine or a GitHub-hosted runner.

For the end-to-end adoption sequence, start with
[../CONFIGURATION.md](../CONFIGURATION.md).

## Workspaces

Create two CLI-driven workspaces in one HCP Terraform organisation:

| Workspace | Configuration directory | Lifecycle |
|---|---|---|
| `infra-fleet-permanent` | `infrastructure/permanent` | retained |
| `infra-fleet-staging` | `infrastructure/staging` | rebuilt and destroyed on demand |

In each workspace, open **Settings → General** and choose **Local** execution.
Do not choose Remote execution: the repository authenticates AWS on the GitHub
runner, and a remote HCP worker would not receive that identity.

Alternative workspace names are supported through the
`TF_WORKSPACE_PERMANENT` and `TF_WORKSPACE_STAGING` GitHub variables and the
matching values in `config.env`.

## Authentication

Run `terraform login` before the one-time local bootstrap. Store the resulting
HCP token only in Terraform's local credentials file.

For GitHub Actions, create a user or team API token with access to both
workspaces and store it as the `TF_API_TOKEN` repository secret. Store the
organisation name as `TF_CLOUD_ORGANIZATION`.

AWS authentication is separate:

- the initial permanent apply uses the operator's local AWS credentials;
- later workflows use GitHub OIDC and `AWS_GITHUB_ACTIONS_ROLE_ARN`; and
- HCP Terraform itself receives no AWS keys or OIDC role because it does not
  execute runs.

Never add long-lived AWS access keys to HCP Terraform or GitHub to work around
a setup failure.

## How the empty cloud block is bound

Both Terraform roots contain an empty `cloud {}` block. Terraform resolves it
before input variables, so workflows and the bootstrap script provide:

```text
TF_CLOUD_ORGANIZATION=<organisation>
TF_WORKSPACE=<workspace>
```

This keeps adopter-specific HCP names out of committed Terraform.

## Troubleshooting

- **Organisation or workspace requested during init:** confirm both environment
  variables are present and the token can access the workspace.
- **A remote run starts:** change the workspace execution mode to Local.
- **State lock remains after interruption:** inspect the run in HCP Terraform
  and force-unlock only after confirming no operation is active.
- **AWS credentials unavailable:** for bootstrap, check
  `aws sts get-caller-identity`; in Actions, check the OIDC role secret and the
  exact repository/environment trust configured by the permanent stack.
