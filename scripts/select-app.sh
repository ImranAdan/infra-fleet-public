#!/usr/bin/env bash
# Select the application the fleet runs. Copies the app's contract to
# k8s/fleet-app/fleet-app.yaml and points k8s/applications at its manifests;
# review and commit the result, then `./fleet sync --profile local`.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 APP_NAME" >&2
  exit 2
fi
app=$1
root=$(git rev-parse --show-toplevel)
[[ "$app" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || { echo "Invalid app name: $app" >&2; exit 2; }
contract="$root/k8s/applications/$app/fleet-app.yaml"
[ -f "$contract" ] || { echo "No app contract at k8s/applications/$app/fleet-app.yaml" >&2; exit 1; }
grep -Eq "^  APP_NAME: $app$" "$contract" || { echo "$contract does not name $app" >&2; exit 1; }

{
  printf '%s\n' \
    '# The application this fleet runs, as Flux and the local facade read it.' \
    '# Do not edit here: run scripts/select-app.sh <name>, which copies' \
    "# k8s/applications/<name>/fleet-app.yaml and selects that app's manifests." \
    '# tests/profiles/app-contract.sh keeps the two identical.'
  sed -n '/^apiVersion:/,$p' "$contract"
} > "$root/k8s/fleet-app/fleet-app.yaml"

# The line after the selection marker names the app's manifest directory.
awk -v app="$app" 'selected { sub(/- .*/, "- " app); selected = 0 }
  /# The selected app/ { selected = 1 } { print }' \
  "$root/k8s/applications/kustomization.yaml" > "$root/k8s/applications/kustomization.yaml.new"
mv "$root/k8s/applications/kustomization.yaml.new" "$root/k8s/applications/kustomization.yaml"
echo "Selected $app. Review and commit, then: ./fleet sync --profile local"
