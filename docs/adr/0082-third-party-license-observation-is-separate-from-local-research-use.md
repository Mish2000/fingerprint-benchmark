# 0082 — A licence observation is separate from a local research-use decision

*Status: Accepted — 2026-08-08, stage 8E*

## Context

Two different questions kept arriving as one field.

*What does upstream licensing say?* is a question about somebody else's document.
It has an answer whether or not this project likes it, and the answer can be
"the notices contradict each other".

*May fpbench execute this locally, under its declared purpose?* is a question
about this project. Its answer depends on the first one, on what this project
actually does, and on nothing else.

Collapsing them produces two failure modes, and this repository has already seen
both.

**Blocking on an irrelevance.** Stage 8A's licence gate required, among other
things, permission for publication and for use in an academic benchmark. A
component licensed "research use only, no redistribution" fails a gate like that
— while permitting, in full, the only thing this project was ever going to do
with it. The gate was measuring a use nobody intended.

**Rewriting the observation to unblock the decision.** The opposite temptation,
and much worse: mark the licence resolved because the experiment is proceeding.
Stage 8B named this explicitly and refused it (ADR 0068) — a false provenance
claim inside a fingerprint gets republished by every downstream stage that binds
to it.

Neither failure is fixed by better judgement. They are fixed by not having a
field that can hold both answers.

## Decision

Three vocabularies, three artifacts, and no path by which one becomes another.

**`LicenseObservation`** describes upstream's notices. Its status is one of
`OPEN_SOURCE_PERMISSIVE`, `OPEN_SOURCE_COPYLEFT`, `ACADEMIC_ONLY`,
`RESEARCH_ONLY`, `NON_COMMERCIAL`, `SOURCE_AVAILABLE`, `CONFLICTING_NOTICES`,
`NO_LICENSE_FOUND` or `UNKNOWN`. The class has no field for what fpbench may do,
and that absence is load-bearing: an observation that could also carry a
conclusion is an observation that will eventually be read as one.
`CONFLICTING_NOTICES` is an ordinary observation, not a problem awaiting
resolution.

**`ResearchUseAssessment`** decides. Its decision is one of `ALLOWED`,
`ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`, `OWNER_RISK_ACCEPTED` or `BLOCKED`. It
cites exactly one observation by fingerprint, so the description it rests on
cannot be edited underneath it.

**`RedistributionRecord`** records what upstream permits by way of
redistribution, and is then ignored: this project redistributes nothing
regardless (ADR 0083).

The operating rule:

> Third-party licensing does not block local personal educational research
> execution merely because commercial use, redistribution, sublicensing or
> publication is restricted.

So these are recorded, respected, and are **not** blockers: non-commercial only,
academic or research only, educational only, no redistribution, no sublicensing,
copyleft, strong copyleft, weights may not be redistributed, a commercial licence
required for commercial deployment, and a notice conflict whose every plausible
reading still permits this project's exact use.

And these **are** blockers, as a closed list: an express prohibition of the
intended research use; an express prohibition of biometric use where fingerprint
recognition is the intended use; a prohibition of the modification that faithful
execution requires; access terms that cannot be satisfied; an artifact obtained
by circumventing authentication, a paywall, an access control or another
technical restriction; terms incompatible with local execution; an artifact whose
identity or provenance cannot be established; unsatisfied dataset access terms;
and permission that is unresolved with no risk accepted (ADR 0084).

**The intersection rule.** Where notices conflict or restrict the field of use,
the project does not pick a winner. It asks which uses *every* plausible reading
permits in common, and if local non-commercial educational research is in that
intersection the decision is
`ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` — leaving `CONFLICTING_NOTICES`
untouched. The intersection is a conjunction: one reading that forbids the
operation blocks it.

**Nothing decides by hand.** `assess_research_use` takes the observation and the
facts and *derives* the decision; there is no parameter through which a caller
could supply one. `fpbench.third_party.verify` re-runs the same table over the
stored facts and compares.

Each component kind — source code, model weights, runtime binary, package
dependency, dataset, documentation, other artifact — gets its own observation.
A repository licence is not a checkpoint licence (ADR 0063), and now the shape of
the record says so.

## Alternatives considered

**One field with more values.** `LICENSE_CLEAR_FOR_RESEARCH` and friends. It
reads well until the first component whose licence is unclear and whose use is
obviously fine, at which point the value is a lie in one direction or the other.

**Resolve every conflict before deciding.** Sometimes impossible, and usually
unnecessary. Deciding which of two contradictory notices governs is a legal
question; deciding whether both of them permit one narrow use often is not.

**Treat a restrictive licence as a blocker and pick different components.** That
is Stage 8A's policy, and it costs the project most of the modern-matcher
landscape for restrictions that do not touch what it does.

**Let the caller pass a decision and validate it.** An engine that accepted a
verdict and then checked it would be an elaborate way of writing the verdict
down. The point of the split is that the answer is mechanical.

## Consequences

The evidence is more verbose: three artifacts per component instead of one field.
In exchange, a reader can see exactly which upstream fact was observed, which
project fact it was weighed against, and which rule produced the answer — and can
disagree with the last of those without touching the first.

A component can be `CONFLICTING_NOTICES` and executable, and the repository says
both. A component can be permissively licensed and still not redistributed here,
and the repository says both.

Stage 8A's and Stage 8B's published conclusions are not revised. They answered
different questions under different policies, and rewriting them to match a later
convenience is exactly what ADR 0068 forbade.
