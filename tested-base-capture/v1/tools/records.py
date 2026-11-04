"""The declared producers' records the adapter normalizes from a recording,
offline, with no gh or network. Run from the root of an engine checkout:
python3 -B records.py <recording.json> [patch.json]

A patch maps a call's joined arguments to a replacement response:
{"stdout": text}, or {"stdout": null, "exit": n} for a provider refusal."""
import json, subprocess, sys
recording = sys.argv[1]
sys.path.insert(0, "mandate/src")
from mandate import delegation as d, evidence as e, gate, shadow  # noqa: E402
rec = json.load(open(recording))
patch = json.load(open(sys.argv[2])) if len(sys.argv) > 2 else {}
answers = {" ".join(c["args"]): c for c in rec["calls"]}
answers.update(patch)
def offline(*args):
    c = answers.get(" ".join(args))
    if c is None:
        raise SystemExit("not recorded: " + " ".join(args))
    if c.get("stdout") is None:
        raise subprocess.CalledProcessError(c.get("exit", 1), "gh")
    return c["stdout"]
gate.gh = offline
gate.configure(*gate.load_scope(shadow.POLICY))
delegation = d.parse(rec["delegation"]["text"], rec["repository"], rec["delegation"]["source"])
snap = shadow.inputs(rec["repository"], rec["pull_request"], delegation)
names = {p.check for _, p in delegation.evidence}
for r in snap.records:
    if r.check in names:
        print(json.dumps({k: getattr(r, k, None) for k in ("check", "conclusion", "check_run_id", "run_id", "run_attempt", "workflow", "head_sha", "base_sha", "compared_sha", "unproven")}))
print("subject", snap.subject.head_sha, snap.subject.base_sha)
for name, _ in delegation.evidence:
    print(f"{name}:", e.evaluate(delegation, (name,), list(snap.records), snap.subject).failures)
