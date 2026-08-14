# fpbench — fingerprint recognition benchmark harness

A reproducible harness for comparing fingerprint recognition algorithms on NIST
Special Database 300 (releases A/500 ppi, B/1000 ppi, C/2000 ppi).

The organising principle:

> The harness owns the experiment. An algorithm never decides what runs, and
> infrastructure never changes an algorithm without saying so in writing.

---

## Purpose and third-party components

fpbench is a **personal educational research project**. It is not a product, not
a service, and not an academic submission.

Third-party algorithms, model weights, datasets and runtimes remain subject to
their upstream terms. This repository records those terms faithfully and
separately from its own decision to run something locally, and it does not
redistribute third-party model weights, datasets or upstream runtime bundles —
whatever their licences permit.

The policy: [purpose](docs/policy/research-only-purpose.md) ·
[third-party usage](docs/policy/third-party-usage.md) ·
[artifact handling](docs/policy/third-party-artifact-handling.md).

*This is not a licence.* No `LICENSE` file is present, so default copyright
applies to this repository's own code
([ADR 0081](docs/adr/0081-fpbench-is-personal-educational-research-only.md)).

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

Phase 6B carried the **documented threshold across unchanged** to the canonical run and
counted it, then answered the question 6A deliberately refused to ask. SD300A's provably
identical pixels did produce identical scores: all 2,000 of its comparisons reproduced
exactly, with no rounding tolerance anywhere.

Phase 7A made **room for a second algorithm**: the research orchestration became
algorithm-agnostic, the shared adapter tools arrived, and a synthetic two-stage route
proved the contract holds for an extract-then-match pipeline — all without producing a
single number.

Phase 7B integrated the **second algorithm**: NIST NBIS 5.0.0, MINDTCT into BOZORTH3,
as one identity. The source is pinned to NIST's own two archives by digest, built from
them with no behavioural patch, and certified against NIST's own reference output —
which it reproduces byte for byte. It also produced no biometric number: the 6,000
comparisons are stage 7C's.

Phase 7C ran **those 6,000 comparisons under NBIS** — the same pair ids, in the same
order, over the same canonical 500 ppi images, proved row by row rather than assumed —
and published the raw scores and the failure codes: 6,000 scored, no algorithmic failure
and no blocking failure. No threshold, no decision, no metric, no paired comparison, and
no SourceAFIS score was read.

Phase 7D **decided those scores and compared the two algorithms**, at two thresholds
neither of which this project chose. NIST's documented `> 40` for NBIS, SourceAFIS's
documented `>= 40` unchanged, a methodology frozen and committed before the first
decision existed, and one engine deriving both chains so that a difference between the
two sets of numbers cannot be a difference in how they were derived. The comparison
records paired decisions and no scores: the two numbers are on two scales, and every
sentence a reader might infer from a table — equal FMR, superiority, significance — is
refused in the receipt and in the report, verbatim.

```
VERIFIED SOURCE IMAGES
        ↓
PREPARATION_READY canonical image set
        ↓
RESEARCH_READY canonical raw run
        ↓
DECISIONS_READY canonical decisions ──┐
        ↓                             │
EVALUATION_READY canonical metrics    │
                                      ↓
        PAIRED_EVALUATION_READY native vs canonical
```

`canonical_500` is a shared **input profile**, not an algorithm feature. Both chains run
the same derivation engines, parameterised by data rather than branched on: one decision
engine, one evaluation engine, two thin wrappers. That is what makes a difference between
the two sets of numbers attributable to the images rather than to how they were counted.

The paired comparison is a **third artefact** with its own identity, not a section of
either report ([ADR 0036](docs/adr/0036-paired-comparison-is-a-third-artefact.md)). It
reports transitions and exact rate differences, and refuses to subtract two rates whose
denominators cover different rows — enforced by the model, which will not construct an
observation carrying an illegitimate difference
([ADR 0038](docs/adr/0038-conditional-rates-over-different-populations-are-not-subtracted.md)).

Still no EER, no ROC, no calibrated threshold, no confidence interval, no significance
test, and no general FMR — the closed-set same-subject negative fraction is published as a
sanity check and is not one. And still no claim that any resolution is better than any
other: the canonical path changes the whole preparation pipeline, not only the resolution.

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
| `fpbench.paired` | built | alignment, the SD300A control, transitions, exact rate differences |
| `fpbench.experiments` | built (eight) | two full runs, the canonical image set, decisions and counts over each run, and the paired comparison — the two chains sharing one decision engine and one evaluation engine |
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

`status` and `finalize` re-run the pinned transform for all 3,000 sources by default.
Finalization persists a fingerprinted transform audit and binds it into the receipt and
marker. The check also binds the definition and manifest to the authoritative dataset,
protocol, cohort, pair manifest and exact ordered source list, so a self-consistent
rewrite of prepared artefacts cannot pass by merely recomputing their hashes.

Audit provenance is independent of pixel-production provenance. The verifier's clean
commit and content-addressed Pillow/Python/zlib transform runtime are captured before
and after the full audit and bound into the public receipt and finalization marker. A
future verifier may re-check the semantic audit under newer code without rewriting who
issued the historical evidence.

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

The canonical research receipt also names the preparation set, transform profile and
transform runtime. Status re-derives those identities from the execution profile and
the verified prepared manifest; a broken preparation preflight is reported as
`INVALID`, not as a command crash.

A SELF comparison reuses one immutable artefact on both sides and still performs two
independent template extractions: independence is a property of extraction, not of
resampling
([ADR 0035](docs/adr/0035-self-reuses-prepared-pixels-but-not-template-extraction.md)).

**No threshold, no decision, no metric, no native score read, no conclusion about
resolution.** Reaching `RESEARCH_READY` here means 6,000 scores exist and can be
attributed to inputs whose identity is provable. Details:
[docs/experiments/sourceafis-canonical500-full.md](docs/experiments/sourceafis-canonical500-full.md).

## Stage 6B: canonical decisions, canonical counts, and the paired comparison

Three artefacts, derived in that order, each with its own identity.

```bash
python -m fpbench.experiments.sourceafis_canonical500_decisions prepare
python -m fpbench.experiments.sourceafis_canonical500_decisions derive
python -m fpbench.experiments.sourceafis_canonical500_decisions finalize
```
```bash
python -m fpbench.experiments.sourceafis_canonical500_evaluation prepare
python -m fpbench.experiments.sourceafis_canonical500_evaluation derive
python -m fpbench.experiments.sourceafis_canonical500_evaluation finalize
```
```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 prepare
python -m fpbench.experiments.sourceafis_native_vs_canonical500 derive
python -m fpbench.experiments.sourceafis_native_vs_canonical500 finalize
```

The threshold is SourceAFIS's documented 40, **transferred unchanged**. The canonical
decision profile records where it came from, that it was not re-chosen, and that nothing
was calibrated — and that transfer block is inside the profile fingerprint, so a profile
that started claiming a calibration would be a different profile
([ADR 0037](docs/adr/0037-the-threshold-transfers-unchanged.md)). It is not a recommended
canonical threshold, not adapted to 500 ppi input, and not validated on SD300.

Both chains run one decision engine and one evaluation engine. Neither wrapper imports
the other, neither performs any derivation of its own, and a structural test enforces
both. The native identities did not move across the extraction: `run_7ac1cecc0bb3`,
`resultset_2bf3cacfd806`, `decisionset_0122544e71b1`, `eligibilityset_77dbf75cdc76` and
`metricset_f6ffa71f3880` are the same ids they were before stage 6B existed.

The paired comparison joins the two chains on `pair_id` only — never on a job id, never
on a score, never on a reconstructed key. The **SD300A exact control** is a hard
acceptance condition: SD300A arrives at 500 ppi, so its canonical preparation is an
identity, and all 2,000 of its comparisons must reproduce exactly. One mismatch aborts
the derivation before any aggregate is written.

It held. `pairedeval_ee2e0fe7ddb6` records 2,000 of 2,000 equal scores, equal result
statuses and equal decisions, with no rounding tolerance anywhere — which is the question
stage 6A proved the pixels for and deliberately did not ask.

Two mated FNMRs are published, and the difference between them is the point. The
common-eligible one is conditioned on the 1,468 units both runs found eligible and is
subtractable. The per-run conditional one is conditioned on each run's own eligible set —
1,468 against 1,472 — and prints `not comparable`, because subtracting two rates over
different populations produces a number that describes nothing.

