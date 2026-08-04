# 0065 — Raw-score readiness does not imply decision readiness

*Status: Accepted — 2026-08-04, stage 8A*

## Context

A complete learned matcher may expose a deterministic similarity function yet
publish no threshold for its released checkpoint. The fact that a score is a
cosine similarity, a dot product or bounded around zero does not make any value
a match boundary. Paper EERs and FARs describe observed operating points; they
are not threshold values that can be transplanted without the underlying raw
calibration data and exact artifact.

Conflating the two forms of readiness creates a dangerous shortcut. An artifact
that can produce numbers looks integrated, and a conventional threshold then
appears to be the only missing constant. Choosing that constant from SD300 would
train on the evaluation cohort; guessing it from the score range would create
decisions with no empirical or upstream authority.

## Decision

Stage 8A records `RAW_SCORE_READY` and `DECISION_PATH_READY` as distinct claims.

`RAW_SCORE_READY` requires all artifact and operational gates necessary for an
auditable image-to-score pipeline: exact code and weights, complete
preprocessing and representation, an unambiguous comparator returning a finite
raw score, score direction and fusion semantics, independent SELF extraction,
acceptable determinism, offline execution, clear required licences and
architectural fit. A boolean-only matcher or a comparator containing an
undisclosed accept/reject threshold cannot satisfy this state.

`DECISION_PATH_READY` requires `RAW_SCORE_READY` and one additional, explicit
path:

1. an external threshold documented for the exact checkpoint and exact score
   profile; or
2. a calibration protocol fixed in advance for an independent, legally and
   operationally available development cohort that is not SD300.

The threshold or calibration protocol is fingerprinted. It records comparator
strictness, score direction, checkpoint relationship and provenance. A reported
EER, reported FAR without raw calibration data, the midpoint of a score range,
or zero for cosine similarity is not a decision path.

The calibration option describes a future authorized stage; stage 8A does not
perform calibration. A raw-ready artifact may therefore be retained as
`QUALIFIED_FOR_RAW_SCORES_ONLY` while remaining ineligible for full decision
integration. Promoting it requires an explicit stage and new evidence, not an
edit to its qualification report.

Determinism is evaluated at the appropriate boundary. Any allowed numeric
tolerance and maximum observed drift are recorded for raw-score readiness. If
that drift could cross the chosen threshold, the artifact is not
`DECISION_PATH_READY` even though its raw scores may remain usable under the
documented tolerance.

The distinction applies independently of the outcome of this registry version:
a future artifact that clears the raw-score gates but has no threshold path
must still stop at the raw-score-only outcome.

## Alternatives considered

**Use zero for a cosine or dot-product score.** Algebraic zero has no necessary
relationship to a target false-match or false-non-match rate.

**Copy the paper's EER or FAR number into the threshold field.** A rate is not a
score, and even a threshold printed beside it is not transferable unless it is
tied to the exact released checkpoint, preprocessing and comparator.

**Calibrate on SD300.** That selects an operating point on the evaluation cohort
and invalidates the later test claim.

**Reject every artifact that lacks a threshold.** This discards a fully
reproducible raw-score implementation that a properly separated future
calibration stage could use. Keeping the two readiness states preserves useful
work without overstating it.

## Consequences

Qualification evidence says precisely whether a candidate can produce scores
and whether those scores can support decisions. Reports and selection cannot
silently turn one claim into the other.

Some candidates will stop at raw scores and require another stage before a
benchmark comparison. That additional work is visible and reviewable: cohort
role, threshold provenance, comparator, tolerances and leakage controls all
have to be settled before a match/non-match result exists.
