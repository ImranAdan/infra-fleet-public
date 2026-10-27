"""Acceptance matrix. Run: python3 mandate/tests/test_acceptance.py [--gate]

Each row of acceptance.toml is one positive or adversarial case. Its fixture
drives only the public Mandate boundary (shadow.findings, decide, delegation,
evidence, receipt and ledger against the transport fakes) and returns what it
observed, keyed by situation; the row holds the literal expected values. A
decision reads "OUTCOME code ...", a check "conclusion title", a refusal
"refused CODE".

A row is PASS when every value matches and nothing is pending, PARTIAL when
every value matches but a behaviour it needs is not built yet, NOT BUILT when
nothing about it is executable yet, and FAIL on any mismatch. Live rows are
only ever credited by linked run evidence. An AUTHORIZE, a success check or
the legacy gate's READY where the row expects anything else is unsafe, and
fails the run on its own.

Exits 0 when no row fails and nothing unsafe was observed; with --gate, only
when every matrix row also PASSes. A self-check reruns every fixture with
decide() stubbed to AUTHORIZE and requires each row that expects a refusal to
fail, so no row can pass without the engine.
"""

from __future__ import annotations

import dataclasses
import hashlib
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

import test_receipt as tr  # noqa: E402
from test_ledger import REF, FakeGit, receipts  # noqa: E402

from mandate import decision as m  # noqa: E402
from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import gate  # noqa: E402
from mandate import ledger as l  # noqa: E402
from mandate import receipt as r  # noqa: E402
from mandate import shadow  # noqa: E402

MANIFEST = HERE / "acceptance.toml"
REPO = "ImranAdan/infra-fleet-public"
HEAD, BASE, OTHER = "a" * 40, "b" * 40, "c" * 40
POLICY = f"{d.DELEGATION_REPOSITORY}@{'d' * 40}:repositories/infra-fleet-public.toml"
NEW_POLICY = POLICY.replace("d" * 40, "f" * 40)
INTENT, RUNTIME = "Intent gate / Declared intent", "Runtime acceptance"
WORKFLOWS = {INTENT: ".github/workflows/intent-gate.yml", RUNTIME: ".github/workflows/runtime-acceptance.yml"}
# The example delegation plus a runtime-acceptance producer, a class that needs
# it, and a Dependabot class that matches on proven provenance facts.
EXAMPLE = (HERE.parent / "examples" / "infra-fleet-public.toml").read_text()
EXTRA = """
[evidence.runtime-acceptance]
check = "Runtime acceptance"
workflow = ".github/workflows/runtime-acceptance.yml"
event = "pull_request"

[[classes]]
id = "admission-routine"
match = { category = "admission-policy" }
decide = "authorize"
require = ["intent-gate", "runtime-acceptance"]

[[classes]]
id = "dependency-bump"
match = { category = "dependency-manifest", author = "dependabot[bot]", signed = true, update = "patch" }
decide = "authorize"
require = ["intent-gate"]
"""
DELEG = d.parse(EXAMPLE + EXTRA, REPO, POLICY)
SUBJECT = e.Subject(REPO, HEAD, BASE, POLICY)
# What a fact extractor would claim for a routine workflow change. Claiming it
# everywhere leaves the reserved findings as the only thing that can refuse.
NONE = {"permission_delta": "none", "secret_delta": "none", "trigger_delta": "none"}
W = ".github/workflows/build.yml"
SHA1, SHA2 = "1" * 40, "2" * 40

gate.configure(*gate.load_scope(ROOT / ".claude/skills/merge-gate/decision-policy.toml"))
FIXTURES = {}


def fixture(fn):
    FIXTURES[fn.__name__] = fn
    return fn


def record(check: str = INTENT, conclusion: str | None = "success", *, workflow: str | None = None,
           event: str = "pull_request", head: str = HEAD, base: str = BASE, run_id: int = 7,
           attempt: int = 1, app: int = e.ACTIONS_APP_ID, policy: str = POLICY) -> e.EvidenceRecord:
    """One check run and the workflow run behind it, through the real normalize()."""
    return e.normalize(
        {"id": run_id * 10, "name": check, "head_sha": head, "conclusion": conclusion,
         "app": {"id": app, "slug": "github-actions"}, "check_suite": {"id": run_id * 100}},
        {"id": run_id, "run_attempt": attempt, "check_suite_id": run_id * 100,
         "path": workflow or WORKFLOWS.get(check, ".github/workflows/other.yml"), "event": event,
         "head_branch": "agent/x", "repository": {"full_name": REPO},
         "pull_requests": [{"number": 7, "head": {"sha": head}, "base": {"sha": base}}]},
        e.Subject(REPO, head, base, policy),
    )


GREEN = (record(),)
BOTH = (record(), record(RUNTIME, run_id=8))