**No ROC, no EER, no significance test, no confidence interval, no general FMR, no
resolution-superiority claim and no causal claim.** Details:
[docs/experiments/sourceafis-native-vs-canonical500.md](docs/experiments/sourceafis-native-vs-canonical500.md).

## Stage 7A: making room for the second algorithm

Nothing in stage 7A produced a number. No run, no result set, no decision set, no
metric set, no paired comparison — the deliverables are code, tests, ADRs and
documentation, and the two finished runs are byte for byte where stage 6B left
them.

What it changed is what adding NBIS will cost. Before it, driving an algorithm
through the research chain meant a module that imported that algorithm; after it,
the orchestration lives in `fpbench.experiments.algorithm_research`, which
imports none and branches on none, and everything algorithm-specific arrives
through one injected record
([ADR 0040](docs/adr/0040-research-orchestration-is-injected-not-algorithm-specific.md)):

```python
ResearchAdapterIntegration(
    integration_id, adapter_id,
    runtime_asset_roles, primary_runtime_asset_role,
    create_development_runtime,   # build from a local build tree
    create_research_delegate,     # build again, pinned to the bundle
    validate_result_set,          # which failures are biometric, which are defects
)
```

`sourceafis_research.py` is now the wrapper: it assembles that record, keeps its
stage 4B names as aliases, and forwards. It materialises nothing, executes
nothing and builds no receipt — checked structurally, by imports and calls,
rather than by counting lines.

**The contract did not move.** `ADAPTER_CONTRACT_VERSION` is still `"1"`, the
mandatory surface is still `descriptor`, `validate_environment` and `compare`,
and a route made of an extractor and a matcher is wrapped as one adapter with the
stages private to it
([ADR 0039](docs/adr/0039-adapter-contract-v1-remains-image-to-score.md)). There
is no `TemplateStore` and no template cache, because there is not yet a second
real algorithm to derive one from
([ADR 0041](docs/adr/0041-intermediate-templates-remain-adapter-local.md)).

That claim is demonstrated rather than asserted. A synthetic two-stage adapter —
deliberately not registered, and not biometric — runs a separate extractor per
side and a separate matcher over the two templates, maps every way a two-process
pipeline fails, and reaches `RESEARCH_READY` through the unmodified
`SingleJobRunner` and the unmodified engine
([ADR 0043](docs/adr/0043-two-stage-synthetic-adapter-proves-extensibility.md)).
Runtime bundles now carry every tool that could change a score, and a rebuild of
any one of them is drift
([ADR 0042](docs/adr/0042-runtime-bundles-support-multi-tool-pipelines.md)).
New receipts and finalization markers are algorithm-neutral and bind the exact
research integration into the environment and run identity, while the published
SourceAFIS schemas remain readable without changing their identities
([ADR 0044](docs/adr/0044-research-evidence-is-algorithm-neutral-and-integration-bound.md)).

Four shared tools mean a new adapter reimplements none of this:

| tool | what it takes off an adapter author |
|---|---|
| `AdapterJobWorkspace` | non-following containment, owned artefacts, meaningless file names |
| `ExternalCommand` | no shell, absolute executable, bounded output, whole-tree timeout termination |
| `runtime_guard` | every pinned tool watched, by role |
| `config_values` | strict YAML: `research_mode: "false"` is refused, not reinterpreted |

The recipe is in
[docs/architecture/adding-an-algorithm.md](docs/architecture/adding-an-algorithm.md);
the checks a new adapter must pass are in
[docs/architecture/adapter-conformance.md](docs/architecture/adapter-conformance.md);
the seam itself is in
[docs/architecture/research-adapter-integration.md](docs/architecture/research-adapter-integration.md).

## Stage 7B: NBIS, and what it cost

Stage 7B produced no number either. No SD300 run, no result set, no decision set,
no metric set, no paired comparison — the deliverables are a source lock, a build
chain, an adapter, a validator, an integration, tests, five ADRs and three
documents. All seven existing artefacts are byte for byte where 6B left them, and
a regression test says so.

What it proves is that stage 7A's claim was true. Adding NBIS meant writing:

```
integrations/nbis/          lock, build, verify, patch series (empty), README
adapters/nbis/              config, PNG contract, XYT parser, score parser,
                            failure mapping, build manifest, adapter
experiments/nbis_validation.py     which failures are data, which are defects
experiments/nbis_research.py       four forwards and one integration record
configs/algorithms/…​.yaml          the identity, written down
```

and **nothing** in `execution`, `storage`, `core`, `imaging`, `decisions`,
`eligibility`, `metrics` or `paired`. `ADAPTER_CONTRACT_VERSION` is still `"1"`,
`RESULT_SCHEMA_VERSION` is still `"1"`, and `SingleJobRunner.__init__` takes the
same eight parameters it took before.

**The identity is the whole route.** `nbis_mindtct_bozorth3`, not `bozorth3`:
MINDTCT makes almost every decision that could move a score, and a descriptor
named after the matcher would let two runs against different extractor builds
share an identity
([ADR 0046](docs/adr/0046-nbis-route-is-mindtct-plus-bozorth3.md)). The runtime
bundle carries three files — both executables and the build manifest — because
all three decide what a score is.

**Two things were measured rather than assumed.** The certified build accepts an
8-bit greyscale PNG directly, so the prepared artefact is copied byte for byte
with no WSQ, no PGM and no re-encoding
([ADR 0048](docs/adr/0048-nbis-input-is-direct-gray8-png.md)). And three images
with identical pixels and different `pHYs` chunks extract to identical XYT, so the
declared resolution is ignored and NBIS's 500 ppi default applies — which is why
this route runs on the canonical 500 ppi set only, and why the stage stops
outright if that measurement ever comes out differently
([ADR 0047](docs/adr/0047-nbis-v1-runs-only-on-canonical-500ppi.md)).

**No tool option is configurable.** MINDTCT runs with no flags and BOZORTH3 with
none at all, so its documented defaults of 150 maximum and 10 minimum minutiae
apply — and those defaults are recorded in the identity rather than passed on a
command line. `bozorth3 -T` in particular is refused outright: it filters which
scores are printed, so a run under it is not a raw-score run
([ADR 0049](docs/adr/0049-nbis-default-tool-options-are-part-of-identity.md)).
A score of 0 is an ordinary success, including for a template with no minutiae at
all.

**Nothing survives a comparison.** Two staged inputs, two XYT files and fourteen
map files are removed in a `finally` on every path out; there is no template
cache, no template store and no published XYT
([ADR 0050](docs/adr/0050-nbis-templates-remain-ephemeral.md)).

The build chain is deliberately five commands, because obtaining a source,
verifying it, compiling it and certifying it fail for different reasons:

```bash
python integrations/nbis/build.py seal --release … --tests …   # once, by a person
python integrations/nbis/build.py fetch                        # verified or nothing
python integrations/nbis/build.py build                        # no network at all
python integrations/nbis/build.py test                         # NIST's own suite
python integrations/nbis/verify_build.py build/nbis-5.0.0/…    # after every cache restore
```

The lock is **sealed** to the two archives NIST publishes at `nigos.nist.gov`, by
digests computed from their bytes rather than copied from a page. Until a lock is
sealed no NBIS research run can be prepared at all, and that is tested.

**The certification found three things worth knowing**, two of which contradicted
what this project expected:

*MINDTCT and BOZORTH3 reproduce NIST's own reference output exactly.* Golden
`.xyt`, `.min` and five map files per image, across all ten of NIST's test images;
golden score logs for all seven BOZORTH3 invocations. Byte for byte, with one
named exception: the ANSI/NIST capture date MINDTCT stamps with today's date.

*The declared resolution really is ignored.* Three PNGs with identical pixels and
`pHYs` chunks saying 500, 1000 and nothing extract to identical XYT — so the
500-ppi-only route rests on a measurement rather than on an expectation
([ADR 0047](docs/adr/0047-nbis-v1-runs-only-on-canonical-500ppi.md)).

*The build accepts 16-bit and indexed-colour PNGs.* NBIS hands PNG to libpng,
which down-converts both. The build script had been written to refuse a build for
that — an assumption enforced as a rule — and the rule was corrected rather than
the measurement. What the build tolerates is now recorded in its manifest; what
keeps the route safe is the adapter, which refuses anything that is not 8-bit
greyscale before a subprocess exists, and which is tested from both sides
([ADR 0048](docs/adr/0048-nbis-input-is-direct-gray8-png.md)).

