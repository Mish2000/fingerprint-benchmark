# 0052 — Stage 7C publishes raw scores, and nothing that interprets them

*Status: Accepted — 2026-08-03, stage 7C*

## Context

Stage 7C produces 6,000 BOZORTH3 scores over the comparisons SourceAFIS already
scored. The two columns will sit in one workspace, joinable by `pair_id`, and
every interesting question anybody has about this project can be asked of them:
which algorithm is more accurate, where the thresholds sit, how the scores
correlate, what the false-match rate is.

None of those questions can be answered honestly yet, and the reasons are
specific rather than procedural:

**The scales are unrelated.** SourceAFIS returns a similarity score whose
documented operating point is 40. BOZORTH3 returns a non-negative integer derived
from compatible minutiae pairings. There is no monotone map between them that
anybody has measured, so subtracting them, correlating them or applying one's
threshold to the other produces a number with no referent.

**There is no threshold for BOZORTH3 here.** SourceAFIS's 40 is documented by its
authors (`DOCUMENTED_NATIVE`, docs/adr/0021). NIST publishes no equivalent for
BOZORTH3 that this project has adopted, and choosing one from the test cohort's
own scores would be calibrating on the test set — the leakage the cohort role
exists to prevent.

**The failure semantics are not yet defined.** MINDTCT declining a print is a
recorded outcome (docs/adr/0006). Whether that outcome is `UNDECIDABLE`, whether
it excludes the finger from the mated denominator, and how SELF eligibility works
on a route whose SELF comparisons can fail differently — all of that is a
decision profile, and there is not one.

**The negative pairs are a sanity check, not an FMR design.** docs/adr/0030 says
so already, and it does not stop being true because a second algorithm ran.

## Decision

**Stage 7C stores raw scores and failure codes. That is the whole product.**

* No `DecisionSet`, no `EligibilitySet`, no `MetricSet`, no `PairedEvaluation`
  over the NBIS run. The experiment module imports none of those packages and a
  test enforces it; `inspect_nbis_canonical500_experiment` raises an issue if a
  `decisions/`, `metrics/` or `eligibility/` directory appears under the run.
* No threshold anywhere in the configuration. `threshold`, `decision_profile`,
  `match_threshold`, `acceptance_threshold` and `calibration` are refused at any
  depth of the experiment YAML.
* No score statistic in the operational summary — no mean, no median, no
  histogram, no split by ground truth, no correlation with the reference run.
  Timings, counts and failure codes only.
* No SourceAFIS score is read. Stage 7C opens the reference run for its identity,
  its plan, its pair manifest, its prepared inputs and its readiness. There is no
  join of the two result tables in this stage.
* A BOZORTH3 score of 0 is a **successful comparison**. It is not `NO_SCORE`, not
  `MATCHING_FAILED` and certainly not `NON_MATCH`: BOZORTH3 returns 0 when a side
  has fewer than ten minutiae, which is an outcome about the print
  (docs/adr/0006).

**What may be written about it.** That NBIS was run over the same 6,000 pair ids
and the same canonical prepared images as the SourceAFIS canonical run, that the
run reached `RESEARCH_READY`, and what the failure counts were. Not that either
algorithm is better, not that the scores are similar, higher or lower, and no
accuracy, FMR, FNMR or EER.

## Alternatives considered

**Publish a score histogram, as description rather than conclusion.** A histogram
of 6,000 scores split by ground truth *is* a performance claim in visual form;
the reader draws the line themselves. If it is worth publishing it is worth
publishing with a stated threshold policy and named denominators, which is stage
7D.

**Apply SourceAFIS's 40 to see what happens.** It would produce decisions and
counts that look exactly like results and mean nothing. docs/adr/0037 transferred
that threshold between two runs of *one* algorithm, and said so precisely because
the transfer is only defensible within a scale.

**Pick a BOZORTH3 threshold from NIST's documentation.** Worth doing — in a stage
that states where the number came from and records its `ThresholdOrigin`. Doing
it here would bury the provenance in a raw-score run.

**Compute the correlation between the two score columns.** It is one line, it is
interesting, and it is a paired analysis over two scales with no stated
relationship. It needs its own stage and its own argument.

## Consequences

The deliverable of stage 7C reads as unfinished, and it is: 6,000 numbers and a
provenance chain. That is what makes stage 7D able to be about deciding, with
every input to that decision already fixed and citable.

The operational summary is the only quantitative thing this stage publishes, and
it is deliberately about the machine — wall clock, adapter time, staging,
extraction, matching, cleanup, failure codes by release and by stage. Those are
engineering questions with engineering answers.

Any later stage that wants to compare the two algorithms starts from two
finalised result sets over one proved-identical set of inputs, which is the
strongest position it could start from.
