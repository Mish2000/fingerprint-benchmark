# Settings are read before they are set

## Status

Accepted, implemented. Extends ADR 0101 — every score-affecting setting carries an
upstream provenance — with an ordering requirement.

## Context

The delivered C++ binding exposes typed accessors for three properties:
`ImageQualityThreshold`, `MatchingAlgorithm` and `TemplateFormat`. The
documentation lists more than three — the minutiae count limits and a
large-template switch among them.

Inspecting the delivered module shows the gap is real: it carries property names
the typed surface never reaches, including at least one — a quality-use switch —
that appeared in no plan written before the archive was opened.

Two failure modes follow.

The first is a closure built by ticking off a list written in advance. It would
report zero unresolved settings while leaving several genuinely unread.

The second is subtler and more damaging. The obvious way to make a run
reproducible is to set every known parameter to its documented default before
running. Doing that *destroys the evidence*: once a value has been written, nobody
can say whether the engine would have had it anyway. A
`DELIVERED_RUNTIME_DEFAULT` can only be observed before it is overwritten.

## Decision

The order is fixed:

```text
construct the engine
  -> read every obtainable property through the supported property mechanism
  -> compare against the version-matched documentation
  -> configure something only where the official route explicitly requires it
```

A generic property setter may not be used to "pin" defaults before they are read.

**The known list is a floor, not a ceiling.** A constant states that it is not
exhaustive, and the discovery surfaces are named: the delivered documentation, the
delivered samples and tutorials, property metadata or reflection on a constructed
engine, and the delivered headers and bindings.

**A mismatch is a finding, not a correction.** Where the delivered runtime reports
a matching algorithm other than the documented default, the gate fails rather than
forcing the documented value back silently. A runtime disagreeing with its own
documentation is information about the artifact.

**An unresolved score-affecting setting fails the closure gate**, and an inventory
that does not exist yields no count at all rather than a count of zero.

## Alternatives

**Set everything explicitly for reproducibility.** Reproducible and unattributable:
the profile would be this project's, not upstream's.

**Trust the documented defaults.** They describe a version, not this build.

## Consequences

The settings closure requires a running engine, which means it cannot be completed
before the trial is activated — and the gate says so as an outstanding action
rather than pretending otherwise.

What it buys is a settings profile every value of which has an upstream authority
behind it, including the ones nobody thought to look for.