Details:
[docs/algorithms/nbis-mindtct-bozorth3.md](docs/algorithms/nbis-mindtct-bozorth3.md),
[docs/architecture/nbis-input-and-ppi-policy.md](docs/architecture/nbis-input-and-ppi-policy.md),
[docs/architecture/nbis-build-provenance.md](docs/architecture/nbis-build-provenance.md).

## Stage 7C: the same 6,000 comparisons, under the second algorithm

Stage 7C runs the certified NBIS route over the comparisons SourceAFIS already ran, and
publishes raw scores and failure codes — nothing that interprets them.

The claim it has to make good on is a claim about *inputs*: the same 6,000 pairs, in the
same order, over the same 3,000 prepared 500 ppi PNGs. Nothing about a run's identity says
so on its own. Two runs can share a `pair_manifest_hash` and still have been planned from
different rows; two runs can quote the same `preparation_set_id` and still have opened
different bytes. So it is proved rather than asserted, record by record, by
`CanonicalRunAlignmentReport`:

* the two ordered pair-id sequences, position by position;
* every pair's release, stage, ground truth, left image and right image;
* every prepared image's source digest, encoded digest, pixel digest, output width,
  height and resolution, transform action and entry fingerprint.

Comparing counts would prove nothing at all, and an alignment of 5,999 of 6,000 is a
failure rather than a near miss — the one row that differs is the row whose two results
cannot be attributed to one comparison. The check runs three times: before the run is
created, again against the plan the engine then builds, and again at finalization against
the copy preparation stored
([ADR 0051](docs/adr/0051-nbis-full-run-reuses-sourceafis-canonical-pairs.md)).

Stage 7C selects nothing. It calls neither `build_cohort` nor `build_pairs`, loads the
manifests with `allow_creation=False`, materialises no image, and pins one named certified
build — `658f9f54a8f2` — passed explicitly, with no "newest", no lexicographic first, no
environment variable and no fallback to the gcc-9 build stage 7B certified
([ADR 0053](docs/adr/0053-stage-7c-pins-one-certified-nbis-build.md)). The execution
profile is not restated: it is `canonical_500_lanczos3_60s_v1`, the reference run's own
file, reused unchanged, so the two runs differ in the algorithm and in nothing else.

And it decides nothing. No `DecisionSet`, no `EligibilitySet`, no `MetricSet`, no paired
evaluation, no threshold anywhere in the configuration — `threshold`, `decision_profile`,
`match_threshold`, `acceptance_threshold` and `calibration` are refused at any depth — and
no score statistic in the operational summary. No SourceAFIS score is read at all: the
reference run is opened for its identity, its plan, its pair manifest, its prepared inputs
and its readiness. A BOZORTH3 score of 0 is a successful comparison, not a `NON_MATCH`.
SourceAFIS's documented 40 is a number about a different scale and does not transfer
([ADR 0052](docs/adr/0052-stage-7c-publishes-raw-scores-only.md)).

The orchestration is stage 7A's, untouched: `nbis_canonical500_full.py` loads two config
files, proves the alignment, and hands a spec plus the NBIS integration to
`algorithm_research`. A structural test walks its syntax tree and fails if it grows a job
loop, opens a raw result, or builds the general runtime/result/receipt chain. The wrapper
adds only the Stage 7C finalization marker that makes its alignment claim authoritative.

**The run happened.** `run_f0468f28ffba` / `plan_db1a526f2a81` /
`resultset_73a9d93a8528`, from commit `05e55f8` (published as
`stage7c-run-source`), on the certified Linux x86_64 build
`658f9f54a8f2`: 6,000 planned, 6,000 stored, **6,000 scored, zero algorithmic failures and
zero blocking failures**, 2,000 comparisons per release and 1,500 per stage. 12,000 MINDTCT
invocations and 6,000 BOZORTH3 invocations, sequential, no retries, 64 minutes of wall
clock. Median adapter time 432 ms — 45 ms staging, 84 ms and 119 ms for the two
extractions, 21 ms matching, 59 ms cleanup — and every working directory empty afterwards.

The alignment came out at 6,000/6,000 pair ids, 6,000/6,000 pair semantics and 3,000/3,000
prepared entries, with no issue, fingerprinted `d25b5215…`. The Stage 7C finalization
fingerprint is `76a678ad…`, binding the alignment to the research chain. No decision set,
no eligibility set, no metric set and no paired evaluation was produced, and no SourceAFIS
score was read ([ADR 0054](docs/adr/0054-stage-7c-alignment-is-completion-authority.md)).

Details: [docs/experiments/nbis-canonical500-raw.md](docs/experiments/nbis-canonical500-raw.md);
evidence under [evidence/nbis-canonical500-raw/](evidence/nbis-canonical500-raw/).

## Stage 7D: decisions for the second algorithm, and a comparison that concludes nothing

Stage 7C left 6,000 BOZORTH3 scores and no threshold, because where the boundary sits on
BOZORTH3's scale was a question nobody had earned the right to answer. Stage 7D answers
it with the number NIST's own guide documents, counts the result under the policy both
SourceAFIS evaluations already use, and puts the two chains side by side under a list of
things the comparison does not establish.

**The threshold is `> 40`, and the comparator is strict because the sentence is.**
SourceAFIS documents a match at a score *of at least* 40; NIST describes a BOZORTH3 score
*greater than* 40 as a rule of thumb. Making them agree on the comparator would mean
making one of them say something it does not. So `ThresholdComparator` grew `GREATER_THAN`
and `LESS_THAN`, and `DecisionProfile` grew a schema version to carry them: schema 1 stays
frozen, hashes under the mapping it always had, and a regression test pins the two
published SourceAFIS profile digests as literals
([ADR 0055](docs/adr/0055-strict-threshold-comparators-preserve-legacy-profiles.md)).

**The methodology was committed before the first decision existed.** `stage7d_fair_measurement_protocol_v1`
(`ac212d98…`) pins both chains, both profiles, the shared alignment and the three
policies. Four fields are left empty because a decision-set id is derived from the
decisions; `bind()` is the only way to fill them, it refuses every other field, and
binding does not move the fingerprint.

**Both algorithms are decided and counted by one engine.** `experiments/algorithm_decisions.py`
and `experiments/algorithm_evaluation.py` name no algorithm — not in an import, a branch
or a literal — and a structural suite walks the syntax trees rather than trusting the
docstrings. Everything algorithm-specific arrives through `DecisionSourceIntegration`,
which answers one question: is this run's evidence chain sound enough to decide? For NBIS
that answer includes stage 7C's alignment, re-derived from the manifests every time
([ADR 0056](docs/adr/0056-decision-and-evaluation-orchestration-is-algorithm-neutral.md)).

**No raw score is compared.** `fpbench.cross_algorithm` is a separate package from
`fpbench.paired`, whose schema assumes one algorithm, one threshold and a meaningful score
delta — all three false between two matchers. The models have no score field and the
comparison is a table of paired *decisions*
([ADR 0060](docs/adr/0060-cross-algorithm-comparison-never-subtracts-raw-scores.md)).

The NBIS chain came out at `decisionset_52b1ee4e6aca` / `eligibilityset_9e717ecf6a82` —
6,000 decisions, **6,000 decided, 0 undecidable** — and `metricset_614450282fdb`, 56
observations, `EVALUATION_READY`. The comparison is `algcompare_7ef9d0c9a0df`, with a
clean fairness audit: same 6,000 pair ids in the same order, same pair meanings, same
3,000 prepared images, same eligibility policy, same metric policy, same execution
profile, nothing calibrated, no test cohort used, no operating points equated, no raw
scores compared.

The primary number is the full mated population — all 1,500 attempts, the same
denominator on both sides, `NON_MATCH` and `UNDECIDABLE` both counted as non-successes.
Pooled, the observed non-success rate was **521/1500 for SourceAFIS** at its documented
`>= 40` and **595/1500 for NBIS** at NIST's documented `> 40`, a difference of exactly
**37/750**. It is not called an FNMR, and neither threshold was calibrated
([ADR 0059](docs/adr/0059-unconditional-attempt-population-is-primary.md)).

