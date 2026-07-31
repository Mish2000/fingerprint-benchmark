# fpbench — fingerprint recognition benchmark harness

A reproducible harness for comparing fingerprint recognition algorithms on NIST
Special Database 300 (releases A/500 ppi, B/1000 ppi, C/2000 ppi).

The organising principle:

> The harness owns the experiment. An algorithm never decides what runs, and
> infrastructure never changes an algorithm without saying so in writing.

---

## What exists right now

Phase 2 built the reproducible experiment definition: **datasets, protocol,
provenance and manifest storage**. It records which exact image delivery was
audited, which 50 subjects were chosen, and which 6,000 comparisons the
protocol calls for — with no algorithm involved.

Phase 3A added the **execution foundation**: an image preparation contract, an
adapter contract with a registry and a deterministic stand-in matcher, derived
run and job identity, and a single-job runner that stores one immutable result
per job and can be interrupted and resumed.

Phase 3B added **full-run planning and orchestration**: a pair manifest becomes
an immutable, deterministically ordered execution plan; a sequential executor
walks it, stops anywhere, and resumes without repeating work; progress is
recomputed from the files rather than counted; and a run is declared verified
only after an integrity audit accounts for every planned comparison. All 6,000
comparisons of the protocol run end to end under the dummy matcher.

Phase 4A added the **first real biometric integration**: SourceAFIS for Java 3.18.1,
behind a stateless Java subprocess bridge. It enters through exactly the same adapter
contract the dummy matcher used — nothing in the runner, the planner, the executor or
the storage layer knows it exists. It closed with a green adapter workflow and a
24/24 SD300 compatibility pilot.

Phase 4B added **research-grade provenance**: a run now identifies the fpbench commit
that produced it and the exact bytes of the executable it ran, the raw results acquire
an immutable identity of their own, and "finished" and "trustworthy" became separate
states with a revalidation step between them.

Phase 5A added the **decision layer**: a documented threshold with a traceable origin,
6,000 deterministic decisions derived from unchanged scores, 1,500 per-finger SELF
eligibility verdicts, and the three evaluation views the protocol asks for — each with
an immutable identity, and none of them a metric.

Phase 5B added the **metric layer**, and with it the project's first biometric result: an
immutable metric policy, fourteen metrics that each name their own denominator, counts
per release and pooled by summing, and a report that publishes every rate as the two
integers it was computed from.

Phase 6A added the **shared canonical input pipeline**: a real resampling of every
participating image to 500 ppi, performed once in `fpbench.imaging` rather than inside
any adapter, producing an immutable content-addressed set that every algorithm evaluated
under the profile receives unchanged — and then the same 6,000 SourceAFIS comparisons
over it, with the algorithm's identity untouched.

```
VERIFIED SOURCE IMAGES
        ↓
PREPARATION_READY canonical image set
        ↓
RESEARCH_READY canonical raw run
        ↓
Stage 6B decisions and paired evaluation
```

`canonical_500` is a shared **input profile**, not an algorithm feature. Stage 6A applies
no threshold, computes no metric, reads no native score and produces no
native-versus-canonical conclusion. It proves that SD300A's pixels came through
untouched; whether identical pixels produced identical scores is stage 6B's observation.

Still no EER, no ROC, no calibrated threshold, no confidence interval, and no general
FMR — the closed-set same-subject negative fraction is published as a sanity check and is
not one. And still no claim that any resolution is better than any other.

| Package | Status | Responsibility |
|---|---|---|
| `fpbench.core` | built | shared vocabulary; stdlib only, imports nothing from the project |
| `fpbench.datasets` | built | what images exist on disk, and do they match their own declarations |
| `fpbench.protocols` | built | which subjects take part, and which comparisons that implies |
| `fpbench.storage` | built | immutable manifests, plans, results, runtime bundles, result sets, decisions |
| `fpbench.imaging` | built | the preparation contract, the identity preparer, and the shared canonical 500 ppi transform |
| `fpbench.adapters` | built | the contract, the registry, `dummy_sha256` and `sourceafis_java` |
| `fpbench.provenance` | built | which build of the harness, and which executable, produced a result |
| `fpbench.execution` | built (sequential) | plan, run, resume, progress, audit, completion, result set, research state |
| `fpbench.decisions` | built | threshold profiles, the decision function, decision sets |
| `fpbench.eligibility` | built | SELF units, the both-must-match rule, eligibility sets |
| `fpbench.evaluation` | built (views) | which comparisons an evaluation covers |
| `fpbench.derivations` | built | derivation receipts, finalization markers, derivation status |
| `fpbench.metrics` | built | metric policy, named denominators, counts, report, evaluation status |
| `fpbench.experiments` | built (five) | the SourceAFIS full run, its decisions, the counts over them, the canonical image set, and the canonical run |
| `fpbench.cli` | not yet | command-line entry points |

Deliberate omissions, so they read as decisions rather than oversights:

* **No calibrated threshold.** The only profile is SourceAFIS's own documented 40,
  recorded as `origin: documented_native` so it can never be presented as something this
  project measured. A calibrated profile needs a development cohort, and drawing one from
  the 50 test subjects is refused outright
  ([ADR 0021](docs/adr/0021-decision-profiles-are-immutable-and-external.md)).
