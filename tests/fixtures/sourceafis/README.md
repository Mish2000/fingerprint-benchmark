# SourceAFIS test fixtures

## What these are

**Synthetic images. Not fingerprints, and not from any person.**

The SourceAFIS tests need images that SourceAFIS can actually extract a template
from. SD300 imagery cannot be committed — it is redistribution-restricted (see
[data/README.md](../../../data/README.md)) — so the fixtures are generated
procedurally at test time by
[`tests/synthetic_ridges.py`](../../synthetic_ridges.py).

No file is stored in this directory. Everything is produced from a seed when a test
asks for it, which is why there are digests below rather than files.

## Provenance and generation method

| | |
|---|---|
| Source | Generated, `tests/synthetic_ridges.py::whorl_png(dpi, seed)` |
| Method | Concentric warped sinusoidal ridges around an off-centre core, faded at the edges |
| Depends on | Python standard library only (`math`, `struct`, `zlib`) |
| Human subject | **None.** Nothing here derives from a person, a scan or a dataset |
| License | Same as this repository; no third-party content is involved |
| Colour | 8-bit greyscale PNG, no `pHYs` chunk |

The pattern is warped rather than a plain sine grating on purpose: a pure grating has
no ridge endings and no bifurcations, so it has no minutiae and SourceAFIS finds
nothing in it.

## Physical scale

Ridge period is held at **≈0.46 mm** (55 ridges per inch) at every resolution, and the
image is **0.5 inch** square. That is the point of scaling the pattern with DPI: an
image shaped for 500 ppi but *labelled* 2000 ppi would be internally rescaled by
SourceAFIS to a two-pixel ridge period and fail extraction — which would look like a
DPI rejection without being one, and would make the 500/1000/2000 acceptance tests
meaningless.

## Expected dimensions and digests

Pinned so that a change to the generator is visible rather than silent. If one of
these moves, the fixtures changed, and so did every score measured against them —
including the pinned regression score in
`tests/regression/test_sourceafis_regression_score.py`.

| DPI | Seed | Pixels | Bytes | SHA-256 |
|---|---|---|---|---|
| 500 | 1 | 250 × 250 | 37,636 | `5930ceb5b634259001f1b18cb968340694c6f1e9698734057acbd5dbd5709ab5` |
| 500 | 6 | 250 × 250 | 32,769 | `1300ca628f22ca37e716c7270e4cc68ce5a8f0d92b884d3dce55bfb9892d8fdc` |
| 1000 | 1 | 500 × 500 | 102,680 | `e622ca620a2e3126ade9b5dc312e1c033a5372bcad975ec5e930ffab84064f8d` |
| 1000 | 6 | 500 × 500 | 93,028 | `af151800189518dbc27ef5ca0ebedfe3845dc473eab814ee8e95b9f3c0d80e34` |
| 2000 | 1 | 1000 × 1000 | 249,250 | `f536daf019a081ed6c91fa116ef1b8bf60f48697b7e4b2d6b986436bb6a0948b` |
| 2000 | 6 | 1000 × 1000 | 227,200 | `fa87b254f83cf3ae54cbfe0f973b465db4acc76a7949e171bac0274b79863762` |

## What these fixtures cannot tell you

Nothing about accuracy. A self-comparison of fixture 1 at 500 ppi scores about 23 and
two different fixtures score 0, but those numbers describe two procedural textures,
not two fingers. They exist to prove the pipeline runs, that both sides are extracted
independently, that all three SD300 resolutions are accepted, and that failures map to
the right codes.

Real numbers require SD300, and even then only after a full run — which stage 4A
deliberately does not perform.
