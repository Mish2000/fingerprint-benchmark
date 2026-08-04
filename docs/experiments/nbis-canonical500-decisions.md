# NBIS canonical 500 ppi — decisions

Turning the 6,000 BOZORTH3 scores stage 7C stored into 6,000 decisions, one SELF
eligibility set and three evaluation views, under a threshold nobody in this
project chose.

```bash
python -m fpbench.experiments.nbis_canonical500_decisions prepare
python -m fpbench.experiments.nbis_canonical500_decisions derive
python -m fpbench.experiments.nbis_canonical500_decisions status
python -m fpbench.experiments.nbis_canonical500_decisions finalize
```

No NBIS executable runs. The scores were produced once, in stage 7C, and are read
here and not modified.

## Where the threshold came from

NIST's NBIS guide describes a BOZORTH3 score **greater than 40** as a rule of
thumb that usually indicates a true match. That sentence is the whole source of
the number, and the profile records both the sentence and its *kind*:

```yaml
rule:
  comparator: greater_than
  threshold: "40"

provenance:
  source_kind: official_upstream_documentation
  source_reference: nistir_7391_section_4_2_3
  source_statement_kind: rule_of_thumb
```

So `39 → NON_MATCH`, `40 → NON_MATCH`, `41 → MATCH`. The comparator is strict
because NIST wrote "greater than", and reading it as "at least" would move the
boundary by one point in a direction nobody documented.

## Why not `>= 40`, like SourceAFIS?

Because SourceAFIS's own documentation says "at least", and NIST's says "greater
than". The two projects wrote two different rules about two different score
scales. Making them agree on the comparator would be making one of them say
something it does not say, in order to produce a symmetry that does not exist.

The four-comparator support and the profile schema that admits strict rules exist
for exactly this: see [ADR 0055](../adr/0055-strict-threshold-comparators-preserve-legacy-profiles.md).

## Why 40 and 40 are not the same operating point

They are the same digits. A BOZORTH3 score of 40 and a SourceAFIS score of 40 are
two numbers on two scales produced by two matchers with two minutiae
representations and two scoring functions. Nothing measured here — and nothing in
either upstream document — establishes that they sit at the same false-match
rate, the same security level, or the same anything.

The comparison downstream is therefore named
`comparison_at_independently_documented_operating_points`, and the refusal is
machine-checked rather than merely written down:
[ADR 0058](../adr/0058-cross-algorithm-operating-points-are-not-equated.md).

## Why nothing was calibrated

There are three ways to get a threshold, and two of them are unavailable.

Calibrating on SD300 would be leakage: SD300 is the test cohort these results are
reported over, and choosing a threshold from the same 50 subjects it is later
reported on invalidates the whole study. The loader refuses a profile that
declares `calibration.test_cohort_used: true`, and refuses one that declares
`calibration.performed: true` at all.

Calibrating on a development cohort is correct, and needs a development cohort, a
calibration manifest and a calibration procedure. None of the three exists. When
they do, the result will be a new profile with a new origin, a new fingerprint
and a new derivation — not an edit to this one.

What remains is the number the algorithm's own authors documented. It is not
optimal for SD300 and the profile says so, inside its own fingerprint.

## What the loader may read

The profile is a function of its own YAML text and of the algorithm fingerprint
it is bound to. It reads no raw result, no ResultSet row, no score distribution,
no mated or non-mated label, no SourceAFIS decision and no SourceAFIS metric. A
structural test asserts the import boundary; the signature of
`load_decision_profile` asserts the rest.

## What the derivation requires before it starts

Seven things, checked in order, each of which stops everything
(`load_nbis_decision_source`):

1. the run is `run_f0468f28ffba` and no other;
2. its result set is `resultset_73a9d93a8528`;
3. the plan holds 6,000 jobs and the result set holds 6,000 results;
4. the NBIS validator finds 6,000 successes and zero blocking failures;
5. the general research chain re-verifies to `RESEARCH_READY`;
6. **stage 7C's alignment still holds**, re-derived from the manifests, and still
   fingerprints to `d25b5215…`;
7. stage 7C's finalization marker is still `76a678ad…`.

Steps 6 and 7 are what make these decisions comparable with the SourceAFIS ones
at all. Being aligned row by row with `run_4c59fa02a6ab` — the same 6,000 pair
ids in the same order over the same 3,000 prepared PNGs — is a property the
general research chain has no field for, so it lives in stage 7C's own marker
([ADR 0054](../adr/0054-stage-7c-alignment-is-completion-authority.md)).

## What a score of zero means

It means the comparison ran and produced a low number. BOZORTH3 returns 0
frequently, and 0 is a score: the decision is `DECIDED`, the value is
`NON_MATCH`, and it is never `UNDECIDABLE` and never a failure.

A comparison that produced no score at all is a different thing entirely:
`UNDECIDABLE`, no decision value, and the failure code travels with it. A failure
is not a non-match ([ADR 0006](../adr/0006-self-failure-semantics.md)), and the
rule is identical for both algorithms because both go through the same engine.

## Expected shape

| | |
|---|---|
| decisions | 6,000 |
| decided | 6,000 |
| undecidable | 0 |
| eligibility units | 1,500 (500 per release) |
| rows per evaluation view | 1,500 |

`undecidable = 0` is asserted rather than hoped for: every stage 7C result is a
success and its receipt says so, so an undecidable decision here would mean the
scores changed under the receipt — a contradiction rather than a new outcome.

No expectation is placed on how many decisions are MATCH. That is the result.

## SELF independence

Before any eligibility verdict rests on a SELF comparison, all 3,000 SELF results
must record `extraction_count=2`, `extraction_policy=independent_both_sides`,
`template_cache=disabled` and `template_persistence=disabled`.

The fourth key is the one the SourceAFIS route does not carry. NBIS writes
minutiae to disk between MINDTCT and BOZORTH3, so "was a template persisted and
reused?" is a real question for this route and the requirement asks it
explicitly. A SELF comparison that reused one template would score perfectly and
prove nothing, which is the opposite of what the SELF stage is for
([ADR 0035](../adr/0035-self-reuses-prepared-pixels-but-not-template-extraction.md)).

## Evidence

```text
evidence/nbis-canonical500-decisions/
├── README.md
├── <decision_set_id>.json      the receipt
├── decision-finalization.json  the last-written marker
└── decision-profile.json       the exact profile the decisions were taken under
```

The receipt is schema 2: it additionally binds the derivation definition, the
derivation software identity and stage 7C's finalization fingerprint. The four
published SourceAFIS receipts remain schema 1 and remain byte-identical.

No raw decision row is published, because none is published for SourceAFIS. The
exposure level is the same for both algorithms, deliberately.
