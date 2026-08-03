# 0054 — Stage 7C alignment is part of completion authority

*Status: Accepted — 2026-08-03, stage 7C closure*

## Context

The general research receipt and finalization marker bind a run, plan, runtime,
result set, audit, algorithm validation and completion. They intentionally know
nothing about Stage 7C's additional claim: that the NBIS run received the
reference run's exact ordered pairs and prepared pixels.

An alignment report beside that chain is not enough. If the report can be
rewritten without invalidating a last-written authority, the central claim of
Stage 7C is informative but not load-bearing. The expected experiment shape is
also part of that claim because it defines what `is_clean` means.

## Decision

`canonical_run_alignment_v2` fingerprints every report claim, including all
fields of `AlignmentExpectations`. A stored report is parsed, its expectations
are validated, its fingerprint is recomputed, and its complete contents are
compared with a report re-derived from the manifests.

Stage 7C writes `stage-7c-finalization.json` after the general research chain and
the alignment have both verified. The marker binds:

* the run and result-set identities and fingerprints;
* the research receipt fingerprint and content hash;
* the general research finalization fingerprint;
* the reference run, plan and result-set identities;
* the alignment fingerprint and complete stored-report content hash;
* the clean committed verifier revision.

`inspect_nbis_canonical500_experiment` re-derives the alignment and reconstructs
the marker from the authoritative stores. Missing, malformed or mismatched Stage
7C finalization makes `is_ready` false. The marker is copied to committed
evidence with the rest of the Stage 7C chain.

## Consequences

Changing verifier logic does not require rerunning 6,000 comparisons. From a
clean committed tree,
`refresh_nbis_canonical500_stage_finalization` re-verifies the existing research
chain, regenerates the alignment and writes a new Stage 7C marker. Raw results,
the plan and the result set remain untouched.

The exact source commit that produced the run remains separately reachable via
the published `stage7c-run-source` ref.
