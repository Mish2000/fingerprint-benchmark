# 0086 — The FLARE candidate identity is FDD D=6, dual-pose × dual-enhancement, max overlap-masked cosine

*Status: Accepted — 2026-08-08, stage 9A*

## Context

ADR 0069 established that what this benchmark executes is *one implementation of
one variant*, and that the variant has to be nameable before anything runs. For
FLARE the variant is not obvious from the name: the published framework has two
descriptor score modes, two pose estimators, two enhancers, and a feature
dimension that only appears in a configuration file and one sentence of the
paper.

A name that said only "FLARE" would be a name that four different runs could
answer to.

## Decision

The candidate algorithm identity is:

```text
flare_fdd_d6_dualpose_dualenh_maxcosine
```

Display name:

```text
FLARE FDD D=6
Dual-Pose × Dual-Enhancement
Max Overlap-Masked Cosine
```

Each segment is a claim, and each claim has an authority:

| Segment | Claim | Authority |
| :--- | :--- | :--- |
| `fdd` | the Fixed-length Dense Descriptor network is the representation | paper §III, `models.model_zoo.FDD` |
| `d6` | `D = 6`, so the descriptor is `2D × 16 × 16 = 12 × 16 × 16` and the mask is `1 × 16 × 16` | paper §IV ("the feature dimension D … is set to 6"), `model_weights/desc_configs.yaml: ndim_feat: 6` |
| `dualpose` | both `VotingPose` and `RegressionPose` are computed, always | paper §III-A and Eq. 8 |
| `dualenh` | both `UNetEnh` and `PriorEnh` are computed, always | paper §III-B and Eq. 8 |
| `maxcosine` | the score is the maximum of four overlap-masked cosine similarities | paper Eq. 7 and Eq. 8 |

And two things the identity deliberately excludes:

* **the binary route.** `binary_representation = false`. `-b` is a separate
  optional mode in the official README with its own thresholds (`0.5` on one
  mask and `0.2` on the other) and its own score expression. It is not the
  paper's Eq. 7.
* **any fpbench-chosen variant.** There is no "FLARE (fast)", no
  "FLARE (VotingPose only)", and no configuration switch that would produce one.

The name becomes a production algorithm id **only** if Stage 9A closes
`FLARE_FULL_ROUTE_ARTIFACTS_READY`. Until then it is a candidate identity: a
label for a qualification, not for a result.

## Alternatives considered

**`flare` alone.** Shorter, and unusable the first time somebody asks whether a
stored score came from the continuous or the binary route.

**Encode the checkpoint digests in the name.** The digests belong in the
artifact manifest, where they can be verified; a name is for reading. The
manifest binds them, and the finalization marker binds the manifest.

**Defer naming until the route is proven.** Then the qualification would have
nothing to be *about*. The identity states what is being qualified; the outcome
states whether it survived.

## Consequences

A `ResultSet` produced under this identity asserts, in its name, that four
branches were computed and fused by a maximum. A future run that computed two
would have to change the identity to stay honest, and changing the identity is
visible in every derivation that binds it.

`D = 6` is pinned in two places that must agree — the paper and the official
inference configuration — and Stage 9A checks that they do. A future upstream
configuration with a different `ndim_feat` is a different algorithm under this
scheme, which is the correct answer: the descriptor length would change.