def diff(path: str, *added: str, removed: tuple[str, ...] = (), old: str | None = None,
         context: tuple[str, ...] = ()) -> str:
    """A one-hunk unified diff for one file (a rename when ``old`` differs)."""
    a = old or path
    body = "".join(f" {x}\n" for x in context) + "".join(f"-{x}\n" for x in removed) + "".join(f"+{x}\n" for x in added)
    return f"diff --git a/{a} b/{path}\n--- a/{a}\n+++ b/{path}\n@@ -1 +1 @@\n jobs:\n{body}"


def findings(text: str, read=lambda path: None) -> tuple[tuple[str, str], ...]:
    return shadow.findings(text, [], DELEG, read)


def said(decision: m.Decision) -> str:
    return " ".join([decision.outcome, *(x.code for x in decision.reasons)])


def decide(found=(("decision-record", "docs/decisions/0001-x.md"),), records=GREEN, *, facts=None,
           blocking=(), delegation=DELEG, subject=SUBJECT) -> str:
    return said(m.decide(m.DecisionInput(delegation, subject, tuple(found), dict(NONE if facts is None else facts),
                                         tuple(records), tuple(blocking))))


def refusal(fn) -> str:
    try:
        fn()
    except (l.LedgerError, d.DelegationError) as exc:
        return f"refused {exc.code}"
    return "accepted"


def shown(checks: tr.FakeChecks) -> str:
    return "; ".join(f"{c} {t}" for c, t in tr.visible(checks)) or "no check"


def live_receipts():
    """A fresh ledger and checks fake, and the reconcile call the publisher makes."""
    git, checks = FakeGit(), tr.FakeChecks()
    api = tr.both(checks, git)
    return git, checks, api, lambda head=HEAD: r.reconcile_check(api, tr.REPO, REF, head, app_id=tr.APP, delegations=tr.RESOLVE)


# --- the acceptance matrix, in acceptance-plan order -------------------------


@fixture
def routine_dependency_bump():
    bump = diff(".github/workflows/ci.yml", f"      - uses: actions/checkout@{SHA2} # v4.1.1",
                removed=(f"      - uses: actions/checkout@{SHA1} # v4.1.0",))
    commits = [{"author": "dependabot[bot]", "verified": True, "message": "update-type: version-update:semver-patch"}]
    failures = gate.dependabot_bump_failures("app/dependabot", "dependabot/github_actions/checkout", commits, bump)
    return {
        "Dependabot provenance": "; ".join(failures) or "version-only",
        "routine bump with intent evidence": decide(findings(bump)),
        "same bump, intent evidence missing": decide(findings(bump), ()),
    }


@fixture
def missing_runtime_evidence():
    policy = findings(diff("policies/require-labels.yaml", "  validationFailureAction: Enforce"))
    return {
        "intent evidence only": decide(policy),
        "runtime acceptance on this head": decide(policy, BOTH),
        "runtime acceptance on another head": decide(policy, (record(), record(RUNTIME, run_id=8, head=OTHER))),
    }


@fixture
def stale_head():
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision()), tr.DELEG)
    reconcile()
    checks.pr_heads = {7: OTHER}  # a push after AUTHORIZE
    moved = refusal(reconcile)
    old = tr.enforced(tr.decision())
    fresh = tr.enforced(tr.decision(subject=dataclasses.replace(tr.SUBJECT, head_sha=OTHER)))
    return {
        "evidence from the evaluated head": decide(subject=dataclasses.replace(SUBJECT, head_sha=OTHER)),
        "the executor observed the push": decide(blocking=("HEAD_CHANGED",)),
        "reconcile after the push": moved,
        "old head's check after the push": shown(checks),
        "trailers for a decision on the new head": refusal(
            lambda: r.trailers(api, tr.REPO, REF, old["subject"], fresh, tr.DELEG, after=None)),
    }


@fixture
def claimed_evidence_only():
    fields = {f.name for f in dataclasses.fields(m.DecisionInput)}
    return {
        "Verification prose, required check absent": decide(records=()),
        "prose is an input": "yes" if fields & {"body", "description", "verification"} else "no",
    }


@fixture
def forged_check_source():
    forged = record(workflow=".github/workflows/forged.yml", run_id=9)
    pr = findings(diff(".github/workflows/forged.yml", "name: Intent gate", "on: pull_request"))
    return {
        "forged check alone": decide(records=(forged,)),
        "forged check beside a genuine one": decide(records=(record(), forged)),
        "the forging workflow itself": decide(pr, (record(), forged)),
    }


@fixture
def forged_dependabot():
    bump = diff("requirements.txt", "requests==2.32.4", removed=("requests==2.32.3",))
    good = {"author": "dependabot[bot]", "verified": True, "message": "update-type: version-update:semver-patch"}
    lock = (("dependency-manifest", "uv.lock"),)
    prov = {"author": "dependabot[bot]", "signed": True, "update": "patch"}

    def bump_failures(author, branch, commit):
        return "; ".join(gate.dependabot_bump_failures(author, branch, [commit], bump)) or "version-only"

    return {
        "agent on a dependabot/ branch": bump_failures("agent", "dependabot/pip/requests", good),
        "unsigned commit": bump_failures("app/dependabot", "dependabot/pip/requests", {**good, "verified": False}),
        "major update": bump_failures("app/dependabot", "dependabot/pip/requests",
                                      {**good, "message": "update-type: version-update:semver-major"}),
        "lockfile bump, provenance unproven": decide(lock, facts={}),
        "lockfile bump, unsigned": decide(lock, facts={**prov, "signed": False}),
        "lockfile bump, agent author": decide(lock, facts={**prov, "author": "agent"}),
        "lockfile bump, major": decide(lock, facts={**prov, "update": "major"}),
        "lockfile bump, proven Dependabot patch": decide(lock, facts=prov),
    }


