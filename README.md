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
per job and can be interrupted and resumed. No thresholds, no decisions, no
real matcher.

| Package | Status | Responsibility |
|---|---|---|
| `fpbench.core` | built | shared vocabulary; stdlib only, imports nothing from the project |
| `fpbench.datasets` | built | what images exist on disk, and do they match their own declarations |
| `fpbench.protocols` | built | which subjects take part, and which comparisons that implies |
| `fpbench.storage` | built | immutable manifests, run manifests, raw results |
| `fpbench.imaging` | built (identity only) | the image preparation contract; resampling and conversion still to come |
| `fpbench.adapters` | built | the adapter contract, the registry and `dummy_sha256` |
| `fpbench.execution` | built (single job) | run and job identity, and a resumable single-job runner |
| `fpbench.decisions` | not yet | thresholds, calibration, score → decision |
| `fpbench.evaluation` | not yet | protocol metrics, FMR/FNMR, failure analysis, reports |
| `fpbench.cli` | not yet | command-line entry points |

Deliberate omissions, so they read as decisions rather than oversights:

* **No real matcher yet.** `dummy_sha256` produces a deterministic pseudo-score
  and nothing else; it exists to exercise the harness, and no biometric
  conclusion may be drawn from it.
* **No thresholds anywhere.** Raw scores are stored with their score direction
  and no decision. Applying a threshold is a separate, later record against
  those unchanged scores.
* **No batch runner, no retries, no parallelism.** One job at a time. The
  storage layout is already the one that makes parallel execution safe, but the
  execution side of it is not written.
* **Optional adapter capabilities are named, not implemented.** Template
  extraction, caching and minutiae export land with the first matcher that
  actually offers them.

## Setup

```bash
conda env create -f environment.yml
conda activate fingerprint-benchmark
pip install -e ".[dev]"
```

Point the harness at your NIST delivery (the directory holding `sd300a/`,
`sd300b/`, `sd300c/`) — see [data/README.md](data/README.md):

```powershell
$env:FPBENCH_SD300_ROOT = "C:\fingerprint-datasets\NIST"
```

Run the tests:

```bash
pytest -m "not dataset"
```

`pytest` without the marker filter also runs the checks against the real
release; those are skipped automatically when `FPBENCH_SD300_ROOT` is unset.
CI runs `pytest -m "not dataset"` on every push and pull request — SD300 is
redistribution-restricted and cannot be uploaded, so the synthetic fixtures are
what CI exercises.

The suite has four levels:

```
tests/unit/          individual functions and model invariants
tests/contract/      one suite every adapter must pass, parametrised over the registry
tests/integration/   dataset → manifest → cohort → pairs, and pair → runner → result
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

## Running a comparison (phase 3A)

Phase 3A adds the execution path: a pair goes in, a stored raw result comes
out, and the whole thing can be interrupted and resumed without duplicating
work or losing any. The only matcher so far is `dummy_sha256`, which derives a
deterministic score from the two images' official digests. **It performs no
biometric matching and no research claim may rest on its output.** It exists so
that the harness can be exercised while a bug is still unambiguously the
harness's fault.

Continuing from the manifests built above:

```python
from fpbench.adapters import create_adapter
from fpbench.execution import (
    DEFAULT_EXECUTION_PROFILE,
    SingleJobRunner,
    build_comparison_job,
    create_run_definition,
)
from fpbench.imaging import IdentityImagePreparer
from fpbench.storage import ResultStore

adapter = create_adapter("dummy_sha256")
pair_manifest_hash = store.pair_manifest_metadata(
    protocol.protocol_id, cohort.cohort_id
)["pair_manifest_hash"]

run = create_run_definition(
    protocol_id=protocol.protocol_id,
    cohort_id=cohort.cohort_id,
    pair_manifest_hash=pair_manifest_hash,
    algorithm=adapter.descriptor,
    environment=adapter.validate_environment(),
    execution_profile=DEFAULT_EXECUTION_PROFILE,
)

runner = SingleJobRunner(
    run=run,
    adapter=adapter,
    preparer=IdentityImagePreparer(),
    result_store=ResultStore(Path("workspace")),
    dataset_root=provider.root,
    image_index={image.image_id: image for image in images},
    workspace_root=Path("workspace"),
)

for pair in pairs:
    outcome = runner.execute(build_comparison_job(run, pair), pair)
    print(outcome.disposition.value, outcome.result.raw_score)
```

Produces, under `workspace/`:

```
results/<run_id>/run.json                        the run manifest
results/<run_id>/raw/jobs/<job_id>.parquet       one immutable row per job
work/<run_id>/<job_id>/                          adapter scratch, disposable
artifacts/<run_id>/<job_id>/                     adapter artefacts, if any
```

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
mixing incomparable results together.

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

## Next stage

1. decision policies, native thresholds and calibration on a development
   cohort;
2. the first real adapter (SourceAFIS), which joins the existing contract suite
   automatically by being registered;
3. a batch runner over the full 6,000-pair plan, plus retries and timeouts;
4. evaluation: protocol metrics, SELF-filtered results, failure analysis,
   FMR/FNMR;
5. a CLI over all of it.

Also outstanding, and cheap: the `imaging` layer currently offers only the
identity preparer. Resampling — 2000 ppi and 1000 ppi down to 500 — becomes a
second preparer with its own id, so results produced under each remain
distinguishable.
