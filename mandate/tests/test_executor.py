"""Executor checks. Run: python3 mandate/tests/test_executor.py

The real executor, receipts and ledger run against fakes: FakeGit (the
fast-forward-only ledger from test_ledger) and FakeGitHub below, a pull
request whose merge endpoint behaves like GitHub's. Nothing calls GitHub, and
nothing here is evidence that a live merge works.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from test_ledger import REF, REPO, FakeGit  # noqa: E402
from test_receipt import ACTORS, BASE, ENF, EXAMPLE, HEAD, POLICY, VERSIONS, decision  # noqa: E402

from mandate import delegation as d  # noqa: E402
from mandate import evidence as e  # noqa: E402
from mandate import executor as x  # noqa: E402
from mandate import ledger as l  # noqa: E402
from mandate import receipt as r  # noqa: E402

AGENT = "fleet-agent[bot]"
LIVE = EXAMPLE.replace('mode = "shadow"', 'mode = "enforce"').replace("agents = []", f'agents = ["{AGENT}"]')
DELEG = d.parse(LIVE, REPO, POLICY)
PR = f"repos/{REPO}/pulls/7"


class FakeGitHub:
    """One pull request. Reads go through the instance; writes only through a
    token from mint(). The merge endpoint refuses a stale sha (409) and a
    closed or merged PR (405), as GitHub does."""

    def __init__(self, author: str = AGENT) -> None:
        self.pr = {"state": "open", "merged": False, "merge_commit_sha": None,
                   "user": {"login": author}, "head": {"sha": HEAD}, "base": {"sha": BASE}}
        self.messages: dict[str, str] = {}
        self.merges: list[dict] = []  # merge requests GitHub carried out
        self.minted = 0
        self.reads = 0
        self.on_read: dict[int, object] = {}  # read number -> change made just before it
        self.refuse: list[int] = []  # statuses for the next merge requests, not carried out
        self.lose: list[int] = []  # statuses for the next merge requests, carried out

    def __call__(self, method: str, path: str, body):
        assert method == "GET", f"read-only transport used for {method} {path}"
        if path == PR:
            self.reads += 1
            change = self.on_read.pop(self.reads, None)
            if change:
                change(self.pr)
            return dict(self.pr)
        if path.startswith(f"repos/{REPO}/commits/"):
            return {"commit": {"message": self.messages[path.rsplit("/", 1)[1]]}}
        raise AssertionError(f"unexpected {method} {path}")

    def mint(self):
        self.minted += 1

        def write(method: str, path: str, body):
            assert (method, path) == ("PUT", f"{PR}/merge"), (method, path)
            if self.refuse:
                raise l.ApiError(self.refuse.pop(0))
            if self.pr["state"] != "open":
                raise l.ApiError(405, "Pull Request is not mergeable")
            if body["sha"] != self.pr["head"]["sha"]:
                raise l.ApiError(409, "Head branch was modified")
            sha = f"{len(self.merges) + 1:040x}"
            self.merges.append(body)
            self.messages[sha] = f"{body['commit_title']}\n\n{body['commit_message']}"
            self.pr.update(state="closed", merged=True, merge_commit_sha=sha)
            if self.lose:
                raise l.ApiError(self.lose.pop(0), "the response was lost")
            return {"sha": sha, "merged": True}

        return write


def evaluate(outcome: str = "AUTHORIZE"):
    """What the adapter and decide() give for the PR as just read."""
    def receipt(pr: dict, enforcement: str) -> dict:
        subject = e.Subject(REPO, pr["head"]["sha"], pr["base"]["sha"], POLICY)
        return r.build(decision(outcome, subject), 7, enforcement, versions=VERSIONS, actors=ACTORS,
                       evaluated_at="2026-10-28T00:00:00Z")
    return receipt


def run(hub: FakeGitHub, git: FakeGit, *, outcome="AUTHORIZE", delegation=DELEG, enforcement=lambda: ENF, evaluator=None):
    return x.execute(hub, hub.mint, git, REPO, REF, REPO, 7, delegation, evaluator or evaluate(outcome), enforcement)


def revisions(git: FakeGit) -> list[str]:
    return [line for line in git.files(REF).get(l.LEDGER, b"").decode().splitlines() if line]


def main() -> int:
    # A delegated AUTHORIZE merges exactly the evaluated head, once, with the
    # trailers naming the receipt revision recorded just before the merge.
    hub, git = FakeGitHub(), FakeGit()
    code, sha = run(hub, git)
    assert (code, hub.minted, len(hub.merges)) == ("MERGED", 1, 1), (code, hub.minted, hub.merges)
    assert hub.merges[0]["sha"] == HEAD and hub.merges[0]["merge_method"] == "squash", hub.merges
    named = r.parse_trailers(hub.messages[sha])
    assert named and named["Mandate-Decision"] == r.decision_id(REPO, 7, HEAD, BASE, POLICY, ENF), named
    assert len(revisions(git)) == 1

    # A duplicate or late wake converges: no token, no second merge.
    assert run(hub, git) == ("ALREADY_MERGED", sha) and (hub.minted, len(hub.merges)) == (1, 1)

    # Refusals record their receipt, and never mint a token or merge.
    hub, git = FakeGitHub(), FakeGit()
    assert run(hub, git, outcome="ESCALATE") == ("REFUSED", "ESCALATE")
    assert (hub.minted, hub.merges, len(revisions(git))) == (0, [], 1)

    # Shadow mode, an unregistered proposer and the owner as an agent never merge.
    shadow = d.parse(LIVE.replace('mode = "enforce"', 'mode = "shadow"'), REPO, POLICY)
    # parse() refuses a live delegation listing the owner as an agent; the
    # executor refuses one built any other way too.
    colliding = dataclasses.replace(DELEG, agents=(AGENT, "ImranAdan"))
    for name, hub, delegation, want in (
        ("shadow", FakeGitHub(), shadow, "SHADOW"),
        ("stranger", FakeGitHub("someone"), DELEG, "PROPOSER_UNREGISTERED"),
        ("owner", FakeGitHub("ImranAdan"), DELEG, "PROPOSER_UNREGISTERED"),
        ("collision", FakeGitHub("ImranAdan"), colliding, "PROPOSER_UNREGISTERED"),
    ):
        git = FakeGit()
        code, _ = run(hub, git, delegation=delegation)
        assert (code, hub.minted, hub.merges, revisions(git)) == (want, 0, [], []), (name, code)

    # The subject is re-read after the token is minted; any drift refuses by name.
    for name, change, want in (
        ("push", lambda pr: pr.update(head={"sha": "c" * 40}), "HEAD_CHANGED"),
        ("base", lambda pr: pr.update(base={"sha": "f" * 40}), "BASE_CHANGED"),
    ):
        hub, git = FakeGitHub(), FakeGit()
        hub.on_read[2] = change
        code, _ = run(hub, git)
        assert (code, hub.merges) == (want, []), (name, code)
    hub, git = FakeGitHub(), FakeGit()
    snapshots = iter([ENF, ENF, "sha256:" + "9" * 64])
    code, _ = run(hub, git, enforcement=lambda: next(snapshots))
    assert (code, hub.merges) == ("ENFORCEMENT_DRIFT", []), code

    hub, git = FakeGitHub(), FakeGit()

    def unreadable():
        raise l.LedgerError("ENFORCEMENT_MISSING", "no ruleset protects the base branch")
    assert run(hub, git, enforcement=unreadable)[0] == "ENFORCEMENT_MISSING" and hub.minted == 0

    # Authorization is decided again after the token is minted. Evidence that
    # changed meanwhile, on the same head, base and enforcement, refuses: the
    # refusal is recorded and nothing is merged.
    hub, git = FakeGitHub(), FakeGit()
    outcomes, seen = iter(["AUTHORIZE", "ESCALATE"]), []

    def changing(pr: dict, enforcement: str) -> dict:
        seen.append(next(outcomes))
        return evaluate(seen[-1])(pr, enforcement)
    code = run(hub, git, evaluator=changing)
    assert (code, seen, hub.minted, hub.merges) == (("REFUSED", "ESCALATE"), ["AUTHORIZE", "ESCALATE"], 1, []), code
    assert [json.loads(line)["outcome"] for line in revisions(git)] == ["ESCALATE"], revisions(git)

    # An expired token is replaced and the whole subject decided again: one merge.
    hub, git = FakeGitHub(), FakeGit()
    hub.refuse = [401]
    code, _ = run(hub, git)
    assert (code, hub.minted, len(hub.merges), len(revisions(git))) == ("MERGED", 2, 1, 2), code

    # A lost merge response is settled by reading the provider back, not by retrying.
    hub, git = FakeGitHub(), FakeGit()
    hub.lose = [502]
    code, sha = run(hub, git)
    assert (code, len(hub.merges)) == ("MERGED", 1) and sha == hub.pr["merge_commit_sha"], code

    # A merge GitHub refuses (required checks, rulesets) is reported, not retried.
    hub, git = FakeGitHub(), FakeGit()
    hub.refuse = [405]
    assert run(hub, git) == ("NOT_MERGED", "HTTP 405 ") and hub.merges == []

    # Refused because someone else merged a newer head meanwhile: unmanaged.
    hub, git = FakeGitHub(), FakeGit()
    hub.refuse = [409]
    hub.messages["d" * 40] = "fix: merged by hand"
    hub.on_read[3] = lambda pr: pr.update(state="closed", merged=True, merge_commit_sha="d" * 40, head={"sha": "c" * 40})
    assert run(hub, git) == ("UNMANAGED_MERGE", "d" * 40) and hub.merges == []

    # Every merged read-back is settled by its anchors, not by its head. Another
    # actor merged the same head without Mandate's trailers: unmanaged.
    hub, git = FakeGitHub(), FakeGit()
    hub.refuse = [405]
    hub.messages["d" * 40] = "fix: merged without Mandate"
    hub.on_read[3] = lambda pr: pr.update(state="closed", merged=True, merge_commit_sha="d" * 40)
    assert run(hub, git) == ("UNMANAGED_MERGE", "d" * 40) and hub.merges == []
    # Another Mandate worker merged the same head under its own recorded
    # AUTHORIZE: that worker's merge, not this one's.
    hub, git = FakeGitHub(), FakeGit()
    hub.refuse = [405]

    def competitor(pr: dict) -> None:
        other = evaluate()(pr, ENF)
        message = r.trailers(git, REPO, REF, other["subject"], other, DELEG, after=r.pr_latest(git, REPO, REF, REPO, 7))
        hub.messages["b" * 40] = f"Merge pull request #7\n\n{message}"
        pr.update(state="closed", merged=True, merge_commit_sha="b" * 40)
    hub.on_read[3] = competitor
    assert run(hub, git) == ("ALREADY_MERGED", "b" * 40) and hub.merges == [] and len(revisions(git)) == 2

    # A merge Mandate did not make is reported as unmanaged.
    hub, git = FakeGitHub(), FakeGit()
    hub.pr.update(state="closed", merged=True, merge_commit_sha="e" * 40)
    hub.messages["e" * 40] = "fix: merged by hand"
    assert run(hub, git) == ("UNMANAGED_MERGE", "e" * 40) and hub.minted == 0
    # So is one whose trailers name a recorded refusal about this head.
    hub, git = FakeGitHub(), FakeGit()
    entry, chain, _ = r.record(git, REPO, REF, evaluate("ESCALATE")(hub.pr, ENF), DELEG, after=None)
    named = zip(r.TRAILERS, (entry["decision_id"], entry["receipt_digest"], chain))
    hub.messages["a" * 40] = "fix: merged\n\n" + "\n".join(f"{k}: {v}" for k, v in named)
    hub.pr.update(state="closed", merged=True, merge_commit_sha="a" * 40)
    assert run(hub, git) == ("UNMANAGED_MERGE", "a" * 40) and hub.minted == 0
    # So is one whose trailers name a decision about another head.
    hub, git = FakeGitHub(), FakeGit()
    code, sha = run(hub, git)
    hub.pr.update(head={"sha": "c" * 40})
    assert run(hub, git) == ("UNMANAGED_MERGE", sha), code

    # A closed PR is left alone.
    hub, git = FakeGitHub(), FakeGit()
    hub.pr.update(state="closed")
    assert run(hub, git) == ("CLOSED", "") and hub.minted == 0

    # A concurrent recorder makes the decision stale: decide again, merge once.
    hub, git = FakeGitHub(), FakeGit()

    def racer():
        other = evaluate("ESCALATE")(hub.pr, ENF)
        after = r.pr_latest(git, REPO, REF, REPO, 7)
        r.record(git, REPO, REF, other, DELEG, after=after)
    git.before_advance = racer
    code, _ = run(hub, git)
    assert (code, len(hub.merges), len(revisions(git))) == ("MERGED", 1, 2), (code, revisions(git))

    print("executor tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
