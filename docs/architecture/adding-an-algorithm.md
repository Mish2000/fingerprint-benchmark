# Adding an algorithm

Ten steps. None of them touches `fpbench.core`, `fpbench.protocols`,
`fpbench.storage`, `fpbench.imaging`, `fpbench.execution.runner`,
`fpbench.decisions`, `fpbench.eligibility`, `fpbench.metrics` or
`fpbench.paired` — and if one of them turns out to, that is a defect in the
extension points rather than a step in the recipe (docs/adr/0043).

Everything you write lives in four places:

```
src/fpbench/adapters/<name>/          the adapter, its config, its failure map
src/fpbench/experiments/<name>_*.py   the validator and the thin wrapper
configs/algorithms/<name>_*.yaml      identity and paths
configs/experiments/<name>_*.yaml     the experiment
tests/...                             yours
```

---

## 1. Define the route's identity

Fill in `AlgorithmPipelineMetadata`. Every field, including the ones that feel
redundant.

```python
PIPELINE = AlgorithmPipelineMetadata(
    family_id="nbis",
    pipeline_kind="extract_then_match",
    extractor_id="mindtct",     extractor_version="...",
    matcher_id="bozorth3",      matcher_version="...",
    implementation_language="c",
    integration_mode="subprocess_per_stage",
    input_mode="converted_file",
    dpi_policy="explicit_effective_ppi",
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_algorithm_has_no_seed",
)
```

`algorithm_id` names the **whole route**, never one half of it. `bozorth3` alone
would omit the extractor, and a score attributed that way could not be traced to
the build that produced it (docs/adr/0014).

All of this reaches `descriptor_fingerprint`, so every one of these strings is
part of what makes two runs comparable. Changing any of them later is a new
algorithm identity and therefore a new run.

## 2. Define the configuration

One frozen dataclass, read with the strict helpers in
`fpbench.core.config_values`. Reject unknown keys; refuse a quoted boolean;
refuse a float where an integer belongs. A typo that is ignored is a setting that
silently did nothing.

Resolve every path to absolute at construction: a subprocess launched from a
relative path depends on whatever directory the caller happened to be in.

## 3. Build and locate the runtime files

List **every file whose bytes could change a score** — each executable, and any
support data they read. Give each one a role:

```python
runtime_asset_roles = ("nbis_mindtct_executable",
                       "nbis_bozorth3_executable",
                       "nbis_support_data")
```

All of them reach the bundle fingerprint. A rebuild of any one of them is a
different runtime and a different run (docs/adr/0042).

The generic receipt records the complete role-to-digest mapping. Do not add a
tool-specific digest field to core evidence; the integration id and its
fingerprint are also bound automatically into the environment (docs/adr/0044).

## 4. Write the adapter

Three methods, and only one of them does any matching.

- `descriptor` — stable for the lifetime of the adapter, built once in `__init__`.
- `validate_environment` — READY, or UNAVAILABLE with a message. Never raises for
  an ordinary missing dependency, and never puts an absolute path in the message.
- `compare(left, right, context)` — convert, extract, extract, match. Both sides
  extracted independently, always, including when they are the same file
  (docs/adr/0035).

Use the shared tools; there is nothing to reimplement:

```python
workspace = AdapterJobWorkspace.from_context(context)
template  = workspace.work_path("left-template.xyt")
result    = run_external_command(ExternalCommand(
    argv=(str(tool), str(source), str(template)),
    working_directory=workspace.working_directory,
    containment_root=workspace.working_directory,
    timeout_seconds=remaining_budget,
))
```

Name intermediate files meaninglessly — `left-input.pgm`, `right-template.xyt`,
`matcher-output.txt`. The workspace helper refuses a name carrying a subject, a
finger or a pair, because an adapter that had one would have been given something
the contract keeps from it (docs/adr/0010).

Record the independence facts in `adapter_metadata`:

```
extraction_policy = independent_both_sides
extraction_count  = 2
template_cache    = disabled
template_persistence = disabled
```

## 5. Map the failures

One file, `failure_mapping.py`, and nothing outside it decides what a failure
means. Order of precedence:

1. the tool's own structured code (its exit status);
2. the stage that was running;
3. a missing or unusable output file;
4. a pattern in stderr — **last resort only**, because a new release that reworded
   a message would silently reclassify every failure that matched it.

Never turn a failure into a score. Not `0`, not `-1`, not `NaN`: a comparison
that produced no number did not score badly, it did not score (docs/adr/0006).

## 6. Write the validator

`ResearchResultValidator` — a function from `ResearchValidationContext` to
something satisfying `AlgorithmValidationReport`. It decides, **for this
algorithm**:

- which failure codes are legitimate biometric outcomes (data, kept and counted);
- which mean the harness broke (defects, and they block a receipt);
- which metadata is mandatory, and which is forbidden;
- which tool versions must appear;
- which extraction policy must appear.

Reuse `check_prepared_inputs` and `check_release_source_resolutions` from
`fpbench.experiments.prepared_input_validation` for the input-set checks; they
are the same for every algorithm and are already tested.

## 7. Assemble the integration

```python
def nbis_research_integration() -> ResearchAdapterIntegration:
    return ResearchAdapterIntegration(
        integration_id="nbis_research_v1",
        adapter_id=ADAPTER_ID,
        runtime_asset_roles=(...),
        primary_runtime_asset_role=...,
        create_development_runtime=...,
        create_research_delegate=...,
        validate_result_set=...,
    )
```

The wrapper then supplies it to
`prepare_algorithm_research_run` and its three siblings, and does nothing else.
If your wrapper opens a result file, builds a receipt or computes a hash, it has
stopped being a wrapper (docs/adr/0040).

## 8. Run the conformance suite

```python
report = run_adapter_conformance(case, working_directory=..., artifact_directory=...,
                                 sandbox_root=...)
report.require_clean()
```

Findings, not a stack trace. Fix them before wiring anything else up; every one
of them is something a 6,000-comparison run would otherwise discover for you.
Each compare gets a fresh directory, and every invocation is checked for
exceptions, input mutation, stray writes and non-regular artifacts. Supply a
`directional_golden` when the route is intentionally asymmetric.

## 9. Smoke run

The shared engine over a handful of subjects — `tests/engineworld.py` builds a
complete synthetic experiment in a temp directory. Prepare, execute, finalize,
inspect, and confirm `RESEARCH_READY`. Anything wrong with the integration
surfaces here, in seconds, rather than in hours.

## 10. Full run

`prepare`, then `execute` as many times as it takes, then `status`, then
`finalize`. The runtime is revalidated on the way into every invocation and on
the way out; nothing is overwritten; the receipt is the last thing written.

---

## What you must not do

Adding an algorithm may not require a change to `SingleJobRunner`, `ResultStore`,
`ExecutionPlan`, the decision engine, the eligibility engine, the metric engine,
`PreparedImageSet` or the paired-evaluation models. If it appears to, stop and
write down why: either the extension points are wrong, or the algorithm needs
something the contract genuinely cannot express — and those two have completely
different fixes (docs/adr/0039, docs/adr/0043).