The eligibility transition matrix is where the two chains differ most: 1,472 units
eligible on both sides, 26 that SourceAFIS found ineligible and NBIS did not, 2
ineligible for both, none undetermined anywhere. So the two conditional populations are
genuinely different, and the conditional rows carry no difference at all — *different
eligible populations, difference undefined*, printed in the cell rather than replaced by
a number nobody could interpret
([ADR 0038](docs/adr/0038-conditional-rates-over-different-populations-are-not-subtracted.md)).

Both thresholds are written "40" and they are **not** the same operating point. The
comparison is named `comparison_at_independently_documented_operating_points`, the
relation is a required field of the protocol, the policy and the receipt, and every
receipt and report carries the refusal verbatim
([ADR 0058](docs/adr/0058-cross-algorithm-operating-points-are-not-equated.md)).

Details: [docs/experiments/nbis-canonical500-decisions.md](docs/experiments/nbis-canonical500-decisions.md),
[docs/experiments/nbis-canonical500-evaluation.md](docs/experiments/nbis-canonical500-evaluation.md),
[docs/experiments/sourceafis-vs-nbis-canonical500.md](docs/experiments/sourceafis-vs-nbis-canonical500.md);
evidence under [evidence/nbis-canonical500-decisions/](evidence/nbis-canonical500-decisions/),
[evidence/nbis-canonical500-evaluation/](evidence/nbis-canonical500-evaluation/) and
[evidence/sourceafis-vs-nbis-canonical500/](evidence/sourceafis-vs-nbis-canonical500/).

## Stage 8A: qualify a modern artifact, or select nothing

Stage 8A froze three candidates before inspection: an official or author-supplied
AFR-Net artifact (tier A), an official or author-supplied MGViT artifact (tier B), and
the exact public `flx` fixed-length extractor/checkpoint (tier C). id3 Finger SDK is a
reserve outside the stage and cannot become selected through fallback.

This stage examines artifacts, not biometric performance. It has no route to SD300,
the 6,000-pair plan, earlier raw results or derivations. It creates no adapter,
`ResultSet`, threshold, calibration or comparison. Every candidate instead has to pass
hard gates for scientific identity, inference code, exact weights, preprocessing,
representation, a finite raw-score API, a future decision path, independent SELF
extraction, determinism, offline operation, licensing, architecture fit and operational
feasibility. Tier and the nine frozen tie-breakers apply only after every gate passes.

**The result is `NO_MODERN_MATCHER_READY`.** AFR-Net and MGViT have identified papers
but no qualifying official executable artifacts. `flx` has separately identified source
and checkpoint bytes, including a detected two-branch 512-dimensional model, but the
checkpoint licence is not established, dependencies are unpinned, and its loaders do
not define one dataset-independent route from the canonical PNG. Static inspection
therefore stopped all fixture execution; the reports do not pretend that determinism,
capacity or SELF independence was measured.

The evidence is re-derived rather than trusted. It binds the frozen registry, separate
acquisition manifests, one report per candidate, the gate-first selection and exact
publication bytes. Missing or edited evidence fails closed, while model weights,
biometric fixtures, embeddings and observed scores remain unpublished.

Details: [the Stage 8A evidence report](evidence/stage8a-modern-matcher-selection/README.md)
and [ADRs 0061–0066](docs/adr/README.md). Verify it with:

```bash
python -m fpbench.experiments.stage8a_modern_matcher_selection verify
```

## Stage 8B: make one artifact runnable, and prove it

Stage 8A rejected `flx` as `LICENSE_BLOCKED`, on gates that included an unpinned
runtime, a dataset-dependent input route and an unexecuted score. Stage 8B builds
exactly what was missing, under an explicit instruction from the project owner to
run the checkpoint locally — which is not a licence finding, and the evidence keeps
saying `weights_license_status: unresolved` (ADR 0068).

Outcome: **`FLX_RAW_SCORE_EXECUTION_READY`**. All fifteen gates passed.

```text
canonical gray8 PNG → deterministic transform → 256+256 representation → raw Decimal score
```

The runtime is a bundle outside the repository, pinned by bytes: thirteen wheels by
version, size, SHA-256 and index, installed with `--require-hashes --no-index` into
a venv created `--without-pip`, so "the installed runtime is the lock" is checkable
rather than checkable-with-exceptions. Torch is imported in one isolated worker
process and nowhere else; the checkpoint is treated as untrusted input and loaded
with `weights_only=True` into a model built from pinned source, strictly.

Determinism holds at tolerance zero — repeated extraction, repeated comparison,
input order, five legal ADR 0070 batch contexts in both branches, and a process
restart, all bitwise. An out-of-contract batch-size-three diagnostic showed small
float32 shape drift and is documented without widening the route's tolerance.
The operational limits were frozen before the authoritative
Stage 8B qualification probe and before the published measurements. A preliminary
generated-fixture timing read no SD300 data and was not used to tune a limit from
a biometric result.

Three things had to be measured rather than assumed, and each is in an ADR: the
pinned texture branch has no batch-of-one path, a SELF score is `2 + 2**-23` rather
than 2, and an all-white image does not resize to a constant.

Details: [the Stage 8B evidence report](evidence/stage8b-flx-runtime-qualification/README.md)
and [ADRs 0067–0073](docs/adr/README.md). Verify it — with no torch and no weights —
with:

```bash
python -m fpbench.experiments.stage8b_flx_runtime_qualification verify
```

## Stage 8C: the same 6,000 comparisons, under the third algorithm

`FLX_CANONICAL500_RAW_READY`. The route Stage 8B qualified ran the canonical
SD300 experiment SourceAFIS and NBIS already ran — the same 6,000 pairs, in the
same order, over the same 3,000 immutable 500 ppi PNGs.

```
6,000 planned      6,000 stored      6,000 raw scores
0 algorithmic failures               0 blocking failures
run_902136b3b8ae / plan_b1e805736760 / resultset_d63e523e0436
```

Nothing here selects a cohort, generates a pair or writes a PNG. The pair
manifest is loaded with `allow_creation=False`, and a
`CanonicalRunAlignmentReport` compares the two runs record by record — every
field of every pair and every field of all 3,000 prepared entries, positionally
in the plan's order — rather than count against count.

The two extraction counts stay distinct, because conflating them either doubles
the number of representations the run produced or halves its measured
throughput: **12,000 logical extractions, 24,000 physical forward rows**. The
pinned texture branch cannot process a batch of one, so one extraction feeds the
identical tensor twice and represents row 0 after asserting the rows are bitwise
equal ([ADR 0070](docs/adr/0070-one-extraction-is-a-duplicated-pair.md),
[ADR 0075](docs/adr/0075-logical-extractions-and-physical-forward-rows-are-different-counts.md)).
Every one of the 6,000 results records its own counts, measured from the route,
and all 6,000 show two preprocess calls and two logical extractions — SELF pairs
included, where both sides point at one PNG and are still read, preprocessed and
extracted independently.

The score reaches the general schema as the IEEE double it already is, with its
canonical 17-significant-digit text beside it. Seventeen digits always recovers
a double exactly, so nothing is truncated and no historical result fingerprint
moved; the validator re-derives the text from the stored double for all 6,000
rows rather than trusting the adapter that wrote it
([ADR 0077](docs/adr/0077-stage-8c-finalization-binds-the-stage-8b-qualified-route.md)).

**What it does not publish**: no threshold, no decision, no eligibility, no
metric, no distribution, no summary statistic and no example score. The flx
scale has no operating point anybody has published, and one may not be chosen
from these scores — SD300 is the evaluation set, and fitting a parameter to it
makes the resulting rate an upper bound on nothing
([ADR 0076](docs/adr/0076-stage-8c-publishes-no-score-distribution-or-decision.md)).
The prohibition is enforced in three independent places: a config loader that
refuses threshold-shaped keys at any depth, an AST boundary check, and a
finalization that refuses to complete while anything derives from the run.

Details: [the Stage 8C evidence report](evidence/flx-canonical500-raw/README.md)
and [ADRs 0074–0077](docs/adr/README.md). Verify it — with no dataset, no
weights, no torch and no workspace — with:

```bash
make stage8c-evidence
```

That verification says what it verified and no more: `algorithm_executed` is
always false, and CI does not run the 6,000 comparisons.

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

## Stage 8D: build the calibration machinery, and calibrate nothing

