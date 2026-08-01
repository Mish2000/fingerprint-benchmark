# The research adapter integration

`fpbench.experiments.algorithm_research` carries out a research run: pin the
runtime, define the run, plan the comparisons, execute them one at a time, audit,
validate, build a result set, write a receipt, write a marker. It does all of
that without knowing which algorithm it is driving, and
`ResearchAdapterIntegration` is the only reason it can (docs/adr/0040).

```
    experiment wrapper                 algorithm_research (generic)
    ─────────────────────              ────────────────────────────
    spec (data)               ──────►  load inputs, check the shape
    preparer factory          ──────►  preflight the input set
    ResearchAdapterIntegration ─────►  everything algorithm-specific
                                       │
                              ┌────────┴─────────┐
                              ▼                  ▼
                    create_development_    create_research_
                          runtime               delegate
                              │                  │
                              ▼                  ▼
                    local build + files    adapter pinned to the bundle
                              │                  │
                              └──── same algorithm? ────┘
                                       │
                                       ▼
                                  RuntimeBundleStore
```

## The record

```python
@dataclass(frozen=True, slots=True)
class ResearchAdapterIntegration:
    integration_id: str
    adapter_id: str

    runtime_asset_roles: tuple[str, ...]
    primary_runtime_asset_role: str

    create_development_runtime: DevelopmentRuntimeFactory
    create_research_delegate: ResearchDelegateFactory
    validate_result_set: ResearchResultValidator
```

`integration_id` is the integration's own identity, distinct from the adapter's:
a second way of driving the same adapter — a different runtime layout, a
different set of roles — is a different integration and says so.

It refuses, at construction, an empty role tuple, a duplicate role, a primary
role that is not among the declared roles, an unusable identifier, and a hook
that is not callable.

## The three hooks

### `create_development_runtime(repository_root, algorithm_config, overrides)`

Build the algorithm from whatever the developer has locally, and say where each
runtime file is:

```python
DevelopmentAdapterRuntime(adapter=..., assets={role: absolute_path, ...})
```

This is the **only** place a build layout is known. The model refuses a relative
path, a symlink, a missing file, and two roles naming the same bytes.

`overrides` is how an experiment says something only this algorithm needs.
SourceAFIS uses `build_jar`, because a Maven shaded jar is not byte-reproducible
and pinning the exact executable an earlier run used means naming the file rather
than rebuilding it. That is a fact about Maven, which is why it arrives as an
override rather than as a parameter on the shared engine.

### `create_research_delegate(repository_root, algorithm_config, bundle, asset_paths, software)`

Build the same algorithm again, pinned to the materialised bundle, and return
**the plain adapter**. The engine wraps it in `ResearchModeAdapter` itself; an
adapter that wrapped itself would put the research environment in two places and
let them disagree.

### `validate_result_set(context) -> AlgorithmValidationReport`

Inspect every stored result against this algorithm's contract. The engine cannot
do this: which failure codes are legitimate biometric outcomes and which mean the
harness broke is an algorithm-specific judgement, and guessing is how a broken run
becomes a published one (docs/adr/0013).

The context carries the run, the plan, the pairs, the images, the result store,
the runtime reference and — for a run over a materialised input set — the
`PreparedInputExpectations`. It carries no threshold and no decision profile.

## What the engine checks around you

**The build is the algorithm you declared.** `require_development_runtime`
compares the produced role set against the declared one and the built adapter's
id against `adapter_id`.

**Pinning did not change the algorithm.** `require_same_algorithm` compares the
development and research descriptors field by field and then by fingerprint.
Materialising a runtime bundle moves bytes; if it moves identity, the environment
check proved nothing about the thing that will produce the scores.

**The bundle is your bundle.** `require_bundle_matches` refuses a bundle missing
a declared role, carrying an undeclared one, or belonging to another adapter —
on creation *and* on every reload, because a bundle can be edited between
invocations (docs/adr/0042).

## What the engine will not do

There is no registry of integrations. No `latest`, no module scanning, no entry
points: the experiment wrapper names one integration, in code.

There is no branching on identity. No `if algorithm_id == ...`, no `match
adapter_id`, no comparison of an identifier against a string literal — enforced
by a structural test over the syntax tree, because the rule is only worth having
if breaking it is noisy.

There is no algorithm in the module at all: it imports no adapter package, and
the names of the algorithms this project runs do not appear in it.

## Worked example

`fpbench.experiments.sourceafis_research` is the whole of what an integration
looks like in practice — roughly two hundred lines, of which the integration is
sixty and the rest is the four compatibility commands. It materialises nothing,
executes nothing, opens no result file and builds no receipt, and
`tests/unit/test_sourceafis_research_wrapper.py` checks that structurally rather
than by counting lines.
