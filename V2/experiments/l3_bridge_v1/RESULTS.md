# First L3 bridge execution — 12 September 2026

The bounded development pilot completed on native SD300B delivery images.
P1 and SourceAFIS produced a score for every planned pair. P2's original
ridge-scale preprocessing admitted too few images for a useful comparison.
These are operational findings, not a successful biometric evaluation.

Execution used clean source commit
`699bde574155a9d1aee37c7dd9f0301e3748e695` and the committed
[settings](settings.json). All three routes bound the same local plan SHA-256,
`8571cbf6be1d9a3bd036c03d0b61872b98bad35ef8998ad3eda42388f585babb`.
The original cohort, image manifests, reserved population and baseline evidence
were unchanged. The actual local cohort contained the expected 832 candidates
and 50 reserved subjects; the separate local delivery CSV matched all 50.
Twenty development subjects were selected before scoring, with no reserved
overlap, and only the first five were executed.

| Route | Planned | Executed | Scored | Failures | Blocked | Matcher calls |
|---|---:|---:|---:|---:|---:|---:|
| P1 — Survey f40 / SIFT / spatial | 250 | 250 | 250 | 0 | 0 | 250 |
| P2 — Experiment 004 / same SIFT / spatial | 250 | 250 | 4 | 246 | 0 | 4 |
| R — existing SourceAFIS bridge | 250 | 250 | 250 | 0 | 0 | 250 |

Executed includes logical pair attempts that inherited an attempted image
extraction failure. All 750 planned rows are present. No failure became zero:
P1's three native zero scores and SourceAFIS's 66 native zeros remain scores.

P1 extracted and described all 100 images once. P2 attempted all 100 images:
15 passed, 82 failed the original ridge-period dispersion guard, two exceeded
the frozen scale-factor band, and one had too few accepted tiles. Its four
scored pairs comprise one genuine and three impostors; the other 246 retain
their extraction failures. No guard, threshold, estimator, model or matcher
parameter was adjusted after these findings.

SourceAFIS performed 500 fresh template extractions through the unchanged
two-extractions-per-pair bridge. In the local summaries, `extraction_attempts`
counts the separate cached-image worker; its zero for R does **not** mean that
SourceAFIS skipped extraction. The raw bridge records carry `extraction_count=2`.

## Local availability and execution conditions

The historical P1 environment and checkouts were initially absent. The public
Survey f40 checkpoint and Dahia mirror were acquired into the external artifact
store and pinned by revision and bytes. P1 ran with Python 3.10.21, PyTorch
1.13.0/torchvision 0.14.0, NumPy 1.26.4 and OpenCV-contrib 3.4.18.65 on CPU,
with four Torch threads. P2 reused the existing Experiment 004 environment:
Python 3.12.14, PyTorch 2.11.0+cu128, NumPy 2.5.2 and OpenCV 4.13.0 on CUDA.
The requested seed40401 checkpoint matched both its size and SHA-256.
Both routes used P1's same SIFT/matcher environment. The existing SourceAFIS
3.18.1 bridge and Java 17 were available. No commercial acquisition or activation
was needed.

Summed recorded P1 time was 1.64 s for model loading, 249.46 s for detection,
8.43 s for descriptions and 5.38 s for pair comparisons, with image input time
recorded separately. P2 model loading took 1.40 s; successful preprocessing and
failed preprocessing took 1.01 s and 5.32 s respectively, inference 1.85 s,
description 0.66 s and pair handling 0.06 s. Most P2 pairs never invoked the
matcher. SourceAFIS recorded 184.42 s of template extraction, 5.62 s of matcher
initialization and 1.50 s of matching; the 250 bridge round trips totalled
260.72 s. These are sums of component measurements, not controlled speed
comparisons. P1 and R ran concurrently, and these conditions differ from
Stage 21C.

## Interpretation and next boundary

P1's genuine and impostor distributions overlap. P2's four-score subset cannot
support a comparison with the complete 250-pair routes. The dominant P2 obstacle
is ridge-period instability, not missing weights or inability to load the model.
P1 and R can technically support a later development expansion after review;
P2 needs a separately declared investigation/variant for full-print scale
estimation. The frozen variant and its failures must remain available.

No further subjects, SD300C, training, fusion, screening or reserved-test
evaluation were run. There is no supported superiority or FAR=0.1% claim:
200 impostors have a 0.5% empirical FAR step, and pairs share subjects/images.
The candidates are not asserted to be historically unexposed. The existing
Experiment 001 selection was checked as metadata and its overlaps retained in
the local report; the reserved cohort was not retrospectively corrected.

The local workspace holds the 20-subject list, input provenance, raw pair
records, combined CSV, detailed report and offline demonstration. Its examples
are the first genuine and impostor in manifest order, plus the first failure
(already the first genuine for P2). Model marks and descriptor correspondences
are not anatomical ground truth. Images, features, identifiers and raw scores
are not published in this repository. The pasted reports/workbook copies named
in the execution brief were not re-audited or used as manifest authority.

## Verification

- Base suite (`make test`'s pytest command): 6,916 passed, 288 skipped,
  351 deselected. Skips concern optional prerequisites; no test failed.
- Existing SourceAFIS suite with `FPBENCH_REQUIRE_SOURCEAFIS=1`: 203 passed.
- Focused bridge contracts: six passed; pinned P1 numerical checks: two passed;
  P2 numerical/checkpoint checks: three passed. Fixtures were synthetic.
- Publication hygiene: 569 passed, 21 skipped. Source-fingerprint and pinned
  verifier checks passed. Stage 21A, Stage 21B and final-baseline verification
  retained their published READY outcomes.
- Local result verification: three routes, 750 ordered pair rows, unchanged
  score/plan/identity bindings. All 115 successful pore templates had finite,
  in-bounds native coordinates and matching descriptor counts. The demo has six
  prescribed examples, 12 local image references and no external resources.
