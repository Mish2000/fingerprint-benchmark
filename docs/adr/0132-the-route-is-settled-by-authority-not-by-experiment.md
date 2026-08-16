# The route is settled by authority, not by experiment

## Status

Accepted, implemented.

## Context

FingerFlow ships an extractor and a matcher and nothing that joins them. The
extractor returns `[x, y, angle, score, class]` per minutia and a frame of core
boxes; `Matcher.verify` consumes an array whose column count is fixed at six by
`MINUTIAE_FEATURES = 9` and `MINUTIA_NEIGHBORS = 5`. The shape of the missing
middle is therefore known exactly. Its contents are not in the package.

Two repository scripts build it, and they disagree on how many minutiae to
retain (30 against 20, with a third script using 40 and no checkpoint published
for it), on what to do when there are fewer than that (no guard against an
explicit refusal), on whether inference rotates the image (a mandatory 90°
against none), and — with the README and the only runnable matcher script — on
which of five published VerifyNet weights is the matcher. Neither script runs as
written.

Every one of those four moves the score. The retained count decides which
minutiae are compared at all and fixes the model's input shape. Rotation moves
every coordinate, every core distance and every neighbour distance. The
below-count behaviour decides whether an image is a refusal or a crash. The
precision selects a different trained network.

There is an obvious way to resolve all four, and it is available today: run each
alternative over a handful of pairs and keep the one that produces more scores,
or better separation, or fewer failures. It would take an afternoon and would
feel like diligence.

It is the thing this benchmark exists not to do. The evaluation set is the thing
being measured; choosing the algorithm's own pipeline by how it performs on that
set makes the measurement a measurement of a pipeline fpbench built. Every
published number afterwards would carry a step that no upstream authority
supports and that was selected because it looked good.

The same reasoning already closed Stage 9A. FLARE was blocked at
`TRANSFORM_ORDER_AMBIGUOUS` and `SCORE_AFFECTING_PARAMETER_UNRESOLVED` with two
of seventeen operations lacking an authority — a border fill and a downsample
kernel, both smaller questions than any of these four.

## Decision

**A route question is settled by upstream authority or the gate fails.** The
ladder, applied in order:

```text
official inference / example establishes it       -> use it
single unambiguous upstream implementation        -> use it
multiple alternatives, upstream declares a default -> use the default
fpbench would have to choose                      -> FAIL
```

The last rung is not a last resort to be argued around. It is the answer whenever
the first three do not apply, and the evidence names the alternatives so a reader
can see exactly what was refused.

`experiments_run_to_choose_between_alternatives` is published as `0` and
`verify_stage16a_evidence` refuses a document where it is anything else. The
marker carries `fpbench_chose_a_score_affecting_step: false` and cannot establish
Algorithm 5 over a route with unsettled questions.

Two clarifications the ladder needs in practice:

- **A tendency is not a default.** "In general, the more minutiae points the
  higher precision" ranks the options without selecting one, and five published
  checkpoints with none marked default is exactly the case rung four is for.
- **Absence can be an answer, when the whole path is upstream code.** No upstream
  code transforms the minutia angle, and every step between the extractor's frame
  and the model's tensor is upstream's — so "the angle is not transformed" is
  settled, not undetermined. This does not extend to a step nobody wrote at all.

## Alternatives

**Pick the README's example and proceed.** Tempting, because `Matcher(30,
"verify_net")` is upstream and looks authoritative. Rejected: the README's usage
snippets stop at `extract_minutiae(image)` and `verify(anchor, sample)` and never
connect them, so it establishes how to *call* the matcher and not what to hand
it. The retained count would still be fpbench's, and the only runnable upstream
script uses 20 against the README's 30.

**Pick the more complete script and proceed.** Rejected. Neither runs, so
"complete" would mean "the one whose defects are further from the entry point".
And the encoding generator's mandatory rotation is unmistakably training
augmentation, which means adopting it wholesale imports a step upstream never
intended for inference.

**Ask the author.** Would very likely work — the repository has an issue tracker
and the author is reachable. Rejected here because docs/adr/0126 made
runnable-without-vendor-action a hard requirement after three consecutive stages
ended waiting on somebody, and because an answer in an issue thread is not the
same artifact class as code at a pinned commit. It remains the one act that would
reopen this candidate, and the evidence says so.

**Proceed with a documented assumption.** Rejected. An assumption recorded in an
ADR is still fpbench choosing; the honesty of the label does not make the
resulting scores upstream's.

## Consequences

Stage 16A closes at G2 with `FINGERFLOW_ROUTE_CLOSURE_FAIL`, Algorithm 5 stays
open, and no adapter is written, no SD300 image is opened and no comparison is
run. Four stages have now ended without filling the slot, three of them at a
vendor and this one at documentation.

What it buys is that every number this benchmark eventually publishes is
attributable to an algorithm's authors rather than partly to its harness. That
property is worth more than a fifth column, and it is not recoverable later: a
route chosen by experiment cannot be un-chosen once results exist.

The gate is also cheap to reopen. If upstream publishes an inference example, or
declares a default precision, or a maintainer states which assembly is the real
one, the four questions close and the stage resumes from G3 with everything G1
established still valid — the artifact is acquired, hashed and loadable.

The general rule for the next candidate: a route question with several upstream
answers and no declared default fails the gate, and no amount of the alternatives
being individually reasonable changes that.
