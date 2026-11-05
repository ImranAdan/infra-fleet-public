# Intent Gate tested-base capture, v2

This is the corrected capture contract, replayed on the same real provider bytes as [v1](../v1/README.md). Review of v1's engine (`46fccac`) found two gaps in its trust contract:

1. Input echo lines counted anywhere in a job log, even stripped of their step or under another action's block.
2. A record whose capture lacked its compared merge, or declared that it proved nothing, could still be read back, satisfy evidence and be recorded.

v1's bytes are unchanged, and this version reuses its recordings. This is research only: nothing here is live, enforced or authorized, and the engine is inactive.

The corrected contract is `tested()` in `mandate/src/mandate/evidence.py` at the after-engine pin, documented in that revision's `mandate/README.md` under "The tested base". It adds two steps to v1's:

- **The comparing step must be identified and must have run.** The producer's executed source must hold exactly one supported comparing step: the Intent Gate action pinned to a full commit, given `base-sha` and `head-sha`. The job's steps must list that step by name with conclusion `success`.
- **The inputs must come from that step's own block.** The job log must open that step's block exactly once (`##[group]Run <its uses>`), and the inputs count only from its `with:` echo. Inputs echoed anywhere else make the log ambiguous.

A record's proof is now whole or absent: a base with its compared merge and no reason, or neither, with the reason. Any other shape cannot be built or read back.

## Pins

| Input | Full revision or hash |
| --- | --- |
| Engine after (corrected contract) | `14297614e199ba0a3a81ffba9372d6e7d3a90e59` |
| Engine before (v1's) | `46fccac89d472a105a5d3a09f04eed445d8ff6d2` |
| Recording `../v1/recordings/pr-249.json` | SHA-256 `a8c302a15a6550f011271d9613c1eb20f8332308b5f348131e4d3630f15f7b35` |
| Recording `../v1/recordings/pr-248.json` | SHA-256 `5c24bca3fe5e974f4f71bc657990e74e46776bf4f83b260a54aaac6d9eb8ace2` |

## Files

- `variants/*.json` each replace responses in `pr-249.json`'s real bytes:
  - `another-action-block`: the comparing step's `##[group]Run ImranAdan/infra-fleet-advisor-public/.github/actions/intent-gate@` header becomes `##[group]Run example/unrelated-action@`. The review used this edit to reproduce the gap.
  - `stripped-context`: the log becomes only its two input echo lines.
  - `skipped-step`: the job reports the comparing step as `skipped`.
  - `unsupported-producer`: the shared gate workflow uses another action, at both the merge and the base.
- `tools/proof.py` reads the recording's accepted evidence back as recorded, and with its compared merge removed, its capture declared unproven, or its base removed. Replays of controls and variants use v1's `tools/records.py`.
- `results/*-46fccac.txt` and `results/*-1429761.txt` are the outputs from each engine. The `pr-249-v1-*` files replay v1's variants through the corrected engine. `SHA256SUMS` covers every file here.

## Results

| Case (real bytes unless noted) | Before `46fccac` | After `1429761` |
| --- | --- | --- |
| #249 control | accepted, base `308ca0a`, compared `5941be3` (v1) | **accepted**, base `308ca0a`, compared `5941be3`: the real job lists `Compare declared intent at base and merge result` as `success`, and the real log opens its block once |
| #248 control | another BASE: `9da742b` against the PR's `b6a59be` (v1) | the same |
| Another action's block | **accepted** | refused: `log does not show exactly one comparison of … by its comparing step` |
| Stripped context | **accepted** | refused: the same reason |
| Comparing step skipped | **accepted** | refused: `did not run its comparing step 'Compare declared intent at base and merge result' to success` |
| Producer without a supported step | **accepted** | refused: `producer has no single supported comparing step` |
| Accepted evidence, compared merge removed | **read back** | refused: `incomplete capture proof` |
| Accepted evidence, capture declared unproven | **read back** | refused: the same reason |
| Accepted evidence, base removed | read back (base unknown) | refused: the same reason |
| v1's six variants | refused (v1) | still refused, for the same reasons. The log cases now add "by its comparing step". |

Every refusal is `EVIDENCE_NOT_APPLICABLE` (VERIFY), with the tested base unknown. None authorizes.

## Reproduce

```sh
git clone --branch mandate-replay-export https://github.com/ImranAdan/infra-fleet-public.git evidence
# Check out the full publication commit named in the research record, then:
(cd evidence/tested-base-capture/v1 && shasum -a 256 -c SHA256SUMS)
(cd evidence/tested-base-capture/v2 && shasum -a 256 -c SHA256SUMS)

git init engine
git -C engine remote add origin https://github.com/ImranAdan/infra-fleet-public.git
git -C engine fetch --depth 1 origin 14297614e199ba0a3a81ffba9372d6e7d3a90e59
git -C engine checkout --detach FETCH_HEAD
cd engine
uv sync --locked --project mandate
V1=../evidence/tested-base-capture/v1 V2=../evidence/tested-base-capture/v2
uv run --locked --project mandate python3 -B $V1/tools/records.py $V1/recordings/pr-249.json $V2/variants/another-action-block.json \
  | diff - $V2/results/pr-249-another-action-block-1429761.txt
uv run --locked --project mandate python3 -B $V2/tools/proof.py $V1/recordings/pr-249.json | diff - $V2/results/pr-249-proof-1429761.txt
```

For the before files, use `46fccac89d472a105a5d3a09f04eed445d8ff6d2` as the engine. Run from the engine root.

## Limits

Contract v1 is keyed to the comparing step, not to the check's name. A job proves its base only by running the supported Intent Gate comparison in its own executed source. Any other producer stays unknown until it has its own contract version. The other limits are v1's.

Keep these bytes unchanged. Publish any correction as a new version.
