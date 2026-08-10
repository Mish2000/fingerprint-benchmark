# 0095 — Operational access and research use are separate gates

*Status: Accepted — 2026-08-10, stage 10B*

## Context

Stage 8E separated three questions that had been collapsing into one: what
upstream licensing says (an observation), whether fpbench may execute a
component locally under its declared purpose (a decision), and whether fpbench
may redistribute it (always: it does not). That split is what lets this
repository hold `license_observation_status: CONFLICTING_NOTICES` beside
`research_use_decision: ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` without
contradiction.

Every component Stage 8E was built for was already in hand. FLARE's checkpoints
sat behind a Drive link, SourceAFIS and NBIS are downloadable, JIPNet's archive
was fetched twice. The question was always *may we run this*, never *do we have
it*.

A commercial SDK breaks that assumption. id3's own samples state that the SDK
archive and the licence activation key are issued together, after a request to
the vendor has been accepted, and that the library checks a licence file before
any other call. Two entirely different things can now go wrong:

```text
the terms forbid what we want to do        ->  a research-use decision
we do not have a copy, or a live licence   ->  something else entirely
```

Collapsing them would be wrong in both directions. Recording "no package" as a
research-use refusal would put a licence finding in this repository that no
reading of id3's terms supports — the same error ADR 0068 corrected when local
execution permission was being confused with a licence finding. And treating a
permissive research-use decision as sufficient to execute would let a stage
declare a route open that cannot run, because no licence has been activated.

## Decision

Stage 10B introduces `OperationalAccessDecision`, a **stage-local** vocabulary
distinct from Stage 8E's `ResearchUseDecision`:

```text
ResearchUseDecision        may this project execute this component
                           under its declared purpose?          (Stage 8E owns it)

OperationalAccessDecision  does this project hold a working copy
                           and an active licence, today?        (Stage 10B owns it)
```

```text
OPERABLE  NO_PACKAGE  NO_LICENSE  LICENSE_INACTIVE
CAPACITY_INSUFFICIENT  UNRESOLVED
```

**Both must be satisfied.** A component may be `ALLOWED` by Stage 8E and
`NO_PACKAGE` here, and execution stays closed. A component may be operable and
`BLOCKED` by Stage 8E, and execution stays closed for a different reason. The
conjunction is the rule; neither substitutes for the other.

**No licensing subsystem is added.** Stage 8E's engine, models and policy are
untouched. The SDK package, each model artifact and the licence file are
ordinary `ThirdPartyComponent`s and will be enrolled as such when one of them
exists. Today none does, and Stage 10B writes no usage manifest at all —
because Stage 8E's own model refuses a manifest with no components, on the
ground that a manifest describing nothing describes nothing.

**Not obtained is not unobtainable.** Two families of code, and only the weak
one is in use:

```text
ID3_PACKAGE_NOT_OBTAINED   ID3_LICENSE_NOT_OBTAINED      a fact about us
ID3_PACKAGE_UNAVAILABLE    ID3_LICENSE_REFUSED           a fact about id3
```

The evidence records `possession: NOT_OBTAINED` beside `obtainability:
NOT_TESTED`, because upstream describes a concrete acquisition route — a
request, an acceptance, then the archive and the activation key — and nobody
walked it. A route nobody walked has not been shown to be closed. This is the
same distinction this project already draws between a checkpoint that does not
fit a model and one whose compatibility was never inspected.

**A blocked outcome says what kind of failure it is.**
`ID3_FINGER_SDK_PREFLIGHT_FAIL` reads identically whether nobody asked or the
vendor refused, so the marker carries a `failure_class` beside it —
`OPERATIONAL_ACCESS_NOT_ESTABLISHED` today — and an explicit
`id3_proven_unobtainable: false`.

**An access failure is final for the route as it stands, and is not worked
around.** The outcome is `ID3_FINGER_SDK_PREFLIGHT_FAIL` and the response is
another candidate. Not a crack, not a licence bypass, not a trial reset, not a
third-party redistribution, and not a reconstruction of the algorithm from its
documentation. The marker publishes `license_bypass_attempted: false` and the
preflight report names the four workarounds that were not considered.

**A blocker says how it would be lifted.** Every Stage 10B blocker carries
`how_this_would_be_lifted` as a mandatory field, because an access blocker is
exactly the kind a person can lift next week and this project should be able to
say what would do it. Today all three name the same act: the maintainer requests
an evaluation or developer licence from the vendor, in their own name, and
re-runs the stage.

## Alternatives

**Extend `ResearchUseDecision` with `NO_ACCESS`.** Rejected. It would edit a
closed stage's vocabulary, and it would put "we do not have a copy" inside an
enum whose every other member is a statement about licence terms.

**Treat absence of a package as `UNRESOLVED` research use.** Rejected for the
same reason in weaker form: an unresolved licence question is a question about
the terms, and nothing about id3's terms is unresolved here. They were not read
for this purpose at all.

**Record no decision until a package exists.** Rejected. The gate has to
conclude something, and "not obtained" is a conclusion a reader can act on.

## Consequences

The evidence can now say, without contradiction, that nothing about id3's terms
blocks research use and that the SDK cannot be executed here.

`research_use_opens_execution` is published as `null` rather than `false` under
a blocked outcome, because no component was assessed and a `false` would read as
a refusal nobody made. The marker refuses a `false` there.

If a licence is obtained later, exactly one gate's inputs change. The stage
re-runs and the eight gates below it become answerable for the first time.

The distinction generalises. Any future commercial candidate inherits it, and so
does any artifact that is permitted but unavailable — which, on the evidence of
Stage 9A's six unenrolled checkpoints, is not a rare shape.

And the blocked outcome cannot be read as a verdict on id3. The candidate failed
no gate about its input domain, its published method, its raw score or its
research-use terms; it failed on a package nobody requested. That is a much
weaker finding than FLARE's or JIPNet's, and the marker says so in a field
rather than leaving it to be inferred.
