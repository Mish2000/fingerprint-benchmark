# FLARE — the transform graph

Every operation between the canonical input bytes and the FDRN tensor, where its
route position comes from, and whether its pixel implementation is complete.
The machine-readable form is
`evidence/stage9a-flare-artifact-qualification/transform-graph-resolution.json`;
this is the reading of it.

## The authority vocabulary

```text
PAPER_EXPLICIT             the paper states it
UPSTREAM_CODE_EXPLICIT     the pinned official source performs it
UPSTREAM_DEFAULT_EXPLICIT  the pinned official inference entry point defaults to it
INTEGRATION_NEUTRAL        fpbench glue that cannot move a score, and is shown not to
---
ASSUMED / GUESSED / CHOSEN_BY_FPBENCH
```

The authority describes the existence and route position of an operation. The
first four are admissible. The last three are admissible only where the
operation provably cannot change a score, and an image-pipeline operation almost
never cannot (docs/adr/0087). A separate implementation-completeness field says
whether every pixel-level parameter needed to perform it is established.

## The graph

| # | Operation | Operation/order authority | Implementation |
| --: | :--- | :--- | :--- |
| 1 | `decode_canonical500` | integration-neutral | complete |
| 2 | `pose_input_center_512` | upstream code | complete |
| 3 | `pose_forward` | upstream code | complete |
| 4 | `pose_back_projection` | upstream code | complete |
| 5 | `alignment_affine_matrix` | upstream code | complete |
| 6 | `aligned_crop_512` | paper explicit | **unresolved: `border_fill`** |
| 7 | `unetenh_preprocessing` | upstream code | complete |
| 8 | `priorenh_preprocessing` | upstream code | complete |
| 9 | `unetenh_forward` | upstream code | complete |
| 10 | `priorenh_forward` | upstream default (`w = 0.5`) | complete |
| 11 | `unetenh_postprocessing` | upstream code | complete |
| 12 | `priorenh_postprocessing` | upstream code | complete |
| 13 | `downsample_512_to_256` | paper explicit | **unresolved: `interpolation`** |
| 14 | `fdrn_input_normalization` | upstream code | complete |
| 15 | `fdrn_forward` | upstream code | complete |
| 16 | `branch_similarity` | upstream code | complete |
| 17 | `max_fusion` | paper (Eq. 8) | complete |

All seventeen operations and their order are authoritative. Two pixel
implementations are incomplete, and those unresolved parameters are the stage.

## The geometry that is settled

**Pose input.** `FingerPoseEvalDataset.process_img` derives its target shape as
`rint(max(1, (512 × 1.0 + 32) // 64) × 64)`, which is 512 at 500 ppi. The warp is
a pure translation of image centres, `cv2.INTER_LINEAR`, `BORDER_CONSTANT` with
value 255, and the estimator receives the raw 0–255 values. The low-pass-and-zoom
branch applies only below 500 ppi and is skipped.

**Pose output.** `pose_2d = (x, y, θ)` in original image coordinates, with `x`
and `y` mapped back through the inverse of the centring transform and `θ` in
degrees wrapped by `(θ + 180) % 360 - 180`. Both estimators do this identically.

**The alignment matrix.** `R = [[cos, −sin], [sin, cos]] × scale` and
`t = R·(−pose_centre) + output_centre`, with `(x, y)` and `y` increasing
downwards, so a positive angle rotates clockwise on screen. The angle is
converted with `numpy.deg2rad`. `scale = tar_shape[0] / middle_shape[0]`, which
is `0.5` under the official configuration — and that factor is what fuses
alignment and the downsample into one warp.

**The FDRN input.** `(x − 127.5) / 127.5`, and nothing else: `input_norm` is
false in `desc_configs.yaml`, so `FDD.img_norm` is not applied. Upstream applies
the normalisation *before* the warp; with linear interpolation the two commute
exactly except at the border, which is where the unresolved fill value lives.

## The enhancer boundary, which does compose

On a 512×512 input both deploy scripts reduce to exact identities:

* UNetEnh resizes to `ceil(512/16)×16 = 512` and back — a `cv2.resize` to the
  same size;
* PriorEnh pads to a square (zero-width, the input is already square), resizes to
  512, and inverts that.

So the paper's aligned crop meets the official enhancer entry points without any
fpbench-chosen resampling at that boundary. The paper corroborates the input
size twice: Table XI gives PriorEnh 512×512, and the training description applies
its geometric augmentation to fingerprints of size 512×512 at 500 ppi.

## The two incomplete pixel implementations

### `aligned_crop_512`

The paper explicitly requires this image at this route position. No upstream
code path produces it: `Descdataset.process_img` always warps to `tar_shape`,
which the official configuration sets to 256, and there is no other caller of
`affine_matrix`.

Reusing that function with `tar_shape = middle_shape = 512` is legitimate — same
coordinate system, same affine formula, same interpolation, same crop semantics.
What it does not settle is what fills the canvas outside the fingerprint:

```text
Descdataset.process_img          passes no borderValue, so fills with 0
                                 *after* normalising — mid-grey once denormalised
FingerPoseEvalDataset.process_img fills with 255 — white
the paper                         says nothing
```

That fill becomes part of the enhancer's input, and a mid-grey frame and a white
frame are different images to a network trained on fingerprints.

### `downsample_512_to_256`

The paper explicitly requires this reduction after enhancement. Neither
repository contains a 512-to-256 reduction of an enhanced image. The only 2:1
factor upstream is the scale inside `Descdataset`'s single warp of the
unenhanced original.

The paper states the target size and not the kernel.
`cv2.INTER_LINEAR`, `cv2.INTER_AREA`, `scipy.ndimage.zoom(order=1)` and a second
`warpAffine` at scale 0.5 all produce different pixels.

## And one contradiction

`alignment_then_enhancement_ordering`. The paper puts enhancement between
alignment and the downsample. The only upstream code that aligns fuses alignment
and the downsample into one interpolation of the unenhanced original, leaving no
512×512 image and no point of insertion. That code path corresponds to the
earlier unenhanced FDD route rather than to this paper's inference route, and
nothing upstream composes the two.

Following either would mean overruling the other, which is not a Stage 9A
decision (docs/adr/0088).

## Reading the graph as a reviewer

Each operation in the JSON carries its operation/order authority,
implementation completeness, unresolved parameters, input and output dtypes,
geometry, interpolation, padding mode and value, normalisation, coordinate
convention, rotation direction, angle units, rounding behaviour and the
branches it applies to. A row you disagree with is a row you can point at.
