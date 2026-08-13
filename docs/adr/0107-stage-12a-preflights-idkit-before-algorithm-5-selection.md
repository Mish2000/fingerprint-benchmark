# Stage 12A preflights Innovatrics IDKit before Algorithm 5 selection

## Status

Accepted, implemented.

## Context

Stage 11B closed Algorithm 4 with 6,000 canonical raw VeriFinger comparisons and
opened a search for Algorithm 5. Innovatrics IDKit is the next candidate, and on
the surface it looks like the easiest one this project has evaluated: it is a
commercial fingerprint SDK, it does 1:1 verification over images, it works in
500 dpi, and its documented score has the shape a benchmark wants.

That surface is exactly the problem. Every one of those facts comes from public
support material — undated, describing an `IEngine_*` API from an older
generation than the version the vendor's own learning portal advertises, and
written for integrators rather than for anybody trying to pin an algorithm. Two
prior stages have already shown what happens when a preflight is built on
material of that kind:

* Stage 10B described id3's SDK carefully and thoroughly, from pages, and then
  discovered the only question that mattered was whether anybody could obtain a
  package at all.
* Stage 11A read VeriFinger's manual, published a profile it called frozen, and
  then found that the manual states a default for every face parameter and for no
  fingerprint one — so most of the values deciding the score had to be read off a
  constructed engine instead.

The specific hazards IDKit adds are structural rather than incidental. It
organises fingerprints into **user records**, and a record holding several
fingers is scored by summing per-position maxima; that number is not a
single-finger similarity and cannot be recovered from one. Its matcher is
documented as **not commutative**. Its image input is documented as **BMP or
raw**, and this benchmark holds PNGs. Any of the three could turn a plausible
candidate into a route that produces numbers which cannot be placed beside the
four algorithms already in the benchmark.

## Decision

A dedicated preflight stage, numbered 12A, that answers exactly one question:

```text
does an official, current Innovatrics IDKit package give fpbench a complete,
upstream-authoritative and reproducible route from canonical_500 to a raw 1:1
fingerprint score, without fpbench inventing preprocessing, extractor settings,
matcher settings or a score transformation?
```

**Ten hard gates, no sub-gates.** Stage 11A's seventeen were the right shape for
an artifact that could be downloaded in one command and interrogated at leisure.
IDKit is delivered through a customer portal, so the ten are ordered so that
acquisition comes first and the raw score is settled before workload and
provenance. Fail-fast throughout.

**The package is the only authority.** No gate below acquisition may be answered
from a support article. Public statements are recorded — with their locators,
their retrieval dates, and a `freezes_a_value: false` field that cannot be set to
true — as the *questions the package will be asked*.

**No production integration.** No adapter, no experiment configuration, no
6,000-runner, no `ResultSet`, no threshold, no calibration, no metric. All of
that is Stage 12B's, and building it here would mean building it before knowing
whether there is a route to build it on. What Stage 12A may build is a state
machine, schemas, a bounded qualification harness, a fake SDK for that harness,
and guards.

**Stage 11A and Stage 11B are not re-opened.** Stage 12A binds Stage 11B's
finalization fingerprint as a predecessor, occupies `algorithm_5`, and its
boundary audit refuses any change under either evidence directory.

## Alternatives

**Go straight to an adapter.** The tempting one, because IDKit looks
integration-ready. It would mean writing a 6,000-comparison layer against an API
nobody in this project has seen, and discovering the consolidated-score problem
after the layer existed.

**Extend Stage 10B's or Stage 11A's machinery.** Both are closed stages whose
markers pin their source byte-for-byte. Extending either would re-open a finished
stage to make room for a new one.

**Seventeen gates again, for symmetry.** Most of Stage 11A's seventeen were
artifact-inspection questions that only make sense when the artifact is a 4.8 GB
archive on disk. Ten gates ask what is actually at risk here and stop.

## Consequences

The stage can answer "no" and can answer "not yet", and today it answers the
second. What it cost was one day of walking official routes and a state machine
that has three outcomes instead of two; what it bought is that the moment a
package arrives, nine gates are already written, the qualification harness
already works end to end against a fake, and nobody has to decide under time
pressure what a frozen setting means.

The risk is that the machinery ages while the package does not arrive. Against
that: every public statement carries its retrieval date, and the whole point of
recording them as questions rather than answers is that a stale question is still
the right question.
