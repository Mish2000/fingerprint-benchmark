# 0032 — Canonical geometry is scaled by manifest effective ppi, not by the file header

*Status: Accepted — 2026-07-31, stage 6A*

## Context

docs/adr/0004 established that SD300C's `pHYs` chunk is wrong: 10,115 of its
19,435 files declare 5080 ppi while being genuinely 2000 ppi images. Their pixel
dimensions are exactly twice the SD300B versions of the same captures, where a
true 5080 ppi scan would have to be 5.08 times. 5080 is the scanner's optical
resolution leaking into the header.

That decision governed what the harness *told SourceAFIS*. Stage 6A introduces a
second consumer of resolution: the scale factor of a resampling. The two are not
the same use, and the mistake available here is much larger. Telling a matcher
the wrong DPI degrades a score; scaling by the wrong factor produces an image of
the wrong size, permanently, in a set every future algorithm will be handed.

Scaling SD300C by 500/5080 instead of 500/2000 would shrink half of one release
by a further factor of 2.54.

## Decision

The scale factor is computed **only** from `ImageRecord.effective_ppi`.

Not from the PNG `pHYs` chunk. Not from the filename. Not from a release name
inferred from a directory. Not from any adapter default. The transform profile
names the field explicitly — `source_ppi_field: effective_ppi` — so that the
rule is in the specification rather than in the implementation.

The declared header value is still read, and is retained in the prepared entry
as `source_declared_ppi`. It is provenance, not input: it records what the file
claimed, which is exactly the evidence that the anomaly was seen rather than
missed.

A prepared entry therefore also fingerprints the *manifest row* it came from,
not only the source bytes. An image manifest rebuilt under a different
resolution policy would leave every file digest unchanged and every scale wrong,
and only a fingerprint over the row catches that.

## Consequences

`effective_ppi` becomes load-bearing in a second, harder-to-reverse way. Changing
the SD300C policy would not merely change what SourceAFIS is told; it would
invalidate every canonical artefact derived under the old policy — which is
correct, and is why the prepared-image set records the policy it was produced
under.

The preparation experiment's configuration states the expected source resolution
per release and refuses to run if the manifest disagrees, so a policy change
cannot silently produce a differently-scaled set under the same name.

## Alternatives considered

**Trust the header where present, fall back to the manifest.** This is the
behaviour that produces a 2.54x error on half of one release, silently, in an
artefact nobody re-measures.

**Repair the source headers.** Rejected in docs/adr/0004 and still rejected: the
delivery is evidence, and rewriting it destroys the ability to show what NIST
shipped.