@fixture
def unauthorized_privilege():
    return {
        "adds contents: write": decide(findings(diff(W, "    permissions:", "      contents: write"))),
        "adds a secret": decide(findings(diff(W, "        env: { TOKEN: '${{ secrets.DEPLOY }}' }"))),
        "adds pull_request_target": decide(findings(diff(W, "on: pull_request_target"))),
        "App manifest grants contents: write": decide(findings(diff("app-manifest.json", '  "contents": "write",'))),
    }


@fixture
def authority_change():
    return {
        "edits the engine": decide(findings(diff("mandate/src/mandate/decision.py", "    return True"))),
        "edits an evidence workflow": decide(findings(diff(".github/workflows/intent-gate.yml", "      - run: true"))),
        "edits a ruleset": decide(findings(diff(".github/rulesets/main.json", '  "enforcement": "disabled"'))),
        "edits the merge gate": decide(findings(diff(".claude/skills/merge-gate/decision-policy.toml", "x = 1"))),
    }


@fixture
def self_approval():
    fields = {f.name for f in dataclasses.fields(m.DecisionInput)}
    collide = EXAMPLE.replace("agents = []", 'agents = ["imranadan"]')
    try:
        enforce: d.Delegation | d.DelegationError = d.parse(collide.replace('mode = "shadow"', 'mode = "enforce"'), REPO, POLICY)
    except d.DelegationError as exc:
        enforce = exc
    return {
        "approval is an input": "yes" if fields & {"approval", "approvals", "comments", "reviews"} else "no",
        "owner listed as an agent, enforce": decide(delegation=enforce),
        "owner listed as an agent, shadow": decide(delegation=d.parse(collide, REPO, POLICY)),
    }


@fixture
def lifecycle_failure():
    return {}


@fixture
def concurrent_workers():
    git, checks, api, reconcile = live_receipts()
    after = r.pr_latest(git, tr.REPO, REF, tr.REPO, 7)
    first = tr.enforced(tr.decision())
    r.record(git, tr.REPO, REF, first, tr.DELEG, after=after)
    second = tr.enforced(tr.decision())
    reconcile()
    reconcile()
    return {
        "decision ID from two workers": "same" if first["decision_id"] == second["decision_id"] else "different",
        "second worker records from the same tip": refusal(lambda: r.record(git, tr.REPO, REF, second, tr.DELEG, after=after)),
        "check after both reconcile": shown(checks),
    }


@fixture
def unmanaged_merge():
    return {}


@fixture
def invalid_delegation():
    bad = EXAMPLE.replace('id = "reserved"  # never delegable in version 1', 'id = "reserved"').replace(
        'decide = "escalate"', 'decide = "authorize"\nrequire = ["intent-gate"]')
    try:
        broken: d.Delegation | d.DelegationError = d.parse(bad, REPO, POLICY)
    except d.DelegationError as exc:
        broken = exc
    return {
        "docs change": decide(delegation=broken),
        "reserved change": decide((("credential", ".github/workflows/x.yml"),), delegation=broken),
        "no findings": decide((), delegation=broken),
    }


@fixture
def non_fleet_repository():
    other = "ImranAdan/infra-fleet-advisor-public"
    source = POLICY.replace("infra-fleet-public.toml", "infra-fleet-advisor-public.toml")
    text = (EXAMPLE + EXTRA).replace(f'repository = "{REPO}"', f'repository = "{other}"')
    deleg = d.parse(text, other, source)
    subject = e.Subject(other, HEAD, BASE, source)
    green = (dataclasses.replace(record(policy=source), repository=other),)
    bump = shadow.findings(diff(".github/workflows/ci.yml", f"      - uses: actions/checkout@{SHA2} # v4.1.1",
                                removed=(f"      - uses: actions/checkout@{SHA1} # v4.1.0",)), [], deleg, lambda p: None)
    widen = shadow.findings(diff(W, "    permissions:", "      contents: write"), [], deleg, lambda p: None)
    return {
        "routine bump": decide(bump, green, delegation=deleg, subject=subject),
        "permission widening": decide(widen, green, delegation=deleg, subject=subject),
        "Fleet's file used for it": refusal(lambda: d.parse(EXAMPLE + EXTRA, other, source)),
    }


