# 0048 — MINDTCT is handed the prepared PNG, byte for byte

*Status: Accepted — 2026-08-02, stage 7B*

## Context

NBIS predates PNG as a working format for fingerprint imagery. Its own tooling is
built around WSQ, ANSI/NIST records, IHead and PGM, and most descriptions of
running MINDTCT begin by converting an image into one of those. This repository
believed the same thing: until stage 7B the synthetic two-stage adapter's docstring
said MINDTCT wants a PGM.

Every conversion is a place where the experiment changes without the experiment
saying so. A WSQ encode is lossy. A PGM round-trip through an image library
depends on the library's version. A greyscale conversion depends on whose
coefficients were used. The canonical input set exists precisely so that every
algorithm sees the same pixels (docs/adr/0031, docs/adr/0033), and a per-adapter
re-encode would undo that quietly.

NBIS 5.0.0 does read PNG. That is a claim about a build, not about a project.

## Decision

**The prepared 8-bit greyscale PNG is copied byte for byte and handed to MINDTCT
unchanged.** No re-encoding, no greyscale conversion, no contrast change, no
resize, no crop, no rotation, no WSQ, no JPEG, no PGM and no IHead.

The copy exists only so the adapter never hands a tool a path outside its own job
directory. It is proved identical to the source before it is used: the staged
file's digest and size must equal the prepared image's own.

**PNG support is an acceptance condition of the build, not a hope about it.**
`build.py test` runs MINDTCT over a gray8 PNG and over a 16-bit, an RGB, an
indexed-colour and a corrupt one, and records what happened. The verdicts are in
the build manifest as `png_support_compiled`, `direct_gray8_png_verified` and
`png_formats_refused_by_build`, and the adapter refuses a manifest without them.

Running that probe corrected an assumption. **The certified build accepts 16-bit
and indexed-colour PNGs**: NBIS 5.0.0 hands PNG to libpng, which down-converts a
16-bit raster and expands a palette. This project had expected MINDTCT to refuse
them, and wrote a build script that would have refused the build for accepting
them — an expectation, enforced as a rule, that the software contradicted.

So the rule was corrected rather than the measurement. What the build tolerates is
*recorded*; what makes the route safe is the adapter, which refuses anything that
is not 8-bit greyscale before a subprocess exists. Two acceptance conditions
remain, because those two would change the pixels being compared rather than
merely convert their representation:

    rgb8      a truecolour image silently flattened is not the image prepared
    corrupt   an unreadable file that produced a template produced it from
              somewhere other than the input

**There is no WSQ fallback.** A build without PNG support is not certified, and
the correct response is to fix the build rather than to introduce a lossy encode
into a benchmark.

The adapter enforces the same contract in Python before any subprocess starts:
signature, IHDR, colour type 0, bit depth 8, non-interlaced, present image data,
proper end. Anything else is `INPUT_INVALID` — recorded, not raised, because an
image of the wrong shape is a fact about the input set (docs/adr/0013).

The one exception: a file of the right shape whose bytes no longer hash to what
the preparer recorded is `PreparedImageDriftError`, raised and fatal. That is not
a property of this pair — it means the artefact changed after preflight approved
it, and nothing written afterwards is attributable (docs/adr/0033).

The wrong comment in the synthetic two-stage adapter is corrected, because a
docstring nobody rechecks is how the belief survived this long.

## Consequences

The NBIS route reads exactly the artefacts the canonical preparation produced, so
"the same pixels reached both matchers" is true by construction rather than by
argument.

If a future NBIS build turns out not to read PNG, this stage stops. It does not
fall back to WSQ, and it does not introduce a conversion step whose parameters
nobody has argued for.

The adapter is now load-bearing in a way it would not have been if the build had
matched the expectation: it is the only thing standing between a 16-bit PNG and
MINDTCT. Its input contract is tested from both sides — the build accepts,
the adapter refuses — so a change to either is visible.

## Alternatives considered

**Convert to PGM in the adapter.** A conversion nobody has to justify is a
conversion nobody reviews, and PGM has no header for resolution — so the route
would then depend on MINDTCT's default anyway, with an extra lossy step in front.

**Convert to WSQ, as most NBIS pipelines do.** Lossy compression tuned for
transmission, applied to a benchmark input, for no reason available here.

**Let the preparer emit whatever each adapter wants.** Then the two algorithms no
longer see the same pixels, and the paired comparison stage 6B built loses its
control.
