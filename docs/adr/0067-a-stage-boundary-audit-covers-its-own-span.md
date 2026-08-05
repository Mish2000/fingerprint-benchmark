# 0067 — A stage boundary audit covers its own span, not everything after it

*Status: Accepted — 2026-08-05, stage 8B*

## Context

Stage 8A carries a workspace gate that proves it did not quietly edit an
earlier stage. The gate lists the paths Stage 8A was entitled to touch, then
refuses anything outside that list.

It computed the set of touched paths as `git diff BASELINE..HEAD`, where
`BASELINE` is the commit that closed Stage 7D. That reads correctly at the
moment Stage 8A is published, because `HEAD` *is* Stage 8A's last commit then.
It stops reading correctly one commit later. `HEAD` keeps moving, so the gate
was no longer asking

> did Stage 8A change a prior stage?

but

> has anything outside Stage 8A's allowlist changed since Stage 7D, ever?

No later stage can satisfy the second question, and Stage 8A was never
entitled to ask it. The two questions had the same answer for exactly as long
as Stage 8A was the newest stage.

The failure is not cosmetic and not recoverable by editing the allowlist.
Stage 8B must publish `evidence/stage8b-flx-runtime-qualification/`, add
`src/fpbench/flx/`, add its own ADRs and its own tests. Every one of those is
outside Stage 8A's list, so Stage 8A's first reaction to Stage 8B's first
commit was:

```
Stage8AFinalizationError: prior-stage paths changed during Stage 8A:
['src/fpbench/_stage8b_boundary_probe.py']
```

Widening the list would work once. It would also mean editing
`src/fpbench/modern_matchers/finalization.py`, which is one of the verifier
authority paths that `stage-8a-finalization.json` pins by
`verifier_source_commit`, so every future stage would have to edit Stage 8A's
source *and* republish Stage 8A's finalization marker in order to exist.

## Decision

A stage's boundary audit compares two fixed commits: the commit that opened
the stage and the commit that published it. Stage 8A therefore pins

```python
STAGE8A_BASELINE_COMMIT    = "f85e360…"   # Stage 7D closed here
STAGE8A_PUBLICATION_COMMIT = "f075dcb…"   # Stage 8A's evidence was last written here
```

and diffs between them. Both endpoints must still be ancestors of the current
history, so a Stage 8A that was rewritten or abandoned is caught rather than
skipped.

The scan for uncommitted work is narrowed in the same spirit. It now covers
only the paths Stage 8A *owns* — `configs/modern-matchers/`,
`integrations/modern-matchers/`, `src/fpbench/modern_matchers/`,
`evidence/stage8a-modern-matcher-selection/`, its named tests and its three
exact source files. An untracked file there is Stage 8A material sitting
outside its own publication and still fails closed. An untracked file anywhere
else belongs to whoever is working now.

Shared files such as `README.md`, `Makefile` and `pyproject.toml` remain
*allowed* changes without becoming *owned* paths, because Stage 8A edited them
without having any claim over their future.

The claim that Stage 8A's own code has not moved is unaffected. It was never
carried by this audit. It is carried, more strictly, by the verifier's
authority-path comparison against `verifier_source_commit`, which requires the
working tree under those paths to be byte-identical to the pinned commit and
clean including untracked files.

## Alternatives considered

**Extend Stage 8A's allowlist with Stage 8B's paths.** Preserves the defect and
pays for it repeatedly: Stage 8C, 8D and every stage after would each require
another edit to Stage 8A's authority source and another republication of its
finalization marker. The published evidence of a closed stage would be
rewritten once per future stage, for reasons having nothing to do with Stage 8A.

**Leave the gate failing.** A gate that is always red stops distinguishing
"something broke in Stage 8A" from "time passed", and it contradicts Stage 8B's
own acceptance condition that CI is green.

**Drop the untracked scan entirely.** It still catches something real —
Stage 8A material that was written but never published — so it was narrowed
rather than removed.

**Re-run Stage 8A's qualification.** Nothing about the artifacts, the licences
or the gates changed. Re-deriving conclusions in order to fix a Git range would
manufacture a new scientific record for a mechanical repair.

## Consequences

`stage-8a-finalization.json` is republished once, because the verifier source
it pins has changed. Only `verifier_source_commit`, `created_utc` and the
marker's own `fingerprint` move. The outcome `NO_MODERN_MATCHER_READY`, the
candidate registry, all three qualification reports, the selection decision,
the selection policy fingerprint and the README stay byte-identical, and no
qualification conclusion is re-derived. Anyone holding the previous marker
fingerprint outside this repository will see it change; every other Stage 8A
fingerprint is unmoved.

Stage 8A is now closed against the future: no later stage needs to edit it
again, and later stages are free to add whatever their own gates permit.

Stages that follow carry the same obligation in their own gate. Stage 8B pins
its own baseline and its own publication commit, and audits only what happened
between them.
