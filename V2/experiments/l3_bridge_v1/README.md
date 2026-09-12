# L3 bridge v1 — first development execution

This bounded pilot connects two existing pore detectors to the same SIFT and
spatial-matching components on original SD300B delivery pixels. It is outside
the frozen baseline. [ADR 0141](../../../docs/adr/0141-l3-bridge-is-a-bounded-development-pilot.md)
defines the boundary; [settings.json](settings.json) pins the actual sources,
weights, environments and parameters used here.

P1 is Survey FCN f40 → Dahia SIFT → Pamplona Segundo/Lemes spatial score.
P2 replaces the detector with Experiment 004 seed 40401 and keeps the same
descriptor and matcher runtime. They are configurations of a composite chain,
not independently published complete systems. R uses the existing SourceAFIS
Java 3.18.1 bridge, with PLAIN as probe and explicit 1000 PPI. SourceAFIS
internally normalizes to 500 PPI; it is not a pore method.

## Population and scope

Read the actual `sd300_50_subjects_test_22f8d52a7478` cohort's 832 candidates.
Exclude its 50 subjects across all fingers, releases and derivatives. Sort the
remaining 782 by SHA256 of UTF-8 `"l3-bridge-v1-dev\0" + subject_id` (a NUL byte,
not two printable characters), breaking ties by subject id. Reserve the first
20 as **development**, then execute only their first five, in that order.

The first execution has 100 images, 50 same-subject/same-finger genuine pairs,
and 200 ordered different-subject/same-finger PLAIN→ROLL impostor pairs. The
existing SD300 mapping supplies PLAIN 11→finger 1 and 12→finger 6. No multi-finger
capture, SELF eligibility, registration success, score or quality filter can
select the population. Missing/failed inputs are not replaced.

The 20 are not claimed to be historically unexposed. The actual Experiment 001
selection is read as metadata to document known exposure. No reserved image or
baseline score is read. The local delivery's 50-subject CSV is checked against
the actual cohort when supplied. The pasted audit reports and four workbook
copies mentioned in the brief are not substitutes for these artifacts.

Only this first execution is authorized by this protocol. A 20-subject run,
SD300C, fusion, training, broad parameter search, additional screening and
reserved-test evaluation need a later protocol. There is no full-run switch.

## Native coordinates and component behavior

- P1 divides gray8 by 255 and uses the unchanged f40 model in evaluation mode.
  Eight valid stride-one 3×3 convolutions reduce each dimension by 16. Output
  tiles of 256 receive 16 pixels of overlapping input; the stitched prediction
  gets one global upstream NMS (probability 0.65, box 17, IoU 0.2). There is no
  resize or padding. Synthetic non-square whole/tiled predictions are compared.
- Survey `writeCoordinates` writes **zero-based row,column plus 8**. The old
  V2 driver's extra subtraction by one is not carried into this new variant.
  Convert row,column to x,y, with no additional offset. Historical results and
  the old driver remain unchanged.
- P2 loads exactly the requested seed40401 checkpoint (28,986,281 bytes, SHA-256
  `06ce96be30f336b48ee19f9107cbd19c83f2b4253dc1aa62440f84f43b60cfcb`). The
  manifest's threshold 0.72 is a detection threshold, not a match decision.
  Keep its original ridge estimator: 256 tiles/128 stride, periods 5–64,
  at least five accepted tiles, MAD/median ≤0.25, target period 34.0 and factor
  band [0.2,1.5]. No widening from Experiment 004's contingency is inherited.
  Estimator failures and rejected factors remain failures, with the estimate.
- P2 uses the original percentile 1/99 clipping, CLAHE 2.0 with 8×8 grid,
  gray8-to-[0,1], tiles 512, overlap 64 and cosine ramp 32. The upstream code
  reflect-pads bottom/right to at least 512 and removes padding after blending.
  It resizes using `fx=fy=factor`, AREA below one/CUBIC otherwise. Convert
  detector x,y back to the original frame by `(p+0.5)/factor-0.5`, including
  OpenCV pixel centres; retain actual shapes, factor and transform.
- Both routes describe the original native gray8 at these original coordinates.
  Dahia's helper takes row,column and swaps internally before OpenCV KeyPoint.
  Pass reversed x,y deliberately; verify against explicit OpenCV keypoints on
  a non-square synthetic image. Its median blur 3, CLAHE clip 3, SIFT scale 4,
  and squared-distance ratio threshold 0.7 remain unchanged. Both use OpenCV
  3.4.18.65, NumPy 1.26.4 and the same unmodified Dahia checkout.
- Spatial scoring requires no successful geometric alignment. Upstream returns
  zero with zero or one correspondence; this is a valid score. Exceptions,
  failed scale estimation, missing models and missing runtimes are not zeros.
  No score normalization or operating threshold is introduced.

## Local setup and execution

Use the repository environment for orchestration (`.venv/Scripts/python` here).
The pore worker has its own Python 3.10 environment outside the checkout; the
existing Experiment 004 environment is used only for its detector. No dependency
or source in `fingerprint-new-method` is changed.

The original P1 checkout/environment were absent on this machine. Public source
and the f40 checkpoint were acquired into the external third-party store using:

