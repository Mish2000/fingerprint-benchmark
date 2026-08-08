# 0085 — Stage 9 selects the full FLARE route, not a runnable subset of it

*Status: Accepted — 2026-08-08, stage 9A*

## Context

Stage 8A selected a modern matcher family and Stage 8B qualified one runtime for
one of them. The fourth algorithm this benchmark wants is FLARE — *Fixed-Length
Dense Fingerprint Representation with Alignment and Robust Enhancement*, TIFS
2026 — and FLARE is not one program. The published method is a preprocessing
pipeline with two independent pose estimators and two independent enhancers,
followed by one descriptor network and one fusion rule.

The public code does not present it that way. `Yu-Yy/FLARE` ships pose
estimation and descriptor extraction; `Yu-Yy/FLARE_ENH` ships the two enhancers,
in a separate repository, with their own command-line entry points and their own
image preprocessing. The main README instructs the reader to run `VotingPose`
**or** `RegressionPose` and then to run `extract_FDD.py` with the chosen `-p`.
Enhancement appears nowhere in that sequence.

So there are two things one could call "FLARE" and only one of them is a
benchmark subject:

* the *method*, which computes four descriptor pairs and takes the maximum of
  four similarities;
* the *scripts*, which compute one descriptor pair from an unenhanced image
  under one pose.

Running the second and calling it the first would be the mistake ADR 0066
already refused in a different costume — not a reimplementation from the paper,
but a *fraction* of the published method wearing the published method's name.

## Decision

Stage 9 targets the full route or it targets nothing.

An integration of FLARE is admissible only if it computes, for every comparison:

```text
two pose estimators   x   two enhancement strategies   =   four branches
                                                              |
                                                          max of four
```

`branch_count = 4` is a gate, not a preference. Two branches is not FLARE with a
missing option; it is a different algorithm that shares a checkpoint. Three is
not a compromise. The paper's Eq. 8 takes the maximum over `i ∈ {0,1,2,3}` and
the maximum over a subset is a different function.

Stage 9A is the qualification that decides whether the full route can be frozen
from authoritative sources. It publishes one of exactly two outcomes:

```text
FLARE_FULL_ROUTE_ARTIFACTS_READY
FLARE_FULL_ROUTE_BLOCKED
```

`BLOCKED` is a complete, correct, publishable outcome. There is no requirement
anywhere in this project to make FLARE run. There is a requirement not to
publish a score attributed to a method the score did not come from.

The binary FDD route (`-b`) is **not** part of the selected identity. The
official README presents it as a separate, optional mode for ultra-fast
matching; the paper's Eq. 7 is continuous. `binary_representation = false`.

## Alternatives considered

**Qualify the two-branch route now and add enhancement later.** It would run
this month. It would also produce a `ResultSet` labelled FLARE whose scores no
published number can be compared against, and every later stage that binds to
that `ResultSet` would inherit the mislabelling. Stage 8C's finalization binds a
*qualified route* (ADR 0077) precisely so that this cannot happen quietly.

**Pick whichever pose estimator and enhancer perform best on SD300.** That is
selection on the evaluation cohort, which Stage 8D spent an entire stage
refusing (ADR 0079), and it is not the published method either way.

**Treat the four branches as four algorithms and report four score columns.**
They are not four algorithms. They are four arms of one matcher, fused by a
maximum before any score leaves the method. Reporting them separately would
publish four numbers none of which is FLARE's.

## Consequences

Stage 9A has a hard gate it can fail, and failing it is cheap: no adapter, no
runtime, no run, no result. That is the point of putting the gate first.

The four branch identities are frozen as names —
`voting_unetenh`, `voting_priorenh`, `regression_unetenh`,
`regression_priorenh` — and travel with any future diagnostic output. Their
numeric order is not part of the algorithm, because `max` does not depend on
order; their *presence*, all four of them, is.

If Stage 9A closes `READY`, Stage 9B inherits an engineering problem: runtime,
determinism, dependency closure, adapter, scheduling. If it closes `BLOCKED`,
the repository has a precise, reviewable statement of what would have to change
upstream — or in a corrective stage here — before FLARE could be executed
faithfully, and no half-built adapter to maintain in the meantime.
