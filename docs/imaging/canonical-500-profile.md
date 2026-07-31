# The canonical 500 ppi profile

`configs/imaging/canonical_gray8_500ppi_lanczos3_v1.yaml`

## What it is

A **real resampling**, performed once, before any run, on every image the
experiment uses. It is not a hint to a matcher, not a metadata rewrite, and not
a resolution flag. SD300B's 1000 ppi images are genuinely reduced to half their
pixel dimensions; SD300C's 2000 ppi images to a quarter.

It is also an *input profile*, not an algorithm feature. Nothing about it
belongs to SourceAFIS, and nothing about it will change when NBIS arrives — that
is the point (docs/adr/0031).

## What it does, exactly

| Release | Effective ppi | Scale | Action |
| --- | --- | --- | --- |
| SD300A | 500 | 1/1 | `identity_pixels_reencode` |
| SD300B | 1000 | 1/2 | `downsample_2x_lanczos3` |
| SD300C | 2000 | 1/4 | `downsample_4x_lanczos3` |

**SD300C uses effective 2000, not declared 5080.** 10,115 of its files carry a
`pHYs` chunk saying 5080 ppi, which is the scanner's optical resolution leaking
into the header. Their pixel dimensions are exactly twice the SD300B versions of
the same captures, where a true 5080 ppi scan would have to be 5.08 times.
Scaling by 500/5080 would shrink half of one release by a further factor of
2.54. The scale comes from `ImageRecord.effective_ppi` and from nowhere else
(docs/adr/0004, docs/adr/0032).

**SD300A is decoded and re-encoded but never resized.** Copying the delivered
file straight through would be faster and would leave one release carrying
NIST's PNG encoding while the other two carried ours. Its raster is preserved
byte for byte — `source_pixel_sha256 == output_pixel_sha256` is a hard invariant
of every SD300A entry — and its file digest necessarily differs.

**SD300C goes 2000 → 500 in one step.** Not 2000 → 1000 → 500. Two Lanczos
passes are a different filter from one, and the golden fixtures show they
produce different pixels; if they agreed there would be nothing for the
profile's `direct_source_to_target` rule to mean.

## Geometry

Per axis, independently:

```
scaled = source_pixels x 500 / source_ppi
output = floor(scaled + 1/2)
       = (2 x source_pixels x 500 + source_ppi) // (2 x source_ppi)
```

Integer arithmetic throughout, and **not** Python's `round()`, which breaks ties
to even: a 1001-pixel axis at 1000 ppi is 500.5 output pixels, and `round()`
answers 500 while half-up answers 501. Both are defensible; having two rules is
not, so the profile names one.

Upsampling is forbidden. An axis that would round away to nothing is refused
rather than clamped. The physical extent is preserved to within half an output
pixel per axis, and the residual is recorded in parts per million.

## Encoding

8-bit grayscale (PNG colour type 0), non-interlaced, compression level 9,
`optimize` off — Pillow's optimiser searches filter strategies and its choice is
not pinned by anything in the profile, so leaving it on would break byte
determinism.

`pHYs` is written as 19685 x 19685 pixels per metre, unit 1 (metre), which is
`int(500 / 0.0254 + 0.5)`. A canonical PNG declares its own resolution, so a
reader who never sees this file still learns it.

Nothing else is written. A canonical artefact may contain `IHDR`, `pHYs`,
`IDAT` and `IEND` and nothing more: no creation time, no software name, no
source filename, no image id, no ICC profile, no gamma. The output is re-parsed
after writing and rejected if any of them appears — a `tEXt` chunk is exactly
where a list of subject ids leaks out of a workspace.

## Two identities

`pixel_sha256` answers "are these the same pixels?"; `encoded_sha256` answers
"is this the same file the adapter opened?". They are different questions and
both are kept. Changing only the compression moves the second and not the first;
changing one pixel moves both (docs/adr/0034).

## The resampler is pinned by content

`Lanczos3` names a mathematical kernel. `requirements-imaging.lock` names the
code that evaluates it, and the *installed distribution's bytes* are
fingerprinted rather than its version string — two wheels can share a version
and differ in a compiled extension. The lock's digest, the Pillow distribution
fingerprint, the interpreter, the platform, Pillow's zlib build and the fpbench
commit all enter `TransformRuntimeManifest.runtime_fingerprint`, which is part
of every prepared-image set's identity.

The Pillow version is deliberately **not** in `profile_fingerprint`. A
specification and an implementation of it are different things, and only the
specification is in the profile (spec section 11).

## What this profile does not claim

Nothing about accuracy. Nothing about whether 500 ppi is enough, or whether
2000 ppi helps. A canonical set proves that every algorithm was handed the same
pixels; observing what that did to any score is a later stage's work, and stage
6A deliberately reads no native score at all.
