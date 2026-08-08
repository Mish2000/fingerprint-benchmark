# FLARE — the method route

## What the paper says

```text
500 ppi fingerprint
        |
   two pose estimators
   VotingPose        RegressionPose
        |
   alignment, cropped to 512 x 512
        |
   for each pose:
   UNetEnh           PriorEnh
        |
   four enhanced images
        |
   downsample to 256 x 256
        |
   FDRN / FDD
        |
   4 x (dense descriptor + foreground mask)
        |
   four overlap-aware similarities
        |
   max
        |
   raw FLARE score
```

Source: arXiv:2505.03597v2 §III-E, and the pipeline overview in §III. The paper
states the order explicitly and footnotes that the rationale for putting pose
estimation before enhancement is discussed in §V.

## The four branches

```text
voting_unetenh
voting_priorenh
regression_unetenh
regression_priorenh
```

Their numeric order is **not** part of the algorithm, because a maximum does not
depend on the order of its arguments. Their presence is: `branch_count = 4`, not
two and not three (docs/adr/0085).

One fingerprint therefore carries four descriptors of 3,072 scalars and four
masks of 256 — not a single representation of 3,072.

## What the public code offers

Three pieces that were never composed into the route above.

**Pose.** `extract_VotingPose.py` and `extract_RegressionPose.py`. Both centre
the image in a 512×512 canvas at 500 ppi, run their estimator, project the
prediction back into original image coordinates, and wrap the angle to
`[-180, 180)`. Both write the same pose file format, so the README's "run one or
the other" is an instruction about running a script, not a claim about the
method.

**Descriptor.** `extract_FDD.py` with `-p VotingPose` or `-p RegressionPose`.
`Descdataset` builds one affine with `scale = tar_shape / middle_shape` —
`256 / 512` under the official configuration — and warps the **original** image
straight to 256×256. Alignment and the downsample are one interpolation, with no
512×512 image in between and nowhere to insert an enhancer. No enhancement
appears anywhere in this script.

**Enhancement.** A separate repository with two deploy scripts, each of which
takes a folder of whole original images and returns images of the same size.

There is no script in either repository that builds four branches, and no `max`
fusion anywhere.

## Why that is the stage's gate

The paper mandates enhancement between alignment and the downsample. The only
upstream code that aligns fuses those two steps into a single interpolation of
the unenhanced image. Composing the pieces naively — run pose, run an enhancer,
run `Descdataset` with the pose — is not neutral plumbing: it reorders alignment
and enhancement relative to the paper and changes what geometry the enhancer
sees.

So the route is `CONTRADICTORY` on that row, and Stage 9A stops rather than
choosing (docs/adr/0088). See `transform-graph.md` for the operation-by-operation
account.

## Input contract

The future route would receive only:

```text
fpbench canonical_500, gray8, 500 ppi
```

Not SD300 raw A/B/C, and no further resampling to 500 ppi inside fpbench — the
canonical profile already produced it (docs/adr/0031). The paper matches from
500 ppi and the official configuration sets `PPI: 500`, so this agrees on both
authorities.

## Excluded from the identity

The binary FDD route. The official README presents `-b` as a separate, optional
mode for ultra-fast matching, with its own mask thresholds (0.5 on one, 0.2 on
the other) and its own score expression. The paper's Eq. 7 is continuous.

```text
binary_representation = false
```
