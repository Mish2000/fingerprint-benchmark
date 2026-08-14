# Pair labels come from the API under test

## Status

Accepted, implemented. Narrows ADR 0109 — an asymmetric matcher is bound by
protocol, not normalised — where the two candidates use different words.

## Context

ADR 0109 settled the substance for Stage 12A: the benchmark's pair order maps onto
the matcher's two roles by a frozen protocol binding, both orderings are run for
observation, and neither is normalised away.

It also chose words. Innovatrics' API names its sides *probe* and *gallery*, so
the binding was written `pair.left -> probe`, `pair.right -> gallery`.

FingerCell's delivered header names them differently:

```c
NResult FingerCellMatch(HFingerCell, HNBuffer hReference, HNBuffer hCandidate, NInt* pScore);
```

Reference and candidate. Carrying probe/gallery across would produce a binding
that describes an API this archive does not have — and, worse, one that reads as
though it had been checked against something.

## Decision

The binding takes its words from the API under test:

```text
pair.left  -> reference
pair.right -> candidate
```

A constant records that pair labels are not copied from another candidate, and the
marker refuses any other orientation string. The contract suite asserts that
neither "probe" nor "gallery" appears in this stage's role names.

Everything else in ADR 0109 is unchanged: both orientations are produced during
qualification, whether they agree is published as a finding, no symmetry is
required, and no reduction — average, maximum, minimum, or picking the higher — is
permitted.

## Alternatives

**Keep probe/gallery as house terminology and translate at the boundary.** One
more translation layer between the protocol and the API, in a stage whose entire
job is establishing what the API actually does.

**Adopt reference/candidate everywhere retroactively.** It would edit closed
stages to rename something they got right for their own API.

## Consequences

Each candidate's evidence uses the vocabulary of the thing it evaluated, so a
reader comparing a document against a vendor header sees the same words.

Cross-candidate reading needs one mapping, which is why both stages state their
binding explicitly rather than implying it.
