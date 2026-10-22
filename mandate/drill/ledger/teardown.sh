#!/usr/bin/env bash
# Ledger drill teardown (owner). All or nothing, in order: resolve exactly
# the two drill rulesets, delete them, then delete the drill ref. Any failure
# stops before the next step, so the ref is never deleted while a drill
# ruleset could not be resolved or removed.
set -euo pipefail
repository=${1:?usage: teardown.sh <owner/repo>}
here=$(cd "$(dirname "$0")" && pwd)
ids=$(PYTHONPATH="$here/../../src" python3 -m mandate.ledger drill-rulesets "$repository")
for id in $ids; do
  gh api -X DELETE "repos/$repository/rulesets/$id"
done
git push "https://github.com/$repository.git" --delete mandate-drill/ledger
