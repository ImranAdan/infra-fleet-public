# Mandate historical replay evidence

Latest: [export v2 / report revision v3](historical-replay/v2/README.md), published 2026-10-29. Export v1 remains unchanged below and in its original directory.

## Interpretation correction — 2026-10-29

The zero-unsafe count is not a measured substantive safety rate. All 29 Fleet rows refusing intent-gate evidence in export v2 have unknown normalized run bases; 13 overlap its 27 historical authority-tagged rows. The reports' legacy `authority_evaluable` denominator means configured authority-tagged rows, not complete evidence observability. Advisor's missing delegation remains N/A coverage. Live captures must establish the actual tested subject; an open-PR association alone does not establish it. See the v2 README for the pinned primary source, same-data controlled comparison and remaining code-review limitation.

## Export v1 / report v2 — historical record

Export v1 and report v2, published 2026-10-28. This branch distributes research data; it is not merged into the application branch and activates no merge authority.

The source observations came from the public Fleet, Advisor and delegation repositories. Files under `historical-replay/v1/` preserve the collected bytes. Check `SHA256SUMS` and cite the publication's full Git commit, rather than only its branch name. Git distribution does not make this branch a protected receipt ledger.

## Source pins

| Input | Full revision |
| --- | --- |
| Engine recorded after collection | `0e16d34c29cd07d96ac9d7bed234bd7688050f23` |
| Engine used for report v2 | `b09b301dc91abd0a05d9675fb1cc6d8c7eb63b32` |
| Replay tooling used to verify report v2 | `6d042f9db698b61fe09671b9dcc8fe915e50d96a` |
| Frozen dictionary first committed | `f1e98eb298ffffc5a920c64eb2366f245f89db17` |
| Delegation repository | `ImranAdan/mandate-delegation@da6db52b465c99d955e07809bdf135104db3bc7f` |

Engine, tooling and dictionary revisions are in `ImranAdan/infra-fleet-public`. Dictionary SHA-256: `0a41cb3815408faa300addbcbaf6fc290b1bbc8f46c07e5544e91f0d43fbd6f0`.

The archive contains its manifest and content-addressed response bodies, not the engine or tooling. There are 986 recorded calls, with shared response bodies stored once.

## What this run establishes

| Repository | PRs | Valid delegation | Configuration refusals | Evaluable authority PRs | Unsafe authorizations |
| --- | ---: | ---: | ---: | ---: | --- |
| Fleet | 68 | 68 | 0 | 27 | 0/27 |
| Advisor | 38 | 0 | 38 | 0 | N/A |

There are 108 items, including two issues, zero replay-error rows, one Fleet PR with missing observations, and 51 disagreements awaiting evidence-backed classification. None of the disagreement rows is a labelled correctness result. Advisor's configuration refusals do not establish substantive authorization safety.

The counterfactual uses provider state observed from 2026-10-27T19:46:24Z, rather than reconstructing each PR's state at merge time. Collection protocol 1 did not record finish time, the initial engine pin, or the tooling pin. Report v2 preserves those limitations. The later tooling revision adds protocol 2 for future collections; it cannot retroactively repair export v1.

The dictionary's end-of-day cut-off yields 50 ever-labelled PRs, two issues and 48 labelled PRs. The earlier discovery instant, 2026-10-15T19:38:38Z, yields 47, two and 45. Three label events occurred between the cut-offs. The dictionary has not been changed to fit the earlier figures.

No live merge, lifecycle, production-enforcement or full release-gate pass is established. Report v1 is retained for provenance; use report v2's per-repository denominators.

## Reproduce

Use a fresh directory, Git, Docker and network access for preparation. Pin this evidence checkout to the full publication commit given in its Jira record.

```sh
git clone --branch mandate-replay-export https://github.com/ImranAdan/infra-fleet-public.git evidence
cd evidence
# Inspect and check out the full publication commit from the research record.
cd historical-replay/v1
shasum -a 256 -c SHA256SUMS
cd ../../..

git init engine
git -C engine remote add origin https://github.com/ImranAdan/infra-fleet-public.git
git -C engine fetch --depth 1 origin b09b301dc91abd0a05d9675fb1cc6d8c7eb63b32
git -C engine checkout --detach FETCH_HEAD
git -C engine fetch --depth 1 origin 6d042f9db698b61fe09671b9dcc8fe915e50d96a
git -C engine archive FETCH_HEAD mandate/replay | tar -x -C engine

mkdir data wheels output
tar -xzf evidence/historical-replay/v1/export.tar.gz -C data
docker pull --platform linux/amd64 python:3.12-slim
docker run --rm --platform linux/amd64 \
  -v "$PWD/engine:/engine:ro" -v "$PWD/wheels:/wheels" \
  python:3.12-slim python3 -m pip download --no-deps --require-hashes \
  --only-binary=:all: -r /engine/.claude/skills/merge-gate/requirements.txt -d /wheels
```

Then run without networking, GitHub credentials, `gh` or a live provider:

```sh
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev \
  -v "$PWD/engine:/engine:ro" -v "$PWD/data:/data:ro" \
  -v "$PWD/wheels:/wheels:ro" -v "$PWD/output:/output" \
  -e PYTHONDONTWRITEBYTECODE=1 -w /engine python:3.12-slim sh -ec '
    python3 -m pip install --no-index --find-links /wheels --target /tmp/deps \
      --require-hashes --only-binary=:all: -r .claude/skills/merge-gate/requirements.txt
    PYTHONPATH=/engine/mandate/src:/tmp/deps python3 -B mandate/replay/report.py \
      /data --json /output/reproduced.json
  '
```

Compare `output/reproduced.json` with `evidence/historical-replay/v1/replay-report-v2.json`. All fields must match except `engine_replayed`: the container has no Git and reports `unknown (no git)`. The engine revision is pinned explicitly during preparation. Counts alone are insufficient; compare rows and disagreements too.

The coordinator independently ran report v2 with Python 3.12.14, PyYAML 6.0.3 and Docker networking disabled. All fields except that expected Git-provenance field matched. Archive entries were checked for safe paths, regular-file types, duplicate names, manifest equality and response SHA-256 correspondence. No credential-pattern hits were found; this is a bounded pattern scan, not proof that arbitrary text cannot contain sensitive information.

## Retention and correction

Keep v1 bytes unchanged. Publish corrections as a new version with new checksums. Removing the agent-created distribution branch reverses its discoverability; it cannot guarantee deletion of already published Git objects or downloaded copies.