`CALIBRATION_INFRASTRUCTURE_READY`.

Stage 8C opened Stage 8D expecting flx decisions, and closed with the sentence
that made them impossible: SourceAFIS and NBIS each had an operating point
published by someone else, flx has none, and so Stage 8D would have to *choose*
one — from the same 6,000 evaluation scores the resulting rate would be reported
on. A threshold fitted to the evaluation set makes that rate an upper bound on
nothing.

Two further facts settled it. The algorithm list is not final — five are intended
and two are not yet identified, so their score directions and scales are unknown.
And no development cohort has ever been drawn; this project has one cohort and
its role is `TEST`.

So Stage 8D kept its name and changed its scope
([ADR 0078](docs/adr/0078-stage-8d-builds-calibration-infrastructure-without-calibrating.md)).
It built the machinery a real calibration will run on, qualified it on synthetic
fixtures, and performed no calibration. Its marker denies, in fields rather than
in prose, everything it did not do:

```
real_calibration_performed           false
real_development_dataset_selected    false
production_threshold_count           0
production_decision_profile_count    0
evaluation_score_rows_read           false
historical_decision_profiles_changed false
stage8c_evidence_changed             false
opens_algorithm_expansion            true
```

`fpbench.calibration` imports `core` and nothing else, names no algorithm,
contains no floating-point value and defines no score normalizer — all four
enforced structurally rather than by review. Each algorithm gets a threshold on
its own scale; what is shared is the *policy*, never the number
([ADR 0080](docs/adr/0080-calibration-selects-native-score-boundaries-without-score-normalization.md)).

Boundaries come from the observed **impostor** scores — `>= s` and `> s`, or
`<= s` and `< s` — so both extremes of the impostor rate are expressible without
inventing a number no comparison produced. Mated scores generate no candidate,
determine no permissiveness and break no tie; a value only a genuine comparison
produced cannot become a threshold, because a boundary standing there would have
been placed by the population the rule is not allowed to optimise for.

Rates are pairs of integers compared by cross-multiplication, because `0.001` is
not one thousandth, and a target is bounded by `[0, 1]`. Ties are atomic: five
impostors scoring `0.4, 0.4, 0.4, 0.7, 0.7` under a ceiling of one in five
produce `> 0.7`, which admits *none* of them, because admitting one of the two
`0.7`s is not something a threshold can express.

Development data is enforced twice, not declared once
([ADR 0079](docs/adr/0079-calibration-data-must-be-development-not-evaluation.md)).
The cohort role is checked before a single row is read, and a
`ProtectedEvaluationRegistry` binds the identities of the evaluation material —
the dataset, the cohort, the pair manifest, the shared prepared-image set, and
the canonical run and `ResultSet` of all three executed algorithms. A binding
that resolves to any of them is refused *whatever role it claims*, and running
with no registry loaded is refused too.

`DecisionProfile` gained schema 3, which carries the three links a calibrated
threshold has to name, under a fingerprint mapping of its own. Schemas 1 and 2
are untouched: the two documented "at least 40" profiles and the documented
"greater than 40" one are pinned by literal digest and verified against the
pre-Stage-8D code.

Details: [the Stage 8D evidence report](evidence/stage8d-calibration-infrastructure/README.md),
[the calibration architecture](docs/calibration/architecture.md),
[how a boundary is selected](docs/calibration/operating-point-selection.md) and
[ADRs 0078–0080](docs/adr/README.md). Verify it — no dataset, no runtime, no
weights, no workspace — with:

```bash
make stage8d-evidence
```

## Stage 8E: say what the project is, then stop arguing about licences

`RESEARCH_ONLY_THIRD_PARTY_POLICY_READY`.

Three algorithms produced three differently-shaped licensing conclusions. Stage
8A rejected a candidate `LICENSE_BLOCKED` under a gate requiring permission for
"an academic benchmark and publication". Stage 8B ran the same artifact anyway,
on an owner instruction, and recorded the licence as unresolved. Stage 8C
inherited that. All three were correct answers to the questions they asked, and
none of them was a rule — so algorithm 4, whose upstream carries conflicting
notices, was about to become the fourth argument.

Stage 8E made the exception into a policy. Four ADRs, and the second is the one
that matters.

**The purpose is frozen**
([ADR 0081](docs/adr/0081-fpbench-is-personal-educational-research-only.md)):
`PERSONAL_EDUCATIONAL_RESEARCH`, with six denials each `False` and each enforced
by the declaration's own constructor. Not `academic` — there is no institution
here. No `LICENSE` file, and no bespoke "research only licence": a purpose
declaration and a copyright licence are different instruments, and inventing one
to express the other creates a legal question rather than answering one.

**A licence observation is not a decision**
([ADR 0082](docs/adr/0082-third-party-license-observation-is-separate-from-local-research-use.md)):

```
What does upstream licensing say?   ->  LicenseObservation      a description
May fpbench execute it locally?     ->  ResearchUseDecision     a decision
May fpbench redistribute it?        ->  RedistributionDecision  never exercised
```

so the repository can hold `CONFLICTING_NOTICES` and
`ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` at once, without claiming the conflict
was resolved. Restrictions on commercial use, redistribution, sublicensing,
publication and copyleft are recorded, respected, and are **not** blockers,
because this project does none of those things — and has committed to that in a
fingerprinted document. Blockers are a short closed list: an express prohibition
of the intended use or of biometric use, a prohibition of a modification faithful
execution needs, access terms that cannot be satisfied, an artifact obtained by
circumventing a technical restriction, terms incompatible with local execution,
an identity that cannot be established, unsatisfied dataset terms, and permission
that is unresolved with no risk accepted.

Where notices conflict, no winner is picked. The question is which uses *every*
plausible reading permits in common — a conjunction, so one forbidding reading
blocks.

**Third-party bytes never enter Git**
([ADR 0083](docs/adr/0083-third-party-bytes-are-never-redistributed-by-fpbench.md)).
`DO_NOT_VENDOR` is the default even for MIT, and even for upstream *source*: an
upstream repository is a runtime artifact exactly like a checkpoint, acquired at
a pinned commit and verified by digest. Everything lives under
`FPBENCH_THIRD_PARTY_ROOT` or `~/.cache/fpbench/third_party/`, and the repository
knows a role, a digest, a size and an upstream identity — never a path. The
enforcement is a guard over `git ls-files`, not `.gitignore`: eight rules, one
named exception for the ten synthetic imaging fixtures.

**An absent licence is not permission**
([ADR 0084](docs/adr/0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md)).
It may be risk-accepted, under all five conditions, and the record then reads
`intended_use_permission_status: UNRESOLVED` — the owner accepted a risk, nobody
established a right. A dataset may never be risk-accepted; dataset rights are
unchanged by this stage.

Twelve already-integrated components were mapped by the same engine Stage 9A will
use: 7 `ALLOWED`, 1 intersection (SD300), 4 `OWNER_RISK_ACCEPTED` (both NIST NBIS
archives, the build made from them, and the flx checkpoint), 0 blocked. No
historical evidence was rewritten.

Details: [the Stage 8E evidence report](evidence/stage8e-research-only-policy/README.md),
[the three policy documents](docs/policy/) and
[ADRs 0081–0084](docs/adr/README.md). Verify it — no dataset, no runtime, no
weights, no network — with:

```bash
make stage8e-evidence
```

## Stage 9A: qualify FLARE's full route, or build nothing

Algorithm 4 is FLARE — *Fixed-Length Dense Fingerprint Representation with
Alignment and Robust Enhancement*, TIFS 2026. Stage 9A asks one question before
a line of adapter exists: can a faithful implementation identity be frozen from
the published method, the two official repositories, the official pretrained
artifacts and integration-neutral glue, and nothing else?

The answer is no, and that is a complete result.

```
FLARE_FULL_ROUTE_BLOCKED
```

**The subject is the whole method or nothing.** Two pose estimators times two
enhancers is four branches fused by a maximum. A runnable two-branch subset is a
different algorithm wearing FLARE's name, and `branch_count = 4` is a gate rather
than a preference (ADR 0085). The candidate identity spells out what is being
qualified — `flare_fdd_d6_dualpose_dualenh_maxcosine` — including the binary FDD
route it excludes (ADR 0086).

