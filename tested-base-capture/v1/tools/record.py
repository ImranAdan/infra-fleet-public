"""Record every provider response the real shadow adapter reads for one PR.

Run from the root of an engine checkout (it reads the merge-gate policy there):
python3 -B record.py <engine commit> <repository> <pr> <delegation sha> <out.json>
Read-only: gh api GETs only. Each response is kept exactly, with its SHA-256.
"""
import datetime, hashlib, json, subprocess, sys
engine, repository, number, dsha, out = sys.argv[1:]
sys.path.insert(0, "mandate/src")
now = lambda: datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
started = now()
from mandate import decision as m, delegation as d, gate, shadow  # noqa: E402

calls = []
real = gate.gh


def recording(*args):
    try:
        text = real(*args)
    except subprocess.CalledProcessError as exc:
        calls.append({"args": list(args), "exit": exc.returncode, "stderr": exc.stderr, "stdout": None})
        raise
    calls.append({"args": list(args), "exit": 0, "stdout": text,
                  "sha256": hashlib.sha256(text.encode()).hexdigest()})
    return text


gate.gh = recording
path = d.path_for(repository)
dtext = real("api", "-H", "Accept: application/vnd.github.raw+json",
             f"repos/{d.DELEGATION_REPOSITORY}/contents/{path}?ref={dsha}")
policy = f"{d.DELEGATION_REPOSITORY}@{dsha}:{path}"
gate.configure(*gate.load_scope(shadow.POLICY))
decision = m.decide(shadow.inputs(repository, int(number), d.parse(dtext, repository, policy)))
json.dump({"engine": engine, "collected": {"started": started, "finished": now()}, "repository": repository, "pull_request": int(number), "delegation": {"source": policy, "text": dtext},
           "calls": calls, "decision": decision.to_dict()}, open(out, "w"), indent=1, sort_keys=True)
print(json.dumps({"outcome": decision.outcome, "reasons": [[r.code, r.detail] for r in decision.reasons],
                  "subject": decision.to_dict()["subject"],
                  "accepted": [[a["requirement"], [{k: x[k] for k in ("check_run_id", "run_id", "head_sha", "base_sha", "compared_sha", "unproven")} for x in a["records"]]] for a in decision.to_dict()["accepted"]]}, indent=1))
