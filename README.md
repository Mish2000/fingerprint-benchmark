# fpbench — fingerprint recognition benchmark harness

A reproducible harness for comparing fingerprint recognition algorithms on NIST
Special Database 300 (releases A/500 ppi, B/1000 ppi, C/2000 ppi).

The organising principle:

> The harness owns the experiment. An algorithm never decides what runs, and
> infrastructure never changes an algorithm without saying so in writing.

---

## What exists right now

This is the first implementation stage: **datasets, protocol and manifest
storage**. It ends with a complete, reproducible experiment definition — which
images exist, which 50 subjects were chosen, and which 6,000 comparisons the
protocol calls for — with no algorithm involved.

| Package | Status | Responsibility |
|---|---|---|
| `fpbench.core` | built | shared vocabulary; stdlib only, imports nothing from the project |
| `fpbench.datasets` | built | what images exist on disk, and do they match their own declarations |
| `fpbench.protocols` | built | which subjects take part, and which comparisons that implies |
| `fpbench.storage` | built (manifests) | immutable manifests as parquet + JSON |
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
* **`storage` implements the manifest store only.** The result and artifact
  stores wait on the runner for the same reason.

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
for release in protocol.releases:
    release_images = list(provider.scan(release))
    release_subjects = summarise_subjects(release_images)
    store.write_images(release_images, dataset_id="sd300", release=release)
    store.write_subjects(release_subjects, dataset_id="sd300", release=release)
    images += release_images
    subjects += release_subjects

cohort = protocol.build_cohort(subjects)
pairs = protocol.build_pairs(cohort, images)

store.write_cohort(cohort)
store.write_pairs(pairs, protocol_id=protocol.protocol_id)
```

Produces, under `workspace/manifests/`:

```
datasets/sd300/SD300A/images.parquet      19,435 rows
datasets/sd300/SD300A/subjects.parquet       888 rows
datasets/sd300/SD300B/...
datasets/sd300/SD300C/...
protocols/sd300_50_subjects/cohort.json    50 subjects (of 832 eligible)
protocols/sd300_50_subjects/pairs.parquet   6,000 rows
```

Checking a release against its own declarations:

```python
report = provider.validate("SD300C")
report.is_clean        # True — the PPI defect is a warning, not an error
report.counts_by_code  # {'metadata_ppi_anomaly': 10115}
```

## The protocol

50 subjects that are complete in **all three** releases — ten anatomical
fingers, present as both plain and rolled impressions. 500 plain + 500 rolled
images per release. Simultaneous-capture slap images (FRGP 13/14) are excluded
at indexing time and can never enter a comparison.

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
SELF. That filtered set is a **derived view** written beside `pairs.parquet`;
the pair manifest itself is never modified.

Cohort selection is arbitrary but reproducible: candidates are sorted and
sampled with a recorded seed, and the full eligible pool is stored alongside the
50 winners so a later change to the eligibility rules cannot pass unnoticed.

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

## Open questions

One assumption is load-bearing and has not been confirmed:

* **How impostor pairs are built.** The protocol says "plain finger 1 against
  rolled finger 2". This implementation reads that as *the same subject's*
  finger *i* against finger *i+1* — the harder, more conservative construction.
  The alternative is pairing across subjects, which yields a different and
  more favourable false-match figure.
  See [ADR 0008](docs/adr/0008-non-mated-pairing-strategy.md); changing it is
  one config value.

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
