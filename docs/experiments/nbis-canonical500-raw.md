# NBIS 5.0.0 over the canonical SD300 comparisons — raw scores

*Stage 7C. Experiment `nbis_canonical500_full_v1`.*

## The one question

> Which raw scores and execution outcomes does the certified NBIS route produce
> when it is given exactly the 6,000 comparisons and the 3,000 prepared images
> the canonical SourceAFIS run was given?

That is the whole question. This stage does **not** answer which algorithm is
better, where a threshold sits, how many MATCH or NON_MATCH decisions there are,
what the FNMR or FMR is, what the accuracy or EER is, or how the two score
columns correlate. Those need a decision profile for BOZORTH3, and there is not
one (docs/adr/0052).

## What is fixed before the run starts

| | |
| --- | --- |
| reference run | `run_4c59fa02a6ab` |
| reference plan | `plan_b4ae66e91923` |
| reference result set | `resultset_087b084fb8a8` |
| prepared image set | `prepset_be560e047991` |
| set fingerprint | `be560e047991a0d58af8f86a4576f8b78dc350e643af82f0e2405350d9e2fd3f` |
| transform profile | `canonical_gray8_500ppi_lanczos3_v1` (`28abd453…`) |
| transform runtime | `imgruntime_31a0a4346a3d` (`31a0a434…`) |
| NBIS build | `658f9f54a8f2` — gcc-13, linux/x86_64 |
| execution profile | `canonical_500_lanczos3_60s_v1`, reused unchanged |

No `PreparedImageSet` is created. No image is resized or re-encoded. No cohort is
selected and no pair is generated (docs/adr/0051).

## The shape

500 comparisons in every one of the twelve release-and-stage cells:

| | SD300A | SD300B | SD300C | total |
| --- | ---: | ---: | ---: | ---: |
| `plain_self` | 500 | 500 | 500 | 1,500 |
| `roll_self` | 500 | 500 | 500 | 1,500 |
| `plain_roll_mated` | 500 | 500 | 500 | 1,500 |
| `plain_roll_non_mated` | 500 | 500 | 500 | 1,500 |
| total | 2,000 | 2,000 | 2,000 | **6,000** |

3,000 prepared images, 1,000 per release. Every one of the 6,000 comparisons
extracts both sides independently — including the 3,000 SELF comparisons, which
hand in the same file twice and extract it twice (docs/adr/0035, docs/adr/0050).
So a complete run performs **12,000 MINDTCT invocations and 6,000 BOZORTH3
invocations**. There is no template cache and no reuse of an XYT between pairs.

## What is expected to differ from the reference run

New, and expected to be new: the run id, the plan id, every job id, the result set
id and the runtime bundle id. A job id is derived from the run fingerprint, so the
two runs' job ids are disjoint by construction — which is why the alignment is
proved by `pair_id` and by pair content, and never by `job_id`.

Unchanged, and checked: the protocol, the cohort, the pair manifest hash, the
6,000 pair ids and their order, the prepared set and every one of its 3,000
entries, the execution profile (and therefore the timeout, the seed, the preparer
and the input-set parameters), the replicate index, the materialization policy and
the sequential, no-retry execution.

## The commands

Everything runs on a certified target — linux/x86_64. On this machine that is the
`NBIS-BUILD-V1` WSL distribution, where the repository is at
`/mnt/c/fingerprint-benchmark`.

### 1. Build and certify the pinned build

```bash
python integrations/nbis/build.py build
python integrations/nbis/build.py test
```

`build.py` puts it at `build/nbis-5.0.0/<build-id>/`. With the distribution's
default compiler that id is `658f9f54a8f2`; the build id covers the compiler, so a
different one is a different build and stage 7C refuses it (docs/adr/0053).

### 2. Verify the build, and run the upstream suite against it

```bash
python integrations/nbis/verify_build.py build/nbis-5.0.0/658f9f54a8f2
```

```bash
FPBENCH_NBIS_BUILD_DIR=build/nbis-5.0.0/658f9f54a8f2 pytest -m "nbis_upstream" -q
```

### 3. Preflight the workspace

```bash
pytest -m "nbis_full_run" -q
```

Before the run this proves the reference chain is `RESEARCH_READY`, the result set
verifies, the prepared set is `PREPARATION_READY`, the alignment is derivable and
clean at 6,000/6,000 and 3,000/3,000, and the pinned build is certified. Missing
workspace: skip. Broken workspace: failure.

### 4. Prepare, execute, finalize

