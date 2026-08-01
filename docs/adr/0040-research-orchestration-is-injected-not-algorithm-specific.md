# 0040 — The research orchestration imports no algorithm

*Status: Accepted — 2026-08-01, stage 7A*

## Context

Stage 6A extracted one orchestration from two SourceAFIS runs, because the
argument of that stage depended on the native and canonical runs differing in
exactly one thing. Two copies of the orchestration would have been two chances
for the difference to be something else.

The same argument applies one level up, and stage 7A is where it has to be made.
If driving a second algorithm requires a second copy of "materialise a runtime
bundle, define a run, plan the comparisons, execute them, audit, validate, build
a result set, write a receipt, write a marker", then any difference between two
algorithms' results could be a difference in their evidence chains rather than in
the algorithms. The whole comparison would be measuring an unknown sum.

The stage 6A implementation could not be shared as it stood. It imported
`SourceAfisJavaAdapter`, materialised exactly one asset under
`BRIDGE_JAR_ROLE`, wrote a pointer containing `bridge_jar_sha256`, and called
`validate_sourceafis_result_set` by name.

## Decision

The orchestration lives in `fpbench.experiments.algorithm_research` and
**contains no algorithm**. It imports no adapter package, and the words
`sourceafis`, `java`, `jar`, `mindtct`, `bozorth` and `nbis` do not appear in it,
including in default values. Nor does it branch on identity: there is no `if
algorithm_id == ...`, no `match adapter_id`, and no comparison of an adapter or
algorithm identifier against a string literal. Both properties are enforced by
structural tests over the syntax tree, because a rule of this kind is only worth
having if breaking it is noisy.

Everything algorithm-specific enters through one injected, immutable record:

```python
ResearchAdapterIntegration(
    integration_id, adapter_id,
    runtime_asset_roles, primary_runtime_asset_role,
    create_development_runtime,   # build from a local build tree
    create_research_delegate,     # build again, pinned to the bundle
    validate_result_set,          # which failures are biometric, which are defects
)
```

The engine wraps the delegate in `ResearchModeAdapter` itself, so every
algorithm's research environment is assembled by one piece of code; an adapter
that wrapped itself could report provenance the run never recorded.

Before a run exists, the engine requires the development adapter and the pinned
research adapter to describe the same algorithm — same ids, same versions, same
score direction, same descriptor fingerprint. Materialising a runtime bundle
moves bytes; it must not move identity, or the environment check proved nothing
about the thing that will produce the scores.

There is **no registry of integrations**. No `latest`, no module scanning, no
entry points: an experiment wrapper names exactly one integration, in code, and
that is the whole selection mechanism.

## Consequences

`sourceafis_research.py` is a wrapper. It builds the integration, translates
`build_jar` into a development override, keeps the stage 4B names as aliases, and
forwards. It materialises nothing, executes nothing, opens no result file and
builds no receipt — checked structurally by imports and calls, never by counting
lines.

The run pointer is now generic: `runtime_bundle_id`,
`runtime_bundle_fingerprint`, `runtime_asset_roles`. Pointers written by earlier
stages still read, because nothing downstream trusts anything in a pointer beyond
the run id.

`run_7ac1cecc0bb3` and `run_4c59fa02a6ab` are untouched. Same execution profiles,
same preparer ids, same descriptor, same 6,000 pairs, therefore the same run
fingerprints and the same everything derived from them.

## Alternatives considered

**A base class with abstract hooks.** Inheritance would let a subclass override
`execute` and silently reintroduce a second orchestration — which is the exact
failure this ADR exists to prevent. A frozen record of callables cannot.

**Keep the SourceAFIS engine and copy it for the second algorithm.** The
resulting comparison could not distinguish an algorithmic difference from an
orchestration difference.

**Discover integrations through entry points.** Import order would decide which
runtime a run used. The registry stayed a plain dict for the same reason
(docs/adr/0007).
