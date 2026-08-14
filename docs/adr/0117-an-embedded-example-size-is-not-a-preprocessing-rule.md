# An embedded example size is not a preprocessing rule

## Status

Accepted, implemented.

## Context

FingerCell targets embedded devices, and its published technical specifications
quote memory and speed figures for specific image sizes — 234x332 at 500 ppi, and
180x256 at 385 ppi. Those numbers exist so an integrator can size a
microcontroller.

Read quickly, they look like an input specification. The temptation is to crop or
resize every canonical image to 234x332 so the algorithm sees "what it expects".

That would be fpbench choosing a preprocessing step and attributing it to
upstream. It would change the pixels every score is computed from, discard part of
every fingerprint in the corpus, and make this benchmark a measurement of a
cropping rule.

## Decision

Canonical image dimensions are unchanged. The example sizes are recorded — so the
refusal can name exactly what it is refusing — and a constant states that they are
not a preprocessing rule.

The delivered extraction tutorial supports this directly: it loads an image and
passes it to the extractor with nothing in between.

Separately, the module carries messages about a minimum resolution of 385 DPI,
which is a genuine input constraint that `canonical_500` satisfies at 500 PPI. A
constraint the algorithm enforces is part of the algorithm; an example size in a
performance table is not.

## Alternatives

**Resize to the example size.** Benchmarks the resize.

**Resize only images larger than it.** Worse: the preprocessing would apply to
some images and not others, and the difference would be invisible downstream.

## Consequences

The canonical corpus enters the algorithm as it is.

Speed and memory on this host will not resemble the vendor's embedded figures,
which is expected: those describe a microcontroller.
