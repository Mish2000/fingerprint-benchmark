# Stage 9A — FLARE full-route artifact and method qualification

## Outcome

```text
FLARE_FULL_ROUTE_BLOCKED
```

A complete result. Stage 9A decides whether a faithful implementation identity of
FLARE can be frozen from the published method, the two official repositories,
the official pretrained artifacts and integration-neutral glue. The answer here
is no, and every reason is named (docs/adr/0085).

Nothing in this directory is a score, a threshold, a decision, a fingerprint
image, a tensor or an upstream byte. What it holds is descriptions: URLs, commit
SHAs, digests, sizes, function names, counts and the arguments those functions
are called with.

## The candidate

```text
flare_fdd_d6_dualpose_dualenh_maxcosine
```

FLARE FDD `D = 6`, dual-pose × dual-enhancement, max overlap-masked cosine.
Four branches — `voting_unetenh`, `voting_priorenh`, `regression_unetenh`,
`regression_priorenh` — fused by a maximum. The binary FDD route is excluded
(docs/adr/0086).

The name becomes a production algorithm id only under a READY outcome. It has
not.

## The blockers

| Code | Affects |
| :--- | :--- |
| `SCORE_AFFECTING_PARAMETER_UNRESOLVED` | `aligned_crop_512.border_fill`, `downsample_512_to_256.interpolation` |
| `PAPER_CODE_CONTRADICTION` | `alignment_then_enhancement_ordering` |
| `FULL_FOUR_BRANCH_ROUTE_UNRESOLVED` | `four_branch_orchestration` |
| `ARTIFACT_IDENTITY_UNRESOLVED` | the six checkpoints |
| `REQUIRED_ARTIFACT_MISSING` | the six checkpoints |
| `RESEARCH_USE_BLOCKED` | the six checkpoints |
| `CHECKPOINT_COMPATIBILITY_UNRESOLVED` | the six checkpoints |

The three route blockers are the stage. The paper explicitly puts the aligned
512×512 crop before enhancement and the downsample after it. The only upstream
code that aligns instead fuses alignment and downsampling into one interpolation
of the unenhanced original, leaving no intermediate image or point of insertion.
The order is known; the crop's border fill and the downsample's kernel are not,
and neither is a free parameter (docs/adr/0087, docs/adr/0088).

The four artifact blockers all follow from one fact: a Google Drive file id is a
locator, not an identity. Enrolling the six checkpoints from their official
locators would resolve them. It would not resolve the route.

## The files

| File | What it holds |
| :--- | :--- |
| `upstream-source-manifest.json` | both repositories, pinned by commit, archive digest and size |
| `artifact-manifest.json` | all ten artifacts, their locators, their identities and what this machine had of them |
| `third-party-usage-manifest.json` | Stage 8E's observation, decision and usage record for each |
| `training-provenance.json` | what the released artifacts were trained on, and what was not found |
| `checkpoint-compatibility.json` | each checkpoint's declared binding to a model class, and the inspection |
| `paper-route-contract.json` | the route as the paper's own sentences give it |
| `public-code-route-audit.json` | one row per operation: paper statement, code location, resolution |
| `transform-graph-resolution.json` | seventeen operations with dtypes, geometry, interpolation, padding, authorities |
| `qualification-report.json` | every gate, every blocker, the route model and the byte guard |
| `stage-9a-finalization.json` | the marker |

## What resolved

* Both repositories pinned to exact commits: `Yu-Yy/FLARE` at `7d13ca72…`,
  `Yu-Yy/FLARE_ENH` at `ee735b03…`. No branch is an identity. Both archives were
  acquired twice and came back byte-identical.
* The FDD checkpoint load is present and active at the pinned commit. An earlier
  reading, against an earlier upstream state, recorded it as disabled — which is
  why a commit is pinned rather than a branch.
* `Prior.ckpt` was found by traversing `vq.yaml`. It appears in no README
  download list, and `VQFPEnhancer_PCNN` cannot be constructed without it.
* All seventeen route operations and their order carry an authority; two pixel
  implementations remain incomplete because parameters are unresolved.
* Both enhancers' preprocessing and postprocessing reduce to exact identities on
  a 512×512 input, so the paper's aligned crop meets the official entry points
  without any chosen resampling at that boundary.
* The score contract is exact: the masked cosine `calculate_score` computes, the
  mask tiled twelve times, the clip on the product of the two denominator terms,
  the continuous sigmoid mask that is never thresholded, and the maximum of four.
  Twelve properties of it were exercised over synthetic vectors and all hold.
* `D = 6` agrees between the paper and `desc_configs.yaml`.

## What this stage did not do

No SD300 image byte and no prior algorithm's score was read. No calibration, no
threshold, no decision profile. No production adapter, no runtime qualification,
no benchmark run. No third-party byte entered Git — checked by Stage 8E's generic
guard and by a FLARE-exact digest guard beside it — and not one byte of Stage 8E
changed.

## No licence question was resolved here

Both repositories carry a permissive `LICENSE` file and a README restricting use
to academic research and education. Stage 9A records both and chooses neither;
Stage 8E's intersection rule answers the only question this project has to ask.
The six checkpoints carry no notice anybody has inspected, which is `UNKNOWN`
rather than `NO_LICENSE_FOUND`.

## Reproducing it

```bash
make stage9a-status
make stage9a-contract
make stage9a-evidence
```

`make stage9a-documents` rewrites the nine derivable documents;
`make stage9a-publish` writes the marker too and refuses a dirty tree.