```python
import os
from pathlib import Path

from fpbench.experiments.nbis_canonical500_full import (
    prepare_nbis_canonical500_run,
    execute_nbis_canonical500_run,
    inspect_nbis_canonical500_experiment,
    finalize_nbis_canonical500_run,
)

build = Path("build/nbis-5.0.0/658f9f54a8f2")

prepared = prepare_nbis_canonical500_run(
    workspace=Path("workspace"),
    dataset_root=Path(os.environ["FPBENCH_SD300_ROOT"]),
    repository_root=Path("."),
    development_overrides={"build_directory": build},
)

execute_nbis_canonical500_run(
    workspace=Path("workspace"),
    dataset_root=Path(os.environ["FPBENCH_SD300_ROOT"]),
    repository_root=Path("."),
)

state = inspect_nbis_canonical500_experiment(
    workspace=Path("workspace"),
    dataset_root=Path(os.environ["FPBENCH_SD300_ROOT"]),
    repository_root=Path("."),
)
assert state.is_ready is False        # results exist; nothing is finalised yet

finalize_nbis_canonical500_run(
    workspace=Path("workspace"),
    dataset_root=Path(os.environ["FPBENCH_SD300_ROOT"]),
    repository_root=Path("."),
)

state = inspect_nbis_canonical500_experiment(
    workspace=Path("workspace"),
    dataset_root=Path(os.environ["FPBENCH_SD300_ROOT"]),
    repository_root=Path("."),
)
assert state.is_ready
```

`execute` accepts `max_new_jobs=N` and may be stopped and resumed as often as
necessary. A stored result is verified and skipped, never re-executed and never
overwritten.

There is **no command-line entry point**, on purpose. The run takes hours, it may
not be resumed under a different commit than it was prepared under, and a
convenient `execute` verb is how that happens by accident.

## What `prepare` checks, in order

1. the working tree is clean and committed (docs/adr/0017);
2. the named build is present, and its manifest holds up against both
   executables, the sealed source lock, the empty patch series and this
   repository's build scripts;
3. the prepared-image set verifies completely — manifest, profile, runtime,
   definition, every entry hash, every PNG's bytes and decoded raster, its receipt
   and its finalization marker;
4. the canonical SourceAFIS run is `RESEARCH_READY`;
5. its result set is `resultset_087b084fb8a8`;
6. the pair manifest is *loaded*, with `allow_creation=False`;
7. the alignment report is derived;
8. it is clean, or nothing further happens;
9. the shared engine creates the run;
10. the engine plans 6,000 jobs;
11. the alignment is re-derived against the plan that now exists, and stored under
    `results/<run>/derived/canonical-run-alignment.json`.

No raw result is written by `prepare`.

## What `finalize` checks

A full audit of the 6,000 stored results, the result set, the `NbisValidationReport`,
the alignment re-derived from the manifests and compared with the one preparation
stored, the research receipt, the finalization marker, `RESEARCH_READY`, and last
the combined Stage 7C state — research-ready **and** aligned **and** no issue.

`blocking_failures` must be 0. `TEMPLATE_EXTRACTION_FAILED` and `TIMEOUT` are
biometric outcomes and are kept as failures with no score; they are never replaced
by a score of 0. A BOZORTH3 score of 0 is a **success** (docs/adr/0006).

## Evidence

Committed under `evidence/nbis-canonical500-raw/`:

```
README.md
research-receipt.json
research-finalization.json
alignment-report.json
operational-summary.json
```

Not committed: raw results, runtime binaries, prepared PNGs, XYT templates and
SD300 imagery.

## What may be written about the result

Allowed:

> NBIS was run over the same 6,000 pair IDs and the same canonical prepared image
> set used by the canonical SourceAFIS run.

Not allowed at this stage: that either algorithm is better, that the scores are
similar, higher or lower, or any accuracy, false-match rate, false-non-match rate
or EER. SourceAFIS scores and BOZORTH3 scores are not on one scale and must not be
subtracted (docs/adr/0052).

## The gate to stage 7D

Stage 7D begins only once this stage is closed, and takes as input the NBIS raw
result set, its 6,000 rows, the same pair ids, the same prepared set and the final
failure analysis. It decides separately how a `DecisionProfile` for BOZORTH3 is
defined, where its threshold comes from, how SELF defines eligibility on this
route, which failures are `UNDECIDABLE`, and how a comparison with SourceAFIS can
be made without mixing two scales. None of those decisions is taken here.
