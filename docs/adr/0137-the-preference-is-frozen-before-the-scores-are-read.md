# 0137 — The preference between two fifth methods is frozen before either is scored

**Status:** Accepted
**Stage:** 20B
**Date:** 2026-08-18

## Context

Stage 19B established `nbis_mindtct_openafis_capacity_extended` as Algorithm 5.
Stage 20A qualified a second candidate for the same slot: `MINDTCT` into the
official Minutia Cylinder-Code SDK v2.0, published by the University of Bologna,
unmodified.

The two routes are close relatives. Both take the certified NBIS MINDTCT 5.0.0
output and hand it to a different matcher; neither is an independent system. So
by the time both have run the canonical 6,000, there will be two score
distributions on the table and a choice to make — and that is exactly the
situation in which the choice makes itself, badly. Whoever looks first at which
distribution separates mated from non-mated more pleasingly has already selected
on SD300.

## Decision

**The preference and its reason are frozen in source before the run**, as
`PREFERENCE_REASON = "OFFICIAL_UNMODIFIED_MATCHER_ROUTE"` in
`fpbench/experiments/stage20b_identity.py`, and the marker publishes
`selection_based_on_sd300_accuracy: false` beside it.

The reason is a property of how the two routes were *built*, and it was knowable
before either was run:

```text
MCC          official SDK, unmodified upstream matcher, vendor's own defaults
OpenAFIS 19B project-defined capacity extension, modified upstream source
```

Both share MINDTCT, so OpenAFIS has no independence advantage to weigh against
that. If the MCC canonical run completes cleanly, MCC becomes the preferred fifth
method for that reason and no other.

**"Cleanly" is defined, not judged.** Section 25's nine conditions are all
structural, and the code evaluates them: both gates pass, 6,000 stored with none
missing, the route unchanged, no systemic bridge or translation defect, and no
parameter selection, calibration or threshold anywhere.

**The one thing the code will not decide.** If the run stores 6,000 outcomes but
some of them are structured failures, the raw run still *completes* — every
attempt is stored, which is the whole completion criterion — but the preference
is published as `null` and waits for `FAILURE_REVIEW`, a constant a person edits
after reading the failure classification. There is deliberately no 90% or 95%
rule: a failure-rate threshold nobody chose in advance, applied to the run whose
outcome it decides, is the same defect in a different place.

**Two gates, not fifteen.** Stage 20A did the research and closed the route, so
Stage 20B checks only the plumbing built on top of it. Gate A drives the
production bridge over Bologna's own sample minutiae and requires Stage 20A's five
doubles back bit-for-bit — no tolerance, because the same assembly through the
same API at the same defaults has no biometric reason to answer differently. Gate
B extracts twelve frozen canonical images through *both adapters' own extraction
paths* and requires byte-identical XYT, so that "Algorithms 2 and MCC use the same
extractor" is literally true rather than approximately so.

Gate A goes through the *production* template API rather than the text-template
one Stage 20A's probe used. Appendix A of the SDK manual defines the sample text
format as image width, height, resolution and one `x y direction` row per
minutia — the exact arguments `CreateMccTemplate(int, int, int, Minutia[])` takes
— so the two carry identical input and the comparison is legitimate. This makes
Gate A exercise the payload format, the bridge, the template API and the matcher
together. It exercises nothing about MINDTCT, and says so in its own record.

## Consequences

`MccSdk.dll` is a Windows .NET Framework assembly and the certified MINDTCT is a
Linux binary, so the route spans two operating systems: fpbench and MINDTCT on
the certified Linux target, the bridge as a Windows process reached by WSL
interop. The alternative — compiling a MINDTCT for Windows — was rejected because
it would have made the shared-extractor claim a statement about two similar
binaries instead of one.

Interop starts the Windows process but does not rewrite its arguments, so the
payload path is translated by `fpbench.adapters.mcc.interop` and a workspace
Windows cannot see is refused rather than guessed at. That is a real constraint of
this route and it is stated in one module rather than discovered per comparison.

One bridge process per comparison, not a persistent worker. It costs about 50 ms
of process launch and roughly 30 ms of JIT per pair against MINDTCT's ~200 ms, and
it buys an audit property worth more than the time: no state between pairs, no
configuration that can leak, every comparison starting from the SDK's own
defaults, and one pair's failure unable to contaminate the next.

OpenAFIS is not deleted. If MCC becomes the preferred fifth, the capacity-extended
result stays valid and moves to *additional experimentally evaluated methods*.

## Related

- `docs/adr/0136` — a modified matcher gets its own identity (Stage 19B).
- `docs/adr/0135` — the translation is settled from source, not from scores.
- `docs/adr/0130` — a candidate is not replaced because of its scores.
