#!/usr/bin/env python3
"""Compare every pinned Helm chart and the Flux version with upstream.

Dependabot reads neither Flux HelmRelease chart versions nor the generated
Flux manifest, so this is their routine version check. It prints a Markdown
table (append it to $GITHUB_STEP_SUMMARY in CI) and exits 1 when anything is
behind or could not be looked up.

    python3 scripts/check-chart-versions.py [--self-test]
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FLUX_MANIFEST = ROOT / "k8s/flux-system/flux-system/gotk-components.yaml"
SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
HEADERS = {"User-Agent": "infra-fleet-chart-check"}
# Deliberately held versions: (component, pinned version) -> the issue that
# holds them. Shown but not failed; the hold lapses when the pin changes.
HELD = {
    ("kube-prometheus-stack", "67.4.0"): "#197: 92.x shelved, too heavy for the local profile",
    ("aws-load-balancer-controller", "3.5.0"): "#192: IAM policy pinned to v3.5.0, owner decision",
}


def parse(version):
    """(major, minor, patch) for a stable release, None for anything else."""
    match = SEMVER.fullmatch(str(version).strip().strip('"'))
    return tuple(int(part) for part in match.groups()) if match else None


def newest(versions):
    stable = [v for v in versions if parse(v)]
    return max(stable, key=parse) if stable else None


def status(pinned, latest):
    have, want = parse(pinned), parse(latest)
    if have is None or want is None:
        return "unknown"
    if have >= want:
        return "current"
    return "behind " + ("major" if have[0] < want[0] else "minor" if have[1] < want[1] else "patch")


def fails(state, held):
    """A hold excuses being behind, never a failed lookup."""
    return state != "current" and not (held and state.startswith("behind"))


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode()


def http_versions(repo_url, chart):
    index = yaml.safe_load(fetch(repo_url.rstrip("/") + "/index.yaml"))
    return [entry["version"] for entry in index.get("entries", {}).get(chart, [])]


def oci_versions(repo_url, chart):
    """Tags from an OCI registry, following its anonymous token challenge."""
    host, _, namespace = repo_url.removeprefix("oci://").partition("/")
    registry = "registry-1.docker.io" if host == "docker.io" else host
    url = f"https://{registry}/v2/{namespace}/{chart}/tags/list"
    try:
        return json.loads(fetch(url))["tags"]
    except urllib.error.HTTPError as error:
        challenge = error.headers.get("WWW-Authenticate", "")
        if error.code != 401 or not challenge.startswith("Bearer "):
            raise
        fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
        token_url = f"{fields['realm']}?service={fields.get('service', '')}&scope={fields.get('scope', '')}"
        token = json.loads(fetch(token_url)).get("token")
        return json.loads(fetch(url, {"Authorization": f"Bearer {token}"}))["tags"]


def flux_latest():
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}
    return json.loads(fetch("https://api.github.com/repos/fluxcd/flux2/releases/latest", headers))["tag_name"]


def documents():
    for path in sorted((ROOT / "k8s").rglob("*.yaml")):
        if path == FLUX_MANIFEST:
            continue
        for document in yaml.safe_load_all(path.read_text()):
            if isinstance(document, dict):
                yield path.relative_to(ROOT).as_posix(), document


def rows():
    """(component, file, pinned, latest-or-error) for each chart, then Flux."""
    repositories, releases = {}, []
    for path, document in documents():
        meta = document.get("metadata", {})
        if document.get("kind") == "HelmRepository":
            spec = document.get("spec", {})
            url = spec.get("url", "")
            if spec.get("type") == "oci" and not url.startswith("oci://"):
                url = "oci://" + url
            repositories[(meta.get("namespace"), meta.get("name"))] = url
        elif document.get("kind") == "HelmRelease":
            releases.append((path, meta, document.get("spec", {}).get("chart", {}).get("spec", {})))
    for path, meta, chart in releases:
        source = chart.get("sourceRef", {})
        url = repositories.get((source.get("namespace", meta.get("namespace")), source.get("name")))
        name, pinned = chart.get("chart"), str(chart.get("version", ""))
        try:
            if not url:
                raise LookupError(f"HelmRepository {source.get('name')} not found under k8s/")
            versions = oci_versions(url, name) if url.startswith("oci://") else http_versions(url, name)
            latest = newest(versions) or "no stable release"
        except Exception as error:  # report every lookup failure, keep going
            latest = f"lookup failed: {error}"
        yield name, path, pinned, latest
    header = re.search(r"^# Flux Version: (v\S+)", FLUX_MANIFEST.read_text(), re.M)
    try:
        latest = flux_latest()
    except Exception as error:
        latest = f"lookup failed: {error}"
    yield "flux", FLUX_MANIFEST.relative_to(ROOT).as_posix(), header.group(1) if header else "", latest


def main():
    table = ["| Component | Pinned | Latest | Status | File |", "|---|---|---|---|---|"]
    stale = 0
    for name, path, pinned, latest in rows():
        state = status(pinned, latest)
        held = HELD.get((name, pinned))
        stale += fails(state, held)
        if held and state.startswith("behind"):
            state = f"{state}, held ({held})"
        table.append(f"| {name} | {pinned} | {latest} | {state} | `{path}` |")
    print("### Helm chart and Flux versions\n")
    print("\n".join(table))
    print(f"\n{stale} behind or unknown and not held." if stale else "\nNothing behind that is not held.")
    return 1 if stale else 0


def self_test():
    assert parse("v1.21.2") == (1, 21, 2) and parse('"67.4.0"') == (67, 4, 0)
    assert parse("2.0.0-rc.1") is None and parse("latest") is None
    assert newest(["1.9.0", "1.10.0", "1.11.0-rc.1", "v1.2.3"]) == "1.10.0"
    assert newest(["0.0.0-dev"]) is None
    assert status("67.4.0", "92.3.0") == "behind major"
    assert status("v1.9.1", "v1.9.2") == "behind patch"
    assert status("3.13.0", "3.14.0") == "behind minor"
    assert status("1.45.0", "1.45.0") == "current"
    assert status("1.0.0", "lookup failed: HTTP Error 403") == "unknown"
    assert not fails("current", None) and fails("behind patch", None)
    assert not fails("behind major", "#197") and fails("unknown", "#197")
    print("self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(self_test() if "--self-test" in sys.argv else main())
