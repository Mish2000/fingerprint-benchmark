# A wait and a chore are not the same non-answer

## Status

Accepted, implemented. Reunites ADR 0104's `ACTION_REQUIRED` and ADR 0108's
`PENDING` into one gate vocabulary, because Stage 14A is the first candidate
where both are live at the same gate.

## Context

Four Algorithm 5 attempts have now produced four different shapes of "not yet".

Stage 10B published a `FAIL` for a vendor nobody had written to. Stage 11A
answered with ADR 0104: `ACTION_REQUIRED` for work this project had not done.
Stage 12A met a chore that was not this project's to perform at all and answered
with ADR 0108: `PENDING`, for a route walked to a vendor who had not replied.
Stage 13A had no vendor dependency whatsoever — Neurotechnology publishes a
direct download — so it carried ADR 0104's vocabulary alone and dropped
`PENDING` entirely.

Griaule is the first candidate where the two are *the same gate at different
moments*. There is no self-service download; the vendor's own documentation
names a request as the route. So acquisition passes through:

```text
routes walked, request not sent    -> our move
request sent, no reply             -> their move
reply, and it declines             -> a finding
```

The middle two look identical from outside — no package either way — and mean
opposite things. If both are published as one state, the evidence cannot
distinguish "Griaule has not answered us" from "we have not asked Griaule", and
the first of those is a quiet, unearned slur on a vendor who was never contacted.

The failure mode is not hypothetical. Stage 13A's own closure had to be corrected
because a blocker described a licensing service as having received and answered a
request at the transport level, when what was actually observed was narrower.
Overstating what an absence proves is this project's recurring publication bug.

## Decision

Five gate states, and three of them are not verdicts.

```text
GateStatus.PASS              asked and answered
GateStatus.FAIL              an attempt or inspection disproved viability
GateStatus.PENDING_ACCESS    a vendor or external dependency is outstanding
GateStatus.ACTION_REQUIRED   a local action has not been performed yet
GateStatus.NOT_REACHED       the run had already stopped
```

Three separate vocabularies, disjoint by construction and checked at import:

- `BlockerCode` — observed findings about the candidate. Ten codes, each with a
  matching `FailureClass`.
- `PendingKind` — reasons somebody outside this project has to move. Available at
  the acquisition gate only, because every later gate is answered by reading
  bytes this project holds.
- `RequiredAction` — steps this project owes.

A `GateResult` may carry at most one kind. A gate cannot be waiting on the vendor
and on this project at once; one of the two is the next move, and the state says
which.

Two non-final outcomes follow, and **neither writes a marker**:

```text
GRIAULE_PREFLIGHT_PENDING_ACCESS   somebody else has to move
GRIAULE_PREFLIGHT_INCOMPLETE       we have a step left to take
```

The marker class refuses both outright rather than validating them leniently, and
a finalized marker must have `gates_pending_access == 0` and
`gates_awaiting_action == 0`.

The request status is a **frozen constant a human edits when they perform the
act**, not something inferred. A mailbox this code cannot see is not a state it
can derive, and a stage that guessed would eventually publish "the vendor did not
reply" about a message nobody sent. The acquisition module validates at import
that a send date exists if and only if the request was sent.

## Alternatives

**Keep `PENDING` only, as Stage 12A did.** It would publish an unsent request as
a vendor wait — precisely the misattribution this ADR exists to prevent.

**Keep `ACTION_REQUIRED` only, as Stage 13A did.** Symmetrically wrong once the
reply is genuinely outstanding: it would report a vendor's silence as this
project's laziness, and would leave a maintainer looking for work to do that does
not exist.

**Derive the request state from a mailbox or a ticket API.** It would make the
state machine depend on a credential in a service this project does not control,
for a fact one line of source records honestly.

**Collapse both into `FAIL` and re-open later.** This is what Stage 10B did, and
it is the reason ADR 0104 exists.

## Consequences

The gate vocabulary is wider than any previous stage's, and the width is load
bearing: five states, three attachment types, and a construction rule that keeps
them apart. Every one of the three has a test that proves the wrong combination
raises.

An honest Stage 14A therefore *cannot* finalize until somebody acts. Today it
publishes eight documents, `GRIAULE_PREFLIGHT_INCOMPLETE`, and no marker — and
the published evidence says, in the acquisition document itself,
`vendor_was_not_asked_and_did_not_refuse: true`.

The cost is that a maintainer must remember to edit one constant when they send
the request. The benefit is that nothing in this repository can claim a vendor
was asked when they were not.
