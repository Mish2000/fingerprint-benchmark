# 0043 — A synthetic two-stage adapter proves the contract before a real one tests it

*Status: Accepted — 2026-08-01, stage 7A*

## Context

Stage 7A's claim is that a second algorithm can be added by writing an adapter, a
runtime bundle, a validator, some configuration and some tests — and not a runner,
a store, a result schema, a decision engine or an evidence chain.

That claim is worth exactly as much as the evidence for it. Asserting it in an
ADR and finding out during the NBIS implementation would be the worst outcome
available: half a real algorithm integrated, and a contract change needed to
finish it, with no way to tell which of the two is wrong.

The obvious way to get evidence is to integrate NBIS. That mixes two risks into
one experiment. If it goes badly, the cause could be the contract, or MINDTCT's
build, or Bozorth3's output format, or the fact that nobody has run it on this
machine before — and the fix for a contract problem is completely different from
the fix for a build problem.

## Decision

Before a real second algorithm is attempted, a **synthetic two-stage adapter**
demonstrates the contract end to end. It is deliberately not biometric and
deliberately **not registered**: a fixture must not appear anywhere an algorithm
would.

It is built from nothing but the shared tools — the same ones an NBIS adapter
would use:

```
AdapterJobWorkspace   scratch files, containment, artefact publication
ExternalCommand       no shell, absolute executable, bounded output, real kill
runtime_guard         both executables watched, by role
RuntimeBundleStore    both executables pinned, by content
```

Its two tools live in `tests/fixtures/two_stage_cli/`. The extractor takes an
input file and writes a template; the matcher takes two templates and prints a
score. Each can fail on demand — by a marker in the input bytes, so a test
chooses a behaviour by writing a file rather than by setting an environment
variable, which matters because the adapter passes no environment through.

What it has to demonstrate, and does:

| scenario | recorded as |
|---|---|
| two extractions and a match | `SUCCESS` with a finite score |
| extractor fails, left or right | `TEMPLATE_EXTRACTION_FAILED` / `EXTRACTION` |
| template missing or empty | `TEMPLATE_EXTRACTION_FAILED` / `EXTRACTION` |
| matcher fails | `MATCHING_FAILED` / `MATCHING` |
| matcher prints no number | `NO_SCORE` / `MATCHING` |
| either process crashes | `PROCESS_CRASHED` / `ADAPTER` or `MATCHING` |
| either process hangs | `TIMEOUT` / `TIMEOUT` |
| a tool missing at preflight | `EnvironmentStatus.UNAVAILABLE` |
| a tool replaced mid-run | `RuntimeDriftError`, raised, no result written |

and, through the unmodified `SingleJobRunner` and the unmodified generic engine,
forty comparisons to `RESEARCH_READY`.

**No failure ever becomes a score.** Not `0`, not `-1`, not `NaN`: every one of
those paths returns `RawMatchResult.failed()` with no score at all, and the
decision layer will call it `UNDECIDABLE` (docs/adr/0006).

## Consequences

If the NBIS integration later needs a change to the runner, a store, the result
schema or the evidence chain, that is a **failure of stage 7A** and is treated as
one — unless it turns out to need something the existing contract genuinely
cannot express, which is then the evidence a contract version 2 would need
(docs/adr/0039).

The fixture stays after NBIS lands. It is the cheapest available regression test
for the extension points: it needs no dataset, no JVM and no installed tool, and
it runs in a few seconds in ordinary CI.

## Alternatives considered

**Integrate NBIS directly and find out.** Two risks in one experiment, and the
diagnosis afterwards would be ambiguous.

**Prove it with a unit test over a mocked two-stage adapter.** A mock would
exercise the parts of the design that were already understood and none of the
parts that were not — process handling, timeouts, containment, drift.

**Skip the demonstration and rely on review.** Review is how the contract came to
look sufficient in the first place.
