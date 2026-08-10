# 0094 — id3 is preflighted in a new stage, not added to Stage 10A

*Status: Accepted — 2026-08-10, stage 10B*

## Context

Stage 10A froze a candidate set of AFR-Net and JIPNet *before* it knew what
either would do, weighed both against seven hard conjunctive gates, and ended
`ALGORITHM4_PREFLIGHT_NO_SURVIVOR`. Its marker opened a candidate search and
explicitly did not open an artifact qualification.

The obvious next move was to add the id3 Finger SDK to that candidate set as a
third entry. It is the wrong move, and the reason is methodological rather than
procedural.

Stage 10A's candidate set is the *question* it asked. It was frozen before the
answer was visible, which is what makes "neither survived" a result rather than
a summary of what happened to be tried. Adding a candidate after the answer is
known changes the question retroactively: a reader could no longer tell whether
id3 was chosen because it is a good candidate or because the first two failed,
and the stage's outcome would silently become "the third one we tried worked".

There is a second reason. Stage 10A weighed two research artifacts against gates
about authorship, published code and released checkpoints. id3 is a commercial
product delivered under a licence, and the questions that decide it — can a copy
be obtained at all, is there an activation, does the quota cover the run — do
not appear in Stage 10A's gate list, because they never arise for a public
GitHub repository. Half of Stage 10B's gates would have to be added to Stage 10A
to accommodate one candidate, and gates added to accommodate a candidate are
gates chosen by the candidate.

## Decision

Stage 10B is a **new stage**, and Stage 10A is immutable.

**Stage 10A is not edited.** Its `candidate-set.json` keeps two candidates, its
outcome keeps its value, and nothing under its evidence directory changes. The
only edits Stage 10A received after publication were two corrective fixes
identified in review — a field renamed from `gates_evaluated_per_candidate` to
`gate_count_defined_per_candidate`, and the AFR-Net absence sentence scoped to
the locations that were searched — neither of which touched the candidate set or
the outcome, and both of which were followed by a re-close.

**Stage 10B binds Stage 10A as a predecessor by fingerprint.** The marker carries
`predecessor_stage_10a_fingerprint`, and the engine refuses to publish if Stage
10A's marker has moved. Adding a candidate to Stage 10A would change that digest
and stop Stage 10B rather than silently reinterpret it.

**One candidate, ten gates, fail-fast.** Stage 10B asks a single question:

```text
does a package of the id3 Finger SDK exist here that is exact, legally and
practically operable for local research, and that defines a complete 1:1 route
from canonical_500 to a raw score with no score-affecting choice left to fpbench?
```

```text
 1  PRODUCT_IDENTITY       which id3 product is this, and which is it not?
 2  ACQUISITION_ACCESS     can we obtain and operate it at all?
 3  PACKAGE_IDENTITY       exact bytes: package, binding, native library, models
 4  INPUT_DOMAIN           canonical_500 in, with no fpbench transformation
 5  EXTRACTION_PROFILE     every model, format and flag frozen
 6  MATCHER_PROFILE        every published option, with a provenance
 7  RAW_SCORE_ROUTE        one integer per attempt, no threshold
 8  WORKLOAD_FEASIBILITY   the frozen run costs what the licence can carry
 9  TRAINING_PROVENANCE    what is disclosed, and does it touch SD300?
10  LOCAL_SMOKE            it constructs, scores, and scores the same after a restart
```

A candidate must pass all ten. There is no weighting and no threshold at which
enough gates make it acceptable.

**Acquisition comes second, and deliberately.** Product identity costs one
reading; acquisition decides whether the other eight gates are answerable at
all. Settling it negatively means no licence is requested, no activation is
attempted, no model is downloaded and no runtime is built.

**The candidate id is provisional.** `id3_finger_sdk_1to1` names the subject of
a preflight. No production `algorithm_id` is frozen here: a final identity has to
carry the exact SDK version, the models, the extractor profile, the matcher
profile and the runtime, and none of those exists before a package does
(docs/adr/0097).

## Alternatives

**Add id3 to Stage 10A and re-run it.** Rejected above: it changes the research
question after the result is known, and it imports commercial-access gates into
a stage built for research artifacts.

**Skip the preflight and integrate id3 directly.** This is exactly the Stage 9A
mistake ADR 0089 was written about, one product later. A commercial SDK makes it
worse rather than better: the integration would be discovered to be impossible
at the point where a licence was needed, after an adapter had been written.

**Fold id3 into a general "commercial matcher" stage.** There is one commercial
candidate. A framework built for a second one that does not exist would be a
framework shaped by guesses.

## Consequences

Stage 10A stays a closed historical document about AFR-Net and JIPNet, and its
result keeps the meaning it had when it was published.

Stage 10B is small and fail-fast, and it may legitimately cost nothing: its
answer today is that the package was never obtained, which was established by
reading four public pages and one public sample file.

A future re-run is a new preflight rather than an amendment. The observations
fingerprint covers every recorded fact, so re-reading the vendor's pages and
finding something different changes the digest and produces a new result rather
than editing this one.

Stage 10C exists only if Stage 10B passes. Under a blocked outcome the marker
carries `opens_stage_10c: false` and `opens_candidate_search: true`, and the
Algorithm 4 slot stays empty.

**The number 10C stays reserved for id3 even so.** It was defined as this
candidate's artifact and runtime integration, and recycling it for the next
candidate would put a 10C in the history that has nothing to do with the 10B
above it. The marker carries `stage_10c_reserved_for_this_candidate: true` and
refuses to say otherwise; the next candidate preflight takes a new stage number.
The two are independent tracks — obtaining an id3 licence is one person's act
and does not sit on the next preflight's critical path.
