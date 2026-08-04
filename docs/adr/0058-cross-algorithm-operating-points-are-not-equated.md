# 0058 — The two operating points are documented independently, not equated

*Status: Accepted — 2026-08-04, stage 7D*

## Context

SourceAFIS is applied at `score >= 40`. NBIS is applied at `score > 40`. The two
thresholds are written with the same digits, and that is a coincidence of
notation: they come from two documents, about two matchers, on two score scales,
neither measured on this project's data.

The temptation is precise and severe. A reader who sees "40" twice will conclude
that the two algorithms were compared at the same security level. If the report
does not refuse that reading explicitly, the refusal does not exist — a caveat in
a methods section does not travel with a table.

There is no evidence available here for the stronger claim. Establishing equal
false-match rates would need an impostor design chosen for estimation, a
development cohort, and a calibration to a common operating point. Stage 7D has
none of them, by design.

## Decision

The comparison is named for what it is:

    comparison_at_independently_documented_operating_points

and never `comparison_at_equal_fmr`, `comparison_at_equivalent_threshold` or
`comparison_at_matched_security_level`.

`operating_point_relation` is a required field of `FairMeasurementProtocol`, of
the comparison policy and of the comparison receipt, and its only permitted value
is `independently_documented_not_equated`. `FairComparabilityAudit` carries
`operating_points_equated`, which must be false for the gate to be clean.

The NBIS profile disclaims `equivalent_to_sourceafis_operating_point` inside its
own fingerprint, so a profile that started claiming it would be a different
profile.

Every receipt and every report carries, verbatim:

> This comparison uses independently documented, uncalibrated operating points on
> identical inputs. It records paired observed outcomes. It does not establish
> equal FMR, general algorithm superiority, causality, or statistical
> significance.

The sentence is inside the comparison policy fingerprint, so a document that
dropped it does not fingerprint to the policy it claims to follow.

## Consequences

The report may say that one algorithm's observed non-success rate was higher or
lower by a stated exact fraction over a stated population. It may not say that
one algorithm is more accurate, safer, or better.

A future stage that calibrates both algorithms to a common FMR on an independent
development cohort would produce a different comparison, under a new protocol id,
and would not supersede this one — it would answer a different question.
