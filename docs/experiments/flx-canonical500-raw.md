# Stage 8C — the canonical 6,000 comparisons under the qualified flx route

What this run answers, and nothing more:

> what raw scores and what execution outcomes does the flx route Stage 8B
> qualified produce, given exactly the same 6,000 pairs and the same 3,000
> `canonical_500` images SourceAFIS and NBIS were given?

It publishes 6,000 stored outcomes. It publishes no distribution, no summary
statistic, no example score, no threshold and no decision (docs/adr/0076).

There is **no command-line entry point**, on purpose. The run takes hours, it
may not be started under a different commit than it was prepared under, and a
convenient `execute` verb is exactly how that happens by accident.

## Where it runs

The flx runtime is a 2.06 GB bundle — a virtual environment, an extracted source
tree and an 875 MB checkpoint — and `flx_cpu_linux_x86_64_v1` is a Linux x86_64
profile. So the run happens in the local Linux environment, at:

```
~/.cache/fpbench/flx/flx_cpu_linux_x86_64_v1/
```

On this Windows host that environment is a WSL distribution whose name,
`NBIS-BUILD-V1`, predates flx entirely: it was created in stage 7B to build
NBIS, and stage 8B later put the flx bundle inside it. The name says nothing
about what Stage 8C runs, and Stage 8C reads nothing of NBIS's — an AST check
refuses an import of any NBIS module from a Stage 8C source, and the boundary
audit refuses any change to `evidence/nbis-*` (spec sections 18 and 31).

`FPBENCH_FLX_BUNDLE` overrides the location, and it is the setting to prefer
over remembering a distribution name. Nothing about the bundle is searched for:
an explicit path, then that variable, then the default cache directory, and no
fallback.

The orchestration runs in the same place as the runtime, because the adapter
starts the worker with the bundle's own interpreter. The repository and the
dataset are reachable from the distribution through `/mnt/c`, and the harness
needs `pyarrow`, `PyYAML` and `Pillow==12.3.0` there — the same versions as the
host, so the prepared set's transform runtime fingerprint still verifies.

## Before anything

```bash
python -m fpbench.experiments.flx_canonical500_full 2>/dev/null || true
```

There is no module entry point; drive it from Python:

```python
from fpbench.experiments.flx_canonical500_full import preflight_flx_canonical500_run

preflight_flx_canonical500_run()
```

`preflight` writes nothing and checks everything the run will read:

1. the working tree is clean and committed;
2. the committed Stage 8B finalization is read, and its outcome must be
   `FLX_RAW_SCORE_EXECUTION_READY`;
3. all four flx profiles are rebuilt from this repository's source and must
   equal what Stage 8B published;
4. the source archive, the six imported source files and all 875,770,140
   checkpoint bytes are re-hashed;
5. the prepared image set verifies, and all 3,000 PNGs with it;
6. the reference SourceAFIS run is `RESEARCH_READY`;
7. the pair manifest is loaded with `allow_creation=False`;
8. the alignment report is derived and must be clean;
9. every input control matches the reference run's.

## Prepare

```python
from fpbench.experiments.flx_canonical500_full import prepare_flx_canonical500_run

prepared = prepare_flx_canonical500_run()
print(prepared.run.run_id, prepared.plan.plan_id)
```

`prepare` re-runs everything preflight did, then creates the run, plans exactly
6,000 jobs, re-derives the alignment against the plan that now exists, and stores
it. It writes no raw result and cannot: it never reaches the executor.

**Commit nothing between prepare and execute.** The run records the commit it was
created from and refuses to resume under another one (docs/adr/0017).

## Execute

```python
from fpbench.experiments.flx_canonical500_full import execute_flx_canonical500_run

execute_flx_canonical500_run(max_new_jobs=5)     # a small first slice
execute_flx_canonical500_run()                   # the rest
```

Sequential, one worker, no retries, in the pair manifest's order. Stopping and
resuming is expected: a stored result is verified and skipped, never re-executed
and never overwritten.

Budget, measured on the pinned runtime during Stage 8B: 0.763 s per extraction,
2.8 s of worker startup, 1.1 s of model load, 0.33 ms per comparison, 1.20 GB
peak RAM. Twelve thousand logical extractions project to about **2.5 hours**.

Note the two counts, and do not conflate them (docs/adr/0075):

```
12,000 preprocess calls          12,000 logical extractions
24,000 physical forward rows      6,000 comparisons
```

## Finalize

```python
from fpbench.experiments.flx_canonical500_full import (
    finalize_flx_canonical500_run,
    inspect_flx_canonical500_experiment,
)

finalize_flx_canonical500_run()
print(inspect_flx_canonical500_experiment().status)
```

`finalize` re-checks the Stage 8B binding and the alignment, then lets the engine
audit, build the result set, validate, write the receipt and write the research
marker. It refuses unless the run reaches `RESEARCH_READY`, the alignment is
clean and nothing derives from the run.

## Publish

```python
from fpbench.experiments.flx_canonical500_full import publish_flx_canonical500_evidence

publish_flx_canonical500_evidence()
```

Seven files, plus a `README.md` written by hand. `stage-8c-finalization.json` is
**not** among them: it is derived afterwards, against the exact bytes of the
commit that published the other seven, and committed on its own.

```python
from fpbench.experiments.flx_canonical500_full import (
    publish_flx_canonical500_finalization,
)

publish_flx_canonical500_finalization(verifier_source_commit="<commit 5's SHA>")
```

## Verify

Two different things, and the difference matters.

**Workspace verification** needs SD300, the prepared set, the raw ResultSet, the
checkpoint and the bundle. It verifies the experiment.

```python
inspect_flx_canonical500_experiment()
```

**Evidence-only verification** needs none of those. It reads the published
documents, rebuilds every profile from this repository's source, re-hashes the
exact bytes and checks the relationships between the documents.

```python
from fpbench.experiments.stage8c_verify import verify_stage8c_evidence

verify_stage8c_evidence()
```

A green evidence-only run says the publication is internally consistent and
byte-stable. It does **not** say the algorithm was executed, and it never claims
to: `Stage8CVerification.algorithm_executed` is always `False`.

## What is never published

The checkpoint, the source archive, SD300 images, prepared PNGs, 299×299
tensors, embeddings, representation hashes, raw score rows, the ResultSet,
temporary worker files, absolute paths and environment secrets. The verifier
walks every published JSON document as data and refuses a forbidden key at any
depth.