**The gate is not checkpoint loading.** An earlier reading of this repository
recorded the FDD checkpoint load as disabled; at the pinned commit it is present
and active. That question is closed, which is exactly why a commit is pinned and
not a branch.

**The gate is the transform graph.** The paper is explicit:

```
pose  ->  align, crop 512  ->  enhance  ->  downsample 256  ->  FDRN
```

The public code contains the same stages and does not compose into that
sequence. `Descdataset.process_img` builds one affine with
`scale = 256/512` and warps the *unenhanced original* straight to 256×256 —
alignment and the downsample are a single interpolation, with no 512×512 image
in between and nowhere to insert an enhancer. The enhancers live in a second
repository and take whole original images. There is no 512-to-256 reduction
anywhere, no four-branch orchestration and no `max` fusion.

All seventeen operations, and their order between the canonical bytes and the
FDRN tensor, carry an authority. The paper explicitly places the aligned
512×512 crop before enhancement and the 512-to-256 downsample after it. What
remains incomplete is their pixel implementation: two upstream warps disagree
about the crop's border fill, and the downsample is one function call with four
reasonable kernels and no upstream implementation to copy. A score-affecting
parameter must come from the paper, the pinned code or a pinned inference
default — and where none of them speaks, this project stops rather than
choosing (ADR 0087, ADR 0088).

**What did resolve** is worth as much, because Stage 9B would build on it: both
repositories pinned by commit with byte-identical archives across two
acquisitions; the transitive `Prior.ckpt` found by traversing `vq.yaml` rather
than a README; both enhancers' preprocessing and postprocessing proved to be
exact identities on a 512×512 input; the masked-cosine score contract
transcribed exactly, clip and continuous mask and all, with twelve of its
properties exercised over synthetic vectors; and `D = 6` agreeing between the
paper and the official configuration.

**Licensing is no longer the argument.** Both repositories carry a permissive
`LICENSE` beside a README restricting use to academic research and education.
Stage 9A records both and chooses neither — Stage 8E's intersection rule answers
the only question this project has to ask, and every FLARE component went through
that one engine. The six checkpoints are blocked, but on identity rather than on
licence: a Google Drive file id is a locator, and the identity is the digest and
the size.

Nothing was fetched by CI, no third-party byte entered Git, no SD300 data was
read and Stage 8E was not touched. Details: [the Stage 9A evidence
report](evidence/stage9a-flare-artifact-qualification/README.md), [the FLARE
method documents](docs/algorithms/flare/) and
[ADRs 0085–0088](docs/adr/README.md). Verify it — no dataset, no torch, no
checkpoint, no network — with:

```bash
make stage9a-evidence
```

## Stage 10A: check the candidates before choosing one

Stage 9A got the order wrong. It *selected* FLARE and then spent a stage
establishing that FLARE could not be executed faithfully — and a selected
candidate creates pressure, because every gap becomes something to work around
rather than something to report.

Stage 10A inverts it. Two candidates, AFR-Net and JIPNet, and one question asked
before either is chosen:

```text
which, if either, can enter fpbench as algorithm 4
without an fpbench reconstruction,
without invented preprocessing,
and without SD300 being consulted to make it fit?
```

Seven hard gates, conjunctive and unweighted, run fail-fast. Identity and input
domain come first because both can be settled by reading, and settling either
negatively means several hundred megabytes are never downloaded.

```text
ALGORITHM4_PREFLIGHT_NO_SURVIVOR
```

| Gate | AFR-Net | JIPNet |
| :--- | :--- | :--- |
| 1 identity | **FAIL** | PASS |
| 2 input domain | not reached | **FAIL** |
| 3–7 | not reached | not reached |

**AFR-Net** has no author-supplied implementation and no author-supplied
checkpoint. Ten locations were searched and each is recorded with what it
returned; one of them, the IEEE article page, was unreadable and is recorded as
unread rather than as empty. A working AFR-Net does exist inside JIPNet's
repository, published as a comparison baseline — and its own authors state it is
a reproduction whose alignment stage was substituted. That is a different
algorithm, and it enters as `jipnet_authors_adjusted_afrnet_reimplementation` or
not at all (ADR 0090).

**JIPNet** passed identity on its first reading: the paper's abstract names the
repository, the repository calls itself the official implementation, and the
archive was acquired twice byte-identically at a pinned commit. It fails on input
domain. Its official `inference.py` reads two images and forwards them — no crop,
no resize, no size check — `cv2.resize` appears nowhere in the repository, and
the only full-fingerprint-to-patch function belongs to training-data
construction, where the crop is sampled from the *common mask of an aligned
pair*, rotated randomly, and preceded by a VeriFinger step the authors state
cannot run. A benchmark input cannot depend on the gallery image it will be
compared against (ADR 0091), and closing the gap would mean fpbench choosing the
crop (ADR 0092).

Cost of reaching that conclusion: **zero checkpoint bytes**, zero runtimes, zero
SD300 reads, zero scores. `NOT_REACHED` is published as itself — neither a pass
nor a soft failure — and the observations gathered incidentally before each stop
are labelled as observations, never as gate conclusions.

No ranking was performed, because ranking happens only among candidates that
passed every gate, and author-reported accuracy is not read at all: the two
papers report on different datasets under different protocols (ADR 0093).

Details: [the Stage 10A evidence
report](evidence/stage10a-algorithm4-candidate-preflight/README.md), [the
candidate records](docs/algorithms/algorithm4-candidates/) and
[ADRs 0089–0093](docs/adr/README.md). Verify it — no dataset, no torch, no
checkpoint, no network — with:

```bash
make stage10a-evidence
```

## Stage 10B: the first candidate of that search

Stage 10A's candidate search produced one: the **id3 Finger SDK**, a commercial
matcher whose 1:1 route is exactly the shape this benchmark needs — one integer
per comparison, in 0..65535, with the threshold applied afterwards.

It is a new stage rather than a third row in Stage 10A's table. Stage 10A froze
its candidate set *before* it knew the answer, which is what makes "neither
survived" a result; adding a candidate afterwards would change the question after
the answer was visible (ADR 0094). Stage 10B binds Stage 10A's fingerprint as a
predecessor and edits nothing of it.

The gates are different too, because a commercial product fails differently from
a GitHub repository:

```text
ID3_FINGER_SDK_PREFLIGHT_FAIL
```

| # | Gate | |
| ---: | :--- | :--- |
| 1 | `PRODUCT_IDENTITY` | PASS |
| 2 | `ACQUISITION_ACCESS` | **FAIL** |
| 3–10 | package, input, profiles, score, workload, provenance, smoke | not reached |

**Acquisition is gate 2 on purpose.** Every gate after it asks about a delivered
package — its digest, its models, its input route, its extractor and matcher
profiles, its score API, its determinism — and none of them can be answered from
a product page. The vendor publishes no self-service download: its own samples
state that the SDK archive and the activation key are issued together, after a
request has been accepted, and that the library checks a licence file before any
other call. No such request has been made from this project — so the blockers
are `ID3_PACKAGE_NOT_OBTAINED` and `ID3_LICENSE_NOT_OBTAINED`, and the marker
classifies the failure as `OPERATIONAL_ACCESS_NOT_ESTABLISHED` with
`id3_proven_unobtainable: false`. Nobody asked, so nobody was refused.

**Capacity is a hard gate, and it fails as `UNRESOLVED`.** The free evaluation is
30 days with `Limited API calls` and a single platform — a limit with no number,
and no statement of which operations consume it. The frozen run performs 12,000
extraction invocations and 6,000 matcher invocations over 6,000 comparison
attempts — two extractions per comparison, Stage 8C's execution semantics —
which is 18,200 high-level biometric operations. What that costs in the licence's
own unit is not derived, because "API call" is undefined; the metered call count
stays `UNRESOLVED`. "Try it and see" is refused by name: a quota exhausted
at comparison four thousand leaves two thousand that were never run, and that is
not a smaller experiment (ADR 0096).

**Access is not research use.** Nothing here says id3's terms forbid anything.
Stage 8E owns that question and has no component to assess, so
`research_use_opens_execution` is published as `null` rather than `false` — a
`false` would be a refusal nobody made (ADR 0095).

