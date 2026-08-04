# 0057 — NBIS decisions use NIST's documented score > 40

*Status: Accepted — 2026-08-04, stage 7D*

## Context

Stage 7C produced 6,000 BOZORTH3 scores and deliberately applied no threshold:
where the boundary between MATCH and NON_MATCH sits on BOZORTH3's scale was
stage 7D's question, and SourceAFIS's documented 40 is a number on a different
scale entirely (docs/adr/0052).

There are three ways to choose a threshold for BOZORTH3, and two of them are
unavailable. Calibrating one on SD300 would be leakage — SD300 is the test
cohort these results are reported over. Calibrating one on a development cohort
is correct and needs a development cohort, a calibration manifest and a
calibration procedure, none of which exists. What remains is the number the
algorithm's own authors documented.

NIST's NBIS guide describes a BOZORTH3 score **greater than** 40 as a rule of
thumb that usually indicates a true match. That is a weaker kind of statement
than SourceAFIS's documented 40, which comes with an approximate false-match rate
of upstream's own measuring — and the difference in kind matters more than the
coincidence that both are written "40".

## Decision

`configs/decisions/nbis_mindtct_bozorth3_5_0_0_nistir7391_gt40_canonical500_v1.yaml`
applies `score > 40`, with `comparator: greater_than`, under profile schema 2.
So `39 → NON_MATCH`, `40 → NON_MATCH`, `41 → MATCH`, and a BOZORTH3 score of `0`
is a *decided* NON_MATCH rather than an UNDECIDABLE or a failure.

The profile records `source_statement_kind: rule_of_thumb`, and a `claims` block
in which `calibrated_fmr`, `equivalent_to_sourceafis_operating_point` and
`optimal_for_sd300` are all false. Every one of those fields is inside the
profile fingerprint, and the loader refuses the file if any is true.

The threshold is applied to the stored ResultSet and only there. BOZORTH3's `-T`
option filters its output at a threshold at run time; it was not used, and using
it would have made the decisions a property of the run rather than of a profile
anyone can reread and reapply.

Loading the profile is a function of its own text and of the algorithm
fingerprint. It reads no raw result, no score distribution, no ground-truth label
and nothing whatsoever from the SourceAFIS chain.

## Consequences

The NBIS operating point is documented, uncalibrated, and not optimal for
anything. Whatever the resulting numbers are, they are the numbers NIST's own
rule of thumb produces on these inputs — which is a defensible thing to report
and a meaningless thing to compare against a calibrated threshold.

Stage 7E may vary the threshold across a pre-registered grid. It may not pick a
winner from one, and it does not change this result.
