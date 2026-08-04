# 0059 — The unconditional attempt population is the primary analysis

*Status: Accepted — 2026-08-04, stage 7D*

## Context

There are four mated populations available once both chains exist:

* all 1,500 mated attempts;
* the attempts each algorithm could decide;
* each algorithm's own SELF-eligible subset;
* the intersection of the two eligible subsets.

Only the first is identical for the two algorithms by construction. The second
differs whenever one side fails a comparison the other did not. The third is each
algorithm's own selection and is the population docs/adr/0038 already refuses to
subtract across. The fourth is an intersection, and intersecting two eligible
sets systematically removes the fingers that were hard for *either* algorithm —
which flatters both, and flatters the worse one more.

A comparison whose headline number came from any of the last three would be a
comparison whose denominator was itself a result.

## Decision

The primary operational metric is

    plain_roll_mated_unconditional_non_success_rate_attempt

over all 1,500 mated attempts, with the same denominator on both sides and with
`NON_MATCH` and `UNDECIDABLE` both counted as non-successes. It is deliberately
not called an FNMR: an FNMR has a decided denominator, and this one does not.

`plain_roll_mated_unconditional_fnmr_decided` is reported for both algorithms as
well. Its difference is stored only when both sides decided the same attempts;
otherwise the observation carries population `different_decided_populations` and
no difference at all.

The report's section order is the population hierarchy, and it does not vary:
full population, then eligibility and exclusions, then common eligible as an
explicitly secondary analysis, then each side's own conditional set as
descriptive only.

The comparison policy fixes `populations.primary` and the loader refuses any
other value.

## Consequences

The headline number is the least flattering one available and is the same
question for both algorithms. Everything more favourable is still reported,
underneath, with its denominator visible and its status named.

`common eligible` answers a real and narrower question — when both algorithms
have shown that a finger's plain and rolled impressions match themselves, how did
the plain-to-rolled decisions differ? — and the report says so where it appears.
