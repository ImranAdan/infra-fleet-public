# Intent Gate tested-base capture, v1

These are real provider observations of the base and synthetic merge that the Intent Gate compared, captured under evidence capture contract v1. Each recording is replayed offline: two real controls, then missing, mixed and spoofed variants of one control's real bytes. This is research only. Nothing here is live, enforced or authorized; the engine is inactive.

Contract v1 is `tested()` in `mandate/src/mandate/evidence.py` at the engine pin below, documented in that revision's `mandate/README.md` under "The tested base". Every step is required: the job is the check run, in its run's attempt, on its head; the run records one pull request merge commit it ran from; that commit's parents are a base and the head; the producer workflows there match the base's; and the runner echoes the comparing step's inputs (`base-sha`, `head-sha`) once, naming that base and merge. Otherwise the base is unknown, with a reason. The open-PR association is never read.

## Pins

| Input | Full revision |
| --- | --- |
| Engine: capture contract v1, evidence record v2, adapter v3 | `46fccac89d472a105a5d3a09f04eed445d8ff6d2` |
| Engine before, which reads the base from the open-PR association (record v1) | `2ba52f396dc4fa58d3ada6213aefbb098423354c` |
| Delegation | `ImranAdan/mandate-delegation@da6db52b465c99d955e07809bdf135104db3bc7f` |
| Advisor action in the observed gate runs | `ImranAdan/infra-fleet-advisor-public@770a258a423c17ec4c3ca0cacb25b4c842eec6d0` |

## Files

- `recordings/pr-249.json`, `recordings/pr-248.json`: every `gh` call the real shadow adapter made for the pull request, read-only, plus the delegation text and the decision. Each call keeps its arguments, exit code, exact output and that output's SHA-256. Collection times are inside (2026-11-04).
- `recordings/expired-job-log.json`: a job completed on 2026-04-02. Its record is still served, but its log is refused with `gh: Server Error (HTTP 410)`.
- `variants/*.json`: each replaces one response in `pr-249.json`'s real bytes.
- `tools/record.py` collects; `tools/records.py` replays offline, with no `gh` or network, and prints the declared producers' records and evaluations.
- `results/*.txt`: the replay outputs listed below. `SHA256SUMS` covers every file.

## Results

| Case | Bytes | Tested base | Compared merge | Intent-gate evidence |
| --- | --- | --- | --- | --- |
| #249, open: applicability-valid control | real | `308ca0a` | `5941be3` (parents `308ca0a`, `043ad63`) | accepted; the PR as a whole stays ESCALATE (reserved surfaces) |
| #249, before engine | same | `308ca0a`, but read from the open-PR association, which proves nothing | none | accepted |
| #248, closed: concrete different base | real | `9da742b` | `e4ff523` | `EVIDENCE_NOT_APPLICABLE`: about another BASE (the PR's recorded base is `b6a59be`) |
| #248, before engine | same | unknown: the association is empty once the PR closed | none | `EVIDENCE_NOT_APPLICABLE`: tested base is unknown |
| Expired log | #249 + the real 410 | unknown | unknown | `job … log is unavailable, expired or missing` |
| Missing job | #249 + a 404 | unknown | unknown | `job … is unavailable` |
| Forged echo | #249's log + one extra `base-sha` echo line | unknown | unknown | `job … log does not show exactly one comparison of …` |
| Another run's log | #249 with #248's genuine gate log | unknown | unknown | same as above |
| Mixed attempt | #249's job reporting attempt 2 | unknown | unknown | `job … is not attempt 1 of run … for this check` |
| Edited producer | #249's shared gate workflow at the merge compares `HEAD~5` | unknown | unknown | `producer .github/workflows/intent-gate-run.yml differs from its version at the tested base` |

Every unproven case refuses with `EVIDENCE_NOT_APPLICABLE` (VERIFY). None authorizes, and no case fills in the PR's base.

The #248 control is a real stale comparison. Its gate ran on 2026-10-24 against `9da742b`. The PR's recorded base is `b6a59be`, so the gate compared a base other than the one the PR records. The open-PR association could not show this: it is empty once a PR closes.

## Reproduce

```sh
git clone --branch mandate-replay-export https://github.com/ImranAdan/infra-fleet-public.git evidence
# Check out the full publication commit named in the research record, then:
(cd evidence/tested-base-capture/v1 && shasum -a 256 -c SHA256SUMS)

git init engine
git -C engine remote add origin https://github.com/ImranAdan/infra-fleet-public.git
git -C engine fetch --depth 1 origin 46fccac89d472a105a5d3a09f04eed445d8ff6d2
git -C engine checkout --detach FETCH_HEAD
cd engine
uv sync --locked --project mandate
E=../evidence/tested-base-capture/v1
uv run --locked --project mandate python3 -B $E/tools/records.py $E/recordings/pr-249.json | diff - $E/results/pr-249-after-46fccac.txt
uv run --locked --project mandate python3 -B $E/tools/records.py $E/recordings/pr-249.json $E/variants/forged-echo.json \
  | diff - $E/results/pr-249-forged-echo-after-46fccac.txt
```

For the before rows, use `2ba52f396dc4fa58d3ada6213aefbb098423354c` as the engine. Replays must run from the engine root, because the adapter reads the merge-gate policy there.

## Limits

- Contract v1 covers one comparing step, the Intent Gate action's. Another producer needs its own contract version.
- This covers two pull requests. It does not recollect the historical corpus, and it does not reclassify export v2's rows or disagreements.
- The variants are edited copies of real bytes. They test that the contract rejects such observations, not how GitHub behaves. No expired Intent Gate job was found, so the 410 response comes from a job of another workflow in the same repository.
- Two observed facts are not documented. One is that an Actions job's ID equals its check run's ID; the contract checks `check_run_url` rather than assuming it. The other is the 410 status: the [job logs endpoint](https://docs.github.com/en/rest/actions/workflow-jobs#download-job-logs-for-a-workflow-run) documents only its redirect.
- The open-PR association proves nothing about the tested base. The pinned REST description says those pull requests "are open with a `head_sha` or `head_branch` that matches the workflow run" and "do not necessarily indicate pull requests that triggered the run" ([rest-api-description at `c66e298`](https://github.com/github/rest-api-description/blob/c66e298030d4070b70a569dcd4268b3a041b5380/descriptions/api.github.com/api.github.com.json), `workflow-run.pull_requests`). For `pull_request`, `GITHUB_SHA` is the last merge commit of `refs/pull/<n>/merge` ([events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request)).

Keep these bytes unchanged. Publish any correction as a new version.
