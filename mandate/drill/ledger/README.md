# Ledger drill (KAN-30 Stage B)

This drill proves the D-20 ledger topology (KAN-4 page 09) on a temporary
ref, `refs/heads/mandate-g0/ledger`, in this repository. It doesn't touch
`main` or its protection.

The drill ref is an orphan: it starts at commit `c328ed1`, which Claude
created and which shares no history with `main`.

Two rulesets protect it, kept separate on purpose:

| Ruleset | Rules | Bypass |
|---|---|---|
| `writer-ruleset.json` | restrict updates, restrict creation | App M (`mandate-fleet-public`, ID 5336871), always |
| `integrity-ruleset.json` | restrict deletion, block force push, require linear history | none |

App M bypasses only the writer rules. Its fast-forward commits still have to
satisfy the integrity rules.

## Steps

**Owner-only steps:** 2 (rulesets), 4 (ordinary-actor probes), 5 (dispatch) and 7 (teardown).

```bash
R=ImranAdan/infra-fleet-public
cd mandate/drill/ledger

# 1. (done by Claude) the drill ref exists
gh api repos/$R/git/ref/heads/mandate-g0/ledger --jq .object.sha

# 2. OWNER: apply both rulesets
gh api -X POST repos/$R/rulesets --input writer-ruleset.json --jq '.id'
gh api -X POST repos/$R/rulesets --input integrity-ruleset.json --jq '.id'

# 3. Read-only topology check; must print PASS (owner session, so bypass actors are visible)
PYTHONPATH=../../src python3 -m mandate.ledger rulesets $R mandate-g0/ledger 5336871

# 4. OWNER: an ordinary actor (you, not a bypass actor) is refused all three. Each must fail with GH013.
git fetch origin mandate-g0/ledger
tip=$(git rev-parse FETCH_HEAD)
probe=$(git commit-tree "$tip^{tree}" -p "$tip" -m "probe: ordinary update")
git push origin "$probe:refs/heads/mandate-g0/ledger"                 # update: refused by the writer ruleset
git push --force origin "$(git commit-tree "$tip^{tree}" -m probe):refs/heads/mandate-g0/ledger"   # force: refused
git push origin --delete mandate-g0/ledger                            # delete: refused

# 5. OWNER: run the App M writer drill (after this PR is on main)
gh workflow run ledger-drill.yml -R $R
gh run watch -R $R "$(gh run list -R $R --workflow ledger-drill.yml --limit 1 --json databaseId --jq '.[0].databaseId')"

# 6. Claude collects the transcript artifact and records the result on KAN-30.

# 7. OWNER teardown, all or nothing (teardown.sh, set -e). It resolves exactly
#    mandate-ledger-writer-drill and mandate-ledger-integrity-drill (each once,
#    each targeting only the drill ref) and deletes them. It deletes the drill
#    ref only after both rulesets are gone. Any failure stops it.
./teardown.sh $R
```

## What the drill shows

| Step | Expected |
|---|---|
| 3 | `PASS  D-20 topology on mandate-g0/ledger` |
| 4 | three GH013 rejections |
| L1 | App M appends a receipt; the entry is printed |
| L2 | an identical retry appends nothing |
| L3 | different bytes at the same revision give `RECEIPT_COLLISION` |
| L4 | of two commits from one parent, the second non-force update is refused |
| L5 | the loser re-reads and appends at the next sequence number |
| L6/L7 | App M's force update and delete are refused by the integrity ruleset |
| L8 | the read-back chain verifies against the head it just wrote |

## Not covered here

- **Merge trailers:** G0 drill D4 (#232) already proved that an App-token merge
  keeps all three `Mandate-*` trailers. The verifier's use of them as anchors
  is covered by `mandate/tests/test_ledger.py`.
- **Owner or bypass rewriting history:** outside the MVP protection boundary,
  and stated as such.
