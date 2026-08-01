# Canonical 500 ppi decision derivations

One committed file per canonical decision set, named by its `decision_set_id`,
kept apart from the native ones so neither can overwrite the other's evidence.

## What a receipt proves

That SourceAFIS's documented threshold of 40 — **transferred unchanged** from
the native profile, not re-chosen — was applied deterministically to the 6,000
canonical raw scores; which prepared-image set those scores came from; how many
comparisons could be decided; and which SELF eligibility verdicts and evaluation
views follow.

Both derivations run the same engine
(`fpbench.experiments.sourceafis_decisions`). That is what makes a difference
between the native and canonical numbers attributable to the images rather than
to how they were counted.

## What a receipt does not contain

No score. No count of MATCH or NON_MATCH. No eligible count. No metric. Those
belong to the evaluation layer, which is a separate artefact with a separate
receipt.

No pair id, job id, subject, finger or image id either.

## What the threshold is, and is not

40 is a number SourceAFIS's authors published for their own evaluation on their
own data. It was carried across to the canonical path without change so that the
two runs differ in one thing. It is **not** a recommended canonical threshold,
not adapted to 500 ppi input, not validated on SD300, and not optimal. Nothing
here was calibrated (docs/adr/0021, docs/adr/0037).
