# V2 component decisions — evidence-backed

Each decision cites the validation-log test (T#) that grounds it. "Validated"
means: it ran here, produced usable output, on ≥1000 dpi-class data, and
integrated with the neighbouring components — not that a README said so.

## D1 — Pore detector: survey-repo FCN, features=40 checkpoint  ✅ validated
- **Choice:** `azimIbragimov/Fingerprint-Pore-Detection-A-Survey`, out-of-the-box
  model `40`, window 17, upstream NMS parameters. MIT, PyTorch, weights in-repo.
- **Evidence:** T1 (runs; F=0.711 vs bundled GT on 50 images; overlays
  anatomically correct; ~0.2 s/img CPU), T3b (f=64 alternative measured worse,
  F=0.515), T3/T5a (downstream EER proves detector quality is sufficient).
- **Alternatives rejected:** f=64 (recall-poor, T3b); Dahia small-FCN
  (weights login-gated; its reimplementation is inside the survey repo anyway);
  DeepResPore/PoreNet detectors (no code anywhere); filipspes YOLO (no license).
- **Open upgrade:** retraining on L3-SF folds via upstream `train.py` if a
  higher F is ever needed; deferred — matcher-level EER already lands on the
  literature's operating point.

## D2 — Pore descriptors + matcher: Dahia SIFT + `matching.spatial`  ✅ validated
- **Choice:** `utils.sift_descriptors` (scale 4, CLAHE) + `matching.spatial`
  (Pamplona Segundo & Lemes 2015 spatial-consistency score), ratio thr 0.7 —
  all upstream code run in place (TF stubbed; opencv-contrib 3.4.18).
- **Evidence:** T3 (12 fingers: EER 4.27 %), **T5a (full R1 protocol, 148
  fingers, 3,700/10,878 pairs: EER 5.41 %** — matches Dahia's published SIFT
  figure of 5.87 % on real PolyU DBI with identical geometry).
- **Alternatives:** DP raw-patch descriptors (same file) — ranked below SIFT by
  upstream's own published numbers; not run. CNN descriptors (their strongest,
  3.05 % published) — **pending**: Drive weights login-gated from this machine;
  browser fetch is the single cheapest upgrade available (T2 action item).
- **License note:** dahia code is CC BY-NC-SA → research-fine; keep out of git
  (clone lives under gitignored third_party/), never redistribute.

## D3 — Standard-features channel: the benchmark's existing matchers  ✅ mechanics validated, role clarified
- **Choice:** unchanged — the five integrated engines; SourceAFIS used here as
  the locally runnable representative (bridge jar already built; 0 failures on
  366 pairs at declared 1200 dpi). VeriFinger remains the preferred production
  channel (strongest engine already integrated; also carries D5).
- **Evidence:** T5b — on 1200 dpi partials the minutiae channel **collapses**
  (EER 28.7 % vs pores' 4.27 % on identical pairs), reproducing Ramos &
  Marana's VeriFinger-on-PolyU result. Consequence: on partial/small-area
  high-res prints the pore channel is the *primary* signal, not a bonus —
  matching the literature and the scoped accuracy claim in the direction report.
- **Consequence for full prints:** the fusion payoff on full prints (where
  minutiae are strong) is untestable on L3-SF (no full prints) → needs
  IITI-HRF; the certified 1000→500 downsample leg (SP 500-306) remains the
  design for production, since every integrated engine is a 500 dpi design.

## D4 — Fusion: score-level, logistic frozen on development data  ✅ direction validated
- **Evidence:** T6 — parameter-free min-max sum improved EER over the better
  single channel (4.27 % → 3.35 %) even with a collapsed minutiae channel;
  leave-one-finger-out logistic was ~pore-alone at this N (66 impostors) —
  fusion *training* needs the larger dev cohort, exactly as the direction
  report prescribes (dev cohort from non-test SD300 subjects / IITI split).
- **No new tooling needed:** ~10 lines of numpy/sklearn; pyeer for reporting.

## D5 — Liveness: VeriFinger built-in PAD primary; retrained CNN fallback  ⏸ one activation away
- **Status (updated after T8):** the SDK is now ON this machine and fully
  verified — the public trial archive proved bit-identical to the pinned Stage
  11B artifact (SHA e30a0b60… match), all 17 runtime-manifest components
  digest-verified, the bridge compiles against it, and the PAD API surface is
  confirmed at bytecode level (`setFingersDetectLiveness` /
  `setFingersLivenessConfidenceThreshold` / `getLivenessConfidence` /
  `SPOOF_DETECTED`). Docs confirm finger PAD is single-image (faces need
  video; fingers don't). The ONLY gate left is license activation (30-day
  trial, on-by-default in the delivered SDK, online) — a vendor-terms decision
  reserved for David. Runbook has both routes:
  `scripts/verifinger_pad_smoke.md` (~30 min once approved).
- **Fallback (unchanged from research):** fine-tuned CNN on LivDet 2015
  (1000 dpi) + 2017/2019; `kongzhecn/dfdm` weights are reference-only (no license).
- **Validation data:** LivDet 2015 HiScan-PRO partition — request is critical
  path for ANY liveness claim; no local substitute exists.

## D6 — Data substrate: L3-SF validated; real-sensor confirmation pending
- L3-SF (bundled in survey repo, 740 pore-GT + full R1–R5) is **sufficient for
  development**: whole pipeline validated on it end to end.
- **Critical externals (requests, in priority order):** IITI-HRF (full-print
  1000 dpi fusion test + external accuracy anchor), LivDet 2015 (+17/19)
  (liveness), NIST SD302 (sensor diversity), SD300 B/C terms check.

## What is NOT yet decided (honest list)
- CNN pore descriptors vs SIFT (pending Drive weights — decide on measured EER delta).
- VeriFinger PAD adequacy (pending smoke test + LivDet 2015 APCER/BPCER).
- Whether detector retraining on L3-SF folds is worth it (decide after CNN-descriptor test).
- Full-print fusion gain magnitude (pending IITI-HRF).
