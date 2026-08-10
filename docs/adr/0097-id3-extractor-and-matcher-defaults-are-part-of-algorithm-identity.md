# 0097 — Extractor and matcher defaults are part of the algorithm's identity

*Status: Accepted — 2026-08-10, stage 10B*

## Context

The id3 Finger SDK does not expose one matcher. It exposes a matcher with five
published options, an extractor with three, and a template whose contents depend
on which models were loaded:

```text
FingerMatcher     maximumRotation  minexOnly  minutiaPatchOnly
                  multiscaleMatch  normalizedScores

FingerExtractor   minutiaDetectorModel  minutiaEncoderModel  threadCount
```

Every one of the matcher options changes the score. So do the first two
extractor options: loading only a minutia detector produces an interoperable
minutiae template, and adding an encoder produces additional proprietary data
that the matcher then uses.

The class reference documents what each option means and states **no default for
any of them**. The vendor's own sample constructs both objects and relies on
whatever the library does when nothing is set — except for `minexOnly`, which it
flips explicitly to obtain a second score from the same pair.

Two failure modes follow, and they pull in opposite directions.

The first is silence. "Use the SDK's defaults" sounds like declining to choose,
and it is not: it is choosing whatever the delivered binary happens to do, in a
run whose result will be published as *the* id3 score. If the next release
changes a default, the same fpbench code produces a different number under the
same name, and nothing in the evidence would show why.

The second is selection. The vendor publishes error rates for four fusion
combinations and recommends one by sensor size — minutiae alone for
interoperability, minutiae with minutia embeddings for small sensors, all three
for sensors above 200×200 px at 500 dpi. SD300's images are well above that
threshold, so a recommendation exists and it is a recommendation *by reported
accuracy*. Choosing the variant with the better published FNMR would make
fpbench's benchmark a report on a configuration fpbench selected for its results
— the failure ADR 0093 forbids for candidates, one level down.

## Decision

Every extraction and matcher option is **part of the algorithm's identity** and
must be frozen with a provenance before any score is produced.

**Per matcher option, four fields:**

```text
observed runtime value    what the delivered library actually reports
documented default        what the documentation states, or null
chosen value              what fpbench sets, if anything
provenance                where the chosen value came from
```

**An undocumented runtime value is labelled `DELIVERED_SDK_DEFAULT`.** Reading a
default out of the running library is legitimate and it is not a documented
fact: it is a fact about one package on one platform, and the label says so.

**The extraction profile is closed over seven things:** template format, finger
data formats, detector model, encoder model, finger-embedding model if the
delivered package has one, thread count, and every extraction flag. "Use the
full id3 somehow" is not a profile and cannot be expressed.

**The profile comes from the documented default single-finger route, not from a
performance ranking.** Vendor-published error rates explain the product; they do
not select the configuration. `fusion_selection_from_vendor_reported_accuracy`
is published as `false`.

**`minexOnly` is not the research default.** It is not switched on to make this
route look more like NBIS, and it is not switched off to make it look less like
NBIS. Stage 10B's job is to discover which route the delivered SDK defines. If a
MINEX-only configuration is ever wanted, it is a *separate algorithm profile*
with its own identity and its own fingerprint, not a flag on this one.

**A selection requires `hidden_score_affecting_defaults: 0`.** Before a pass,
every score-affecting setting has a recorded value and a provenance. Today that
count is 7 — five matcher options and two extractor models, none with a
documented default — and it is published as 7 rather than rounded to a
reassurance.

## Alternatives

**Freeze only what fpbench sets explicitly.** Rejected. The options fpbench does
not set are exactly the ones nobody would notice changing.

**Take the documented defaults as the profile.** There are none to take. That is
the finding, not an obstacle to it.

**Follow the vendor's sensor-size recommendation.** Rejected. It is a
recommendation derived from reported accuracy, and adopting it would make the
benchmark a report on a configuration chosen for its numbers.

**Run several profiles and report all of them.** Not refused in principle, and
not this stage. Each would be a separate algorithm identity with its own
fingerprint, and producing several before one is qualified is the wrong order —
which is the whole lesson of Stage 9A (docs/adr/0089).

## Consequences

The Stage 10B matcher and extraction profile documents publish every option with
its meaning, its absent documented default, and null for the three fields a
delivered package would fill. They are a form waiting to be completed, and the
form is what a future run is measured against.

A pass requires the count of unresolved score-affecting defaults to be zero, so
a package whose behaviour cannot be introspected cannot be admitted quietly.

An SDK upgrade is a new algorithm identity. The version, the models and the
profile are all inside the fingerprint, so 4.5.0 and a later release cannot
report under one name.