```text
git clone --depth 1 --filter=blob:none --sparse https://github.com/azimIbragimov/Fingerprint-Pore-Detection-A-Survey.git <survey-dir>
git -C <survey-dir> sparse-checkout set architectures util out_of_the_box_detect/models
git clone --depth 1 --filter=blob:none --sparse https://github.com/xiaochengcike/high-res-fingerprint-recognition.git <dahia-dir>
```

The exact acquired revisions and used-file hashes are in `settings.json`.
Reproduction must check out those revisions, not a later branch tip. Acquisition
does not establish new upstream rights; sources and checkpoints stay outside
Git under the repository's third-party handling policy. No commercial setup is
needed. Dependencies installed in the isolated pore environment:

```text
torch==1.13.0 torchvision==0.14.0 numpy==1.26.4
opencv-contrib-python==3.4.18.65 scipy==1.15.3 tqdm psutil pytest
```

Create an ignored `workspace/l3-bridge-v1/local.json` with these path keys:
`workspace`, `data_root`, `survey_dir`, `dahia_dir`, `method_dir`, `pore_python`,
`p2_python`, `java`, `jar`, and optionally `reference_subject_manifest` (the
local 50-subject delivery CSV). `data_root` contains `sd300b/`; `method_dir`
is the existing `fingerprint-new-method` checkout. Do not put local paths in
the public settings. `pin` is the one-time, create-only artifact-inventory step
used before the implementation commit; reproduction uses the committed pins.

```powershell
.venv/Scripts/python V2/experiments/l3_bridge_v1/run.py prepare --local workspace/l3-bridge-v1/local.json --out workspace/l3-bridge-v1/first-five
# Run the checks below, commit the implementation, and keep the tree clean.
.venv/Scripts/python V2/experiments/l3_bridge_v1/run.py run --route P2 --local workspace/l3-bridge-v1/local.json --out workspace/l3-bridge-v1/first-five
.venv/Scripts/python V2/experiments/l3_bridge_v1/run.py run --route P1 --local workspace/l3-bridge-v1/local.json --out workspace/l3-bridge-v1/first-five
.venv/Scripts/python V2/experiments/l3_bridge_v1/run.py run --route R --local workspace/l3-bridge-v1/local.json --out workspace/l3-bridge-v1/first-five
```

`prepare` freezes selection and all 250 pairs before copying/opening the 100
selected inputs. It verifies original delivery checksums, and copies bytes
unchanged to opaque local filenames. Workers receive these paths and pair
aliases only, without subject identities or truth. Each route can run separately
on the same committed source. Do not edit or commit while any route is active.
An existing route directory is refused, preserving every attempted execution.

In the P2 environment (NumPy is needed for the local demo), run:

```text
<p2-python> -B V2/experiments/l3_bridge_v1/report.py --out workspace/l3-bridge-v1/first-five
<p2-python> -B V2/experiments/l3_bridge_v1/report.py --out workspace/l3-bridge-v1/first-five --verify
```

Each route retains `identity.json`, `scores.csv`, `summary.json`, raw per-pair
JSON, worker logs and per-image records. Pore coordinates and descriptors remain
in local NPZ files. `identity.json` binds source revision, settings, weights,
runtime versions and the frozen plan. Image input, model loading, extraction,
description and comparison timing fields are retained where available. Shared
image extraction timings must not be summed once per pair. SourceAFIS keeps its
existing two extractions/JVM per pair contract; its templates are not cached.

The combined report, CSV and offline `demo.html` remain local. Demo examples are
the first genuine, first impostor and first failure per route in manifest order.
Originals, pore marks and descriptor correspondences are toggleable. This is a
development demonstration, not anatomical annotation or evidence of superiority.

`executed = scored + failures`; `planned = executed + blocked`. Executed counts
logical pair attempts, including propagated attempted-extraction failures;
`matcher_invocations` is a separate count. Missing resources block a route.
All score distributions and atomic-tie sweeps explicitly use scored-only
denominators. With 200 impostors the empirical FAR step is 0.5%; the pilot cannot
establish FAR=0.1%. No EER from the historical V2 implementation is reused.

## Verification

```text
python -m pytest tests/unit/test_l3_bridge_v1.py -q
python -m pytest -m "not dataset and not sourceafis and not full_run"
python -m pytest tests/contract/test_evidence_carries_no_absolute_paths.py tests/contract/test_published_workbooks_obey_adr0030.py tests/contract/test_stage_registry.py tests/contract/test_source_fingerprints_are_pinned.py -q
python scripts/stage21a_freeze.py --verify
python scripts/stage21b.py verify
python scripts/final_baseline.py verify
```

Numerical checks require real local dependencies and fail if their configured
sources are absent. Set `FPBENCH_L3_SURVEY_DIR` and `FPBENCH_L3_DAHIA_DIR`, then
run `test_numerical.py` with `pore_python -B -m pytest`. Set
`FPBENCH_L3_METHOD_DIR`, then run `test_p2_runtime.py` with
`p2_python -B -m pytest`. All numerical fixtures are synthetic; no reserved
fingerprint is opened. Do not collect these optional tests in the base suite.