@fixture
def base_changed():
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision()), tr.DELEG)
    reconcile()
    checks.pr_bases = {7: {"sha": OTHER}}
    moved = refusal(reconcile)
    old = tr.enforced(tr.decision())
    fresh = tr.enforced(tr.decision(subject=dataclasses.replace(tr.SUBJECT, base_sha=OTHER)))
    return {
        "evidence from the old base": decide(subject=dataclasses.replace(SUBJECT, base_sha=OTHER)),
        "the executor observed the move": decide(blocking=("BASE_CHANGED",)),
        "reconcile after the move": moved,
        "check after the base moved": shown(checks),
        "trailers for a decision on the new base": refusal(
            lambda: r.trailers(api, tr.REPO, REF, old["subject"], fresh, tr.DELEG, after=None)),
    }


@fixture
def enforcement_drift():
    git, checks, api, reconcile = live_receipts()
    old = tr.enforced(tr.decision())
    drifted = tr.build(tr.decision(), enforcement="sha256:" + "9" * 64)
    shadowed = tr.build(tr.decision())
    return {
        "the executor observed drift": decide(blocking=("ENFORCEMENT_DRIFT",)),
        "the executor found no protection": decide(blocking=("ENFORCEMENT_MISSING",)),
        "trailers after the snapshot changed": refusal(
            lambda: r.trailers(api, tr.REPO, REF, old["subject"], drifted, tr.DELEG, after=None)),
        "trailers for a shadow decision": refusal(
            lambda: r.trailers(api, tr.REPO, REF, shadowed["subject"], shadowed, tr.DELEG, after=None)),
    }


@fixture
def insufficient_evidence():
    manifests = record("Kubernetes manifests", workflow=".github/workflows/k8s-manifest-validate.yml", run_id=11)
    return {"only an unrequired check is green": decide(records=(manifests,))}


@fixture
def called_script_edit():
    base = {
        WORKFLOWS[INTENT]: "jobs:\n  gate:\n    steps:\n      - run: bash scripts/intent-gate.sh\n",
        "scripts/intent-gate.sh": "python3 scripts/lib/compare.py \"$@\"\n",
    }
    read = base.get
    return {
        "edits the script the producer runs": decide(findings(diff("scripts/intent-gate.sh", "exit 0"), read)),
        "edits a script that script runs": decide(findings(diff("scripts/lib/compare.py", "sys.exit(0)"), read)),
        "edits an unrelated script": decide(findings(diff("scripts/other.sh", "exit 0"), read)),
    }


@fixture
def delegation_changed():
    new = d.parse(EXAMPLE + EXTRA, REPO, NEW_POLICY)
    subject = dataclasses.replace(SUBJECT, policy=NEW_POLICY)
    receipt = r.build(m.decide(m.DecisionInput(new, subject, (("decision-record", "docs/decisions/x.md"),), {},
                                               (record(policy=NEW_POLICY),), ())),
                      7, "shadow", versions={}, actors={}, evaluated_at="2026-10-25T00:00:00Z")
    return {
        "evidence produced under the old policy": decide(records=GREEN, delegation=new, subject=subject),
        "rules changed between decision and merge": "drifted" if d.drifted(DELEG, new) else "unchanged",
        "receipt names": "new policy" if receipt["subject"]["policy"] == NEW_POLICY else receipt["subject"]["policy"],
    }


@fixture
def conflicting_evidence():
    unattributable = dataclasses.replace(record(run_id=12), run_id=None, run_attempt=None, workflow=None, event=None)
    return {
        "success and failure from two runs": decide(records=(record(), record("Intent gate / Declared intent", "failure", run_id=13))),
        "success beside an unattributable result": decide(records=(record(), unattributable)),
        "a rerun supersedes its failed attempt": decide(records=(record(conclusion="failure"), record(attempt=2))),
    }


@fixture
def ledger_anchors():
    git = FakeGit()
    first = tr.put(git, tr.enforced(tr.decision()), tr.DELEG)[0]
    tr.put(git, tr.enforced(tr.decision("ESCALATE")), tr.DELEG)
    third = tr.put(git, tr.enforced(tr.decision()), tr.DELEG)[0]
    text, blobs = git.files(REF)[l.LEDGER].decode(), receipts(git)
    lines = text.splitlines(keepends=True)
    anchor = lambda x: {"Mandate-Decision": x["decision_id"], "Mandate-Receipt-Digest": x["receipt_digest"],  # noqa: E731
                        "Mandate-Chain-Head": x["entry_digest"]}

    def audited(ledger, anchors):
        failures, limits = r.audit(ledger, blobs, anchors)
        return "detected" if failures else "; ".join(limits)

    rewritten = FakeGit()
    tr.put(rewritten, tr.enforced(tr.decision("ESCALATE")), tr.DELEG)
    fresh = tr.enforced(tr.decision())
    after = r.pr_latest(git, tr.REPO, REF, tr.REPO, 7)
    message = "Merge pull request #7\n\n" + r.trailers(git, tr.REPO, REF, fresh["subject"], fresh, tr.DELEG, after=after)
    parsed = r.parse_trailers(message) or {}
    newest = l.read(git, tr.REPO, REF).text.splitlines()[-1]
    return {
        "middle entry deleted": audited(lines[0] + lines[2], [anchor(third)]),
        "tail truncated behind an anchor": audited("".join(lines[:2]), [anchor(third)]),
        "full rewrite": audited(rewritten.files(REF)[l.LEDGER].decode(), [anchor(first)]),
        "no anchor (key compromise)": audited(text, []),
        "check run expired, merge anchor kept": audited(text, [anchor(third)]),
        "merge trailers resolve to the ledger": "resolve" if parsed.get("Mandate-Chain-Head", "?") in newest else "missing",
    }


