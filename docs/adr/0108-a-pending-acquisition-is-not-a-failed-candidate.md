# A pending acquisition is not a failed candidate

## Status

Accepted, implemented. Applies the lesson of ADR 0104 to the acquisition gate,
where ADR 0095 had already half-drawn the line.

## Context

Stage 10B published `ID3_FINGER_SDK_PREFLIGHT_FAIL` for a vendor nobody had
written to. Every individual statement in it was true: no package had been
delivered, so no gate below the second could be answered. The composite was
misleading, and the evidence had to spend a paragraph in almost every document
explaining that the word *fail* did not mean the vendor had refused anything.

ADR 0095 had already seen half of this and separated the *blocker codes*:
`ID3_PACKAGE_NOT_OBTAINED` for "we did not ask" against `ID3_PACKAGE_UNAVAILABLE`
for "we cannot have it". ADR 0104 saw the other half one layer up and added
`ACTION_REQUIRED` and an `INCOMPLETE` outcome for gates waiting on a chore
somebody in this project could do.

Neither covers the case Stage 12A is actually in. Innovatrics delivers through a
customer portal. The chore is not this project's — it is a commercial
relationship, or a person-to-vendor email in the maintainer's own name. It is not
a defect in the candidate, not a defect in this project's setup, and not
something a preflight can perform on anybody's behalf.

## Decision

A third gate status and a third outcome, both narrower than ADR 0104's.

```text
GateStatus.PENDING       an official route was walked and somebody else has to move next
IDKIT_PREFLIGHT_PENDING_ACCESS   the run paused at acquisition
```

**`PENDING` belongs to exactly one gate.** `PENDING_CAPABLE_GATES` holds
`ACQUISITION_ACCESS` and nothing else, and the gate model raises if any other
gate reports it. Acquisition is the one question whose answer can legitimately be
"a vendor has to reply"; anywhere else, pending would be a way of not deciding.

**A pending gate carries no blocker, and no blocker code can be raised by
waiting.** The blocker vocabulary has eighteen members; the acquisition gate owns
two of them — `ACCESS_REFUSED_BY_VENDOR` and `OFFICIAL_PACKAGE_UNAVAILABLE` — and
both are claims about the vendor that only an actual refusal can produce.

**The acquisition state machine is partitioned at import time.** Four pending
states (`NOT_ATTEMPTED`, `PORTAL_ACCESS_REQUIRED`, `REQUEST_SENT`,
`REQUEST_PENDING`), two refusal states, one possession state, and a check that
refuses any member that is in neither set.

**Possession is never asserted.** A person may declare any of the six non-
possession states with a reason and a date; `PACKAGE_OBTAINED` is produced only
by a package in the store that verifies against a declaration of what it is and
where it came from.

**No marker is written while the run is pending.** The marker model raises on the
pending outcome outright, and the publisher refuses before it gets there. A
marker is a finalization, and nothing about waiting for a vendor is final.

**A pending gate names what would move it.** `PendingReason` requires a non-empty
list, and one of the entries is always the route that would produce a genuine
refusal — because `ACCESS_REFUSED` is a legitimate outcome and the stage must not
be structured so that it can only ever wait.

## Alternatives

**Reuse ADR 0104's `ACTION_REQUIRED` and `INCOMPLETE`.** Nearly right, and wrong
in the part that matters. Those describe a chore inside this project — install a
toolchain, activate a trial — with a named person who can do it today. This is
somebody else's decision, and the marker has to be unable to imply otherwise.

**Publish `FAIL` with a `failure_class` of `ACCESS_NOT_ESTABLISHED`.** What Stage
10B did. The verdict string is what gets read, quoted and compared against the
other candidates; a classification field does not travel with it.

**Let a pending run publish a marker with `outcome: PENDING`.** This is the
option that would eventually be used for everything. If a marker can say "still
waiting", then a stage that is stuck for six months looks finalised, and the next
stage's binding check has something to bind to.

## Consequences

Today Stage 12A publishes eleven evidence documents, an outcome of
`IDKIT_PREFLIGHT_PENDING_ACCESS`, zero blockers, no failure class and no marker.
Nothing in it says anything adverse about IDKit, because nothing adverse was
found.

The cost is that the evidence directory is legitimately incomplete, and every
check that walks it has to know that — `require_expected_evidence_files` takes a
`marker_expected` flag, and the CI step that forbids silent skips asserts that
every skip names the missing marker. Both are narrow, and both fail loudly if a
marker ever appears beside a pending run.

The risk is the mirror of ADR 0104's: that `PENDING` becomes a comfortable place
to leave things. The guard is that it is the only outcome with no marker, so it
cannot be bound by a later stage, and the acquisition document publishes the two
concrete acts that would end it.
