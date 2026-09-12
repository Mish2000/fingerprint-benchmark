# 0142 — L3 scale repair has separate development identities and TRAIN provenance

## Status

Accepted for the bounded local continuation, 2026-09-12.

## Context

The first L3 pilot retained 85 P2 image failures and 246 pair failures. Synthetic
diagonal gratings expose an incorrect rotation sign in Experiment 004's ridge
period estimator. Its historical target of 34 pixels was derived using the same
estimator, so correcting only the sign does not establish a suitable target.
The original run remains valid evidence of the configuration it executed.

## Decision

Implement the repair in `V2/experiments/l3_bridge_scale_repair/`, leaving v1,
the external Experiment 004 checkout and all baseline contracts untouched.
This is a development experiment, not a published benchmark stage or adapter.
No shared runner or storage extension is required.

The versioned tile estimator changes only the subtraction used for rotation.
Read-only upstream helpers preserve orientation, normalization and tile starts.
Synthetic tests cover both diagonal signs, known periods, low information,
the exact one-expression difference, and the unchanged scale/MAD/tile guards.
Do not monkey-patch any upstream function.

Recompute the target once from the original 440 TRAIN images in 88 groups.
Bind their identities and bytes to the original split, training protocol and
model; take the median of reliable image estimates by the historical rule.
Do not read validation/test pixels or infer annotated-512/final-320 identities.
Keep seed40401, its checkpoint, threshold 0.72, NMS 2, preprocessing after resize,
tiling, native-coordinate SIFT and spatial matching unchanged.

The predecessor's exact 100 images and 250 pairs remain the complete population.
The rotation-only diagnostic uses historical target 34 and band [0.2,1.5].
P2R uses the corrected TRAIN target and band [0.2,1.5]; P2R-wide uses the same
target and the historically declared contingency band [0.2,3.0]. Declare both
before scoring. Wide is sensitivity analysis, not a sign-only repair or an
established valid policy. Keep every failure and true zero. Identical physical
inference, description and matching may be shared with explicit receipts,
but independently failing primary eligibility is never filled from wide.

Reuse verified P1/R records. Descriptive FAR targets 1% and 5% use atomic
`score >= cut` ties, maximal TA, then minimal FA, then highest cut. Rates retain
50 genuine and 200 impostor attempts, with failures counted as operational
nonacceptance and disclosed separately from matcher rejections. A missing scored
class makes comparison unsupported. Do not create operating profiles or claims
of independent evaluation, superiority, FAR=0.1% or independent binomial precision.

The current user request explicitly requires no commits. For this local
continuation, archive the actual uncommitted source bytes and an exact diff
before estimating TRAIN or development scales, hash the archive and all inputs,
and verify them at execution boundaries. Record the base commit as a base only;
do not claim it is the executed source or that the working tree is clean. The
recoverable archive is mandatory. This scoped instruction does not relax
ADR 0017, the v1 clean-commit rule, or any frozen research runner. No source
changes occur during estimation or inference.

## Alternatives

Overwriting v1 would erase evidence. Globally replacing the estimator would
silently change the historical route. Keeping 34 without TRAIN verification or
selecting a scale band by development TAR would conceal another algorithmic
change. Committing merely to satisfy an older run rule would contradict the
current explicit request; an archived, hash-bound local snapshot records what
actually ran without changing those older rules.

## Consequences

Coverage can remain incomplete, and correction can reveal a scale-band failure
previously hidden by a wrong estimate. Per-image audits attribute these causes.
Raw comparisons, TRAIN manifests, demos and review bundles remain in ignored
local workspace. Delivery ends the experiment; there is no automatic tuning,
training, fusion, SD300C access or extension beyond the original five subjects.
