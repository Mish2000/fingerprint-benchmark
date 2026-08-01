# 0036 — A paired comparison is a third artefact, not a section of either report

*Status: Accepted — 2026-08-01, stage 6B*

## Context

Stage 6A produced a second SourceAFIS run over canonical 500 ppi inputs. Stage 6B
derives decisions and metrics from it, and then compares the two runs.

The obvious place for that comparison is inside the canonical evaluation's
report: it is the new thing, and the native run is the baseline it is measured
against. That framing is wrong in a way that would be hard to unpick later.

The comparison is symmetric in its inputs. Both runs are finished, both are
published, both have their own receipt, and neither is a control for the other in
any sense except the SD300A subset. Filing the comparison under one of them
would assert an asymmetry the data does not have, and would make the canonical
evaluation's identity depend on the native one — so that re-deriving the native
chain would invalidate a canonical report that never used it.

## Decision

A paired comparison is a **third artefact** with its own identity, its own
policy, its own store and its own status ladder.

- It lives at `workspace/paired-evaluations/<paired_evaluation_id>/`, under
  neither run.
- Its identity folds in both runs, both result sets, both decision sets, both
  eligibility sets, both metric sets, the pair-manifest hash, the comparison
  policy and the derivation commit.
- Its own three refusals are its own: no significance test, no confidence
  interval, no claim of superiority or causality.
- Each side's standalone evaluation stands alone. The canonical report makes no
  reference to the native one, and vice versa; the comparison is what refers to
  both.

The only asymmetry the comparison admits is a direction: deltas are written as
*canonical minus native*, because a signed number needs an orientation. That is
a rendering convention, stated in the policy, and it is not a claim that one side
is the baseline.

## Consequences

Either chain can be re-derived without invalidating the other's report. The
comparison, which cites both by fingerprint, is invalidated — correctly, because
it was a comparison of the fingerprints it named.

A future third path — NBIS over the same canonical set, say — needs a new
comparison artefact rather than a new section in an existing one, and gets one
for free.

The cost is a third four-command lifecycle and a third evidence directory. That
is real, and it is the same cost every other layer in this project pays for
having an identity.

## Alternatives considered

**A section in the canonical report.** Cheaper, and it would make the canonical
evaluation's identity depend on the native chain for no reason.

**A notebook.** Not reproducible, not fingerprinted, not verifiable, and the
first thing anyone would copy a number out of.
