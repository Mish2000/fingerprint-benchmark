# 0022 — A decision set cites one exact result set and one exact profile

## Status

Accepted. Implemented in `fpbench.core.decision_models`, `fpbench.decisions.apply` and
`fpbench.decisions.verify`.

## Context

The obvious way to store decisions is a table keyed by `run_id`: "these are the decisions
for run X". It works until any of three things happens, and all three will.

A second threshold is applied to the same run. A raw result is regenerated. The code that
maps failures to codes changes. In each case the natural table either has to be
overwritten — losing the previous answer — or acquires a second meaning under the same
name.

[ADR 0019](0019-result-sets-have-independent-immutable-identity.md) already established
that the *scores* have an identity of their own, precisely so a later stage could cite
them. Decisions need the same treatment, one level up, for the same reason: the stage
after this one will apply metrics to a specific set of decisions, and "the decisions for
run X" is not specific.

## Decision

**A decision set is identified by everything that could change a decision, and by
nothing else.**

`decision_set_fingerprint` covers:

* the run and plan fingerprints;
* the **result-set fingerprint** — the exact ordered scores, not "the run's results";
* the **decision-profile fingerprint** — the exact threshold, comparator and provenance;
* the **derivation software fingerprint and commit** — the code that applied it;
* the ordered `(ordinal, job_id, source_result_hash, decision_record_hash)` tuples;
* the decided and undecidable counts.

`decision_set_id` is `decisionset_<12 chars>` of that digest, and it is the directory
name. A different threshold, a different score, or a different derivation commit lands
somewhere else and cannot collide.

Two further rules make it evidence rather than a cache:

**The raw score is not copied into a decision.** A decision cites its result by hash and
leaves the number where it was written. Copying it would create a second place a score
lives, and the first thing a reader would have to stop trusting.

**Verification re-derives.** `verify_decision_set` goes back to every raw result file,
re-hashes it, re-applies the threshold, and compares — record hash, ordering, counts and
the set fingerprint included. A decision set is not evidence of itself; a manifest is a
file, and a file can be edited.

The derivation definition stores the complete immutable `SoftwareProvenance` — source
revision and tree state, package and Python versions, and the tracked PyArrow/PyYAML
versions — beside its fingerprint. Verification re-hashes that record and requires its
revision to agree with the decision set, receipt and finalization marker. The derivation
commit is also covered as its own field in the decision-set digest so the two claims
cannot drift independently.

## Alternatives

**Key decisions by run and profile id.** Almost right, and silently wrong when a raw
result changes underneath: the id would stay the same while the decisions no longer
followed from anything.

**Store the score alongside the decision "for convenience".** Rejected above. The
convenience is real and the cost is a second copy of the truth.

**Trust the manifest's own fingerprint and skip re-derivation.** Cheaper, and it proves
only that the manifest is internally consistent. A tampered set can be perfectly
self-consistent.

**Let a decision set float over "the latest results".** This is the failure mode the
whole ADR exists to prevent, and it is the one that produces numbers nobody can
reproduce a year later.

## Consequences

* Applying two thresholds to one run produces two directories, both complete, neither
  overwriting the other. That is the intended way to compare thresholds later.
* Re-deriving with unchanged inputs is a genuine no-op: same id, same files, nothing
  rewritten.
* Verification costs roughly what derivation cost — it reads every result file — and it
  runs at finalisation and on every status query. That is deliberate.
* A change to the derivation code changes every decision set it produces, including over
  identical scores under an identical threshold. This is the same trade
  [ADR 0017](0017-research-runs-pin-fpbench-source-revision.md) made for runs, and it is
  accepted for the same reason: the code decides ordering, failure classification and
  hashing, and the harness cannot tell which lines could matter.
