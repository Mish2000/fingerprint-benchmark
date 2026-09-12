# V2 — practical validation workspace

Self-contained experimental project for the pores + ≥1000 dpi + liveness
direction. Nothing here modifies the benchmark; third-party clones, envs and
bulk results are kept out of git (see `.gitignore`).

## Layout

The [L3 bridge first execution](experiments/l3_bridge_v1/README.md) is a separate,
bounded development pilot on original SD300B. Its source and artifact inventory
are checked locally; the historical environment/results below are not evidence
that those assets are installed on another machine.

```
V2/
├── notes/            validation-log.md (what was tested, what happened)
│                     decisions.md (component choices + why)
├── scripts/          runnable drivers + the VeriFinger PAD runbook
├── results/          scores, eval JSONs, coordinate dumps (gitignored)
├── env/              uv virtualenvs (gitignored)
│   ├── pore/         Python 3.10.20 · torch 1.13.0 CPU · opencv-contrib 3.4.18
│   └── dl/           downloader utils (gdown)
└── third_party/      clones + weights (gitignored)
    ├── pore-survey/        azimIbragimov/Fingerprint-Pore-Detection-A-Survey (MIT)
    ├── dahia-pipeline/     xiaochengcike mirror of Dahia & Segundo (CC BY-NC-SA)
    ├── dahia-fcn-mirror/   willamezhang mirror (small-FCN detector)
    └── dahia-weights/      (empty until the Drive links are fetched via browser)
```

## Architecture under validation

```
                       canonical ≥1000 dpi grayscale image
                          │                        │
              certified downsample            native resolution
                          │                        │
              standard-features matcher      pore detector (survey FCN, pretrained)
              (SourceAFIS here; VeriFinger        │
               on the SDK machine)           SIFT descriptors @ pores (dahia utils)
                          │                        │
                       score s₁              matching.spatial → score s₂
                          └────────────┬───────────┘
                              fusion (logistic, dev-frozen)
                                       │
                                 one raw score
   liveness: VeriFinger Fingers.DetectLiveness (primary, runbook) /
             retrained CNN on LivDet (fallback) — separate per-image score
```

## Reproduce

```bash
# env
uv venv env/pore --python 3.10
uv pip install --python env/pore "torch==1.13.0" "torchvision==0.14.0" \
  "numpy<2" "opencv-contrib-python==3.4.18.65" scipy tqdm psutil

# detector quality vs bundled ground truth (survey repo, 50 images)
cd third_party/pore-survey
../../env/pore/Scripts/python out_of_the_box_detect.py \
  --groundTruthFolder dataset --testingRange 1-50 --features 40 --device cpu
cd ../..
env/pore/Scripts/python scripts/eval_pore_detection.py \
  --survey-dir third_party/pore-survey --range 1-50

# end-to-end pore verification on L3-SF R1
env/pore/Scripts/python scripts/pore_e2e_l3sf.py \
  --survey-dir third_party/pore-survey --dahia-dir third_party/dahia-pipeline \
  --out-dir results/e2e_r1_12fingers --fingers 12 --device cpu

# standard-features channel on the same pairs (bridge jar from the benchmark)
env/pore/Scripts/python scripts/sourceafis_pairs.py \
  --pairs results/e2e_r1_12fingers/scores.csv \
  --images-dir third_party/pore-survey/L3SF_V2/L3-SF/R1 \
  --jar ../integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar \
  --dpi 1200 --out results/e2e_r1_12fingers/safis_scores.csv
env/pore/Scripts/python scripts/fusion_eval.py \
  --pore results/e2e_r1_12fingers/scores.csv \
  --safis results/e2e_r1_12fingers/safis_scores.csv \
  --out results/e2e_r1_12fingers/fusion_summary.json
```

## Results so far

See `notes/validation-log.md` for the full record. Headlines:

| Test | Result |
|---|---|
| Pore detector (survey, pretrained, f=40) on 50 GT images | runs, mean F = 0.711 (P 0.76 / R 0.68), ~0.2 s/img CPU |
| Detector alternative f=64 | F = 0.515 (recall-poor) → f=40 kept |
| End-to-end pore verification, 12 fingers (300 gen / 66 imp) | EER 4.27 % (spatial score); genuine median 521 vs impostor 0.07 |
| **Full R1 protocol** (148 fingers, 3,700 gen / 10,878 imp) | **EER 5.41 %** — matches Dahia's published 5.87 % SIFT figure on real PolyU DBI (identical geometry) |
| SourceAFIS on the identical 366 pairs @1200 dpi | **EER 28.7 %** — minutiae collapse on high-res partials, reproducing Ramos & Marana; 0 execution failures |
| Fusion on identical pairs | min-max sum **3.35 %** (beats both channels; demonstrative normalisation); LOO-logistic 4.44 % (small-N) |
| VeriFinger PAD smoke | SDK now **acquired + digest-verified here** (bit-identical to the pinned Stage 11B archive; bridge compiles; PAD API confirmed by javap) — needs only a trial activation (David's decision) — runbook: `scripts/verifinger_pad_smoke.md` |
| Dahia CNN descriptor weights | Drive links login-gated from here — browser check pending; SIFT route validated as stand-in (upgrade path: 5.4 % → ~3 % per upstream's paper) |

## Pending externals — see `notes/acquisitions.md` for exact steps + email drafts

Acquisition sweep ran 2026-08-27 (validation-log T7). Current state:

| Item | State |
|---|---|
| Neurotec/VeriFinger 2025.2 trial SDK + 124 MB API docs | **downloaded + verified here** (`C:\Users\david\fpbench-third-party\neurotec\`): archive bit-identical to the pinned Stage 11B artifact; 17/17 manifest components digest-verified; bridge compiled against it; PAD confirmed single-image, API surface confirmed by javap. Running PAD needs one thing: a trial activation (David's call) — or route 1 on the Stage 11B machine |
| Dahia weights (4 Drive files) | blocked on Google sign-in — David: open the four links (2 min) or send the author email draft |
| IITI-HRF | Google Form is sign-in-gated — David fills it (~5 min) |
| LivDet 2015 (+17/19) | email license — draft ready for livdet@gmail.com |
| NIST SD302 | org-agreement web form — fields documented; may need Menachem ("authority" checkbox) |
| SD300 B/C | not publicly downloadable (NIST offers 500-ppi A only) — copy release B / a subset from the benchmark machine |

Local data staging: `V2/data/` (gitignored).