@fixture
def wake_disorder():
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision()), tr.DELEG)
    tr.put(git, tr.enforced(tr.decision("ESCALATE")), tr.DELEG)  # its wake was missed
    reconcile()  # the scheduled backstop
    reconcile()  # a duplicate wake
    return {"check after a missed then a duplicate wake": shown(checks), "check runs": str(len(checks.runs))}


@fixture
def break_glass_merge():
    return {}


@fixture
def wrong_workflow_same_app():
    return {
        "same App and name, another workflow": decide(records=(record(workflow=".github/workflows/lint.yml", run_id=14),)),
        "same App, name and workflow, another event": decide(records=(record(event="workflow_dispatch", run_id=15),)),
        "same name from another App": decide(records=(record(app=1, run_id=16),)),
    }


@fixture
def token_expiry():
    return {}


@fixture
def bypass_topology():
    writer = {"name": "writer", "enforcement": "active", "conditions": {"ref_name": {"include": [f"refs/heads/{REF}"]}},
              "rules": [{"type": "update"}, {"type": "creation"}],
              "bypass_actors": [{"actor_type": "Integration", "actor_id": 5, "bypass_mode": "always"}]}
    integrity = {"name": "integrity", "enforcement": "active", "conditions": writer["conditions"],
                 "rules": [{"type": t} for t in sorted(l.INTEGRITY_RULES)], "bypass_actors": []}
    exempt = {**writer, "bypass_actors": [{"actor_type": "Integration", "actor_id": 5, "bypass_mode": "exempt"}]}
    extra = {**integrity, "bypass_actors": [{"actor_type": "Integration", "actor_id": 5, "bypass_mode": "always"}]}
    return {
        "sound topology": "; ".join(l.ruleset_failures([writer, integrity], REF, 5)) or "sound",
        "writer App exempt": "; ".join(l.ruleset_failures([exempt, integrity], REF, 5)) or "sound",
        "App bypasses the integrity rules": "; ".join(l.ruleset_failures([writer, extra], REF, 5)) or "sound",
    }


# --- classifier evasion: hide an authority change from the scope classifier ---

# Each attempt is a workflow diff; the evasion rows decide them through the new
# engine, and live_gate_evasions through Fleet's legacy gate.
EVASIONS = {
    "evade_flow_permissions": {
        "flow-style block": diff(W, "    permissions: {contents: write}"),
        "nested flow mapping": diff(W, "  build: {runs-on: ubuntu-latest, permissions: {contents: write}}"),
        "quoted value": diff(W, "      contents: 'write'"),
        "quoted key": diff(W, '      "contents": write'),
        "write-all": diff(W, "permissions: write-all"),
        "block scalar": diff(W, "      contents: >-", "        write"),
        "explicit key": diff(W, "      ? contents", "      : write"),
        "a comment naming write and secrets (control)": diff(W, "    # write to the cache; no secrets here"),
        # YAML decodes escapes in double-quoted scalars, and an escaped line
        # break joins two lines with no space.
        "hex-escaped value": diff(W, '      contents: "wri\\x74e"', removed=("      contents: read",)),
        "unicode-escaped value": diff(W, '      contents: "\\u0077rite"', removed=("      contents: read",)),
        "escaped line break": diff(W, '      contents: "wri\\', '        te"', removed=("      contents: read",)),
        "only the continuation line changes": diff(W, '        te"', removed=('        ad"',), context=('      contents: "wri\\',)),
        "a value under an unknown tag": diff(W, "      contents: !!binary d3JpdGU=", removed=("      contents: read",)),
        "an escaped string in a script (control)": diff(W, '        run: printf "a\\tb\\n"'),
        "a shell inequality (control)": diff(W, '        run: test "$A" != "b"'),
    },
    "evade_yaml_aliases": {
        "anchor then alias": diff(W, "x-perm: &w", "  contents: write", "    permissions: *w"),
        "alias of an existing anchor": diff(W, "    permissions: *w"),
        "anchored value": diff(W, "      contents: &w write"),
        "tagged value": diff(W, "      contents: !!str write"),
        "value aliased to an unchanged anchor": diff(W, "      contents: *w", context=("x-w: &w write",)),
        "merge key": diff(W, "    <<: *perms", context=("x-perms: &perms", "  permissions:", "    contents: write")),
        "numeric anchor name": diff(W, "      contents: *1", removed=("      contents: read",), context=("  WRITE_PERMISSION: &1 write",)),
    },
    "evade_secret_expressions": {
        "toJSON(secrets)": diff(W, "        env: { ALL: '${{ toJSON(secrets) }}' }"),
        "computed index": diff(W, "        env: { T: '${{ secrets[inputs.name] }}' }"),
        "after another operand": diff(W, "        token: ${{ inputs.token || secrets.DEPLOY }}"),
        "expression across lines": diff(W, "        run: |", '          echo "${{', '            secrets.DEPLOY }}"'),
        "upper-case context name": diff(W, "        token: ${{ SECRETS.DEPLOY }}"),
        "expression in a script comment": diff(W, "        run: |", "          # ${{ toJSON(secrets) }}"),
        "secrets: inherit": diff(W, "    secrets: inherit"),
    },
    "evade_reusable_triggers": {
        "reusable workflow gains pull_request_target": diff(".github/workflows/reusable.yml", "on:", "  pull_request_target:"),
        "flow-map trigger": diff(W, "on: {workflow_run: {workflows: [ci]}}"),
        "list trigger": diff(W, "on: [push, issue_comment]"),
    },
    "evade_moved_workflows": {
        "evidence workflow renamed": diff(".github/workflows/other.yml", old=WORKFLOWS[INTENT]),
        "evidence workflow moved out": diff("scripts/intent-gate.yml", old=WORKFLOWS[INTENT]),
        # A pure rename shows no content, so the moved file's triggers and
        # permissions are invisible to a line classifier.
        "privileged file moved in": "diff --git a/scripts/new.yml b/.github/workflows/new.yml\nsimilarity index 100%\n"
                                    "rename from scripts/new.yml\nrename to .github/workflows/new.yml\n",
    },
}
for _row in EVASIONS:
    FIXTURES[_row] = (lambda row: lambda: {k: decide(findings(v)) for k, v in EVASIONS[row].items()})(_row)


