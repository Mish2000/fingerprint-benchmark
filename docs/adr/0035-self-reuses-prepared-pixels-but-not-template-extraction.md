# 0035 — A SELF comparison reuses one prepared artefact, but never one extraction

*Status: Accepted — 2026-07-31, stage 6A*

## Context

docs/adr/0006 established that a SELF comparison — an image against itself —
must go through the same code path as every other stage, because the path a
short-cut would create is exactly the path a bug hides in. The runner therefore
calls the preparer twice even when both sides name the same image, and the
SourceAFIS bridge extracts two templates rather than reusing one.

Canonicalisation raises the question again in a different form. A SELF pair now
means two lookups of the same immutable artefact. Should the preparation produce
*two* identical canonical PNGs, so that the two sides are independent all the
way down?

## Decision

No. **Independence is a property of template extraction, not of resampling.**

- A canonical artefact is materialised once per source image. A SELF comparison
  reuses it on both sides, and the two prepared images name the same file.
- The runner still calls the preparer twice. Skipping the second call would make
  SELF take a different code path from every other stage.
- The SourceAFIS bridge still performs two independent extractions, and
  `extraction_count == 2` is checked on every successful result.

Duplicating the PNG would prove nothing. Resampling is deterministic: the second
copy would be byte-identical to the first by construction, so producing it could
not detect any error that producing one does not. What a SELF comparison is
testing is whether the *matcher* behaves consistently on an image it has already
seen, and that is decided entirely by the extraction and matching steps.

## Consequences

A prepared-image set holds exactly one artefact per source image — 3,000 for the
SD300 experiment, not 4,500 — and the two entry hashes recorded on a SELF result
are equal, which is asserted rather than merely expected.

Content addressing makes this automatic rather than a special case: two entries
that genuinely produce identical bytes share one file whether or not they belong
to a SELF pair.

## Alternatives considered

**Materialise a second copy per SELF pair.** More storage, more time, and no
additional evidence, because the copies could not differ.

**Skip the second `prepare` call for SELF.** Would put a branch on protocol
stage into the runner, which is both what docs/adr/0007 forbids and the change
that would make SELF the one stage nothing tests.
