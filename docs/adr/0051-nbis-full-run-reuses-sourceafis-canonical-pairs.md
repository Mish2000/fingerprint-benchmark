# 0051 — Stage 7C does not choose pairs; it reuses the canonical run's

*Status: Accepted — 2026-08-03, stage 7C*

> **Stage 7C does not select pairs. It uses the same `PairManifest` and the same
> 6,000 pair IDs as the canonical SourceAFIS run `run_4c59fa02a6ab`.**

## Context

Every experiment before this one built its own inputs. The protocol selected a
cohort from the image manifests, generated 6,000 comparisons from that cohort,
and the planner froze them into an order. Doing the same thing again for NBIS
would produce 6,000 comparisons that are *probably* the same 6,000 — because the
selection is seeded and deterministic — and "probably" is not a property a
comparison between two algorithms can rest on.

Four things could make the second selection differ without anybody noticing:

* an image manifest rebuilt under a different validation policy, changing the
  candidate pool;
* a subject that became ineligible because one file was re-checksummed;
* a change to the pairing rules, which the seed does not cover;
* a filtering step added with good intentions — dropping the pairs the first
  algorithm failed on, or the low-quality prints — which would compare the two
  algorithms over populations chosen by one of them.

The fourth is the dangerous one, because it is the one somebody would do
deliberately.

## Decision

**Stage 7C reads the pair manifest and never generates one.** The experiment
module calls neither `protocol.build_cohort` nor `protocol.build_pairs`, does not
rescan SD300 to choose participants, and loads the manifests with
`allow_creation=False` so that a missing manifest is an error rather than an
invitation. A test walks the module's syntax tree and fails if any of those
appears.

**The reference chain is named, not searched for.** `run_4c59fa02a6ab`,
`plan_b4ae66e91923` and `resultset_087b084fb8a8` are written into
`configs/experiments/nbis_canonical500_full_v1.yaml`. There is no "most recent
finished run".

**Alignment is proved record by record, not by counting.** Before the NBIS run is
created, and again after its plan exists, and again at finalization, a
`CanonicalRunAlignmentReport` compares:

* the two ordered pair-id sequences, position by position;
* every pair's release, protocol stage, ground truth, left image and right image;
* every prepared image's source digest, encoded digest, pixel digest, output
  width, height and resolution, transform action and entry fingerprint.

Two sides of 6,000 rows each that merely *count* the same prove nothing at all.

**All but one is a failure.** `is_clean` is true only when all three equalities
hold across the whole experiment — 6,000 pair ids, 6,000 pair semantics, 3,000
prepared entries — and no issue was raised. 5,999 is not a near miss; it is one
row whose two results cannot be attributed to one comparison.

**No filtering, ever.** Not by the first algorithm's success, not by quality, not
by anything. A pair the reference run failed on is a pair NBIS runs.

## Alternatives considered

**Trust `pair_manifest_hash`.** It is one digest over one file, and both runs do
carry it. But it says the manifest is the same file, not that the two plans were
built from the same rows in the same order — and a plan's order is part of its
identity (docs/adr/0011).

**Regenerate and compare the results.** The selection is deterministic, so
regenerating would usually agree. "Usually" is exactly the word this stage cannot
use, and a regeneration that disagreed would leave two manifests in a workspace
that is meant to hold one.

**Compare the two runs' stored results instead.** That would mean opening
SourceAFIS's scores, which stage 7C is not entitled to do (docs/adr/0052), and it
would prove alignment only for the pairs that produced results.

**Drop the pairs either algorithm failed on.** This is the tempting one. It would
make later numbers tidier and it would silently define the population by one
algorithm's behaviour. Failure analysis is a result of this stage, not a filter
on it (docs/adr/0013).

## Consequences

The alignment check costs a full re-read of two pair manifests and the prepared
set's 3,000 entries on every preparation, inspection and finalization. That is
seconds against a run measured in hours.

Stage 7D can join the two result sets by `pair_id` and defend the join, because
the pair ids were proved equal before either side had a score. It cannot join by
`job_id`, and should not want to: a job id is derived from the run fingerprint, so
the two runs' job ids are disjoint by construction.

The reference run is now load-bearing. It cannot be deleted, re-derived or
re-finalised without invalidating stage 7C's claim, and a workspace that has lost
it cannot verify this stage at all.
