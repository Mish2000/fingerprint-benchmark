# One upstream sample is the route, not several

## Status

Accepted, implemented. Refines ADR 0101.

## Context

ADR 0101 established that every score-affecting setting needs a value with an
upstream provenance, and named `OFFICIAL_SAMPLE_EXPLICIT` as one of the four
authorities: where upstream's own working code sets a value, that is the route
being qualified.

Stage 11A's first publication then applied it to two samples at once. It took
`FingersMatchingSpeed = LOW` from `verify-finger` and `FingersTemplateSize =
LARGE` from `enroll-finger-from-image`, and recorded both as
`OFFICIAL_SAMPLE_EXPLICIT`.

Those are different programs and they are configured differently. `verify-finger`
sets a matching speed and never touches the template size; `enroll-finger-from-
image` sets a template size and never touches the matching speed. A profile
holding both would be a configuration **no upstream program has ever run** — and
it would carry an authority label saying upstream chose it.

The failure is subtle precisely because each half is true. "Upstream sets this
value" was a correct sentence about each setting individually and a false one
about the pair.

## Decision

Exactly one upstream sample is the authoritative route, it is named as a
constant, and the observation type enforces it.

```text
AUTHORITATIVE_ROUTE_SAMPLE
    Tutorials/Biometrics/Java/verify-finger
```

It is the authoritative one because it is the only sample in the archive that
performs the whole route this benchmark needs: two images in, one scalar score
out, with the score read under both `OK` and `MATCH_NOT_FOUND`.

A setting record that carries an `official_sample_value` must also carry the
locator it came from, and a locator that is not the authoritative sample is
refused at construction. A value with no locator is refused too — a value from
"a sample" is a value from nowhere in particular.

**A setting the authoritative sample does not touch is a delivered runtime
default**, to be read off a constructed engine and recorded as
`DELIVERED_RUNTIME_DEFAULT`. It is never a value borrowed from a neighbouring
tutorial that happens to set it.

Where the authoritative sample sets something the raw route discards — it sets a
matching threshold of 48 — that value is recorded as discarded rather than
carried. The route stops at the score.

## Alternatives

**Rank the samples and take the most specific.** Requires a ranking nobody
upstream published, which is fpbench choosing again, one level up.

**Union the samples and call it "the upstream configuration".** The thing that
was done, and it invents a configuration.

**Treat any sample-set value as merely a hint and read everything off the
engine.** Defensible, and it discards real information: where upstream's own 1:1
program makes an explicit choice, that choice *is* the documented route for the
operation being qualified, and a delivered default would silently replace it.

## Consequences

`FingersTemplateSize` moved from settled to outstanding, so the extraction gate
now has eight unresolved score-affecting settings rather than seven, and exactly
one setting in the whole stage carries `OFFICIAL_SAMPLE_EXPLICIT`. That is a less
comfortable number and a true one.

The qualification harness follows the same rule in code: it sets only what
`verify-finger` sets, and *reads* everything else. A harness that configured the
engine the way this stage wished it were configured would produce a record about
a route nobody uses.

The published profile identity says "the official-sample route" rather than "the
VeriFinger default", because the manual states no default for any of these — and
those are different claims, which was ADR 0101's point and is now enforced
against a single named sample.
