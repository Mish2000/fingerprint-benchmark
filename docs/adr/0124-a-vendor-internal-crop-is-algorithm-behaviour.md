# A vendor-internal crop is algorithm behaviour

## Status

Accepted, implemented.

## Context

Griaule's documentation states two things that sit awkwardly together. Capture
supports images up to 1280 × 1280 at 125–1000 DPI. Extraction states a maximum
image size of **500 × 500 pixels**, and that *larger images are cropped*.

That sentence does not say who crops. Two readings are possible and they are not
close:

1. The caller hands the extractor a full image; the extractor reduces it
   internally as part of its own processing.
2. The caller is required to hand the extractor an image already within the
   limit, and doing otherwise is undefined or rejected.

Under the first reading, Griaule is a normal candidate. Under the second, fpbench
would have to choose a crop window for every one of 6,000 images — an origin, a
size, a policy — and that choice would silently enter every score in the result
set. Two algorithms compared over inputs one of them had cropped by fpbench are
not being compared on the same protocol, and the benchmark's central claim would
be false.

This project has met the near-miss before. Stage 13A's ADR 0117 refused to treat
an embedded example's image size as a preprocessing rule. This is the same
mistake in a more tempting form, because here a specific number is stated by the
vendor and reducing to it would feel like compliance rather than intervention.

## Decision

The crop's *author* decides whether it is acceptable, and nothing else does.

```text
extractor crops a full image it was handed
    -> VENDOR_INTERNAL_ALGORITHM_BEHAVIOUR, published as such

fpbench crops before the extractor sees the image
    -> G2 FAIL, FPBENCH_PREPROCESSING_REQUIRED, hard reject
```

The passing route hands over the full canonical gray8 matrix at 500 ppi through
the vendor's own image object or loader, and every geometric decision after that
is made inside the vendor's code. A vendor-internal crop is recorded in the
marker as `vendor_internal_crop`, published rather than assumed, because it is a
property of the algorithm under test and a reader is entitled to know it happened.

`REFUSED_PREPROCESSING` names what fpbench will not do under any justification:
crop to the extractor's limit, choose a crop origin, resize, pad, rotate, select
a region of interest, enhance or normalise.

One adaptation is permitted, and only where the delivered API accepts no other
container: a lossless decode of the canonical PNG into the container the API
takes — BMP, on the vendor's documented evidence — carrying 500 ppi in the
container's own resolution metadata. It qualifies only if **every pixel value is
identical and the geometry is unchanged**. Both are checked; a conversion that
alters either is preprocessing wearing a file extension, and it fails the gate as
`DIRECT_INPUT_ROUTE_UNRESOLVED`.

Which reading is true is not decided here. It is decided by a delivered header
and a delivered sample, and until a package exists the gate is `NOT_REACHED`. The
documented limit is published as `UPSTREAM_EXTRACTION_PIXEL_LIMIT` beside
`upstream_limit_is_an_indication_not_a_route: true`.

## Alternatives

**Crop to 500 × 500 centred, and document it.** It is what an integrator would
do, and it would make fpbench the author of a score-affecting choice in one
algorithm's pipeline and not the others'.

**Downscale to fit.** Worse: it changes the effective ridge frequency, which is
an input to every minutiae extractor, and it would be invisible in the result
set.

**Treat the limit as disqualifying outright.** Too strong, and it would reject a
candidate whose extractor may handle the reduction perfectly well internally —
which is exactly what an algorithm's own preprocessing is for.

## Consequences

G2 cannot be settled from the documentation, and that is the honest state: the
question this gate exists to answer is precisely the one the public page leaves
open.

If the delivered API turns out to require caller-side reduction, Griaule fails
Stage 14A at G2 — early, cheaply, and before an adapter exists. If it crops
internally, the benchmark measures Griaule's own choice of window, which is the
correct thing to measure.
