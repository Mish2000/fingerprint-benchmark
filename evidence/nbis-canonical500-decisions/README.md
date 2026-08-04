# NBIS canonical 500 ppi decision derivation

The 6,000 BOZORTH3 scores stage 7C stored, turned into 6,000 decisions, one SELF
eligibility set and three evaluation views, under a threshold this project did
not choose.

## What the receipt proves

That NIST's own documented rule of thumb — a BOZORTH3 score **greater than 40**
usually indicates a true match — was applied deterministically to the 6,000
canonical NBIS raw scores; which prepared-image set those scores came from; that
stage 7C's alignment with the SourceAFIS run still held when the threshold was
applied; how many comparisons could be decided; and which SELF eligibility
verdicts and evaluation views follow.

The receipt is schema 2, so it additionally binds the derivation definition, the
derivation software identity and stage 7C's finalization fingerprint. The four
published SourceAFIS receipts are schema 1 and are unchanged.

Both algorithms' decisions come from one engine
(`fpbench.experiments.algorithm_decisions`), which names no algorithm. That is
what makes a difference between the SourceAFIS and NBIS numbers attributable to
the algorithms rather than to how they were derived (docs/adr/0056).

## What the receipt does not contain

No score. No count of MATCH or NON_MATCH. No eligible count. No metric. Those
belong to the evaluation layer, which is a separate artefact with a separate
receipt.

No pair id, job id, subject, finger or image id either.

No raw decision rows are published here, because none are published for
SourceAFIS. The exposure level is deliberately the same for both algorithms.

## What the threshold is, and is not

`> 40` is the number NIST published, in NIST's own guide, as a rule of thumb. It
is **not** calibrated, **not** an operating point with a measured false-match
rate, **not** optimal for SD300, and **not** equivalent to SourceAFIS's
documented `>= 40`.

The two thresholds are written with the same digits. They come from two
documents about two matchers on two score scales, and nothing measured anywhere
establishes that they sit at the same error rate. The comparison downstream is
named `comparison_at_independently_documented_operating_points` for exactly this
reason (docs/adr/0057, docs/adr/0058).

Nothing was calibrated. SD300 is the test cohort these results are reported over,
and choosing a threshold from it would be the one form of leakage that
invalidates the whole study. The profile file refuses to declare otherwise, and
the loader refuses the file if it ever does.

## Why `> 40` and not `>= 40`

Because NIST wrote "greater than" and SourceAFIS wrote "at least". Making the two
agree on the comparator would mean making one of them say something it does not
say, in order to produce a symmetry that does not exist. So a score of exactly 40
is a NON_MATCH here and a MATCH on the SourceAFIS side, and both are what their
own documentation states.

## Files

```text
<decision_set_id>.json      the sanitised receipt
decision-finalization.json  the last-written marker that makes the rest authoritative
decision-profile.json       the exact profile the decisions were taken under
```

`bozorth3 -T` was not used. The threshold was applied to the stored ResultSet
and only there, which is what allows anyone to reapply a different one to the
same scores later without re-running anything (docs/adr/0052).

The full method note is in `docs/experiments/nbis-canonical500-decisions.md`.
