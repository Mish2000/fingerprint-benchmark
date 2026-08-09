# 0091 — Benchmark input-domain compatibility is a hard candidate gate

*Status: Accepted — 2026-08-09, stage 10A*

## Context

fpbench hands every matcher the same thing: one `canonical_500` image, 500 ppi,
8-bit grayscale, prepared once from SD300 and independently of any comparison it
will later take part in (ADR 0031). That is the benchmark's input domain, and it
is fixed.

A candidate algorithm has an input domain too, and it is whatever its released
artifacts were built for. Usually the two coincide closely enough that nobody
notices. Occasionally they do not, and the mismatch is invisible from the tensor
shapes.

JIPNet is the case that made this explicit. It is a partial-fingerprint matcher.
Its released configuration declares a 160×160 input, its shipped examples are
all exactly 160×160, and its inference script reads two images and passes them
straight to the model without inspecting their size. The model would accept a
larger tensor without complaining. That tells you nothing, because the question
is not what the tensor layer tolerates.

Worse, its input is not even a property of one fingerprint. Upstream's patches
are cut from the *common mask of an aligned genuine pair*: which 160×160 window
an image yields depends on which other image it is being matched against. A
benchmark input cannot depend on the gallery image, because then a template is
not a template and 6,000 comparisons are 6,000 different preprocessings.

## Decision

Input-domain compatibility is Gate 2 of the Algorithm 4 preflight, ahead of
artifacts, route, score and runtime, and it is hard.

**The gate asks one thing.** Is there an upstream-authoritative way to turn
`canonical_500` into the input the released artifact requires?

```text
canonical_500
      ↓
authoritative transformation
      ↓
declared model input
```

**The resolutions are closed:**

```text
NATIVE_INPUT_ACCEPTED                    the model takes what the benchmark makes
UPSTREAM_AUTHORITATIVE_TRANSFORMATION    upstream defines the conversion
FPBENCH_CONSTRUCTION_REQUIRED            a conversion exists, and fpbench would be choosing it
UNRESOLVED                               nothing was established
NOT_REACHED                              an earlier gate stopped the candidate
```

Only the first two admit a candidate.

**"The tensor fits" is not an answer.** Neither is "the model is fully
convolutional", "resizing is standard practice", or "any reasonable crop would
do". The gate is about the existence of an authority, not about the existence of
a possibility.

**A pixel geometry is not a physical scale.** Every candidate records its
declared PPI or the fact that it declares none. Where none is declared, resizing
is not assumed neutral: a resize changes ridge frequency in the image, and ridge
frequency is what these networks look at.

**Training-time and evaluation-set construction are not inference.** A procedure
that upstream uses to *build a dataset* is not promoted into a route that
*processes a query*, however carefully it is described.

## Alternatives

**Put input domain after artifacts.** Rejected: it is the reason a candidate
fails, and it is readable before anything is downloaded. Ordering it later means
paying for the download to learn something free.

**Make it a soft criterion with a note.** Rejected: preprocessing is part of the
algorithm (ADR 0064). A soft input-domain finding is a soft algorithm identity.

**Accept a documented fpbench crop, marked as such.** Rejected here, and
separately in ADR 0092, which is where that question belongs.

## Consequences

A strong, official, MIT-licensed, well-documented matcher is refused for a
reason that is not about its quality at all. That is uncomfortable and it is
correct: JIPNet solves a problem this benchmark does not pose.

Every future candidate is asked the same question at the same point, and the
answer is cheap to obtain — for both candidates here it came from reading one
inference script and grepping the repository for a resize.

The recorded contract is reusable. If upstream later publishes a deterministic
full-fingerprint entry point, the gate re-runs against it and nothing else in the
preflight has to change.