@fixture
def live_gate_evasions():
    """The same attempts through Fleet's legacy gate, which decides workflow
    changes on evidence alone and permission or credential changes by the owner."""
    rules, _ = gate.load_policy(ROOT / ".claude/skills/merge-gate/decision-policy.toml")

    def verdict(text: str) -> str:
        outcome, why = gate.decide(gate.scope_findings(text), rules, set(), None)
        return " ".join([outcome, *why])

    return {f"{row.removeprefix('evade_').replace('_', ' ')}: {k}": verdict(v)
            for row, attempts in EVASIONS.items() for k, v in attempts.items()}


# --- regressions found in review --------------------------------------------


@fixture
def forged_receipts():
    fabricated = tr.enforced(tr.decision("ESCALATE"))
    fabricated["decision"] = {**fabricated["decision"], "outcome": "AUTHORIZE", "reasons": []}
    elsewhere = tr.enforced(tr.decision())
    elsewhere["decision"]["accepted"][0]["records"][0]["head_sha"] = OTHER
    invented = tr.enforced(tr.decision())
    invented["decision"] = {**invented["decision"], "classes": ["invented-class"]}
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision("ESCALATE")), tr.DELEG)
    reconcile()
    planted = {**invented, "receipt_revision": "r2"}
    l.append(git, tr.REPO, REF, planted["decision_id"], "r2", l.canonical(planted), planted["subject_digest"], "AUTHORIZE", "t")
    record = lambda receipt: lambda: tr.put(FakeGit(), receipt, tr.DELEG)  # noqa: E731
    return {
        "AUTHORIZE with its reasons deleted": refusal(record(fabricated)),
        "evidence about another head": refusal(record(elsewhere)),
        "a class the delegation never declared": refusal(record(invented)),
        "a renamed decision ID": refusal(record({**tr.enforced(tr.decision()), "decision_id": "d-" + "0" * 64})),
        "an unsupported schema": refusal(record({**tr.enforced(tr.decision("ESCALATE")), "schema_version": 2})),
        "planted below record()": refusal(reconcile),
        "check after the planted receipt": shown(checks),
    }


@fixture
def shared_head():
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision()), tr.DELEG)  # only #7 is decided
    checks.open_prs = {7, 8}
    reconcile()
    shared = shown(checks)
    checks.open_prs = {7}
    reconcile()
    alone = shown(checks)
    checks.open_prs = {9}
    return {
        "an undecided PR shares the head": shared,
        "the other PR closed": alone,
        "the only open PR is undecided": refusal(reconcile),
    }


@fixture
def base_drift():
    git, checks, api, reconcile = live_receipts()
    tr.put(git, tr.enforced(tr.decision()), tr.DELEG)
    checks.pr_bases = {7: None}
    missing = refusal(reconcile)
    checks.pr_bases = {7: {"sha": OTHER}}
    tr.put(git, tr.enforced(tr.decision(subject=dataclasses.replace(tr.SUBJECT, base_sha=OTHER))), tr.DELEG)
    reconcile()
    decided = shown(checks)
    checks.pr_bases = {}  # retargeted back to the base of the older green receipt
    return {
        "base missing": missing,
        "a fresh decision at the new base": decided,
        "retargeted back to the old base": refusal(reconcile),
        "check after the retarget": shown(checks),
    }


