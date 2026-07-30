# 0021 — Thresholds and decisions are immutable derivations outside the adapter

## Status

Accepted. Implemented in `fpbench.core.decision_models` and `fpbench.decisions`.

## Context

[ADR 0003](0003-decision-outside-adapter.md) said, before any adapter existed, that a
threshold would not live inside one. Stage 5A is where that promise has to become code,
and the shape of the code decides three things that are easy to get wrong.

**Where a threshold comes from is part of what it is.** SourceAFIS documents 40. That is
a number its authors published, about their own evaluation, on their own data. It is a
perfectly reasonable place to start and it is not a measurement this project made. The
distance between "SourceAFIS documents 40" and "40 is the right threshold for SD300" is
the entire next stage, and a config file that recorded only the number would lose it.

**A threshold is not a float.** `0.1 + 0.2` is not `0.3`, and a threshold parsed into
binary floating point has a value that depends on how it was parsed. Worse, `40` and
`40.0` would fingerprint differently while meaning the same thing, so two people writing
the same profile would produce two profiles.

**A threshold is a claim about a specific matcher.** "Score 40 means match" says nothing
without naming what produced the score. The same number against a different build of
SourceAFIS, or against images prepared differently, is a different claim.

## Decision

**A decision profile is an immutable, externally defined record with its own
fingerprint, and it is applied to unchanged stored results.**

Concretely:

* **Origin is a required, closed vocabulary.** `documented_native`,
  `calibrated_development`, `external_fixed`. Stage 5A executes only the first and third;
  a calibrated profile is refused until a calibration manifest drawn from a *development*
  cohort exists. A profile whose config says `test_cohort_used: true` is refused outright
  — choosing a threshold on the 50 subjects it is then reported over is the one form of
  leakage that would invalidate everything.
* **The threshold is a canonical decimal string.** One canonicaliser, in one place:
  `"40"`, `"40.0"`, `"+40"`, `"4e1"` and `Decimal(40)` all become `"40"`; `NaN` and
  infinities are refused. The comparison itself is done in `Decimal`, so a score exactly
  at the boundary is decided by the rule rather than by the parser.
* **The comparator must agree with the score direction.** `higher_is_better` requires
  `>=`; the other pairing would invert every decision in a run while looking like a
  setting.
* **The profile binds to one algorithm fingerprint and a named list of execution
  profiles**, and applying it to anything else is a fatal `DecisionProfileApplicabilityError`.
  There is no warn-and-continue path.
* **A failure is never a decision.** A comparison that produced no score gets
  `application_status = UNDECIDABLE` and `decision = None`. There is no
  `NO_MATCH_DUE_TO_FAILURE` member and there will not be one
  ([ADR 0006](0006-self-failure-semantics.md)).

The adapter is untouched. Nothing in `fpbench.decisions` imports one, and the SourceAFIS
adapter still returns a raw score and the direction it runs in.

## Alternatives

**A threshold field on the adapter config.** Rejected in ADR 0003 and rejected again for
a new reason: a threshold that lived with the algorithm could not be re-applied to
existing scores, so every new threshold would mean re-running 6,000 comparisons.

**A float threshold.** Simpler to write and wrong at the boundary. `Decimal` costs
nothing here — one comparison per stored result — and buys an exact answer to "is this
score at the threshold?".

**One profile per algorithm, implicit.** Rejected: the project will hold several
thresholds for one matcher (documented, calibrated, perhaps a procurement-mandated one),
and they must be citable side by side.

**Allowing a calibrated profile now, with the manifest to follow.** Rejected. A profile
that claims calibration with nothing behind it is worse than no profile: it reads as
having been validated.

## Consequences

* Re-thresholding is free. The same 6,000 raw results can be decided under any number of
  profiles, each producing its own decision set, without executing a comparison.
* A documented threshold can never be silently reported as a calibrated one — the origin
  is inside the profile fingerprint, so a change of story changes the identity.
* Upstream's own claim about their threshold travels as `metadata.upstream_claim`,
  explicitly flagged `upstream_claim_is_not_benchmark_result`.
* The first calibrated profile will need a calibration manifest format and a development
  cohort. Both are deliberately out of scope here, and the loader refuses in the
  meantime rather than accepting a placeholder.
