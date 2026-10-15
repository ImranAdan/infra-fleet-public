# mandate-g0 — KAN-20 G0 drill branch

This orphan branch exists only to prove GitHub provider behaviour for
[KAN-20](https://project-mandate.atlassian.net/browse/KAN-20) (gate G0) and
[KAN-30](https://project-mandate.atlassian.net/browse/KAN-30). It shares no
history with `main`. Fleet's own workflows do not exist here, so they never run
on drill PRs. The ruleset targets only `refs/heads/mandate-g0/main`, so Fleet's
`main` protection is untouched.

## Owner steps (one sitting)

1. **Create a GitHub App** (Settings → Developer settings → GitHub Apps → New).
   No webhook. Repository permissions: **Contents: write**, **Checks: write**,
   **Pull requests: write**, Metadata: read. This App is also the repo-only
   merge App that Fleet #191 needs, so G0 tests the App that will merge for real.
2. **Generate a private key.** Store it and the App's Client ID as Fleet repository
   secrets `RELEASE_PLEASE_APP_PRIVATE_KEY` and `RELEASE_PLEASE_APP_CLIENT_ID`
   (the names #191 expects). Don't paste the key anywhere else.
3. **Install the App on `infra-fleet-public` only.**
4. Tell the agent the App's **numeric App ID**, which is not secret.
5. Let the agent manage rulesets **only** for `refs/heads/mandate-g0/**`, or run
   `drill/g0.sh ruleset <variant>` yourself when prompted.
6. **D6, by hand.** The agent's permission classifier blocks these. Both must be **rejected**:
   ```
   git push --force origin HEAD~1:mandate-g0/main
   git push origin --delete mandate-g0/main
   ```

## Agent steps

```
APP_ID=<id> drill/g0.sh preflight   # branch, secrets, labels
APP_ID=<id> drill/g0.sh run         # D1–D10, writes drill/evidence-*/summary.md
APP_ID=<id> drill/g0.sh cleanup     # removes ruleset and drill PRs
```

| Drill | Proves |
|---|---|
| D1 | Ordinary actor cannot merge without the App's `mandate/decision` (E-1 core) |
| D2 | Same-name check from `github-actions` does not satisfy the rule (P-1) |
| D3 | After a decision, a non-App actor *can* merge (D-4: record the executor) |
| D4 | App-token exact-head merge persists three `Mandate-*` trailers (KAN-30) and starts the push workflow (E-2) |
| D5 | Control: a `GITHUB_TOKEN` merge does not start the push workflow |
| D6 | Force-push and deletion rejected (owner runs) |
| D7 | Owner break-glass is visible as `bypass` in rule suites (P-8, provider side of A-23) |
| D8 | `exempt` leaves no rule-suite entry (A-26: why it's banned) |
| D9 | Whether making the App a bypass actor skips its own check (P-12) |
| D10 | Ruleset disablement is observable |

## Cleanup

`drill/g0.sh cleanup`, then the owner deletes this branch. The App stays because #191 needs it.
