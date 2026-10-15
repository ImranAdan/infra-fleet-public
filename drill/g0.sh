#!/usr/bin/env bash
# KAN-20 G0 drill runner for ImranAdan/infra-fleet-public, branch mandate-g0/main.
# Usage: APP_ID=<numeric app id> drill/g0.sh <preflight|ruleset VARIANT|run|cleanup>
# Every step appends command, exit code and output to $EVIDENCE.
set -uo pipefail

REPO=ImranAdan/infra-fleet-public
BASE=mandate-g0/main
HERE=$(cd "$(dirname "$0")" && pwd)
EVIDENCE=${EVIDENCE:-$HERE/evidence-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$EVIDENCE"
SUMMARY=$EVIDENCE/summary.md

log() { printf '%s\n' "$*" | tee -a "$EVIDENCE/log.txt"; }
step() { # step NAME CMD... : run and record, return the command's exit code
  local name=$1; shift
  { echo "### $name"; echo "\$ $*"; } >> "$EVIDENCE/log.txt"
  "$@" >> "$EVIDENCE/log.txt" 2>&1; local rc=$?
  echo "exit=$rc" >> "$EVIDENCE/log.txt"; return $rc
}
expect() { # expect ID WANT(pass|fail) RC DESCRIPTION
  local got=fail; [ "$3" -eq 0 ] && got=pass
  local verdict=PASS; [ "$got" = "$2" ] || verdict=REVISE
  echo "| $1 | $4 | expected $2, got $got | **$verdict** |" >> "$SUMMARY"
  log "$1 $verdict ($4)"
}

ruleset_id() { gh api "repos/$REPO/rulesets" -q '.[]|select(.name=="mandate-g0-drill").id'; }

ruleset() { # ruleset VARIANT : base | bypass-owner | bypass-owner-exempt | app-only | disabled
  : "${APP_ID:?set APP_ID to the numeric ID of the Mandate test App}"
  local body
  body=$(sed "s/\"__APP_ID__\"/$APP_ID/" "$HERE/ruleset.template.json")
  case $1 in
    base) ;;
    bypass-owner)        body=$(jq '.bypass_actors=[{"actor_type":"RepositoryRole","actor_id":5,"bypass_mode":"pull_request"}]' <<<"$body") ;;
    bypass-owner-exempt) body=$(jq '.bypass_actors=[{"actor_type":"RepositoryRole","actor_id":5,"bypass_mode":"exempt"}]' <<<"$body") ;;
    app-only)            body=$(jq --argjson app "$APP_ID" '.rules+=[{"type":"update"}] | .bypass_actors=[{"actor_type":"Integration","actor_id":$app,"bypass_mode":"always"}]' <<<"$body") ;;
    disabled)            body=$(jq '.enforcement="disabled"' <<<"$body") ;;
    *) echo "unknown variant $1" >&2; return 2 ;;
  esac
  local id; id=$(ruleset_id)
  if [ -n "$id" ]; then
    step "ruleset:$1" gh api -X PUT "repos/$REPO/rulesets/$id" --input - <<<"$body"
  else
    step "ruleset:$1" gh api -X POST "repos/$REPO/rulesets" --input - <<<"$body"
  fi
  gh api "repos/$REPO/rulesets/$(ruleset_id)" > "$EVIDENCE/ruleset-$1.json"
}

new_pr() { # new_pr NAME [forge] -> prints PR number
  local br="mandate-g0/drill-$1-$(date +%s)" tmp; tmp=$(mktemp -d)
  git clone -q --depth 1 --branch "$BASE" "https://github.com/$REPO.git" "$tmp"
  git -C "$tmp" switch -q -c "$br"
  date -u > "$tmp/drill-$1.txt"
  if [ "${2:-}" = forge ]; then
    mkdir -p "$tmp/.github/workflows"
    cat > "$tmp/.github/workflows/g0-forge.yml" <<'YML'
name: G0 forge
on: { pull_request: { branches: ["mandate-g0/**"] } }
permissions: { checks: write }
jobs:
  forge:
    runs-on: ubuntu-latest
    steps:
      - env: { GH_TOKEN: "${{ github.token }}", SHA: "${{ github.event.pull_request.head.sha }}" }
        run: gh api "repos/$GITHUB_REPOSITORY/check-runs" -f name=mandate/decision -f head_sha="$SHA" -f status=completed -f conclusion=success
YML
  fi
  git -C "$tmp" add -A && git -C "$tmp" commit -qm "G0 drill $1" && git -C "$tmp" push -q origin "$br"
  gh pr create -R "$REPO" -B "$BASE" -H "$br" -t "G0 drill: $1" -b "KAN-20 G0 drill PR. Not for main." | grep -oE '[0-9]+$'
}

