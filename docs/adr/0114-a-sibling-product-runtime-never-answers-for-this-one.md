# A sibling product's runtime never answers for this one

## Status

Accepted, implemented. New with Stage 13A, and specific to it.

## Context

Algorithm 4 is Neurotechnology VeriFinger 2025.2. The Algorithm 5 candidate is
Neurotechnology FingerCell 3.3. For the first time this benchmark is evaluating
two products from the same vendor, and they share a component ecosystem: the same
common runtime, the same image runtime, the same licensing runtime, the same
naming convention, and in places the same file names.

Three distinct ways that goes wrong:

**In the route.** The delivered documentation says FingerCell uses other
Neurotechnology components for image formats and scanner support. A route that
passed a canonical image into a general biometric engine would still return an
integer. It would be VeriFinger's integer, published under FingerCell's name, and
nothing downstream could tell.

**In the licence.** A Neurotechnology licensing service is already running on this
host for Algorithm 4. "A licence was obtained" is therefore nearly meaningless: it
can succeed while saying nothing about a FingerCell entitlement.

**In the code.** A Stage 13A module importing Algorithm 4's adapter, bridge or
published identity is one line, and it would make this stage's answers depend on
what Algorithm 4 had been run with.

## Decision

The runtime closure is established from *this* archive and is never inherited
from the sibling. A constant says so and the gate checks it.

**Common utility components are permitted; algorithm components are not.** The
common runtime, the image runtime, the licensing runtime and platform libraries
may appear in the closure — but only because the FingerCell trial itself ships and
requires them, and only when pinned as part of this closure. Any extractor or
matcher belonging to the sibling product is refused outright, and there is a
blocker code for it.

**The entitlement must be FingerCell's own.** The gate requires the licence to
name the FingerCell component specifically, and refuses to infer one from a
running licensing service. The delivered tutorials obtain a licence for the
component named `FingerCell`, so this is upstream's own route rather than an
invention.

**Imports are audited.** A source-level guard walks every Stage 13A module and
refuses any import that reaches the sibling algorithm's adapter, bridge, runtime,
qualification or published identity. It has its own error class so the failure
cannot be mistaken for an ordinary gate result.

**Prior scores are never read.** Stage 11B's marker is bound by fingerprint and
its outcomes are never opened, which is unchanged policy — but here it also stops
the obvious shortcut of "compare the two and see if the numbers look similar".

## Alternatives

**Assume the closure matches Algorithm 4's.** Cheap, and unfounded. The delivered
FingerCell module's dependencies turn out to be a small subset of what the archive
ships, which nobody could have known without looking.

**Rely on the module names.** They are similar on purpose; that is the hazard,
not the mitigation.

**Ban common components entirely.** The route would not run. Image loading and
licensing genuinely go through them.

## Consequences

The route can be shown to be FingerCell's, positively, rather than assumed to be.

It costs an extra error class, an import audit, and a gate that can refuse a
licence that was genuinely obtained.

The static closure alone is not treated as proof; see ADR 0120.
