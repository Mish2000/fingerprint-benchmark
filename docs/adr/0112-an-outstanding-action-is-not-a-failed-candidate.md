# An outstanding action is not a failed candidate

## Status

Accepted, implemented. Carries ADR 0104's vocabulary into Stage 13A from the
first day rather than after the first misleading publication, and narrows it
where ADR 0108's answer does not apply.

## Context

Three stages have now met the same problem from three directions.

Stage 10B published `ID3_FINGER_SDK_PREFLIGHT_FAIL` for a vendor nobody had
written to. Stage 11A hit it again with chores of its own and answered with ADR
0104: `ACTION_REQUIRED`, an `INCOMPLETE` outcome, and a separate vocabulary for
work nobody had done. Stage 12A hit a third variant — a chore that was not this
project's to perform at all — and answered with ADR 0108's `PENDING`.

Stage 13A is the first candidate where **none of the outstanding work belongs to
anybody else**. Neurotechnology publishes a direct FingerCell trial download: no
portal, no sales conversation, no permission. Every remaining question is one
this project can answer for itself by doing the work.

That makes `PENDING` meaningless here and makes ADR 0104's distinction the whole
state machine rather than an exception in it. It also raises the risk that
matters: when every gate is answerable, a gate reported as `FAIL` because nobody
got round to it would be a published verdict about a vendor's algorithm derived
from this project's own idleness.

## Decision

Four gate states, and no vendor-pending state at all.

```text
GateStatus.PASS              asked and answered
GateStatus.FAIL              an action was performed and exposed an incompatibility
GateStatus.ACTION_REQUIRED   a local action has not been performed yet
GateStatus.NOT_REACHED       the run had already stopped at a FAIL
```

```text
FINGERCELL_PREFLIGHT_PASS         every gate asked, every gate passed
FINGERCELL_PREFLIGHT_INCOMPLETE   nothing failed; something was not done
FINGERCELL_PREFLIGHT_FAIL         something was found wrong with the route
```

The rule is stated as a pair, because it is the pair that carries the meaning:

```text
local action not yet performed
    -> ACTION_REQUIRED

action actually performed and exposed an incompatibility
    -> FAIL
```

**The two vocabularies are disjoint and it is checked at import time.** Blockers
name findings; `RequiredAction` members name work. No string may be both, and a
gate awaiting an action carries no blocker.

**`ACTION_REQUIRED` produces no finalization marker.** The marker class refuses
`INCOMPLETE` outright, and the publisher refuses to write one while any gate
awaits an action. An incomplete stage looks incomplete in its published evidence.

**An incomplete run reopens nothing.** It does not open Stage 13B and it does not
reopen the Algorithm 5 candidate search, because it has decided nothing. Only a
final `FAIL` returns selection to the next candidate.

**A failed run is not an incomplete one.** A qualification that started, loaded
the runtime and then broke is recorded `FAILED` and read as a failure. Turning an
execution failure into `ACTION_REQUIRED` would convert a finding into a chore.

## Alternatives

**Reuse ADR 0108's `PENDING`.** It says "somebody else has to move next", which
is false here and would misdescribe every gate it touched.

**Report unperformed gates as `FAIL` and explain in prose.** Stage 10B did this
and had to repeat the explanation in nearly every document. The composite claim
is what readers carry away, and it was wrong.

**Report them as `NOT_REACHED`.** It is not false, but it loses the only useful
part: which action, and what it would answer.

## Consequences

The published evidence of an incomplete stage is a to-do list with a gate against
each item, which is more useful than a verdict and considerably harder to
misread.

It costs a vocabulary that must be maintained in two disjoint halves, and an
import-time check to keep them that way.

The main risk is a stage sitting at `INCOMPLETE` indefinitely and being mistaken
for a finished negative result. The README states the status in its first line
for exactly that reason.
