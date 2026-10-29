# Historical replay export v2 / report revision v3

Published 2026-10-29 as research evidence. This directory preserves the four original files and their checksums. Report revision v3 uses report schema version 2; the filename is a revision label.

## Pins and collection

| Input | Full revision |
| --- | --- |
| Collection engine, clean at start and end | `e7a053ad5ca4e86cf49a064c6a9b4ca226da1be4` |
| Replay engine | `e7a053ad5ca4e86cf49a064c6a9b4ca226da1be4` |
| Collector/reporter tooling, clean | `6d042f9db698b61fe09671b9dcc8fe915e50d96a` |
| Delegation root | `ImranAdan/mandate-delegation@da6db52b465c99d955e07809bdf135104db3bc7f` |
| Frozen dictionary | version 1, SHA-256 `0a41cb3815408faa300addbcbaf6fc290b1bbc8f46c07e5544e91f0d43fbd6f0` |

Engine and tooling commits are in Fleet. Collection protocol 2 ran from 2026-10-28T21:57:15Z to 2026-10-28T22:06:07Z, recording 1,106 calls, zero collection errors and 108 items. The archive expands into `export-v2/`, containing its manifest and content-addressed response bodies. It contains no engine or tooling code.

## Interpretation

Fleet has 68 configured PRs and 27 historical authority-tagged PRs; none authorizes. Advisor has 38 configuration refusals and no substantive policy coverage. Replay errors are zero, one Fleet row has missing observations, and 51 disagreements remain unadjudicated.

**Zero unsafe authorizations is an observed count, not an estimated safety rate.** All 29 Fleet rows refusing intent-gate evidence have an unknown normalized run base. Thirteen of those rows overlap the 27 historical authority-tagged rows. The report's legacy `authority_evaluable` field counts configured authority-tagged rows; it does not certify complete evidence observability.

GitHub's [pinned OpenAPI schema](https://github.com/github/rest-api-description/blob/c66e298030d4070b70a569dcd4268b3a041b5380/descriptions/api.github.com/api.github.com.json) describes `workflow-run.pull_requests` as currently open associations and warns they need not identify the triggering PR. Missing association/base is unknown. An open association alone also does not prove which base a run tested. Preserve fail-closed behavior until that subject binding is established from a trusted source.

Use live shadow captures with demonstrated tested-subject provenance or trusted decision-time evidence to test applicability. A receipt merely repeating an unproven association does not repair it. These results are a counterfactual over provider state at collection, not reconstructed as-of-merge decisions.

The coordinator replayed baseline engine `043ad63b523ba774ca60a3f087e115189bca2aa5` and the fact engine against **the same export-v2 bytes**, with the same tooling and no networking. Ten rows change outcomes/reasons, all losing `UNDELEGATED:dependency-manifest`; only Fleet #166 changes outcome, ESCALATE to VERIFY. No row authorizes. Negative `lockfile_sibling` coverage is fixture-only in this corpus.

The pinned fact implementation has a separately reproduced review finding: a requirement version containing runtime environment substitution can be incorrectly reported as exactly pinned. Keep this historical artifact unchanged; test the correction separately. Neither this export nor successful reproduction establishes implementation readiness, live merging, lifecycle health or a full release-gate pass.

## Verify the distribution

From this directory:

```sh
shasum -a 256 -c SHA256SUMS
```

The archive, manifest and report hashes are recorded independently in Jira. Cite the full publication commit rather than only the mutable branch pointer. Export v1 remains available unchanged in its sibling directory.

## Reproduce offline

Start in an empty directory with Git and Docker. Network access is used only to fetch pinned sources, the evidence and the pinned parser wheel.

```sh
git clone --branch mandate-replay-export https://github.com/ImranAdan/infra-fleet-public.git evidence
# Check out the full evidence publication commit from the research record.
git init engine
git -C engine remote add origin https://github.com/ImranAdan/infra-fleet-public.git
git -C engine fetch --depth 1 origin e7a053ad5ca4e86cf49a064c6a9b4ca226da1be4
git -C engine checkout --detach FETCH_HEAD
git -C engine fetch --depth 1 origin 6d042f9db698b61fe09671b9dcc8fe915e50d96a
git -C engine archive FETCH_HEAD mandate/replay | tar -x -C engine
mkdir data wheels output
tar -xzf evidence/historical-replay/v2/export-v2.tar.gz -C data
docker pull --platform linux/amd64 python:3.12-slim
docker run --rm --platform linux/amd64 \
  -v "$PWD/engine:/engine:ro" -v "$PWD/wheels:/wheels" \
  python:3.12-slim python3 -m pip download --no-deps --require-hashes \
  --only-binary=:all: -r /engine/.claude/skills/merge-gate/requirements.txt -d /wheels
docker run --rm --platform linux/amd64 --network none --read-only \
  --tmpfs /tmp:rw,nosuid,nodev \
  -v "$PWD/engine:/engine:ro" -v "$PWD/data/export-v2:/data:ro" \
  -v "$PWD/wheels:/wheels:ro" -v "$PWD/output:/output" \
  -e PYTHONDONTWRITEBYTECODE=1 -w /engine python:3.12-slim sh -ec '
    python3 -m pip install --quiet --no-index --find-links /wheels --target /tmp/deps \
      --require-hashes --only-binary=:all: -r .claude/skills/merge-gate/requirements.txt
    PYTHONPATH=/engine/mandate/src:/tmp/deps python3 -B mandate/replay/report.py \
      /data --json /output/reproduced.json
  '
```

The coordinator ran this offline command successfully. The complete output must match `replay-report-v3.json` except `engine_replayed`, which is `unknown (no git)` in the container; the engine source was pinned during preparation. Compare all rows, reasons, populations, observations and disagreements, not just counts. The same-data baseline comparison uses the baseline engine pin above with the same tool revision and archived inputs.

Archive verification checked safe paths, unique names, permitted directory/regular-file types, manifest equality, every response hash and all 1,106 call-body references. The bounded credential-pattern scan found no matches. This branch distributes already-public research data; it is not a protected ledger. Corrections require a new version. Removing its agent-created distribution branch cannot erase already downloaded or retrievable Git objects.

