# A preflight that was not run is not a preflight that failed

## Status

Accepted, implemented. Supersedes the two-outcome model in ADR 0099.

## Context

Stage 11A's first publication reported `VERIFINGER_PREFLIGHT_FAIL`, stopped at
its sixth gate, and left eleven gates `NOT_REACHED`. Every individual statement
in it was true. The composite was not.

What had actually happened was that nobody had activated a 30-day trial. Nothing
about VeriFinger had been found wanting: not the artifact, not the licence terms,
not the input domain, not the representation, not the score, not the network
role, not the provenance. The stage nevertheless published the same verdict
string it would have published if the score had turned out to be
non-deterministic — and alongside candidates whose refusals were genuine
methodological findings, that reads as a fifth rejection.

This is the same error Stage 10B took care to avoid one layer down, and then
Stage 11A committed one layer up. Stage 10B distinguished `NOT_OBTAINED` from
`UNAVAILABLE` because "we did not ask" and "we cannot have it" are different
claims. `FAIL` for an unperformed run collapses exactly that distinction at the
level of the whole stage.

Three consequences followed from it, and each was independently wrong:

* **Fail-fast hid answers.** Stopping at gate 6 left the *decisive* raw-score
  gate unpublished, along with the representation, the network role and the
  provenance — all four answerable from the artifact, and none of them dependent
  on the extraction profile.
* **The marker could not describe its own success case.** It asserted
  `licenses_activated == 0` and `scores_produced == 0`. A qualification run
  obtains two licences and scores fixtures, so the marker forbade the very act
  the stage was asking for.
* **It opened a candidate search.** Which would have meant abandoning the
  strongest candidate so far over an unpaid chore.

## Decision

A third gate status and a third outcome, with the difference between them
enforced rather than described.

```text
GateStatus.PASS              asked and answered
GateStatus.FAIL              asked and answered badly — a real blocker
GateStatus.ACTION_REQUIRED   not asked; a named person can make it askable
GateStatus.NOT_REACHED       not asked; the run had already stopped at a FAIL
```

```text
VERIFINGER_PREFLIGHT_PASS         every gate asked, every gate passed
VERIFINGER_PREFLIGHT_INCOMPLETE   everything asked passed; some was not asked
VERIFINGER_PREFLIGHT_FAIL         something was found wrong with the route
```

**Only a `FAIL` stops the run.** Gates awaiting an action are recorded and the
run continues, because most of these gates do not depend on each other. Fail-fast
exists so a broken route is not investigated expensively; it was never meant to
let an unpaid chore hide nine later answers.

**Pending actions are a separate vocabulary** — `QUALIFICATION_RUN_NOT_PERFORMED`,
`TRIAL_LICENCE_NOT_ACTIVATED`, `JAVA_RUNTIME_NOT_AVAILABLE`,
`RUNTIME_PLATFORM_NOT_LOCKED` — and a constant asserts at import time that no
code is both a blocker and an action. A gate awaiting one carries **no blocker**,
and an incomplete marker carries **no failure class**: that is the whole
distinction, so it is a refusal rather than a convention.

**An incomplete outcome does not open a candidate search.** No adverse finding
means no reason to move on.

Three further corrections follow from the same root:

* **Scores are classed.** `qualification_scores_produced` counts fixtures and is
  permitted; `benchmark_scores_produced` and `sd300_scores_produced` must be
  zero. No score *value* is ever published under either name — the harness emits
  a SHA-256 per score and compares digests, so determinism is provable without a
  number leaving the JVM.
* **The licence invariant is inverted.** Instead of `licenses_activated == 0`,
  the marker requires that a recorded qualification run *have* activated one, and
  keeps `license_activated_in_ci` denied.
* **Counts are scoped.** Each profile gate counts its own unresolved settings —
  eight for extraction, two for matching — and any total is derived and labelled
  where it is used. The first publication put a seven in one document and a nine
  in another with nothing saying which was which.

## Alternatives

**Keep two outcomes and call this one PASS.** Would claim a route was qualified
on evidence nobody has.

**Keep two outcomes and leave it FAIL, with prose explaining.** What was tried.
The verdict string is what gets read, quoted and compared against the other four
candidates; a paragraph does not travel with it.

**Add `PENDING` as a synonym for "waiting on a person".** Nearly this decision,
without the part that matters: the point is not that time will pass, it is that
*nothing was found wrong*, and the marker has to be unable to say otherwise.

## Consequences

Today's run publishes eight gates passed on artifact evidence, nine awaiting one
bounded qualification run, zero blockers and no failure class. The decisive
raw-score gate is published as a `PASS` rather than hidden behind an unrelated
chore, which is the single most useful thing this stage now says.

The bar for `PASS` did not move: it is still every gate, conjunctively. What
moved is that failing to reach it now has two different names, and only one of
them is about VeriFinger.

The cost is a genuinely more complicated state machine — four statuses, three
outcomes, two vocabularies — and the risk that `INCOMPLETE` becomes a comfortable
place to leave things. The guard against that is that every pending action names
the deed, the person who can do it, and the gates it would close, and the report
publishes them together.
