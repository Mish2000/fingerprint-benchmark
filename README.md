# fpbench — fingerprint recognition benchmark harness

A reproducible harness for comparing fingerprint recognition algorithms on NIST
Special Database 300 (releases A/500 ppi, B/1000 ppi, C/2000 ppi).

The organising principle:

> The harness owns the experiment. An algorithm never decides what runs, and
> infrastructure never changes an algorithm without saying so in writing.

---

## What exists right now

Phase 2 is the reproducible experiment definition: **datasets, protocol,
provenance and manifest storage**. It records which exact image delivery was
audited, which 50 subjects were chosen, and which 6,000 comparisons the
protocol calls for — with no algorithm involved.

| Package | Status | Responsibility |
|---|---|---|
| `fpbench.core` | built | shared vocabulary; stdlib only, imports nothing from the project |
| `fpbench.datasets` | built | what images exist on disk, and do they match their own declarations |
| `fpbench.protocols` | built | which subjects take part, and which comparisons that implies |
| `fpbench.storage` | built (phase 2) | immutable manifests plus run-scoped SELF eligibility |
| `fpbench.imaging` | not yet | resampling, format conversion, transform provenance |
| `fpbench.adapters` | not yet | one package per algorithm, behind a shared contract |
| `fpbench.decisions` | not yet | thresholds, calibration, score → decision |
| `fpbench.execution` | not yet | planner, runner, retries, timeouts |
| `fpbench.evaluation` | not yet | protocol metrics, FMR/FNMR, failure analysis, reports |
| `fpbench.cli` | not yet | command-line entry points |

Two deliberate omissions worth naming, so they read as decisions rather than
oversights:

* **`core` defines only the models the built packages exchange.** `PreparedImage`,
  `RawMatchResult`, `DecisionResult`, `FailureInfo`, `ExecutionProfile` and
  `AlgorithmDescriptor` are named in the architecture but not written yet —
  their fields cannot be designed honestly without a real adapter to satisfy.
* **`storage` implements manifests and the one result artifact whose contract
  phase 2 already fixes.** General result and artifact stores wait on the
  runner; per-finger SELF eligibility is already scoped by run and decision
  profile so it cannot be confused across algorithms or thresholds.

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

## Next stage

The natural order from here, one reviewable step at a time:

1. a dummy adapter that returns a deterministic score from `pair_id` — enough
   to exercise the runner, the decision layer and the storage schema before any
   real matcher's failure modes enter the picture;
2. the runner and the raw-result store;
3. decision policies and native thresholds;
4. the first real adapter;
5. evaluation and reporting.

The dummy adapter comes first on purpose: it lets the architecture be tested
while a bug is still unambiguously the harness's fault.
