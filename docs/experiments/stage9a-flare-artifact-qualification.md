# Stage 9A — FLARE full-route artifact and method qualification

## What this stage decides

Whether a complete and faithful implementation identity of FLARE can be frozen
from:

```text
the published FLARE method
+ the official FLARE repository
+ the official FLARE_ENH repository
+ the official pretrained artifacts
+ integration-neutral fpbench glue, and nothing else
```

Two outcomes, and both are complete:

```text
FLARE_FULL_ROUTE_ARTIFACTS_READY
FLARE_FULL_ROUTE_BLOCKED
```

There is no requirement anywhere in this project to make FLARE run. There is a
requirement not to publish a score attributed to a method the score did not come
from (docs/adr/0085, docs/adr/0087).

## The outcome

```text
FLARE_FULL_ROUTE_BLOCKED
```

Seven blockers, in two groups.

**The route.** All seventeen operations and their order between the canonical
input bytes and the FDRN tensor carry an authority — the paper, the pinned code,
or a pinned inference default. Two pixel implementations remain incomplete:

| Operation | Why |
| :--- | :--- |
| `aligned_crop_512` | the paper explicitly places the crop here, but no upstream code produces it and no authority settles the fill around the fingerprint |
| `downsample_512_to_256` | the paper explicitly places the reduction here, but gives no kernel and no upstream implementation performs it on the enhanced image |

and one audit row is a contradiction rather than a gap:

| Row | Paper | Public code |
| :--- | :--- | :--- |
| `alignment_then_enhancement_ordering` | align → crop 512 → **enhance** → downsample 256 → FDRN | `Descdataset.process_img` fuses alignment and the 256/512 scale into a single warp of the **unenhanced** original |

The public four-branch orchestration is unavailable as a consequence: the paper
defines the four branches and max fusion, but no executable upstream route
composes them, and each would repeat the incomplete pixel pipeline.

**The artifacts.** Six checkpoints are published on Google Drive links the
official READMEs name. A Drive file id is a locator, not an identity, so their
identity is not established, they do not verify locally, and Stage 8E's engine
returns `BLOCKED` for each of them. Their compatibility with the intended model
classes is therefore unresolved; no mismatch has been observed.

The four artifacts that ship inside the pinned source trees — both source
archives, `desc_configs.yaml` and `vq.yaml` — are pinned by digest and size and
verify locally.

## What did resolve

Worth as much as what did not, because it is what a later stage would build on.

* **Both repositories are pinned to exact commits.** `Yu-Yy/FLARE` at
  `7d13ca72…` and `Yu-Yy/FLARE_ENH` at `ee735b03…`, with archive digests, sizes,
  and the branch name recorded as a note rather than used as an identity. Both
  archives were acquired twice and came back byte-identical.
* **The FDD checkpoint load is present and active.** The earlier reading of this
  repository — against an earlier upstream state — recorded it as disabled. In
  the pinned source the model is built, wrapped in `DataParallel`, and
  `load_model` is called. That question is closed, which is why a commit is
  pinned rather than a branch.
* **The transitive PriorEnh artifact was found.** `Prior.ckpt` appears in no
  README download list; `vq.yaml`'s `ckpt_path` names it, and
  `VQFPEnhancer_PCNN` asserts on it before it can be constructed.
* **The enhancer boundary composes cleanly.** On a 512×512 input both deploy
  scripts' preprocessing and postprocessing reduce to exact identities — the
  multiple-of-16 resize is a no-op, the square padding is zero-width, and both
  inverse resizes return the same size. The paper's aligned crop therefore meets
  the official entry points without any chosen resampling at that boundary.
* **The score contract is exact.** The masked cosine `calculate_score` computes,
  the mask tiled twelve times, the clip on the product of the two denominator
  terms, the continuous sigmoid mask that is never thresholded, and the maximum
  of four. Vanishing overlap drives the score to zero and keeps it finite with no
  new policy.
* **`D = 6`** agrees between the paper's §IV and `desc_configs.yaml`.
* **No SD300 training overlap was found**, and that is recorded as
  `NO_EVIDENCE_FOUND` rather than as proof of absence.

## How to run it

```bash
python -m fpbench.experiments.stage9a_flare_finalization status
```

Derives every gate and prints the outcome and its blockers without writing
anything. `documents` writes the nine derivable documents; `publish` writes those
and the marker, and refuses a dirty tree.

Acquiring the artifacts is local-only and is never done by CI:

```bash
python -c "
from pathlib import Path
from fpbench.experiments import stage9a_flare_artifacts as a
from fpbench.experiments import stage9a_flare_identity as f
for art in f.REQUIRED_ARTIFACTS:
    print(art.artifact_id, a.acquire_artifact(art, repository_root=Path('.')).name)
"
```

A checkpoint acquired for the first time has no expected digest to check against.
`enroll_artifact` reports the digest and size that would have to be frozen in
`stage9a_flare_identity`; freezing them is a reviewed edit, never something the
code does to itself.

## What this stage did not do

No SD300 image byte and no prior algorithm's score was read. No calibration, no
threshold, no decision profile. No production adapter, no runtime qualification,
no benchmark run. No third-party byte entered Git, and not one byte of Stage 8E
changed.

## What would lift the blockers

Each is a concrete thing, not a mood:

1. an authoritative statement of the resampling used between 512 and 256 —
   upstream code that performs it, or a statement in the paper or its
   supplementary material;
2. an authoritative statement of what fills the aligned 512×512 crop outside the
   fingerprint;
3. an upstream orchestration that composes pose, alignment, enhancement and FDD
   in the paper's order — or a statement resolving which of the two orders the
   released checkpoints were used under;
4. enrollment of the six checkpoints from their official locators, which
   establishes their identities and makes the compatibility inspection possible.

Items 1 to 3 are upstream's to answer or a corrective stage's to decide
explicitly. Item 4 is a local operation the project owner can perform.

## See also

* `docs/algorithms/flare/upstream-artifacts.md`
* `docs/algorithms/flare/method-route.md`
* `docs/algorithms/flare/transform-graph.md`
* `docs/algorithms/flare/score-semantics.md`
* `evidence/stage9a-flare-artifact-qualification/`

There is deliberately no `performance.md`. No benchmark ran.
