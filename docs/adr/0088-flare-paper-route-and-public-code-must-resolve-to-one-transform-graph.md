# 0088 — The paper route and the public code must resolve to one transform graph

*Status: Accepted — 2026-08-08, stage 9A*

## Context

The earlier reading of FLARE treated checkpoint loading as the open question:
the reference extraction script appeared not to load the FDD weights. That is no
longer true. In the pinned public source the model is built, wrapped in
`DataParallel`, and `load_model(desc_model, model_path)` is called. The
checkpoint question is closed.

The question that replaced it is harder, and it is the reason this ADR exists.

The paper describes one sequence:

```text
500 ppi image
  -> pose estimation
  -> alignment, cropped to 512 x 512
  -> enhancement of the aligned image
  -> downsample to 256 x 256
  -> FDRN
```

The public code contains the same *stages* and does not compose into that
sequence:

* `datasets/FPdataset.py`'s `Descdataset` builds a single affine with
  `scale = tar_shape / middle_shape` — `256 / 512` under the official
  configuration — and warps the **original** image straight to `256 × 256`.
  Alignment and the downsample are one interpolation, with no `512 × 512` image
  in between and nowhere to insert an enhancer.
* the enhancers live in a second repository and do their own geometry.
  `deploy_unetenh.py` resizes to the next multiple of 16 and resizes back;
  `deploy_priorenh.py` pads to a square, resizes to `512 × 512`, and inverts
  that afterwards. Both consume and return **original-sized** images.
* there is no `512 → 256` downsample anywhere in either repository, because no
  code path ever needs one.
* there is no four-branch orchestration and no `max` fusion in any script.

So the pieces are all present and the *graph* is not. Composing them naively —
run pose, run an enhancer, run `Descdataset` with the pose — is not a neutral
act of plumbing. It reorders alignment and enhancement relative to the paper,
changes what geometry the enhancer sees, and silently applies whichever
resampling the composer happened to reach for.

## Decision

Stage 9A must produce a single artifact, `FLARETransformGraph`, that states
every operation from the canonical input bytes to the FDRN input tensor:

```text
canonical_500 bytes
  -> decode
  -> pose preprocessing
  -> pose coordinates
  -> affine matrix
  -> 512 x 512 aligned image
  -> enhancer preprocessing
  -> enhancement
  -> enhancer postprocessing
  -> 256 x 256 FDRN input
  -> FDRN normalization
```

and, for each operation:

```text
the library or function that is the authority
input dtype and output dtype
geometry
interpolation
padding mode and padding value
normalization
coordinate convention
rotation direction and angle units
rounding behaviour
```

**One graph, not two.** If the paper route and the public code route cannot be
shown to denote the same graph, the disagreement is a finding about FLARE, not a
choice for fpbench. The `paper_route_vs_public_code` audit carries one row per
operation and resolves each to `EXACT_MATCH`,
`IMPLEMENTATION_SUPPLIES_DETAIL`, `INTEGRATION_NEUTRAL_GLUE`, `AMBIGUOUS` or
`CONTRADICTORY`. `READY` requires zero score-affecting `AMBIGUOUS` and zero
score-affecting `CONTRADICTORY` rows.

**Reusing an upstream function differently is allowed, and must be proved.**
Calling `Descdataset.process_img` with `tar_shape = middle_shape = 512` to
obtain the aligned `512 × 512` image is legitimate integration glue *if* it is
shown to preserve the coordinate system, the affine formula, the interpolation,
the crop semantics and the absence of any extra transform. "It looks like what
the paper says" is not a proof; a row in the audit with an authority is.

**The FDRN input is a tensor, not a picture.** The graph continues past the
image into `(img - 127.5) / 127.5`, the channel layout, the dtype and whether
`input_norm` is applied — because `desc_configs.yaml` sets `input_norm: False`
and a graph that stopped at the PNG would have left that unstated.

## Alternatives considered

**Follow the code and treat the paper as prose.** The code is not a route; it is
three scripts that were never composed. Following it would mean inventing the
composition and calling the invention upstream.

**Follow the paper and fill in the code.** Two of the operations the paper needs
— an aligned-512 producer that feeds an enhancer, and a 512→256 downsample —
have no implementation upstream. Filling them in is exactly the
`CHOSEN_BY_FPBENCH` that ADR 0087 refuses on score-affecting operations.

**Declare the transform the way Stage 8B declared its own.** ADR 0071's
declaration was about *this project's* preprocessing, where fpbench is the
authority and a declaration is the honest form. Here the transform belongs to
somebody else's method, and declaring it would be asserting authority this
project does not have.

**Prove equivalence numerically instead of structurally.** Without the
checkpoints and without a reference output to compare against, there is nothing
to be numerically equivalent *to*. Structural resolution is what is available,
and it is what the audit records.

## Consequences

The transform graph, not the checkpoints, is Stage 9A's hard gate. An outcome of
`FLARE_FULL_ROUTE_BLOCKED` with `TRANSFORM_ORDER_AMBIGUOUS` is a specific,
actionable statement: it names the operations whose order or parameters no
authority settles.

If the graph does resolve, Stage 9B is an engineering problem — CUDA, torch
version, cuDNN, determinism, dependency closure — and none of those can change
which operations run.

If it does not, this project does not build FLARE according to its own
interpretation. It stops, and says why.