Reading the public record settled things the gates never got to use, and they are
published as observations rather than as conclusions: the single-image sample
performs no detection and no ROI extraction while the product page's headline
sample does both, because it starts from a slap; `canonical_500` is already the
500 ppi 8-bit grayscale the SDK requires; and seven score-affecting settings —
five matcher options and two extractor models — have **no documented default
anywhere public**, which would each have to be read from a delivered package and
labelled `DELIVERED_SDK_DEFAULT` (ADR 0097).

Cost: zero package bytes, zero model bytes, zero activations, zero SD300 reads,
zero scores. No credential appears in the evidence, and the verifier refuses to
publish if one does — by key name or by value shape, checked twice, once over the
objects and once over the published bytes (ADR 0098).

Details: [the Stage 10B evidence
report](evidence/stage10b-id3-finger-sdk-preflight/README.md), [the candidate
record](docs/algorithms/algorithm4-candidates/id3-finger-sdk.md) and
[ADRs 0094–0098](docs/adr/README.md). Verify it — no dataset, no SDK, no licence,
no network — with:

```bash
make stage10b-evidence
```

## Stage 11A: the first candidate whose package was actually opened

The candidate search's next candidate is **VeriFinger 2025.2**, and this is the
first preflight in the project that begins by downloading something.

Stage 10B could not get id3's package — the vendor issues it on request, after
acceptance — so eight of its ten gates were questions about an archive that did
not exist. Neurotechnology publishes a direct link with no form, no account and
no approval step, so publishing "unresolved" here would have meant staying
ignorant of facts one transfer away (ADR 0100).

```text
VERIFINGER_PREFLIGHT_INCOMPLETE     8 of 17 gates passed, 9 awaiting one run
                                    0 blockers, no failure class
```

| # | Gate | |
| ---: | :--- | :--- |
| 1 | `OFFICIAL_ARTIFACT_ACQUISITION` | PASS |
| 2 | `RUNTIME_IDENTITY` | action required |
| 3 | `RESEARCH_USE_PERMISSION` | PASS |
| 4 | `ARTIFACT_CLOSURE` | PASS |
| 5 | `CANONICAL500_INPUT_ROUTE` | PASS |
| 6 | `EXTRACTION_PROFILE` | action required |
| 7 | `REPRESENTATION_PROFILE` | PASS |
| 8 | `MATCHER_PROFILE` | action required |
| 9 | `RAW_SCORE_ROUTE` | **PASS** |
| 10–13 | pair order, SELF, determinism, failure semantics | action required |
| 14 | `NETWORK_DEPENDENCY` | PASS |
| 15–16 | feasibility, licence capacity | action required |
| 17 | `TRAINING_PROVENANCE` | PASS |

**An unperformed run is not a failure.** The first publication of this stage said
`VERIFINGER_PREFLIGHT_FAIL` — the same verdict string it would have used if the
score had turned out to be non-deterministic — when what had actually happened
was that nobody had activated a 30-day trial. There is now a third gate status
and a third outcome, and the difference is enforced rather than described: a gate
awaiting an action carries **no blocker**, an incomplete marker carries **no
failure class**, and only a real `FAIL` stops the run. That last part is why gate
9, the decisive one, is published at all (ADR 0104).

**What was acquired.** 4,743,229,435 bytes of SDK archive (`e30a0b60…`) and
124,277,015 bytes of manual (`ae8acd23…`), both verified against the length the
server declared. The manual is *provably* the right one: byte-for-byte the copy
inside the archive. All 8,702 archive members hashed. Zero bytes in Git, and a
guard that refuses the repository if that changes.

**The route was chosen by a version number.** The vendor's Python packages — the
route the preceding research favoured — are published at **2025.1**. Opening the
2025.2 archive also settled that it ships C, C++, .NET and Java bindings and no
Python binding, so an integration goes through a Java bridge, as SourceAFIS does.

**What the artifact settled.** One scalar raw score, higher is more similar, on
the vendor's own claimed-FAR scale (`score = -12·log₁₀(FAR)`), with the threshold
a separate engine property that upstream's tutorial applies *after* reading the
score — a native transformed quantity is still a raw score, and fpbench converts
nothing (ADR 0102). The representation compared is the proprietary template. The
required internet connection is a licence check, not part of the computation
(ADR 0103). Stage 8E permits local research execution.

**What the nine remaining gates needed was one bounded qualification run, and
it happened.** `VERIFINGER_PREFLIGHT_PASS`, seventeen of seventeen. The trial was
activated once, by hand, on the one platform the route locks to, and
`integrations/verifinger-qualification/` read the ten score-affecting values out
of a *running* engine — the manual states a default for every `Faces.*`
parameter and for no `Fingers.*` or `Matching.*` one, so reading them was the
only way to know them (ADR 0105).

That harness published no score value: it emitted a SHA-256 per score and
compared digests, so determinism across a restart was provable without a number
leaving the JVM.

**The candidate search stays closed, and now because the candidate succeeded.**
No methodological blocker was found at any of the seventeen gates.

Details: [the Stage 11A evidence
report](evidence/stage11a-verifinger-2025_2-preflight/README.md), [the candidate
record](docs/algorithms/algorithm4-candidates/verifinger-2025-2.md), [the stage
write-up](docs/experiments/stage11a-verifinger-2025_2-preflight.md) and
[ADRs 0099–0105](docs/adr/README.md). Verify it — no dataset, no SDK, no licence,
no network — with:

```bash
make stage11a-evidence
```

## Stage 11B: the fourth algorithm, over the same 6,000 comparisons

`VERIFINGER_CANONICAL500_RAW_COMPLETE`. The route Stage 11A qualified ran the
canonical SD300 experiment SourceAFIS, NBIS and flx already ran — the same 6,000
pairs, in the same order, over the same 3,000 immutable 500 ppi PNGs.

```
6,000 planned      6,000 stored      0 missing        0 duplicate
5,919 scores       81 algorithm failures              0 infrastructure failures
run_52731bb3407e / plan_0a66249b7412 / resultset_960baecb83b8
```

**Six thousand outcomes, not six thousand scores.** The 81 are VeriFinger
declining a print — `BAD_OBJECT`, against a quality threshold it set itself. That
is a property of real fingerprints; it is counted, and it was not "fixed" to
reach full coverage. A failure is never recorded as a score of zero, and the
separation is enforced rather than intended: an extraction the engine declines is
data, while a licence that was refused, a model file that moved or a JVM that
died would each have blocked the result set.

**The vendor's 48 is provenance, not an operating point.** VeriFinger's own 1:1
sample sets `MatchingThreshold = 48`; the bridge keeps it so upstream's route is
reproduced exactly, and fpbench then reads the integer score under `OK` *and*
under `MATCH_NOT_FOUND`. 1,477 of the 5,919 scores came back under
`MATCH_NOT_FOUND` — successful comparisons that scored below the vendor's own
threshold. Recording those as failures, or as zeros, would have been fpbench
choosing an operating point by accident.

**One JVM per comparison.** Slower than a persistent worker and chosen anyway: it
makes a cross-comparison cache, a representation cache and a score cache
impossible rather than merely absent, and it makes restart determinism the
ordinary behaviour of every job rather than a property somebody has to test for.
6,000 processes, 12,000 logical extractions, 6,000 `verify` calls, median
1,775 ms each including JVM startup and licence acquisition.

**Seventeen pinned runtime components.** Stage 11A pinned ten — five DLLs, two
model data files and three jars. The engine reports *seven* loaded modules, and
the qualification harness put every jar in `Bin/Java` on the classpath, so
`NMediaProc.dll`, `NDevices.dll` and five jars could have changed underneath a
result without anything noticing. The production closure names all seventeen by
size and SHA-256, proves each one against the pinned SDK archive rather than
merely hashing what is on disk — integrity is not provenance — re-verifies the
lot before and after the run, and checks file identity before every single
comparison. Drift stops the run and is never stored as a biometric failure.

**What it does not publish**: no threshold, no decision, no calibration, no
metric, no distribution, no summary statistic and no example score. The
prohibition is enforced in four independent places: a config loader that refuses
threshold-shaped keys at any depth, a bridge that cannot return a decision, a
validator that refuses a stored score with a fractional part, and a finalization
that refuses to publish a document carrying a forbidden key.

The 4.7 GB of vendor SDK stayed in a local artifact store outside the repository
throughout. What is committed is the bridge source, a manifest of digests, the
runtime policy and derived evidence.

