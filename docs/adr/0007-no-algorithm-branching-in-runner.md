# 0007 — No algorithm-specific branching outside adapters

## Status

Accepted. Implemented: `fpbench.adapters.registry` is the only module that
names an algorithm, `SingleJobRunner` receives its adapter and preparer by
injection, and a test walks the source tree to assert that no algorithm id
appears outside `fpbench/adapters/`.

## Context

The fastest way to integrate a second algorithm is a conditional in the runner.
The fastest way to make a benchmark harness unmaintainable is to keep doing
that: within a few algorithms, the orchestration code encodes every tool's
quirks, and no algorithm can be added or removed without touching shared code
that all the others depend on.

## Decision

The runner is algorithm-agnostic. It obtains an adapter from a registry:

```python
adapter = registry.create("sourceafis", config)
```

and there is no

```python
if algorithm == "sourceafis":
    ...
elif algorithm == "bozorth3":
    ...
```

anywhere outside the adapter registry. Every algorithm-specific concern —
format conversion, temporary files, subprocess invocation, output parsing,
score direction, dependency checks — lives inside that algorithm's adapter
package. A heavy or exotic dependency is imported inside its own adapter, so
installing NBIS is never a precondition for running SourceAFIS.

The same rule applies to `decisions`, `evaluation` and `storage`: none of them
may import a specific adapter.

## Alternatives

**A dispatch table in the runner.** Rejected: it is the same coupling with
better formatting; the runner still has to know every algorithm's needs.

**Dynamic plugin discovery via entry points.** Rejected *for now* as
premature. A plain dict registry gives the same isolation for two algorithms
and can be replaced with entry points later without any adapter changing.

## Consequences

* Adding an algorithm means adding one package and one registry entry. Nothing
  shared is edited, so nothing shared can regress.
* An algorithm that genuinely needs different *input* — a different resolution,
  a different colour depth — expresses that as an execution profile in
  configuration, not as a branch in the runner.
* The shared contract test suite is what enforces this in practice: if an
  adapter needs special handling to pass it, the abstraction is wrong and the
  fix belongs in the contract, not in the runner.
