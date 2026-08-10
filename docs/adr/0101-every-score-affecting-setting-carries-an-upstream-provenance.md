# Every score-affecting setting carries an upstream provenance

## Status

Accepted, implemented.

## Context

ADR 0097 established for id3 that extractor and matcher defaults are part of an
algorithm's identity: a setting fpbench never touches still decides the score, so
a profile with unrecorded values is not frozen. VeriFinger turns that principle
into a live decision rather than a hypothetical one, because the artifact is here
and can be read.

Reading it produced a precise finding. The pinned 2025.2 manual's parameter
tables give every `Fingers.*` and `Matching.*` entry a type and a meaning and
state a default for none of them — while the `Faces.*` entries in the very same
tables carry `Default: false`, `Default: 90 pixels`, `Default: ntsMedium`. The
absence on the fingerprint side is a property of the document, not of the
reading.

Meanwhile upstream's own 1:1 tutorial sets three values explicitly:
`FingersTemplateSize` to `LARGE`, `FingersMatchingSpeed` to `LOW`, and a matching
threshold that the raw route discards. And `NMatchingSpeed` is exactly the preset
family that invites the worst possible selection rule: three values documented as
an accuracy trade-off, one of which will produce prettier score distributions on
any given dataset.

## Decision

A route this project is willing to call "VeriFinger" carries, for every setting
that can change the score, a value and a provenance drawn from one of four
upstream authorities:

```text
UPSTREAM_DOCUMENTED_DEFAULT        the manual states it
DELIVERED_RUNTIME_DEFAULT          a constructed engine reports it
OFFICIAL_SAMPLE_EXPLICIT           upstream's own working code sets it
UPSTREAM_EXPLICIT_RECOMMENDATION   upstream recommends it for this case
```

`FPBENCH_CHOICE` is not among them, and it is deliberately not a member of the
enumeration at all — a constant checked at import time asserts that it never
becomes one, so no code path can select it.

Where a value comes from the official sample rather than from a stated default,
the profile identity says *that*. "The official-sample route" and "the VeriFinger
default" are different claims, and where the manual states no default they are
not interchangeable.

A preset is never chosen by running all of them and keeping the one whose scores
look better. Where upstream expresses no preference, the setting is unresolved and
the gate fails; it does not fall back to a performance comparison.

The profile gates therefore require two things and not one: a **closed
inventory** — every setting that can change the result, discovered from the
package rather than assumed from another vendor's API — *and* a value with a
provenance for each score-affecting member of it.

## Alternatives

**Pass on a closed inventory alone.** Tempting, because the inventory is the hard
research and it is complete. It would also publish a profile called frozen while
most of the settings that decide the score had no recorded value at all, which is
precisely the failure the whole apparatus exists to prevent.

**Accept "whatever the engine was constructed with" as a provenance.** That *is*
an acceptable provenance — once somebody reads it off a running engine and writes
it down as `DELIVERED_RUNTIME_DEFAULT`. Until then it is not a value, it is an
assumption about one.

**Freeze only the settings upstream documents and ignore the rest.** Would make
the record shorter and the algorithm no more identified.

## Consequences

Stage 11A fails at its extraction-profile gate with nine score-affecting settings
unresolved across extraction and matching, and the failure is honest about its
cause: not that the settings are unknowable, but that reading them needs a
licensed engine nobody has run.

The path forward is correspondingly narrow and clear. Construct the engine once,
read each value, record it as a delivered runtime default, and the two profile
gates close. Nothing about the algorithm has to change and no value has to be
chosen — which is the point.
