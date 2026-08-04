# 0055 — Strict comparators arrive under a second profile schema

*Status: Accepted — 2026-08-04, stage 7D*

## Context

SourceAFIS documents a match at a score **of at least** 40. NIST's NBIS guide
describes a BOZORTH3 score **greater than** 40 as a rule of thumb that usually
indicates a true match. Those are two different sentences about two different
scales, and reading either one as the other moves a boundary nobody moved.

Until stage 7D, `ThresholdComparator` had exactly two members, both inclusive,
and `DecisionProfile` enforced one comparator per score direction. Adding the
strict spellings is easy. Adding them *without changing anything else* is not:
`decision_profile_fingerprint` is cited by four decision sets, four eligibility
sets, four metric sets and every receipt and finalization marker above them. A
mapping that acquired a field, or a validation table that silently widened,
would move all of those at once — and nothing downstream would report it,
because the artefacts would simply stop verifying against identities that no
longer exist.

## Decision

`ThresholdComparator` gains `GREATER_THAN` and `LESS_THAN`, and `decide_score`
handles all four through one table of predicates, in `Decimal`, with no epsilon.

`DecisionProfile` gains a `schema_version`, defaulting to `"1"`:

* **schema 1** admits one comparator per score direction — the inclusive one —
  and hashes under `decision_profile_fingerprint_v1` with exactly the fields it
  always had. It is frozen. A `claims` block or a `source_statement_kind` under
  schema 1 is refused rather than ignored, because a field outside the
  fingerprint is an assertion the identity does not cover.
* **schema 2** admits the inclusive or the strict comparator for each direction
  and hashes under `decision_profile_fingerprint_v2`, which additionally records
  `comparator_is_strict`.

A profile file with no `schema_version` is schema 1, which is what every profile
written before stage 7D is.

The same shape applies one layer up. `DecisionDerivationReceipt` and its
finalization marker gain schema 2, which binds the derivation definition, the
derivation software identity and the source run's stage marker; schema 1 carries
none of them and hashes exactly as before. Fields introduced after publication
are removed from the hashed document when absent rather than hashed as `null`.

## Consequences

A schema-2 profile whose every other field matches a schema-1 profile is a
*different* profile with a different identity. That is the intended reading: it
was written under a grammar in which `greater_than` was possible.

`tests/regression/test_legacy_decision_profile_identities.py` pins the two
published SourceAFIS profile digests as literals, so an edit to the schema-1
mapping fails a test instead of invalidating a verified chain.

The cost is two mappings to maintain. The alternative — one mapping and a
migration — would have required re-deriving and re-publishing six artefacts to
express a change that affects none of them.