@fixture
def stale_recorder():
    git = FakeGit()
    landed = r.record(git, tr.REPO, REF, tr.enforced(tr.decision()), tr.DELEG, after=None)[0]
    lost = FakeGit()

    def lost_response(method, path, payload):
        out = lost(method, path, payload)
        if method == "PATCH":  # the ref moved; the response never arrived
            raise l.ApiError(502, "response lost")
        return out

    again = r.record(git, tr.REPO, REF, tr.enforced(tr.decision()), tr.DELEG, after=landed["entry_digest"])[0]
    return {
        "retry with the original tip after landing": refusal(
            lambda: r.record(git, tr.REPO, REF, tr.enforced(tr.decision()), tr.DELEG, after=None)),
        "decide again with a fresh tip": f"appended {again['receipt_revision']}",
        "append response lost": refusal(
            lambda: r.record(lost_response, tr.REPO, REF, tr.enforced(tr.decision()), tr.DELEG, after=None)),
        "retry after the lost response": refusal(
            lambda: r.record(lost, tr.REPO, REF, tr.enforced(tr.decision()), tr.DELEG, after=None)),
    }


GROUP = f"    concurrency:\n      group: {r.CANONICAL_GROUP}\n      cancel-in-progress: false\n"
STEP = 'PYTHONPATH=mandate/src python3 -m mandate.receipt reconcile "$GITHUB_REPOSITORY" "$LEDGER_REF" "$HEAD" --app-id "$APP_ID"'
RECORDER = ("    permissions:\n      contents: write\n    steps:\n      - run: "
            + STEP.replace("reconcile", "record") + "\n        shell: bash\n")
PUBLISHER = "    needs: record\n    if: always()\n    permissions:\n      checks: write\n"


def workflow(recorder: str = RECORDER, publisher: str = PUBLISHER + GROUP, steps: str = "") -> str:
    steps = steps or f"    steps:\n      - run: {STEP}\n        shell: bash\n        if: always()\n"
    jobs = {"record": recorder, "publish": publisher + steps}
    return "on: workflow_call\njobs:\n" + "".join(f"  {k}:\n    runs-on: ubuntu-latest\n{v}" for k, v in jobs.items())


def violations(text: str) -> str:
    return ", ".join(r.serial_violations({"w.yml": text})) or "none"


@fixture
def publisher_contract():
    step = f"    steps:\n      - run: {STEP}\n        shell: bash\n"
    return {
        "the supported publisher": violations(workflow()),
        "a publisher that only echoes": violations(workflow(steps="    steps:\n      - run: echo done\n")),
        "a skipped reconcile step": violations(workflow(steps=step + "        if: false\n")),
        "a reconcile step without its own if": violations(workflow(steps="    steps:\n      - run: exit 1\n" + step[11:])),
        "help instead of arguments": violations(workflow(steps=step.replace(STEP.split("reconcile ")[1], "--help") + "        if: always()\n")),
        "an argument bash comments out": violations(workflow(steps=step.replace('"$HEAD"', "#head").replace("run: ", "run: |\n          ") + "        if: always()\n")),
    }


@fixture
def cancellation():
    return {
        "a recorder waiting in a group": violations(workflow(recorder=RECORDER + GROUP)),
        "a publisher that cancels in progress": violations(workflow(publisher=PUBLISHER + GROUP.replace("false", "true"))),
        "a publisher outside the canonical group": violations(workflow(publisher=PUBLISHER)),
    }


@fixture
def ledger_limits():
    git = FakeGit()
    l.append(git, tr.REPO, REF, "d1", "r1", b'{"a":1}', "sha256:s", "AUTHORIZE", "t")

    class Large(FakeGit):  # over the contents API's 1 MB inline limit
        def __call__(self, method, path, payload):
            if method == "GET" and f"contents/{l.LEDGER}" in path:
                return {"content": "", "encoding": "none"}
            return super().__call__(method, path, payload)

    identical = l.append(git, tr.REPO, REF, "d1", "r1", b'{"a":1}', "sha256:s", "AUTHORIZE", "t")
    return {
        "an identical retry": "appended nothing" if identical is None else "appended",
        "other bytes at one revision": refusal(lambda: l.append(git, tr.REPO, REF, "d1", "r1", b"{}", "sha256:s", "AUTHORIZE", "t")),
        "a ledger over the inline limit": refusal(lambda: l.append(Large(), tr.REPO, REF, "d1", "r1", b"{}", "sha256:s", "AUTHORIZE", "t")),
    }


