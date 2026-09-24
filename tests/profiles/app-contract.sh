#!/usr/bin/env bash
# The fleet runs whichever app k8s/fleet-app selects, and names none itself.
# Checks the selected contract, then proves every app can be selected: each is
# swapped in on a scratch worktree and both profiles must render completely.
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"
fail() { echo "app contract: $*" >&2; exit 1; }
value() { awk -v key="$1" '$1 == key":" { sub(/^[^:]*:[ \t]*/, ""); gsub(/^"|"$/, ""); print; exit }' "$2"; }

selected=$(value APP_NAME k8s/fleet-app/fleet-app.yaml)
[ -n "$selected" ] || fail 'k8s/fleet-app/fleet-app.yaml sets no APP_NAME.'
diff <(sed -n '/^apiVersion:/,$p' k8s/fleet-app/fleet-app.yaml) \
  <(sed -n '/^apiVersion:/,$p' "k8s/applications/$selected/fleet-app.yaml") >/dev/null ||
  fail "k8s/fleet-app/fleet-app.yaml differs from k8s/applications/$selected/fleet-app.yaml; run scripts/select-app.sh $selected."
awk '/# The selected app/ { getline; print $2 }' k8s/applications/kustomization.yaml | grep -Fxq "$selected" ||
  fail "k8s/applications/kustomization.yaml does not select $selected."

apps=()
for contract in k8s/applications/*/fleet-app.yaml; do
  app=$(value APP_NAME "$contract")
  [ "$contract" = "k8s/applications/$app/fleet-app.yaml" ] || fail "$contract names $app."
  [ -f "$(value APP_SOURCE "$contract")/Dockerfile" ] || fail "$app has no Dockerfile at its APP_SOURCE."
  # The platform may not name any app: only its own directories and the
  # selection may. Fixtures under tests/ are sample data, not platform.
  if git grep -n -w "$app" -- k8s scripts policies platform fleet \
    ":(exclude)k8s/applications/$app" ':(exclude)k8s/fleet-app' \
    ':(exclude)k8s/applications/kustomization.yaml'; then
    fail "platform files name the $app app; read it from the app contract instead."
  fi
  apps+=("$app")
done
[ "${#apps[@]}" -ge 2 ] || fail 'Keep at least two apps so the swap stays proven.'

scratch=$(mktemp -d)
trap 'git worktree remove --force "$scratch/tree" >/dev/null 2>&1 || true; rm -rf "$scratch"' EXIT
git worktree add --quiet --detach "$scratch/tree" HEAD
for app in "${apps[@]}"; do
  (
    cd "$scratch/tree"
    git checkout --quiet --force HEAD -- .
    ./scripts/select-app.sh "$app" >/dev/null
    ./scripts/render-k8s-for-validation.sh "$scratch/$app" >/dev/null
    for profile in local aws-staging; do
      resources="$scratch/$app/$profile/resources.yaml"
      grep -Eq "^    name: $app$" "$resources" || fail "$profile renders no $app objects."
      awk -v app="$app" '/^kind: Canary$/ { canary = 1 } canary && $1 == "name:" { print $2; exit }' "$resources" |
        grep -Fxq "$app" || fail "$profile has no Canary for $app."
    done
    grep -q "image: fleet-local-registry:5000/$app:git-validation" "$scratch/$app/local/resources.yaml" ||
      fail "local does not run the image built for $app."
  )
  echo "app contract: $app renders in both profiles."
done
