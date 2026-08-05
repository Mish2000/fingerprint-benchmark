# 0071 — The Stage 8B transform is declared, not inherited

*Status: Accepted — 2026-08-05, stage 8B*

## Context

ADR 0064 says preprocessing is part of the algorithm. Stage 8A then recorded
`PREPROCESSING_DATASET_DEPENDENT` and
`GENERIC_CANONICAL_PNG_ROUTE_NOT_DEFINED` against `flx`, because upstream has
no dataset-independent input path. Its loaders branch by corpus — SFinGe crops
32 rows off the bottom, MCYT optical takes a 310-row centre region, FVC2004 and
SD4 take the image whole — and a benchmark that picked one of those branches
would be importing a corpus-specific decision it never made.

Upstream's shared helper is also not directly usable:

```python
pad_width  = 0 if width  >= height else int((height - width) / 2)
pad_height = 0 if height >= width  else int((width - height) / 2)
img = VTF.pad(img, padding=(pad_width, pad_height, pad_width, pad_height), fill=fill)
assert img.shape[1] == img.shape[2]
```

The same floor is applied to both sides, so an odd difference between height
and width leaves the image one pixel short of square and trips the assertion.
Our canonical inputs happen to be 381×891, an even difference, so the fault
would never fire on this cohort — which is exactly the kind of latent rule that
should not be inherited silently.

## Decision

Stage 8B declares its own transform, `fpbench_canonical500_to_flx299_squarepad_v1`,
as an `fpbench` component. It is fixed, total, and depends on nothing but the
input's dimensions:

* decode the PNG as one-channel 8-bit, rejecting truncated, malformed,
  multi-frame, wrong-bit-depth and wrong-colour-type input;
* no polarity inversion, no crop, no localization, no pose estimation, no
  rotation correction, no alignment;
* pad symmetrically to a square of side `max(width, height)` with 255, with
  the odd pixel going to the right and bottom:
  `left = top = floor(total / 2)`, `right = bottom = total - left`;
* resize to 299×299 with `InterpolationMode.BILINEAR` and `antialias=True`,
  both named explicitly rather than left to a library default;
* produce `[1, 299, 299]` float32 in `[0, 1]` by exact `uint8 / 255`, with no
  mean or standard-deviation normalization, no contrast or histogram work, no
  ridge enhancement and no channel replication;
* never re-encode the image before inference.

Every one of those nineteen questions is a named step in the profile, and
`FlxPreprocessingProfile` refuses to be constructed unless all nineteen are
present in order. "Not applicable" and "we use the default" are answers that
have to be written down.

The profile is an `fpbench` decision. Nothing in the evidence presents it as
the official DeepPrint pipeline or as the `flx` authors' choice.

## Alternatives considered

**Call upstream's `pad_and_resize` directly.** Inherits the parity fault, and
inherits it invisibly on a cohort where it cannot fire. A later cohort with an
odd difference would fail inside third-party code, at extraction time, on a
rule nobody chose.

**Copy upstream's floor/floor rule but fix the assertion.** Produces a
non-square image and a silently distorted resize. The rule needs to be correct,
not merely non-crashing.

**Pick the SD4 loader, since SD300 is closest to SD4.** "Closest" is a
similarity judgement about the evaluation corpus, made in order to configure
the algorithm. That is the corpus leaking into the method.

**Put the odd pixel left/top instead of right/bottom.** Arbitrary either way.
It is fixed, tested in both parities, and inside the profile fingerprint, which
is what actually matters.

## Consequences

Stage 8B's inputs are the Stage 6A canonical PNGs and nothing else. The route
cannot be pointed at a raw corpus without a new profile.

The transform is reproducible from the profile document alone: a reader with
the profile and the input bytes can recompute the tensor without reading our
code.

Because the profile is part of the algorithm identity, changing the padding
value, the parity rule, the interpolation, the antialias flag, the dtype or the
scaling produces a different algorithm — and the tampering tests assert exactly
that.