wait_decision() { # wait_decision PR CONCLUSION : until the App's check shows it (5 min max)
  local sha; sha=$(gh pr view "$1" -R "$REPO" --json headRefOid -q .headRefOid)
  for _ in $(seq 60); do
    gh api "repos/$REPO/commits/$sha/check-runs?check_name=mandate/decision" \
      -q ".check_runs[]|select(.app.id==$APP_ID)|.conclusion" | grep -qx "$2" && return 0
    sleep 5
  done; return 1
}

merged_sha() { gh pr view "$1" -R "$REPO" --json mergeCommit -q '.mergeCommit.oid // empty'; }

wait_merged() { for _ in $(seq 60); do [ -n "$(merged_sha "$1")" ] && return 0; sleep 5; done; return 1; }

observer_ran() { # observer_ran SHA : did the push observer run on that SHA (wait 2 min)
  for _ in $(seq 24); do
    gh run list -R "$REPO" -w "G0 push observer" --json headSha -q '.[].headSha' | grep -qx "$1" && return 0
    sleep 5
  done; return 1
}

run() {
  : "${APP_ID:?set APP_ID}"
  printf '# G0 evidence %s\n\nRepo `%s`, branch `%s`, App ID `%s`\n\n| ID | Drill | Result | Verdict |\n|---|---|---|---|\n' \
    "$(date -u +%FT%TZ)" "$REPO" "$BASE" "$APP_ID" > "$SUMMARY"
  ruleset base

  p=$(new_pr no-decision);       wait_decision "$p" failure
  step "D1 merge without decision" gh pr merge "$p" -R "$REPO" --merge; expect D1 fail $? "Ordinary actor cannot merge without the App's decision"

  p=$(new_pr forged forge);      sleep 60
  step "D2 checks on head" gh api "repos/$REPO/commits/$(gh pr view "$p" -R "$REPO" --json headRefOid -q .headRefOid)/check-runs?check_name=mandate/decision" -q '.check_runs[]|{app:.app.slug,conclusion}'
  step "D2 merge with forged same-name check" gh pr merge "$p" -R "$REPO" --merge; expect D2/P-1 fail $? "Same-name check from github-actions does not satisfy the App-bound rule"

  p=$(new_pr authorized-other);  gh pr edit "$p" -R "$REPO" --add-label g0-authorize >/dev/null; wait_decision "$p" success
  step "D3 non-App actor merges after decision" gh pr merge "$p" -R "$REPO" --merge; expect D3 pass $? "After a valid decision, a non-bypass actor CAN execute the merge (D-4: record the executor)"

  p=$(new_pr app-merge);         gh pr edit "$p" -R "$REPO" --add-label g0-authorize >/dev/null; wait_decision "$p" success
  gh pr edit "$p" -R "$REPO" --add-label g0-merge >/dev/null
  wait_merged "$p"; expect D4a pass $? "App-token exact-head merge succeeded"
  m=$(merged_sha "$p")
  step "D4 trailers" gh api "repos/$REPO/commits/$m" -q .commit.message
  gh api "repos/$REPO/commits/$m" -q .commit.message | grep -c '^Mandate-\(Decision\|Receipt-Digest\|Chain-Head\): sha256:' | grep -qx 3; expect D4b/KAN-30 pass $? "All three Mandate trailers persisted on the merge commit"
  observer_ran "$m"; expect D4c/E-2 pass $? "App-token merge started the push-triggered workflow"

  p=$(new_pr token-merge);       gh pr edit "$p" -R "$REPO" --add-label g0-authorize >/dev/null; wait_decision "$p" success
  gh pr edit "$p" -R "$REPO" --add-label g0-merge-ghtoken >/dev/null
  wait_merged "$p"; m=$(merged_sha "$p")
  observer_ran "$m"; expect D5/E-2-control fail $? "GITHUB_TOKEN merge did NOT start the push workflow"

  ruleset bypass-owner
  p=$(new_pr break-glass);       wait_decision "$p" failure
  step "D7 owner break-glass" gh pr merge "$p" -R "$REPO" --merge --admin; expect D7a pass $? "Owner bypass (pull_request mode) can merge without decision"
  step "D7 rule suites" gh api "repos/$REPO/rulesets/rule-suites?ref=refs/heads/$BASE" -q '.[0:5][]|{actor_name,result,evaluation_result,pushed_at}'
  gh api "repos/$REPO/rulesets/rule-suites?ref=refs/heads/$BASE" -q '.[].result' | grep -qx bypass; expect D7b/P-8 pass $? "Break-glass is visible as bypass in rule-suite history"

  ruleset bypass-owner-exempt
  p=$(new_pr exempt);            wait_decision "$p" failure
  before=$(gh api "repos/$REPO/rulesets/rule-suites?ref=refs/heads/$BASE" -q 'length')
  step "D8 exempt merge" gh pr merge "$p" -R "$REPO" --merge --admin
  after=$(gh api "repos/$REPO/rulesets/rule-suites?ref=refs/heads/$BASE" -q 'length')
  [ "$before" = "$after" ]; expect D8/A-26 pass $? "Exempt actor leaves no rule-suite entry (why exempt is banned)"

  ruleset app-only
  p=$(new_pr app-only-undecided); wait_decision "$p" failure
  gh pr edit "$p" -R "$REPO" --add-label g0-merge >/dev/null
  if wait_merged "$p"; then r="MERGED: App bypass skips its own required check, so App-only via bypass is an UNSAFE topology (keep App non-bypass; D-4)"; else r="NOT MERGED: bypass did not skip the required check"; fi
  echo "| D9a/P-12 | App as bypass actor vs. its own required check | $r | **OBSERVED** |" >> "$SUMMARY"; log "D9a $r"
  p=$(new_pr app-only-other);    gh pr edit "$p" -R "$REPO" --add-label g0-authorize >/dev/null; wait_decision "$p" success
  step "D9 non-App merge under restrict-updates" gh pr merge "$p" -R "$REPO" --merge; expect D9b fail $? "Restrict-updates blocks non-bypass executors"

  ruleset disabled
  [ "$(gh api "repos/$REPO/rulesets/$(ruleset_id)" -q .enforcement)" = disabled ]; expect D10 pass $? "Ruleset disablement is observable via the API"
  ruleset base
  log "Done. Summary: $SUMMARY. Owner still runs D6 (force-push/delete) by hand; see README."
}