* **No accuracy figure, even now that the 6,000 decisions have been counted.** The
  denominators are defined and the counts are published, which is a much narrower claim
  than "accuracy": every rate is an observation about this closed cohort under one
  documented threshold. See
  [The first result](#the-first-result) and
  [what these results do not establish](docs/reports/sourceafis-native-first-evaluation.md).
* **Sequential only.** One job at a time, no retries, no worker pool, no hard timeout
  termination. The storage layout is already the one that makes parallelism safe — one
  immutable file per job, no shared table, no locks — so adding workers later changes
  the executor and nothing beneath it.
* **One JVM per SourceAFIS comparison.** Correct and slow, on purpose. Whether to move
  to a persistent worker is a question for measurement, not guesswork
  ([ADR 0015](docs/adr/0015-sourceafis-uses-stateless-java-bridge.md)).
* **No templates stored, cached or serialised**, and no algorithm transparency output.
  Optional adapter capabilities are named in the contract, not implemented.

## Setup

```bash
conda env create -f environment.yml
conda activate fingerprint-benchmark
pip install -e ".[dev]"
```

The environment includes JDK 17 and Maven, because the SourceAFIS adapter runs a Java
bridge. Build it once:

```bash
make sourceafis-build
```

Point the harness at your NIST delivery (the directory holding `sd300a/`,
`sd300b/`, `sd300c/`) — see [data/README.md](data/README.md):

```powershell
$env:FPBENCH_SD300_ROOT = "C:\fingerprint-datasets\NIST"
```

Run the tests:

```bash
make test
```

which is `pytest -m "not dataset and not sourceafis and not full_run"` — exactly what
CI runs on every push and pull request. Three markers are excluded, each with its own
way in:

| Marker | Needs | How to run it |
|---|---|---|
| `dataset` | the real SD300 delivery | `pytest -m dataset` with `FPBENCH_SD300_ROOT` set; skipped automatically when it is not |
| `sourceafis` | a JVM and the built bridge | `make sourceafis-test`; its own [workflow](.github/workflows/sourceafis-adapter.yml) |
| `full_run` | a couple of minutes | `make full-run`; its own [workflow](.github/workflows/full-dummy-run.yml) |

The `decisions` and `metrics` markers are *not* excluded — neither layer needs a JVM or
the data, so both run in the ordinary suite. `make decisions-test` and `make metrics-test`
run them alone, and each has its own workflow
([decisions](.github/workflows/decision-derivation.yml),
[metrics](.github/workflows/biometric-evaluation.yml)).

`make test-all` runs everything available on the machine.

Set `FPBENCH_REQUIRE_SOURCEAFIS=1` — as the Make targets and CI do — to turn "the
bridge is unavailable" from a skip into a failure. Without it, a broken Java build would
produce a green run full of skips.

The suite has five levels:

```
tests/unit/          individual functions and model invariants
tests/contract/      one suite every adapter must pass, parametrised over the registry
tests/integration/   dataset → manifest → cohort → pairs, and plan → executor → verified run
tests/regression/    pinned run, plan and job identities
tests/…              marked `dataset`: assertions that only mean something
                     against the real 58,305-image delivery
```

## Building the experiment

There is no CLI yet, so the pipeline is composed explicitly. This is the whole
of it:

```python
from pathlib import Path

from fpbench.datasets import create_provider, load_dataset_spec, summarise_subjects
from fpbench.protocols import SD300Protocol
from fpbench.storage import ManifestStore

provider = create_provider(load_dataset_spec(Path("configs/datasets/sd300.yaml")))
protocol = SD300Protocol.from_config_file(Path("configs/protocols/sd300_50_subjects.yaml"))
store = ManifestStore(Path("workspace"))

images, subjects = [], []
image_manifest_hashes = {}
validation_override_reason = None  # set a documented reason only when intentional
verify_checksums = False  # set True before constructing final research manifests
for release in protocol.releases:
    report = provider.validate(release)
    store.write_validation_report(
        report, dataset_id=protocol.dataset_id, release=release
    )
    if not report.is_clean and validation_override_reason is None:
        raise RuntimeError(f"{release}: blocking dataset validation errors")

    release_images = list(
        provider.scan(release, verify_checksums=verify_checksums)
    )
    release_subjects = summarise_subjects(release_images)
    store.write_images(
        release_images,
        dataset_id=protocol.dataset_id,
        release=release,
        validation_override_reason=validation_override_reason,
    )
    store.write_subjects(
        release_subjects, dataset_id=protocol.dataset_id, release=release
    )
    image_manifest_hashes[release] = store.image_manifest_hash(
        protocol.dataset_id, release
    )
    images += release_images
    subjects += release_subjects

cohort = protocol.build_cohort(subjects, image_manifest_hashes)
pairs = protocol.build_pairs(cohort, images)

store.write_cohort(cohort)
store.write_pairs(pairs, cohort=cohort)
```

Produces, under `workspace/manifests/`:

```
datasets/sd300/SD300A/images.parquet      19,435 rows
datasets/sd300/SD300A/subjects.parquet       888 rows
datasets/sd300/SD300A/validation.json       audit report
datasets/sd300/SD300B/...
datasets/sd300/SD300C/...
protocols/sd300_50_subjects/cohorts/<cohort_id>/cohort.json
protocols/sd300_50_subjects/cohorts/<cohort_id>/pairs.parquet
```

Checking a release against its own declarations:

```python
report = provider.validate("SD300C")
report.is_clean        # True — the PPI defect is a warning, not an error
report.counts_by_code  # {'metadata_ppi_anomaly': 10115}
```

Every scanned `ImageRecord` carries NIST's `expected_sha256`. A regular scan
does not hash 113 GB; `checksum_status` remains `not_verified`. Before final
research runs, perform and persist a full verification once:

```python
verified_images = list(provider.scan("SD300A", verify_checksums=True))
assert all(image.checksum_status.value == "verified" for image in verified_images)
# Use verified_images as release_images before selecting the final cohort.
```

Warnings remain usable, including the documented SD300C metadata anomaly.
Validation errors remain in `images.parquet` through `blocking_issues` for
audit only when `write_images()` receives a non-empty, documented
`validation_override_reason`; otherwise storage refuses the write.
`summarise_subjects()` and pair indexing always ignore blocked records. A
parseable file absent from NIST's checksum manifest is reported as an error and
is not minted as an `ImageRecord`, because no official source digest can be
attached.

## The protocol

50 subjects that are complete in **all three** releases — ten anatomical
fingers, present as both plain and rolled impressions. 500 plain + 500 rolled
images per release. Simultaneous-capture slap images (FRGP 13/14) are excluded
at indexing time and can never enter a comparison. FRGP 15 is unknown in SD300
and is never treated as a multi-finger image.

Four stages per release, 500 pairs each:

| Stage | Left | Right | Ground truth |
|---|---|---|---|
| `plain_self` | plain finger *i* | itself | mated |
| `roll_self` | rolled finger *i* | itself | mated |
| `plain_roll_mated` | plain finger *i* | rolled finger *i* | mated |
| `plain_roll_non_mated` | plain finger *i* | rolled finger *i+1* | non-mated |

The PLAIN–ROLL stage is reported twice: over all 500 pairs, and over only those
whose finger survived both SELF stages. A finger that fails *either* SELF stage
disqualifies its pair — failing PLAIN SELF is sufficient regardless of ROLL
SELF. The pair manifest itself is never modified. The decision is stored as an
explicit per-finger table at
`results/<run_id>/decisions/<decision_profile_id>/self_eligibility.parquet`,
from which the eligible pair view can be derived for that exact run/profile.

Cohort selection is arbitrary but reproducible: candidates are ranked by
`SHA256(seed || subject_id)`. The cohort id fingerprints source image-manifest
hashes, criteria, the full candidate pool and the 50 winners. Pair manifests
carry protocol id, cohort id, the composite image-manifest hash, their own
semantic content hash and schema version in Parquet metadata.

## Architecture

Three planes, and a strict dependency direction:

```
Control  — what should run?     datasets · protocols · experiment planning
Execution— how is it run?       imaging · adapters · decisions · runner
Analysis — what does it mean?   metrics · failure analysis · reports
```

```
core        imports nothing from the project (stdlib only)
datasets    → core                    never protocols
protocols   → core                    never adapters
adapters    → core                    never protocols
storage     → core
execution   → everything above
evaluation  → core, storage           never adapters
```

The rules exist so that adding an algorithm cannot change the experiment, and
changing the experiment cannot silently change what an algorithm does. Every
decision behind them is recorded in [docs/adr](docs/adr/README.md).

## Pairing decision

The non-mated stage is the accepted deterministic same-subject,
different-finger negative sanity test: plain finger *i* against rolled finger
*i+1*, wrapping at ten. See
[ADR 0008](docs/adr/0008-non-mated-pairing-strategy.md).

## Running the experiment

A pair goes in, a stored raw result comes out, and the whole thing can be
interrupted and resumed without duplicating work or losing any. The harness-only
matcher is `dummy_sha256`, which derives a deterministic score from the two images'
official digests. **It performs no biometric matching and no research claim may rest
on its output.** It exists so that the harness can be exercised while a bug is still
unambiguously the harness's fault. The first real biometric matcher,
`sourceafis_java`, is described below.

### 1. Define the run and plan it

Continuing from the manifests built above:

```python
from fpbench.adapters import create_adapter
from fpbench.execution import (
    DEFAULT_EXECUTION_PROFILE,
    build_execution_plan,
    create_run_definition,
)

adapter = create_adapter("dummy_sha256")
pair_metadata = store.pair_manifest_metadata(
    protocol.protocol_id, cohort.cohort_id
)

run = create_run_definition(
    protocol_id=protocol.protocol_id,
    cohort_id=cohort.cohort_id,
    pair_manifest_hash=pair_metadata["pair_manifest_hash"],
    algorithm=adapter.descriptor,
    environment=adapter.validate_environment(),
    execution_profile=DEFAULT_EXECUTION_PROFILE,
)

plan = build_execution_plan(
    run=run, pairs=pairs, pair_manifest_metadata=pair_metadata
)
# 6,000 jobs: 1,500 per stage, 2,000 per release
plan.definition.stage_counts, plan.definition.release_counts
```

The planner refuses a pair manifest that does not belong to the run, refuses
duplicates, and imposes its own order — stage, then release, then `pair_id` — so
that shuffling the input cannot change the plan or a single job id
([ADR 0011](docs/adr/0011-immutable-deterministic-execution-plan.md)).

### 2. Execute it

```python
from fpbench.execution import (
    RunCompletionService,
    SequentialRunExecutor,
    SingleJobRunner,
)
from fpbench.imaging import IdentityImagePreparer
from fpbench.storage import ResultStore

result_store = ResultStore(Path("workspace"))
executor = SequentialRunExecutor(
    plan=plan,
    pair_index={pair.pair_id: pair for pair in pairs},
    job_runner=SingleJobRunner(
        run=run,
        adapter=adapter,
        preparer=IdentityImagePreparer(),
        result_store=result_store,
        dataset_root=provider.root,
        image_index={image.image_id: image for image in images},
        workspace_root=Path("workspace"),
    ),
    result_store=result_store,
    completion_service=RunCompletionService(result_store=result_store),
)

summary = executor.execute()
summary.newly_executed_jobs, summary.remaining_jobs, summary.verified
```

To run a slice instead of the whole thing — for a smoke test, or just to stop
for the night:

```python
executor.execute(max_new_jobs=500)
```

Jobs already stored are checked and skipped without counting against the budget,
so a resumed run spends its allowance on new work.

Produces, under `workspace/`:

```
results/<run_id>/run.json                        the run manifest      immutable
results/<run_id>/runtime.json                    which bundle ran it   immutable
results/<run_id>/plan/plan.json                  the plan definition   immutable
results/<run_id>/plan/jobs.parquet               one row per job       immutable
results/<run_id>/raw/jobs/<job_id>.parquet       one row per result    immutable
results/<run_id>/result-set/manifest.json        the results' identity immutable
results/<run_id>/result-set/results.parquet      one row per result    immutable
results/<run_id>/completion.json                 written after a clean audit
results/<run_id>/research-receipt.json           sanitised, committable
results/<run_id>/research-finalization.json      last-written commit marker
results/<run_id>/derived/                        progress, summaries   disposable
results/<run_id>/decisions/<set_id>/             one threshold applied immutable
runtime/bundles/<bundle_id>/                     pinned executables    immutable
work/<run_id>/<job_id>/                          adapter scratch       disposable
artifacts/<run_id>/<job_id>/                     adapter artefacts, if any
```

The last four arrive with a research run; an ordinary dummy run produces only the
first block ([ADR 0018](docs/adr/0018-external-runtime-assets-are-content-addressed.md),
[ADR 0019](docs/adr/0019-result-sets-have-independent-immutable-identity.md)).

### 3. Check progress, and audit

```python
from fpbench.execution import audit_run, inspect_run_progress

progress = inspect_run_progress(run=run, plan=plan, result_store=result_store)
progress.state              # planned | partial | complete | verified | invalid
progress.stored_results, progress.missing_results

report = audit_run(run=run, plan=plan, result_store=result_store)
report.is_clean, report.success_count, report.failure_count
report.missing_job_ids, report.extra_result_job_ids
```

Progress is recomputed from the plan and the files every time it is asked for —
there is no counter anywhere, and no persisted `RUNNING` state, because after a
crash nothing on disk could honestly claim either
([ADR 0012](docs/adr/0012-run-progress-is-derived.md)).

`COMPLETE` and `VERIFIED` are different claims. The first says every planned job
has a result; the second says an audit compared each of those results against
the plan — job fingerprint, pair, images, pair manifest hash, algorithm
fingerprint, execution profile hash, and the digest in its own parquet header —
and found nothing wrong. Only a clean audit writes `completion.json`, and only
that file makes a run `VERIFIED`.

A run can be verified with failures in it. 30 comparisons that produced no score
out of 6,000 is a finished, trustworthy run with 30 failures to analyse
([ADR 0013](docs/adr/0013-comparison-failure-does-not-invalidate-run.md)). What
does stop a run is a *conflict*: a result contradicting the plan, a corrupt file,
a job that does not match its pair.

### The full protocol under the dummy matcher

```bash
pytest -m full_run
```

Plans and executes all 6,000 comparisons, audits them, verifies the run, then
re-runs it to confirm that the second pass performs zero comparisons. Takes a
couple of minutes.

### Resume

`run_id` and `job_id` are *derived*, not assigned: `run_id` is the first twelve
characters of a digest over the protocol, cohort, pair manifest hash, algorithm
and adapter versions, environment, execution profile, seed and replicate index.
Identical inputs therefore land in the same directory, and re-executing a job
whose result is already stored returns `SKIPPED_EXISTING` without preparing an
image or calling the adapter. A stored result whose `job_fingerprint` disagrees
raises `ResultConflictError` — nothing is ever overwritten
([ADR 0009](docs/adr/0009-one-immutable-result-per-job.md)).

Changing anything that could change a score — a new pair manifest, a bumped
adapter version, a different seed — produces a new `run_id` instead of quietly
mixing incomparable results together. The same holds for `plan_id`, and a
different plan under an existing run is a `PlanConflictError` rather than a
silent replacement.

In practice, resuming looks like this:

```
executor.execute(max_new_jobs=137)   → 137 results,  state PARTIAL
executor.execute(max_new_jobs=200)   → 137 skipped, 200 new, state PARTIAL
executor.execute()                   → the rest, audit, completion, VERIFIED
```

`Ctrl-C` at any point leaves every already-written result intact and complete;
the interrupted job is simply not among them. `KeyboardInterrupt` is never
caught and never recorded as a comparison failure.

### What is recorded, and what is not

A stored result carries its own provenance: protocol, cohort, pair manifest
hash, algorithm fingerprint, execution profile hash, timings and either a raw
score or a structured failure. It carries **no** threshold, **no** decision,
**no** ground truth, **no** protocol stage and **no** absolute path. Evaluation
joins the ground truth back in from the pair manifest through `pair_id`.

Operational failures and biometric outcomes stay apart: a comparison that ran
and scored low is a `success` with a low score, while one that never produced a
score is a `failure` with a specific code — `input_invalid`,
`preparation_failed`, `timeout`, `internal_error`
([ADR 0006](docs/adr/0006-self-failure-semantics.md)). An adapter that throws,
returns NaN, or contradicts its own declared score direction becomes a recorded
`internal_error` with `details.kind = adapter_contract_violation`; it never
takes the run down with it.

The adapter is told nothing about the comparison it is performing. It receives
two prepared images and an operational context with no `pair_id`, no
`protocol_stage`, no `ground_truth` and no threshold, and `job_id` is a hash so
that nothing leaks through it
([ADR 0010](docs/adr/0010-adapter-context-excludes-ground-truth.md)).

## The first real algorithm

`sourceafis_java` — SourceAFIS for Java 3.18.1, extraction and matching, pinned exactly.
It is registered like any other adapter and selected by id:

```python
adapter = create_adapter("sourceafis_java_subprocess")
adapter.validate_environment()   # READY, or a reason why not
```

Nothing else changes. The same `SingleJobRunner`, the same planner, the same executor,
the same stored result schema — swapping the adapter is the only difference between a
dummy run and a real one, which is what
[ADR 0007](docs/adr/0007-no-algorithm-branching-in-runner.md) was for.

What the integration commits to:

* **The identity names the whole pipeline**, extractor and matcher both, so the next
  algorithm — where they differ — cannot be mislabelled
  ([ADR 0014](docs/adr/0014-algorithm-identity-describes-full-pipeline.md)).
* **One stateless JVM per comparison.** No state can carry between comparisons, a crash
  costs one result, and the JVM's arguments, locale and timezone are pinned. The jar's
  SHA-256 is part of the environment fingerprint, and the bridge reports the SourceAFIS
  version *SourceAFIS itself* reports at runtime — so a jar built from a different
  release is refused during preflight
  ([ADR 0015](docs/adr/0015-sourceafis-uses-stateless-java-bridge.md)).
* **Explicit DPI per side**, from `effective_ppi`: 500, 1000 and 2000, all verified to be
  accepted with no clamp and no fallback. SourceAFIS ignores embedded DPI, which is
  exactly why SD300C's false 5080 header cannot mislead it
  ([ADR 0016](docs/adr/0016-sourceafis-receives-explicit-effective-dpi.md)).
* **Both sides extracted independently**, even for a SELF comparison where the two paths
  are identical. The bridge reports `extraction_count: 2` and the adapter refuses any
  other value.
* **Left is the probe, right the candidate.** Fixed; never reversed or averaged.
* **Raw score only.** No threshold, no decision, no template stored or cached, no
  transparency output.

Full details, including the wire protocol and what has deliberately *not* been done, are
in [docs/algorithms/sourceafis-java.md](docs/algorithms/sourceafis-java.md).

### The SD300 pilot

```bash
make sourceafis-sd300-smoke
```

24 real comparisons — one subject, two fingers, four stages, three releases — drawn from
the real execution plan. It asserts that all 24 produce a raw score at 500, 1000 and
2000 ppi with no crash, timeout or rejected resolution.

It leaves the run `PARTIAL` and writes no completion manifest, because 24 of 6,000
comparisons must never be able to look finished. **No accuracy conclusion follows from
it.**

## The full run, and what makes it research-grade

A pilot can run from a build directory. A run whose numbers will be cited cannot, and
the four things that separate them are all provenance rather than scale.

### The build jar is not the runtime

The adapter ordinarily runs `integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar`,
which is convenient and is *build output*: one `mvnw package` replaces those bytes at the
same path. Before a research run, the jar is copied once into an immutable bundle
identified by its contents:

```
workspace/runtime/bundles/<bundle_id>/
├── bundle.json
└── assets/fpbench-sourceafis-bridge.jar
```

`bundle_id` derives from the digests, not the path — so the same jar built on another
machine materialises to the same id, and a jar that differs by one byte can never be
mistaken for it. No symlink and no hardlink: a hardlink would let a rebuild rewrite the
"immutable" asset in place. A research adapter refuses to run anything outside its
bundle, re-hashes it before and after every executor invocation, and `stat`s it before
every single comparison. A jar replaced mid-run raises `RuntimeDriftError`, which stops
the executor and is **never** recorded as a comparison failure
([ADR 0018](docs/adr/0018-external-runtime-assets-are-content-addressed.md)).

### The commit is part of the run's identity

Nothing in a run currently covers the Python between the pair manifest and the stored
result — request serialisation, failure mapping, resume, metadata, audit — and all of it
can change a result. So a research run captures its own source revision and folds it into
the environment, which is already inside the run fingerprint.

Two consequences, both intended. **A dirty working tree cannot start a research run**;
there is no override, because uncommitted code cannot be recovered from a receipt written
a year later. And **a documentation-only commit produces a new `run_id`** — the harness
cannot tell which lines of a diff could change a number, so it treats them all as if they
could. To resume a run, check out the commit it was created from
([ADR 0017](docs/adr/0017-research-runs-pin-fpbench-source-revision.md)).

### prepare / execute / status / finalize

```bash
python -m fpbench.experiments.sourceafis_native_full prepare
python -m fpbench.experiments.sourceafis_native_full execute --max-new-jobs 500
python -m fpbench.experiments.sourceafis_native_full execute
python -m fpbench.experiments.sourceafis_native_full status
python -m fpbench.experiments.sourceafis_native_full finalize
```

`prepare` is where everything stops if it is going to: a dirty tree, an unbuilt jar, an
image without VERIFIED checksum evidence, a protocol that does not yield exactly 6,000
comparisons. It hashes the delivery once to build the image manifests, materialises the
bundle, derives the run and the plan, and writes the run's runtime binding. Running it
again with the same inputs produces the same `run_id`, the same `plan_id` and the same
`bundle_id`, and overwrites nothing.

`execute` can be run as often as it takes — a few hundred comparisons at a time, or the
rest of them. Existing results are checked and skipped without calling Java, so a resumed
run spends its budget on new work. Every invocation re-verifies the bundle's full digest
on the way in and on the way out, and re-checks that the commit still matches.

`execute` always passes `finalize=False`, so a run with all 6,000 results reports
`completed` and **not** `verified`, and has no completion manifest. That is the point:
something has to revalidate the runtime before anything says the run is sound.

`finalize` does that, in a fixed order that stops at the first failure: runtime, executor
source provenance, the finalizer's clean committed revision, core audit and SourceAFIS
evidence validation. It then builds all claims, writes idempotent intermediate artefacts,
reads and verifies them, and writes `research-finalization.json` last. An interrupted
attempt can leave intermediates, but without that matching marker they are not authoritative
([ADR 0020](docs/adr/0020-research-finalization-follows-runtime-revalidation.md)).

### RESEARCH_READY

`status` reports a state stronger than `VERIFIED`, recomputed from the files every time:

```
NOT_PREPARED → PREPARED → PARTIAL → RESULTS_COMPLETE → CORE_VERIFIED → RESEARCH_READY
                                                    ↘ INVALID
```

`CORE_VERIFIED` is a real and common state: the audit passed and `completion.json` exists,
but the results have no citable identity yet. `RESEARCH_READY` needs the whole chain:
current audit and algorithm validation, runtime bundle/JAR, executor source revision,
cohort and pair manifest, the exact plan-ordered result set, completion, every receipt
claim, and the finalization marker. Any broken link reports `INVALID` rather than
degrading quietly. `status` also records the committed verifier revision that performed
the inspection; it need not equal the older executor revision named by an existing run.

### The result set

`completion.json` says a run was audited. It does not say *which scores* — and the
decision stage has to be able to name them and re-check that claim later. So finalisation
writes an immutable index:

```
results/<run_id>/result-set/manifest.json      the identity
results/<run_id>/result-set/results.parquet    ordinal, job_id, result_hash
```

`result_set_fingerprint` covers the run, the plan, the runtime bundle, and the ordered
`(ordinal, job_id, result_hash)` triples. One changed score changes it. One changed
failure code changes it. Rewriting the same results tomorrow does not, because no
timestamp is in it. Every hash is re-derived from the raw files when the set is written
*and* when it is verified
([ADR 0019](docs/adr/0019-result-sets-have-independent-immutable-identity.md)).

### The receipt

One file from the run is meant to leave the workspace and enter version control:

```
results/<run_id>/research-receipt.json          in the workspace
evidence/sourceafis-native-full/<run_id>.json   committed
```

It is defined by what it must not contain. No score, no subject id, no image id, no
filename, no dataset path, no workspace path, no template, no minutiae, no absolute path
to anything — enforced mechanically over the rendered document, not by care. What it does
contain is identifiers, fingerprints and counts: the commit, the cohort, the pair manifest
hash, the run, the plan, the environment, the runtime bundle, the jar digest, the result
set, the audit, the validation, the completion, and the failure counts by code.

And a sentence it states verbatim:

> This receipt proves execution completeness and provenance. It contains no biometric
> performance conclusion.

## Decisions

Stage 5A applies a threshold to those 6,000 stored scores. It changes nothing about them:
`raw/jobs/` and `result-set/` are read, hashed and left alone, and everything the stage
produces lands in a new `decisions/` subtree beneath the run.

### The threshold, and where it came from

```
configs/decisions/sourceafis_java_3_18_1_documented_40_v1.yaml
```

SourceAFIS documents a recommended threshold of 40. That is a number *its authors*
published about *their* evaluation, and the profile says so in a field that reaches its
own fingerprint:

```yaml
profile:  { origin: documented_native }
rule:     { comparator: greater_than_or_equal, threshold: "40" }
calibration: { performed: false, test_cohort_used: false }
```

Presenting it as a calibrated threshold would change `origin`, which changes the
fingerprint, which changes every decision derived under it. A profile whose config claims
`test_cohort_used: true` is refused outright — choosing a threshold on the same 50
subjects it is reported over is the one form of leakage that would invalidate everything.

The threshold is a **canonical decimal string**, not a float: `"40"`, `"40.0"` and
`"4e1"` all normalise to `"40"`, and the comparison is done in `Decimal`. **A score of
exactly 40 is a MATCH.** No epsilon, no rounding, no clipping
([ADR 0021](docs/adr/0021-decision-profiles-are-immutable-and-external.md)).

### A failure is still not a non-match

```
SUCCESS + score  → DECIDED,     decision = match | non_match
FAILURE          → UNDECIDABLE, decision = null, failure code preserved
```

There is no `NO_MATCH_DUE_TO_FAILURE` and there will not be one. For the current SD300
run the second branch is unused — all 6,000 comparisons scored — and the code supports it
because the next run may not.

### prepare / derive / status / finalize

```bash
python -m fpbench.experiments.sourceafis_native_decisions prepare
python -m fpbench.experiments.sourceafis_native_decisions derive
python -m fpbench.experiments.sourceafis_native_decisions status
python -m fpbench.experiments.sourceafis_native_decisions finalize
```

`prepare` refuses a dirty tree, a source run that is not `RESEARCH_READY`, or a profile
that does not describe this exact algorithm build. Its immutable definition records the
complete software provenance (commit, Python, package, PyArrow and PyYAML versions), not
only a commit label. `derive` produces the decisions, the eligibility set and the three
views, and can be repeated. `finalize` requires that stored definition to match the
current clean environment, then re-verifies the whole chain from the raw scores upward
and only then writes the receipt and the marker.

The status chain mirrors the run's:

```
RESEARCH_READY raw run
        ↓
NOT_PREPARED → PROFILE_READY → DECISIONS_READY → ELIGIBILITY_READY → VIEWS_READY → DECISION_READY
                                                                                 ↘ INVALID
```

`DECISION_READY` is recomputed from the files every time it is asked for: every decision
re-derived from its raw score, every verdict from its two SELF decisions, every inclusion
flag from its verdict, and every view row matched exactly to the execution plan in order.
The definition, decision set, receipt and finalization marker must all name the same
source commit. **`DECISION_READY` ≠ performance evaluated.**

### SELF eligibility

1,500 units — one per (release, subject, anatomical finger), 500 per release. A unit is
eligible only when *both* its SELF comparisons matched under this profile. A SELF
comparison that produced no score makes the unit `UNDETERMINED` rather than
`INELIGIBLE`, because "we could not tell" is not "it failed"
([docs/evaluation/self-eligibility.md](docs/evaluation/self-eligibility.md)).

Eligibility is stored *beneath the decision set*, because the same finger can change
status when the threshold does.

### Three views, no metrics

| View | Rows | Included |
|---|---|---|
| `plain_roll_mated_unconditional_v1` | 1,500 | all |
| `plain_roll_mated_both_self_match_v1` | 1,500 | where the finger passed both SELF tests |
| `plain_roll_non_mated_same_subject_cyclic_v1` | 1,500 | all — no SELF filter |

The conditional view **keeps its excluded rows**, each with the reason
(`self_ineligible` or `self_undetermined`) and the eligibility unit that caused it.
Dropping them would make the inclusion rule unauditable
([ADR 0024](docs/adr/0024-conditional-mated-evaluation-requires-both-self-matches.md)).

The impostor view records what it is — closed set, same subject, cyclic shift 1 — and
what it is not: `primary_fmr_estimate: false`. A view or policy name containing `fmr`,
`fnmr`, `eer` or `accuracy` is refused by the code, because a name outlives its caveat
([ADR 0025](docs/adr/0025-same-subject-different-finger-is-a-sanity-check.md)).

### What the decisions do not entitle us to say

Nothing about accuracy. Not FMR, not FNMR, not EER, not a best threshold, not a count of
matches or false matches, not which resolution "won".

The reason is not that scores are missing, or even that decisions are. It is that the
definitions that would make such a number honest did not exist yet: how a failed
comparison is counted, whether an `UNDETERMINED` unit is excluded or imputed, and what the
denominator of a conditional report is. Stage 5B supplies exactly those, and no more
([ADR 0003](docs/adr/0003-decision-outside-adapter.md)).

The derivation receipt says the same thing in its own text, and carries no outcome count
of any kind — not how many matched, not how many fingers were eligible, not how many rows
the conditional view included:

> This receipt proves deterministic decision and eligibility derivation. It contains no
> biometric performance metric or conclusion.

## Evaluation

Stage 5B counts those decisions. It changes nothing about them: `decisions/` is read and
verified, and everything the stage produces lands in a new `evaluations/` subtree beside
it. **It applies no threshold and tries no alternative** — 40 was fixed in 5A, and there
is no code path here that could change it.

### One refusal, four rules

No rate is published without the two integers it was computed from, and no denominator is
passed between functions. A metric names one member of a closed enum
(`ALL_ATTEMPTS`, `DECIDED_ATTEMPTS`, `ALL_ELIGIBILITY_UNITS`,
`INCLUDED_CONDITIONAL_ATTEMPTS`, `DECIDED_CONDITIONAL_ATTEMPTS`), and both the deriver and
the verifier resolve it against the stored counts. A stored `3/487` is checked by
re-resolving `DECIDED_ATTEMPTS`, not by confirming that 3 ≤ 487
([ADR 0026](docs/adr/0026-metrics-name-their-denominators.md)).

| Rule | ADR |
|---|---|
| Every rate stores and names its numerator and denominator | [0026](docs/adr/0026-metrics-name-their-denominators.md) |
| Decision-conditional and attempt-level rates stay separate metrics | [0027](docs/adr/0027-attempt-and-decided-rates-are-separate.md) |
| Pooled values sum counts and divide once | [0028](docs/adr/0028-pooled-metrics-sum-counts.md) |
| A conditional result is published only with its selection fraction | [0029](docs/adr/0029-conditional-results-must-report-selection.md) |
| The cyclic negative fraction is observed, never a false-match rate | [0030](docs/adr/0030-negative-sanity-is-not-general-fmr.md) |

The metric policy lives in
[`configs/metrics/plain_roll_biometric_metrics_v1.yaml`](configs/metrics/plain_roll_biometric_metrics_v1.yaml)
and **selects** metrics from a catalogue fixed in code. It cannot define one, and an
unrecognised switch is an error rather than a shrug. Four settings are refusals rather
than options: labelling the sanity set as an FMR, dropping the conditional exclusion
counts, averaging release percentages, and weighting by subject.

### prepare / derive / status / finalize / show

```bash
python -m fpbench.experiments.sourceafis_native_evaluation prepare
python -m fpbench.experiments.sourceafis_native_evaluation derive
python -m fpbench.experiments.sourceafis_native_evaluation status
python -m fpbench.experiments.sourceafis_native_evaluation finalize
python -m fpbench.experiments.sourceafis_native_evaluation show
```

`show` prints the verified report and refuses anything that is not `EVALUATION_READY`.
There is no partial view: a report over an unverified chain is a table of numbers with
nothing behind it.

The full status chain, from raw scores to publishable result:

```
RESEARCH_READY
    ↓
DECISION_READY
    ↓
POLICY_READY → COUNTS_READY → METRICS_READY → REPORT_READY → EVALUATION_READY
                                                           ↘ INVALID
```

`EVALUATION_READY` means the defined metrics are reproducible: every count re-derived from
the decisions and the views, every denominator re-resolved from its enum, every pooled
value checked against the sum of its releases, the definition and manifest linked field by
field to the actual source chain, and both the summary and report rebuilt canonically from
that chain before the finalization marker is accepted. JSON-backed counts and ordinals are
exact integers: floats, strings, booleans and nulls are rejected rather than coerced.
**It does not mean the threshold was calibrated or that the benchmark estimates
population-wide false-match performance.**

### The first result

Metric set `metricset_f6ffa71f3880`, over the 6,000 SourceAFIS decisions at native
resolution under documented threshold 40. All 6,000 comparisons produced a score, so every
decided rate equals its attempt-level counterpart — and they are still reported as two
metrics, because the day one comparison fails they stop being equal.

| Population | Pooled |
|---|---|
| PLAIN SELF match rate | 1468/1500 (97.8667%) |
| ROLL SELF match rate | 1500/1500 (100.0000%) |
| SELF eligibility | 1468/1500 (97.8667%), 32 ineligible, 0 undetermined |
| Mated decision FNMR, unconditional | 492/1500 (32.8000%) |
| Mated decision FNMR, SELF-conditional | 460/1468 (31.3351%), selection 1468/1500 |
| Same-subject different-finger sanity | 2/1500 observed matches |

Read [docs/reports/sourceafis-native-first-evaluation.md](docs/reports/sourceafis-native-first-evaluation.md)
before quoting any of these. In particular: the mated non-match fraction is a result about
threshold 40 rather than about SourceAFIS, the conditional figure covers a different
population rather than an improved one, and the sanity fraction is not a false-match rate.

The evaluation receipt is the first artefact in this project permitted to carry outcomes,
and it carries them as integer pairs — never percentages — per release and pooled. It
still carries no score, no subject, no finger, no image, no pair, no job, no path, and no
breakdown finer than a release.

## The shared canonical 500 ppi input set

SD300 arrives at three resolutions. The next question is what happens when every
algorithm sees the same one — and answering it honestly means deciding, in writing,
*whose* downsampler produces the pixels.

The answer is: nobody's, in particular. Canonical resampling is an experiment-wide
imaging operation in `fpbench.imaging`, performed once before any run, producing an
immutable set every algorithm receives unchanged
([ADR 0031](docs/adr/0031-canonical-resampling-is-shared-before-adapters.md)). An
adapter may not resample, pick a filter, change dimensions, sharpen afterwards or reach
back to the higher-resolution original.

| Release | Effective ppi | Scale | Action |
| --- | --- | --- | --- |
| SD300A | 500 | 1/1 | `identity_pixels_reencode` |
| SD300B | 1000 | 1/2 | `downsample_2x_lanczos3` |
| SD300C | 2000 | 1/4 | `downsample_4x_lanczos3` |

Four things about that table are load-bearing.

**SD300C uses 2000, not the 5080 its header declares.** Scaling by 500/5080 would shrink
half of one release by a further factor of 2.54. The scale comes from
`ImageRecord.effective_ppi` and nowhere else
([ADR 0032](docs/adr/0032-effective-ppi-controls-canonical-geometry.md)).

**SD300C goes 2000 → 500 in one resampling.** Not 2000 → 1000 → 500: two Lanczos passes
are a different filter from one, and the golden fixtures prove they disagree.

**SD300A is decoded and re-encoded but never resized,** and its raster is preserved byte
for byte. Copying the delivered file would be faster and would leave one release carrying
NIST's PNG encoding while the others carried ours.

**Rounding is half-up, in integers.** Python's `round()` breaks ties to even, so a
1001-pixel axis at 1000 ppi would come out 500 instead of 501.

Each artefact keeps two identities — the raster's and the file's — because "same pixels"
and "same file" are different questions
([ADR 0034](docs/adr/0034-pixel-and-encoded-identities-are-separate.md)). The resampler
itself is pinned by the bytes of the installed distribution, not by its version string,
and that pin is part of the set's identity.

### PREPARATION_READY

```
python -m fpbench.experiments.sd300_canonical500_images prepare
python -m fpbench.experiments.sd300_canonical500_images materialize --max-new-images 500
python -m fpbench.experiments.sd300_canonical500_images status
python -m fpbench.experiments.sd300_canonical500_images finalize
```

```
NOT_PREPARED → PROFILE_READY → PARTIAL → IMAGES_COMPLETE → VERIFIED → PREPARATION_READY
```

`INVALID` is off that ladder rather than at the bottom of it: it means two artefacts
contradict each other, and materialising more images never fixes it. A materialisation
resumes only under the same definition, the same transform runtime and the same source
commit; a Pillow upgrade half way through voids the set rather than being absorbed by it
([ADR 0033](docs/adr/0033-prepared-image-sets-are-immutable-reusable-evidence.md)).

Details: [docs/imaging/canonical-500-profile.md](docs/imaging/canonical-500-profile.md)
and [docs/imaging/prepared-image-sets.md](docs/imaging/prepared-image-sets.md).

### The canonical run

```
python -m fpbench.experiments.sourceafis_canonical500_full prepare
python -m fpbench.experiments.sourceafis_canonical500_full execute --max-new-jobs 500
python -m fpbench.experiments.sourceafis_canonical500_full status
python -m fpbench.experiments.sourceafis_canonical500_full finalize
```

Same cohort, same 6,000 pairs in the same order, same SourceAFIS 3.18.1, same unchanged
adapter and bridge, same timeout, sequential, no retries — and the same orchestration
code, shared with the native run so that the difference between them cannot be anything
except the preparer. The algorithm's identity does not move; the execution profile, the
preparation set and therefore the run fingerprint do.

Every stored result names the input set, both entry hashes, both file digests, both
raster digests and both output dimensions, and the validator checks each against the
set's actual entries rather than against another copy of the same claim.

A SELF comparison reuses one immutable artefact on both sides and still performs two
independent template extractions: independence is a property of extraction, not of
resampling
([ADR 0035](docs/adr/0035-self-reuses-prepared-pixels-but-not-template-extraction.md)).

**No threshold, no decision, no metric, no native score read, no conclusion about
resolution.** Reaching `RESEARCH_READY` here means 6,000 scores exist and can be
attributed to inputs whose identity is provable. Details:
[docs/experiments/sourceafis-canonical500-full.md](docs/experiments/sourceafis-canonical500-full.md).

## Architecture note: where the models live

Several containers sit in `core` rather than in the package that derives them:
`RunDefinition` and `ComparisonJob` (with `ExecutionPlan` and the run-state
records), and since stage 4B also `SoftwareProvenance`, `RuntimeBundleDefinition`,
`RunRuntimeReference`, `ResultSetManifest` and `ResearchRunReceipt`. The reason is
the dependency rule — `storage` must persist them and is only allowed to import
`core` — and the split is consistent: the *data* lives in `core`, the *rules for
deriving it* live in the package that owns them, and that package re-exports the
container so callers import model and factory from one place.

`fpbench.experiments` is the one package allowed to know both what an experiment is
and what an algorithm is. That is what makes it possible for
[ADR 0007](docs/adr/0007-no-algorithm-branching-in-runner.md) to keep holding
everywhere else: "run SourceAFIS over SD300 at native resolution" is a sentence about
one experiment, and it needs somewhere to live that is not the planner.

## Next stage

1. metrics over the three views — FMR, FNMR and the conditional PLAIN–ROLL report — with
   the one thing that makes them honest written down first: what happens to a failed
   comparison and to an `UNDETERMINED` finger in each denominator;
2. a development cohort and a calibration manifest, so that a *calibrated* threshold
   becomes possible without touching the 50 test subjects
   ([ADR 0021](docs/adr/0021-decision-profiles-are-immutable-and-external.md));
3. failure analysis over the algorithmic failure codes the run recorded;
4. stage 6B: decisions and a *paired* evaluation over the canonical run, joined to the
   native one by `pair_id` — including whether SD300A's provably identical pixels
   produced identical scores, which stage 6A deliberately did not ask;
5. NBIS as the second algorithm — `nbis_mindtct_bozorth3`, both halves named — which is
   the real test of whether the adapter contract holds, and the second consumer of the
   runtime-bundle mechanism;
6. the persistent-JVM decision, on the strength of the full run's operational summary
   rather than a guess ([ADR 0015](docs/adr/0015-sourceafis-uses-stateless-java-bridge.md));
7. a better negative set, if a real false-match rate is ever wanted: cross-subject, and
   either exhaustive or a stated sample
   ([ADR 0025](docs/adr/0025-same-subject-different-finger-is-a-sanity-check.md));
8. parallel execution, a retry policy keyed to the failure taxonomy, and a CLI over all
   of it.
