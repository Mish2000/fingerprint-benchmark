# 0084 — Ambiguous upstream rights may be risk-accepted without becoming a licence finding

*Status: Accepted — 2026-08-08, stage 8E*

## Context

Some artifacts arrive with no terms at all. The learned extractor's checkpoint is
one: it was published by its authors on a cloud drive, and nothing accompanied it
— no licence file, no notice, no statement. Two of NIST's NBIS archives are
another: obtained from NIST's own distribution index, sealed by digest, and no
licence document from that distribution has ever been inspected and recorded in
this repository.

There are two wrong answers and this project has been offered both.

**"No licence means free to use."** False. In the absence of a licence, default
copyright applies and nobody has granted anybody anything. Writing
`license: permissive` because none was found would put a fabrication inside a
fingerprint, where every downstream stage would republish it.

**"No licence means blocked, permanently."** Defensible, and it is what Stage 8A
did. It is also, for a personal learning project running one program on one
machine and publishing no bytes, a rule that ends the project. The owner
weighed that and instructed otherwise for one checkpoint in Stage 8B (ADR 0068).

What Stage 8B could not do was generalise, because it had one instruction about
one file, not a rule. Stage 8E needs a rule, and the rule must not quietly turn
the first wrong answer into the project's default.

## Decision

A third state, named so that nobody can mistake it for permission:

```
intended_use_permission_status:   UNRESOLVED
research_use_decision:            OWNER_RISK_ACCEPTED
```

It says the project owner decided to proceed with a local research operation
despite an ambiguity nobody resolved. It does **not** say the use is permitted,
and the permission field stays `UNRESOLVED` precisely so that the distinction
survives into every document that cites it.

It is available only when all five of these hold:

```
the artifact was intentionally published by its official authors
the artifact is publicly obtainable without circumventing any access control
the intended operation is local research only
no located term expressly prohibits that use
no bytes will be redistributed by this project
```

All five, together. `OwnerRiskAcceptance` refuses to construct with four, and the
message says so: a partial acceptance is a decision to block. Where no acceptance
is offered at all, the absence of permission stands on its own as the blocker
`PERMISSION_UNRESOLVED_AND_NOT_RISK_ACCEPTED` — silence is not a grant.

Three further limits.

**Risk cannot be accepted over terms that were found.** If a licence was
identified, the answer follows from it. The owner may accept a risk where nothing
is established; they may not overrule a document.

**A dataset may never be risk-accepted.** Biometric access terms, privacy and
data-use conditions are a different subject, and Stage 8E changed nothing about
them. A dataset record must state that its own access terms are satisfied, and if
it cannot, it is blocked.

**Historical evidence is not rewritten.** Stage 8A's `LICENSE_BLOCKED` and Stage
8B's `weights_license_status: unresolved` remain exactly as published. This is a
new mapping beside them, not an amendment to them. Stage 8E's legacy audit
produces new documents; it edits none.

## Alternatives considered

**Mark the licence resolved because the owner authorised use.** Wrong category,
and ADR 0068 already rejected it for one artifact: the owner can authorise their
own machine, they cannot supply terms the author never published.

**Refuse everything with no established licence.** Stage 8A's answer. It is
coherent and it costs this project the learned-representation route and the NBIS
route both. The cost is the owner's to weigh, and they weighed it.

**Record the permission and drop the licence fields.** Silence reads as "not a
problem" to the next reader. An explicit `NO_LICENSE_FOUND` beside an explicit
`UNRESOLVED` reads as what it is.

**One boolean, `owner_approved`.** It would collapse "the owner accepted a risk"
into "this is fine", which is the whole thing this ADR exists to prevent.

## Consequences

Four of the twelve components in Stage 8E's legacy audit carry
`OWNER_RISK_ACCEPTED`, and the marker refuses to be written with a count of zero
— a marker claiming this repository has no unresolved permissions would be
describing a different repository.

Every future document derived from those components inherits the unresolved
status rather than a cleared one. Any future publication of results derived from
them has to confront that rather than discover it late, exactly as Stage 8B said.

If terms are ever established for one of these artifacts, that is a new
observation with its own provenance and a new assessment beside it — not an edit
to these.

The risk is the owner's, it is recorded as theirs by name, and it is scoped to
one operation: local execution, no redistribution, no publication of upstream
bytes. Nothing here extends to anybody else running this repository, and the
policy documents say so.