@fixture
def renamed_reserved_paths():
    def moved(old, new):
        return f"diff --git a/{old} b/{new}\nsimilarity index 100%\nrename from {old}\nrename to {new}\n"

    return {
        "the engine moved out": decide(findings(moved("mandate/src/mandate/gate.py", "docs/gate.py"))),
        "agent instructions moved": decide(findings(moved("AGENTS.md", "docs/agents.md"))),
        "a ruleset moved": decide(findings(moved(".github/rulesets/main.json", "docs/main.json"))),
    }


@fixture
def dependabot_inline_comment():
    def bump(old, new):
        return diff("requirements.txt", new, removed=(old,))

    commits = [{"author": "dependabot[bot]", "verified": True, "message": "update-type: version-update:semver-patch"}]

    def failures(text):
        found = gate.dependabot_bump_failures("app/dependabot", "dependabot/pip/requests", commits, text)
        return "; ".join(found) or "version-only"

    return {
        "comment kept": failures(bump("requests==2.32.3  # via requests", "requests==2.32.4  # via requests")),
        "comment changed": failures(bump("requests==2.32.3  # via requests", "requests==2.32.4  # via urllib3")),
        "comment added": failures(bump("requests==2.32.3", "requests==2.32.4  # via requests")),
        "package swapped, comment kept": failures(bump("requests==2.32.3  # via requests", "request==2.32.4  # via requests")),
    }


# --- runner -------------------------------------------------------------------


# What lets a change through: an AUTHORIZE, a green check, or the legacy gate's READY.
GRANTS = ("AUTHORIZE", "success", "READY")


def run(rows: list[dict]) -> list[tuple[dict, dict, str, int]]:
    results = []
    for row in rows:
        try:
            observed = FIXTURES[row["fixture"]]()
        except Exception as exc:  # noqa: BLE001 - a crash is a failed row, never a pass
            observed = {"fixture error": f"{type(exc).__name__}: {exc}"}
        expect = row.get("expect", {})
        unsafe = sum(
            1 for k, v in observed.items()
            if v.startswith(GRANTS) and not str(expect.get(k, "")).startswith(GRANTS)
        )
        if observed != expect:
            status = "FAIL"
        elif row.get("pending"):
            status = "PARTIAL" if expect else "NOT BUILT"
        else:
            status = "PASS"
        results.append((row, observed, status, unsafe))
    return results


def stub_check(rows: list[dict]) -> list[str]:
    """Rows that expect a refusal from decide() but still pass with it stubbed."""
    real = m.decide
    m.decide = lambda snapshot: m.Decision("AUTHORIZE", (), (), (), "", snapshot.subject)
    try:
        results = run(rows)
    finally:
        m.decide = real
    refusing = ("BLOCK", "ESCALATE", "VERIFY")
    return [row["slug"] for row, _, status, _ in results
            if any(str(v).startswith(refusing) for v in row.get("expect", {}).values()) and status != "FAIL"]


def main(argv: list[str]) -> int:
    manifest = tomllib.loads(MANIFEST.read_text())
    rows = manifest["case"]
    assert len({x["slug"] for x in rows}) == len(rows), "duplicate slug"
    assert {x["fixture"] for x in rows} == set(FIXTURES), set(FIXTURES) ^ {x["fixture"] for x in rows}
    results = run(rows)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    print(f"package {commit or 'unknown'}, manifest sha256:{hashlib.sha256(MANIFEST.read_bytes()).hexdigest()}, "
          f"registry {m.REGISTRY_VERSION}, fixture policy {POLICY}")
    for kind in ("matrix", "evasion", "regression"):
        group = [x for x in results if x[0]["kind"] == kind]
        print(f"\n{kind}: " + ", ".join(f"{s} {sum(1 for x in group if x[2] == s)}"
                                       for s in ("PASS", "PARTIAL", "NOT BUILT", "FAIL")) + f" of {len(group)}")
        for row, observed, status, unsafe in group:
            print(f"  {status:9} {row['slug']:28} live: {row.get('live', 'not applicable')}"
                  + (f"  UNSAFE x{unsafe}" if unsafe else ""))
            for item in row.get("pending", []):
                print(f"            pending: {item}")
            if status == "FAIL":
                for k in sorted(set(observed) | set(row.get("expect", {}))):
                    want, got = row.get("expect", {}).get(k), observed.get(k)
                    if want != got:
                        print(f"            {k}: expected {want!r}, observed {got!r}")
    unsafe = sum(x[3] for x in results)
    failed = [x[0]["slug"] for x in results if x[2] == "FAIL"]
    hollow = stub_check(rows)
    matrix = [x for x in results if x[0]["kind"] == "matrix"]
    passed = sum(1 for x in matrix if x[2] == "PASS")
    print(f"\nunsafe AUTHORIZE: {unsafe}; failed rows: {len(failed)}; "
          f"rows passing with decide() stubbed: {hollow or 'none'}; fixture gate: {passed}/{len(matrix)} matrix rows PASS")
    ok = not failed and not unsafe and not hollow
    if "--gate" in argv:
        ok = ok and passed == len(matrix)
    print("acceptance " + ("passed" if ok else "FAILED") + (" (fixture gate)" if "--gate" in argv else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
