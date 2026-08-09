# Stage 10A — Algorithm 4 candidate preflight qualification

## Outcome

```text
ALGORITHM4_PREFLIGHT_NO_SURVIVOR
```

A complete result. Stage 10A decides which, if either, of AFR-Net and JIPNet can
enter fpbench as Algorithm 4 without an fpbench reconstruction, without invented
preprocessing, and without SD300 being consulted to make it fit. The answer here
is neither, and every reason is named (docs/adr/0089).

Nothing in this directory is a score, a threshold, a decision, a fingerprint
image, a tensor or an upstream byte. What it holds is descriptions: URLs, a
commit SHA, digests, sizes, function names, declared tensor shapes, and the
arguments upstream calls its own functions with.

## The candidates

```text
AFRNET   AFR-Net: Attention-Driven Fingerprint Recognition Network
         Grosz and Jain, IEEE TBIOM vol. 6 no. 1 (2024) pp. 30-42

JIPNET   Joint Identity Verification and Pose Alignment for Partial Fingerprints
         Guan, Pan, Feng and Zhou, IEEE TIFS vol. 20 (2025) pp. 249-263
```

Neither name becomes a production algorithm id under this outcome. Neither has.

## The gate matrix

| Gate | AFR-Net | JIPNet |
| :--- | :--- | :--- |
| 1 `IDENTITY` | **FAIL** | PASS |
| 2 `INPUT_DOMAIN` | not reached | **FAIL** |
| 3 `ARTIFACTS` | not reached | not reached |
| 4 `INFERENCE_ROUTE` | not reached | not reached |
| 5 `SCORE_CONTRACT` | not reached | not reached |
| 6 `TRAINING_PROVENANCE` | not reached | not reached |
| 7 `RUNTIME_SMOKE` | not reached | not reached |

`NOT_REACHED` is not a pass and not a soft failure. It records that the
candidate had already stopped, so the question was never asked. The documents
for those gates carry the gate, the reason, and whatever was observed
incidentally before the stop — labelled as observations, never as conclusions.

Cost of reaching this conclusion: **zero checkpoint bytes**, zero runtimes, zero
SD300 reads, zero scores.

## The blockers

| Candidate | Code | Affects |
| :--- | :--- | :--- |
| AFR-Net | `OFFICIAL_IMPLEMENTATION_NOT_FOUND` | the inference implementation |
| AFR-Net | `OFFICIAL_CHECKPOINT_NOT_FOUND` | the trained weights |
| AFR-Net | `THIRD_PARTY_REIMPLEMENTATION_ONLY` | the reproduction inside JIPNet |
| JIPNet | `BENCHMARK_INPUT_ROUTE_UNRESOLVED` | `canonical_500` to the 160×160 model input |
| JIPNet | `FPBENCH_PREPROCESSING_CHOICE_REQUIRED` | the patch construction the route would need |
| JIPNet | `INPUT_DOMAIN_INCOMPATIBLE` | the released input domain against `canonical_500` |

The two candidates failed for entirely unrelated reasons. AFR-Net stopped on
authenticity: there is no author-supplied artifact to qualify. JIPNet stopped on
input domain: the artifact is official, MIT licensed and well documented, and it
is a matcher for a different kind of input than this benchmark produces.

Neither verdict is a judgement about the quality of either method.

## The two decisive questions

> Does an original-author-supplied executable AFR-Net artifact set exist that
> defines the published verification score route sufficiently for fpbench?

```text
NO
```

> Can the exact released JIPNet checkpoint consume fpbench canonical500 full
> fingerprints through a published deterministic inference transformation,
> without fpbench inventing a partial-patch construction?

```text
NO
```

## The files

| File | What it holds |
| :--- | :--- |
| `candidate-set.json` | both candidates, the gate order, the tie-break criteria, the non-goals, and Stage 8E's record for the one component obtained |
| `afrnet/source-discovery.json` | ten searched locations and what each returned |
| `afrnet/authenticity-report.json` | the origin classification and the excluded evidence |
| `jipnet/source-manifest.json` | the repository pinned by commit, archive digest and cited-file digests |
| `jipnet/authenticity-report.json` | the origin classification and what it covers |
| `<candidate>/input-domain-contract.json` | the declared model input, the observations, and the constructions fpbench refuses to invent |
| `<candidate>/artifact-manifest.json` | `NOT_REACHED`, with a sketch of what the gate would have had to close over |
| `<candidate>/inference-route-audit.json` | `NOT_REACHED`, with route observations |
| `<candidate>/score-contract.json` | `NOT_REACHED`, with score observations |
| `<candidate>/training-provenance.json` | `NOT_REACHED`, with dataset observations and the SD300 overlap status |
| `<candidate>/runtime-smoke.json` | `NOT_REACHED`, with runtime red flags |
| `<candidate>/preflight-report.json` | the verdict, gate by gate, with every blocker and the decisive question |
| `candidate-comparison.json` | both side by side, and why no ranking was performed |
| `stage-10a-finalization.json` | the marker |

## What resolved

* JIPNet's repository is pinned to `XiongjunGuan/JIPNet` at
  `40d8445c5b3afa55b409ae3221377e54e3ace53f`. No branch is an identity. The
  archive was acquired twice and came back byte-identical.
* Every upstream statement this stage rests on cites a file by SHA-256, and each
  digest was computed from the pinned archive and cross-checked against
  `raw.githubusercontent` at the same commit.
* JIPNet's identity gate passed on two sentences that name each other: the
  paper's abstract names the repository, and the repository's README calls
  itself the official implementation.
* Both candidates' SD300 overlap status is `NO_EVIDENCE_FOUND` — which is not
  `PROVEN_ABSENT`, and is never converted into it.
* Exactly one third-party component was obtained: the JIPNet source archive,
  MIT, `ALLOWED` under Stage 8E's engine. No checkpoint of either candidate was
  fetched.

## What was deliberately not done

```text
no production adapter        no threshold             no SD300 read
no AlgorithmConfig           no calibration           no crop optimisation
no 6,000 comparisons         no metrics               no model selection from performance
no DecisionProfile           no fine-tuning           no ranking of failed candidates
```

Author-reported accuracy was not read and did not enter any comparison. No gate
was weakened to produce an Algorithm 4.

## What opens

```text
opens_algorithm4_artifact_qualification: false
opens_candidate_search:                  true
```

The slot stays empty. A third candidate is the response to this outcome; a lower
bar is not (docs/adr/0093).