Details: [the Stage 11B evidence
report](evidence/stage11b-verifinger-canonical500-raw/README.md) and [the run
write-up](docs/experiments/verifinger-canonical500-raw.md). Verify it — with no
dataset, no SDK, no licence, no JVM and no workspace — with:

```bash
make stage11b-evidence
```

## Stage 12A: Innovatrics IDKit access refused

`IDKIT_PREFLIGHT_FAIL`. On 2026-08-14 an Innovatrics Business Development
representative explicitly declined to provide an IDKit SDK licence for academic
or research-only evaluation and non-commercial benchmarking. This is a vendor
access refusal, not an inference from a missing download and not a pending sales
request. The repository records the category and date, not the correspondence,
the representative's identity or an address.

The acquisition gate therefore failed fast with `ACCESS_REFUSED_BY_VENDOR` and
`VENDOR_ACCESS_REFUSED`. No package or licence was offered, and none of the API,
runtime, score or provenance questions was reached:

```
G1  ACQUISITION_ACCESS                 FAIL
G2  PACKAGE_RUNTIME_IDENTITY           not reached
G3  RESEARCH_USE_AND_LICENSE           not reached
G4  CANONICAL500_INPUT_ROUTE           not reached
G5  SINGLE_FINGER_EXTRACTION_PROFILE   not reached
G6  SINGLE_FINGER_MATCHER_RAW_SCORE    not reached
G7  SCORE_AFFECTING_SETTINGS_CLOSURE   not reached
G8  PAIR_SELF_DETERMINISM_FAILURES     not reached
G9  WORKLOAD_RUNTIME_FEASIBILITY       not reached
G10 TRAINING_PROVENANCE                not reached
```

The previously prepared qualification machinery remains unreachable for this
candidate and does not contribute to the finding. Stage 12A intentionally stops
at G1 instead of revising a harness for an SDK the vendor has said it will not
supply to this project. Stage 12B stays closed and the Algorithm 5 candidate
search reopens.

Details: [the Stage 12A evidence
report](evidence/stage12a-idkit-preflight/README.md), [the stage
write-up](docs/experiments/stage12a-idkit-preflight.md) and [the candidate
record](docs/algorithms/algorithm5-candidates/innovatrics-idkit.md). Verify it —
with no dataset, no package, no licence and no network — with:

```bash
make stage12a-evidence
```

## Next stage

**Algorithm 4 exists.** Stage 11B ran the canonical 6,000 under VeriFinger
2025.2 and stored 6,000 raw outcomes, so the benchmark now holds four raw result
sets over identical inputs.

```
Stage 9A    algorithm 4 = FLARE  — artifact and method qualification   BLOCKED
Stage 10A   algorithm 4 candidates — AFR-Net vs JIPNet preflight       NO SURVIVOR
Stage 10B   algorithm 4 candidate — id3 Finger SDK preflight           BLOCKED (access)
Stage 10C   id3 artifact and runtime integration                       reserved, unopened
Stage 11A   algorithm 4 candidate — VeriFinger 2025.2 preflight        PASS (17/17)
Stage 11B   VeriFinger production integration and canonical raw run    COMPLETE (6,000)
Stage 12A   algorithm 5 candidate — Innovatrics IDKit preflight        FAIL (vendor refusal)
Stage 12B   IDKit production integration and canonical raw run         CLOSED
```

**Algorithm 5 selection continues.** IDKit is closed after the explicit refusal;
the id3 Finger SDK request remains under vendor review in the background; and
Neurodactyl is the next active candidate. Stage 12A does not contact another
sales representative, use a reseller or reframe the research use as commercial.

**What is open, and what is not.** The Stage 11B marker records
`opens_algorithm_5_search: true` and `opens_common_calibration: false`, and the
second matters more than the first. Four raw result sets are not a ranking: each
algorithm's scores live on its own scale, VeriFinger's vendor anchor of 48 is not
comparable to SourceAFIS's documented 40 or to NBIS's, and an operating point may
not be chosen from the SD300 scores SD300 will then be evaluated at. Until a
common calibrated operating policy exists, nothing here says which algorithm is
more accurate — and nothing here may.

**Stage 10C stays reserved for id3.** It was defined as the id3 artifact and
runtime integration that a passing 10B would open, and recycling the number for
a different candidate would make the history unreadable — a later reader would
find a 10C with nothing to do with the 10B above it. The marker carries
`stage_10c_reserved_for_this_candidate: true` and refuses to say otherwise.

**Two tracks, and neither waits for the other.** Requesting an id3 evaluation
licence — the package, the activation, the exact quota and metering semantics,
and confirmation that the planned research workload is permitted — is one act by
one person, and it reopens Stage 10B if it succeeds. The next candidate preflight
does not depend on it and should not wait for it. If id3 answers quickly and the
quota is sufficient, 10B requalifies and 10C opens. If not, no time was lost.

id3's blocker is much weaker than FLARE's or JIPNet's, and the marker says so:
the candidate failed no gate about its input domain, its published method, its
raw score or its research-use terms.

The search still starts from a written specification rather than an impression: a
candidate must be an official artifact, must accept `canonical_500` through a
route somebody upstream defined, must name its artifacts by bytes, must produce
one finite scalar per attempt with no threshold, must not have been fitted on
SD300, and must run here. Any candidate that fails one of those fails, and no
gate is weakened to fill the slot.

Four things would lift the route blockers, and each is concrete: an authoritative
statement of the 512-to-256 resampling; an authoritative statement of what fills
the aligned crop outside the fingerprint; an upstream orchestration that composes
pose, alignment, enhancement and FDD in the paper's order, or a statement
resolving which order the released checkpoints were used under; and enrollment of
the six checkpoints from their official locators. The first three are upstream's
to answer or a corrective stage's to decide explicitly. The fourth is a local
operation, and it would not by itself change the outcome.

The premise Stage 8E changed still holds for whatever algorithm comes next:
conflicting upstream notices stay conflicting and are no longer a blocker by
themselves. Every algorithm from here on fills in the same
`ThirdPartyUsageRecord` instead of relitigating licensing.

**A real calibration stage opens only when the algorithm list is declared
final.** It will choose a development cohort, a pair-generation protocol and a
target operating point *once*, and then run exactly the Stage 8D methodology over
every algorithm — which is the whole reason that methodology was built before any
of it was needed.

**Stage 8C is closed.** The checkpoint's licence remains unresolved; that does
not block the instructed local experiment but does block publishing anything
derived from the weights themselves — no embedding, no representation hash and
no score row appears under `evidence/`.

Reconsidering id3 Finger SDK or VeriFinger remains a separate stage with its own
registry version and its own legal and runtime qualification. No later stage may
weaken Stage 8A retroactively or use SD300 to repair a missing preprocessing,
threshold or runtime claim.

Also outstanding from earlier stages: a real FMR needs a cross-subject
negative-pair design chosen for estimation — a new pair manifest and a new run,
not a new metric over this one.

## Longer-term backlog from earlier stages

1. metrics over the three views — FMR, FNMR and the conditional PLAIN–ROLL report — with
   the one thing that makes them honest written down first: what happens to a failed
   comparison and to an `UNDETERMINED` finger in each denominator;
2. a development cohort and a calibration manifest, so that a *calibrated* threshold
   becomes possible without touching the 50 test subjects
   ([ADR 0021](docs/adr/0021-decision-profiles-are-immutable-and-external.md));
3. failure analysis over the algorithmic failure codes the run recorded;
4. **stage 7E** — a sensitivity analysis over a pre-registered grid of documented
   thresholds, with no winner chosen from it and no change to stage 7D's primary result.
   Calibrating both algorithms to a common FMR is a different and larger piece of work:
   it needs an independent development cohort, a calibration manifest, a ban on touching
   the SD300 test cohort, and a new evaluation under a new profile
   ([ADR 0058](docs/adr/0058-cross-algorithm-operating-points-are-not-equated.md));
5. the persistent-JVM decision, on the strength of the full run's operational summary
   rather than a guess ([ADR 0015](docs/adr/0015-sourceafis-uses-stateless-java-bridge.md));
6. a better negative set, if a real false-match rate is ever wanted: cross-subject, and
   either exhaustive or a stated sample
   ([ADR 0025](docs/adr/0025-same-subject-different-finger-is-a-sanity-check.md));
7. parallel execution, a retry policy keyed to the failure taxonomy, and a CLI over all
   of it.
