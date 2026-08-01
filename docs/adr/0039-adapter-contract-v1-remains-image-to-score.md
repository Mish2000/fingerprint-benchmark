# 0039 — The adapter contract stays two images to one score

*Status: Accepted — 2026-08-01, stage 7A*

## Context

docs/adr/0002 fixed the mandatory adapter surface at three members:
`descriptor`, `validate_environment` and `compare`. That was written when the
only adapter was a dummy matcher, and it held comfortably for SourceAFIS, which
extracts and matches inside one library call.

The next algorithm will not be so tidy. NBIS is two programs: MINDTCT turns an
image into a minutiae template, Bozorth3 compares two templates. The obvious
reading is that the contract is now wrong — that it should grow `extract()` and
`match_templates()`, because that is visibly what the algorithm does.

It is the wrong reading, and stage 7A is where the project commits to saying so
before the second algorithm rather than after it.

An `extract()` in the mandatory surface would have to be implemented by every
adapter, including the ones that have no such stage. SourceAFIS would have to
either expose an intermediate it does not naturally produce, or return something
opaque that only its own `match_templates()` understands — at which point the
method pair carries no shared meaning and the abstraction is decorative. The
harness would gain the ability to call `extract` once and `match` many times,
which is a real optimisation, and with it the obligation to decide when a
template may be reused across pairs — a decision that changes what SELF measures
(docs/adr/0035) and that no two algorithms would answer the same way.

## Decision

`ADAPTER_CONTRACT_VERSION` remains `"1"` and the mandatory surface remains three
members. **A pipeline made of an extractor and a matcher is wrapped as one
adapter**, and the division into stages is a private implementation detail:

```
left  PreparedImage ─┐
                     ├─ extract ─ template ─┐
right PreparedImage ─┘                      ├─ match ─ raw score
                                            ┘
```

all of it inside `adapter.compare(left, right, context)`. The runner does not
know the stages exist, `SingleJobRunner` gains no extractor and no matcher, and
`RESULT_SCHEMA_VERSION` does not move.

Intermediate files live under `context.working_directory` and are gone with it.
Per-stage timings are reported through the existing
`RawMatchResult.timing_components_ms`, and per-stage facts through
`adapter_metadata`; neither needs a new top-level field.

`SUPPORTED_ADAPTER_CONTRACT_VERSIONS` exists so that a future version 2 can be
introduced without every stored run becoming unreadable at once. Raising the
version requires its own ADR, a compatibility path for version 1, and evidence
that the existing runs still verify.

## Consequences

`tests/unit/test_synthetic_two_stage_adapter.py` and
`tests/integration/test_algorithm_research_engine.py` demonstrate the claim
rather than asserting it: a two-executable route runs three subprocesses per
comparison, writes four intermediate files, maps five distinct failures, and
reaches `RESEARCH_READY` through the unmodified runner (docs/adr/0043).

The optimisation the contract forgoes is real: an N-pair run extracts a template
per side per pair, so an image appearing in several pairs is extracted several
times. That cost is accepted deliberately. It is the same cost SELF already pays
for the same reason — an experiment whose per-pair independence depends on a
cache policy is an experiment whose result depends on a cache policy.

If a future algorithm genuinely cannot be expressed this way, that is the
evidence a version 2 needs, and it will be a decision made against real code
rather than against an anticipation of it.

## Alternatives considered

**Add `extract()` and `match_templates()` as optional capabilities.** Optional
methods that nothing calls are documentation; optional methods that something
calls are mandatory in disguise. Either way the contract would have to say when
a template may be reused, which is the part that changes results.

**Version the contract to 2 now, pre-emptively.** Every stored run would be
attributed to a contract version whose only purpose was to anticipate a need
nobody had demonstrated.

**Let the runner orchestrate the stages.** Precisely the algorithm-specific
branching docs/adr/0007 exists to prevent, and it would make every future
algorithm's shape a change to the one component every algorithm shares.
