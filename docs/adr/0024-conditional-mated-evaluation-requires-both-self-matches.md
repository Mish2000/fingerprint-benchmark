# 0024 — The conditional mated view includes a pair only when both its SELF decisions match

## Status

Accepted. Implemented in `fpbench.evaluation.views` and `fpbench.evaluation.verify`.

## Context

The protocol asks for the PLAIN–ROLL stage to be reported twice: once over everything,
once over "only those that did not fall in the SELF stages". The supervisor was explicit
about the rule — failing PLAIN SELF disqualifies the pair regardless of how ROLL SELF
went.

The question this ADR settles is not the rule. It is what the *artefact* looks like, and
in particular what happens to the pairs the rule excludes.

## Decision

**Both views hold all 1,500 mated comparisons. The conditional one marks each row
included or excluded, and says why.**

```
plain_roll_mated_unconditional_v1       1,500 rows, all included
plain_roll_mated_both_self_match_v1     1,500 rows, included where ELIGIBLE
```

A row is included exactly when its unit's eligibility status is `ELIGIBLE`. Otherwise it
is present, `included = false`, and carries one of two reasons:

* `self_ineligible` — a SELF comparison produced a `NON_MATCH`;
* `self_undetermined` — a SELF comparison produced no decision at all.

**The excluded rows are not deleted**, and that is the decision. A view that dropped them
would be smaller, would look tidier, and would make the first question any reviewer asks
— "which pairs did you leave out, and why?" — unanswerable without re-deriving the whole
chain. Keeping them costs a few hundred rows and makes the inclusion rule auditable
row by row.

Two things follow that are worth stating:

**The conditional view never changes the unconditional one.** They are separate
artefacts with separate fingerprints. A finger failing SELF removes a comparison from one
report and not the other, which is precisely what "reported twice" means.

**Neither view stores how many rows were included.** In the conditional view that number
*is* the interesting result, and it stays in the workspace: it is derived on demand from
the entries, and it appears in no manifest, no fingerprint and no receipt. Publishing it
would be publishing a finding under a threshold nobody has justified
([ADR 0021](0021-decision-profiles-are-immutable-and-external.md)).

## Alternatives

**Filter the rows out.** Rejected above. It is also lossy in a way that cannot be undone
from the artefact alone.

**A single view with a boolean column and no second manifest.** Tempting, and it conflates
two reports that must be citable separately — a paper will reference one or the other.

**Treat `UNDETERMINED` as `INELIGIBLE` and use one exclusion reason.** Rejected in
[ADR 0023](0023-self-eligibility-is-profile-specific.md); the two are different facts and
a later stage may want to account for them differently.

**Compute the conditional count here.** That is a metric, and metrics need denominators
that do not exist yet.

## Consequences

* The conditional view's row count always equals the unconditional view's. A difference
  would mean the mapping and the manifest disagree.
* Every exclusion is attributable to one eligibility unit, by unit id and record hash.
* Verification recomputes the `included` flag from the eligibility verdict rather than
  trusting it, because it is one boolean per row and the easiest thing in the chain to
  change unnoticed.
* Changing the threshold changes which rows are included, which changes the view
  fingerprint — so a conditional result can never be quoted against the wrong threshold.