preflight() {
  local ok=0
  gh api "repos/$REPO/branches/$BASE" -q .name >/dev/null 2>&1 && log "branch $BASE: present" || { log "branch $BASE: MISSING"; ok=1; }
  for s in RELEASE_PLEASE_APP_CLIENT_ID RELEASE_PLEASE_APP_PRIVATE_KEY; do
    gh secret list -R "$REPO" --json name -q '.[].name' | grep -qx "$s" && log "secret $s: present" || { log "secret $s: MISSING (owner)"; ok=1; }
  done
  for l in g0-authorize g0-merge g0-merge-ghtoken; do
    gh label create "$l" -R "$REPO" -c 5319e7 -d "KAN-20 G0 drill" >/dev/null 2>&1 || true
  done
  [ -n "${APP_ID:-}" ] && log "APP_ID: $APP_ID" || { log "APP_ID: unset (owner supplies the numeric App ID)"; ok=1; }
  return $ok
}

cleanup() {
  local id; id=$(ruleset_id); [ -n "$id" ] && step cleanup-ruleset gh api -X DELETE "repos/$REPO/rulesets/$id"
  for pr in $(gh pr list -R "$REPO" -B "$BASE" --state open --json number -q '.[].number'); do gh pr close "$pr" -R "$REPO" --delete-branch; done
  log "Branch $BASE itself is deleted by the owner: git push origin --delete $BASE"
}

case ${1:-} in
  preflight) preflight ;;
  ruleset) ruleset "${2:?variant}" ;;
  run) run ;;
  cleanup) cleanup ;;
  *) sed -n '2,4p' "$0"; exit 2 ;;
esac
