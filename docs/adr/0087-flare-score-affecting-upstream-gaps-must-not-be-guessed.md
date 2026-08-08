# 0087 — A score-affecting gap in the upstream sources is a blocker, not a decision for fpbench to take

*Status: Accepted — 2026-08-08, stage 9A*

## Context

There is a failure mode that looks exactly like success. A pipeline is
assembled from official checkpoints and official model classes, it runs, it
produces plausible similarity scores, and mated pairs score higher than
non-mated ones. Every ingredient is authentic. And somewhere in the middle of
it, a resampling kernel, an interpolation flag, a border fill value or an
operation order was chosen by whoever wrote the glue, because no upstream source
said what it should be.

The resulting numbers are not wrong in any way a test can see. They are simply
not that method's numbers, and nothing downstream can ever tell.

This project has met the honest version of this problem twice already. ADR 0066
refused a paper reimplementation as an upstream algorithm. ADR 0071 established
that a preprocessing transform is *declared*, never inherited by accident. Stage
9A is where both pressures arrive at once, because FLARE's published method and
FLARE's published code do not describe the same sequence of operations.

An executable FLARE-like pipeline is not the deliverable. The deliverable is a
pipeline whose score-affecting behaviour follows from authoritative FLARE
sources.

## Decision

Every operation in the route carries an authority, drawn from a closed
vocabulary:

```text
PAPER_EXPLICIT             the paper states it
UPSTREAM_CODE_EXPLICIT     the pinned official source performs it
UPSTREAM_DEFAULT_EXPLICIT  the pinned official inference entry point defaults to it
INTEGRATION_NEUTRAL        fpbench glue that cannot move a score, and is shown not to
ASSUMED                    nobody stated it and it was assumed
GUESSED                    nobody stated it and it was guessed
CHOSEN_BY_FPBENCH          fpbench picked among alternatives that differ numerically
```

The first four are admissible. The last three are admissible only where the
operation provably cannot change a score.

**The gate.** If any operation is `ASSUMED`, `GUESSED` or `CHOSEN_BY_FPBENCH`
and it can affect a score, Stage 9A closes `FLARE_FULL_ROUTE_BLOCKED`. Not "with
a caveat". Not "pending review". Blocked.

The authority hierarchy, in order:

1. the published paper and its official supplementary material;
2. the exact pinned official source;
3. the exact pinned official inference configuration or entry-point default;
4. fpbench integration glue.

and the rules that run over it:

```text
paper explicit
    -> the paper wins

paper silent, official implementation explicit
    -> the implementation may supply the missing operational detail

paper and implementation conflict on score-affecting behaviour
    -> BLOCKED

both silent, and the choice can affect a score
    -> BLOCKED
```

"Both silent" is the case worth naming, because it is the one that feels like
freedom. A missing interpolation flag is not an invitation. Two reasonable
engineers will pick `INTER_LINEAR` and `INTER_AREA` for the same downsample and
get two different score distributions, and the repository would have no way to
say which one it published.

**What is not blocked.** Making upstream callable is not a gap. An external
artifact path, a stdin/stdout wrapper, a filesystem layout, calling an official
model class directly instead of through its CLI, removing a `DataParallel`
wrapper while loading — these are `INTEGRATION_ONLY` under Stage 8E's
transformation model, and they are permitted where numerical equivalence is
shown rather than asserted.

**What is blocked as a matter of kind, not of evidence.** Changing an enhancer,
an interpolation, an alignment formula, the CFT weight `w`, the mask handling or
the fusion rule; removing a branch; fine-tuning; retraining. Those are
`BEHAVIOUR_AFFECTING`. They are not Stage 9A's to make at all — they are a
separate ADR and a separate stage.

## Alternatives considered

**Pick the most reasonable option and document it.** This is the alternative
that always wins on the day and loses afterwards. A documented guess is still a
guess, and it is published under a name that claims otherwise. The
documentation is read by the person who wrote it and by nobody else.

**Ship with an accuracy check against the paper's reported numbers.** Tempting
and unavailable: the paper reports on datasets this project does not have, and
tuning glue until a number matches a table is fitting the pipeline to the
answer.

**Ask the authors.** Reasonable, and out of scope for a qualification stage — a
Stage 9A outcome must be derivable from sources that exist. If a correspondence
later resolves an operation, it becomes a new pinned authority and the stage is
re-derived against it.

**Weaken the gate for "small" operations.** Every operation in an image pipeline
is small. The 512→256 downsample is one function call.

## Consequences

Stage 9A can close `BLOCKED` with every artifact present, every checkpoint
loading cleanly and every model constructing — and that is a correct outcome,
not a failure of the stage. The blocker list says exactly which operations lack
an authority, and each entry is a concrete thing that could be resolved.

The route audit is verbose: one row per operation, each with its paper
statement, its code location, its parameter sources and a `score_affecting`
flag. That verbosity is the deliverable. A reader who disagrees with a
resolution can point at the row.

No fpbench module may add `strict=False`, a key filter, an interpolation
argument or a threshold to make something work. Where upstream's own loader
performs a mapping — the `"model"` key, the `module.` prefix strip — that is
upstream behaviour and is recorded as such, not replaced by a loader of ours
that pretends there was no mapping.
