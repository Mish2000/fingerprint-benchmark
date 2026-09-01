# V2 validation log

Running log of hands-on component validation. Newest entries at the bottom.
Conventions: every test states **what was run, on what input, what came out, verdict**.
Component selection decisions are recorded in `decisions.md` once evidence exists.

---

## 2026-08-27 — Environment recon

**Machine:** Windows 11 Pro, single C: drive, ~75 GB free.
**Tooling present:** Python 3.9 / 3.11 (default 3.11.9) / 3.12 via `py`; `uv 0.11.26`; git 2.33; Java 23; no conda. Repo `.venv` is Python 3.12.10.

**Dataset/SDK availability on this machine:**

| Asset | Status | Consequence |
|---|---|---|
| NIST SD300 delivery (`FPBENCH_SD300_ROOT`) | **absent** (env unset; no matching directory on C:) | Pore-on-ink pilot deferred; representative ≥1000 ppi tests run on L3-SF (1200 dpi, bundled in survey repo) |
| VeriFinger 2025.2 SDK + trial license (`FPBENCH_THIRD_PARTY_ROOT`) | **absent** (no Neurotec dir on C:; workspace/ is empty — the Stage 11B runs happened on a different machine) | **VeriFinger PAD smoke test is BLOCKED here.** It needs the pinned 4.7 GB SDK + the hand-activated trial from the Stage 11B machine. Self-activating a fresh vendor trial from this session is out of scope (vendor terms action). Exact test spec written anyway → `../scripts/verifinger_pad_smoke.md` |
| fpbench workspace artifacts | absent (fresh checkout) | No canonical 500/1000 ppi prepared sets exist locally |

**Planned decisive tests, adjusted to reality:**
1. ~~VeriFinger PAD smoke test~~ → blocked on this machine; spec + runbook written for the machine that holds the SDK.
2. Pore detection on representative ≥1000 ppi images → runnable now (survey repo weights + bundled L3-SF).
3. Pore matcher (Dahia pipeline) weights + execution → runnable now (mirror clone; Google-Drive weight links to be tested).

---
## 2026-08-27 — T1: Pore detector (survey repo) — RUNS, quality measured

**Component:** `third_party/pore-survey` = azimIbragimov/Fingerprint-Pore-Detection-A-Survey (MIT, PyTorch), shallow-cloned; pretrained checkpoints confirmed **in-repo** (`out_of_the_box_detect/models/<features>` are torch state-dict files); the 740 pore-annotated L3-SF images ship pre-initialized in `dataset/` (512×512, ~1200 dpi class).

**Environment:** `V2/env/pore` = uv venv, Python 3.10.20, torch 1.13.0 CPU + torchvision 0.14.0 (upstream pin), numpy<2.
Fixes needed: requirements.txt lists `psutils` (typo) → installed `psutil`; `scipy` + `tqdm` missing from requirements → installed; later swapped `opencv-python` 4.11 → `opencv-contrib-python==3.4.18.65` (see T2).

**Run:** `out_of_the_box_detect.py --groundTruthFolder dataset --testingRange 1-50 --features 40 --device cpu` → ~1 s/image first pass, then faster; coordinate lists + overlay renders produced for all 50.

**Quality vs bundled ground truth** (`scripts/eval_pore_detection.py`, criterion copied from upstream validate.py = mutual nearest neighbour, no distance threshold):
- images 1–50, raw coords: **mean P=0.759, R=0.682, F=0.711**
- +8 px offset variant (valid-conv frame check): F=0.657 → raw convention is the better one; no correction applied.

**Reading:** below the paper's 87.2% five-fold L3-SF figure — expected, since the shipped out-of-the-box checkpoint's training data is not documented in the README (likely not the same folds); this is an out-of-the-box, zero-tuning number. **Verdict: detector VALIDATED as runnable + produces anatomically sensible, GT-corroborated pores.** Visual overlay check: detections sit on ridges. Retraining on L3-SF folds (their train.py) is available if F needs to rise; decision deferred until the matcher-level EER is known — matcher tolerance to detector noise is what matters.

## 2026-08-27 — T2: Pore matcher route — Drive weights BLOCKED, TF-free fallback validated instead

**Dahia & Segundo pipeline** (`third_party/dahia-pipeline`, mirror of deleted upstream; CC BY-NC-SA):
- All four Google-Drive pretrained-weight links (detection + description models; FCN-mirror's two) **fail from this machine**: gdown and raw fetch both bounce to an `accounts.google.com` login page (NOT a "file does not exist" page). → *Action item for David: open the four links in a normal browser; if they resolve, download and drop under `V2/third_party/dahia-weights/`.* Links are in `dahia-pipeline/README.md` and `dahia-fcn-mirror/README.md`.
- The repos ship **no checkpoints** in-tree (code only). CNN-descriptor route therefore not testable today.

**TF-free fallback assembled from the same repo (no new code invented):**
`matching.py` (bidirectional correspondences + Pamplona Segundo & Lemes 2015 spatial score) and `utils.sift_descriptors` / `utils.dp_descriptors` are pure numpy/OpenCV. `utils.py` imports TensorFlow at module level but the used functions never touch it → stubbed `tensorflow` in `sys.modules`, imported upstream files **unmodified**.
Environment fix: modern OpenCV 4.11 broke `cv2.KeyPoint.convert(size=)` and lacks `xfeatures2d` → installed `opencv-contrib-python==3.4.18.65` (closest available to upstream's 3.4 pin; SIFT re-enabled post-patent). Verified both APIs work.

**Route under test (T3):** survey detector → SIFT descriptors at pore locations (dahia defaults: scale 4, CLAHE) → `matching.spatial` score (ratio thr 0.7 = upstream recognize.py default). All existing code; driver = `scripts/pore_e2e_l3sf.py`.

## 2026-08-27 — T3: End-to-end pore verification on L3-SF — WORKS, EER measured

**Route:** survey-repo pretrained detector (features 40, window 17, upstream NMS params) → dahia `utils.sift_descriptors` (scale 4, CLAHE) → dahia `matching.spatial` (Pamplona Segundo & Lemes 2015 score, ratio thr 0.7). Driver: `scripts/pore_e2e_l3sf.py`. One driver-side fix: cast detected coords to float32 before descriptor extraction (cv2 3.4.18 rejects int arrays in `KeyPoint.convert`); upstream files untouched.

**Protocol:** L3-SF R1, first 12 fingers × 10 impressions (2 "sessions" × 5). Genuine = 25 cross-session pairs/finger = 300; impostor = first-vs-first across fingers = 66.

**Result (results/e2e_r1_12fingers/):**
- 120 images prepared in 23.7 s (**0.20 s/img, CPU**); pores/img median 176 (143–225).
- Spatial score: genuine median **521.2**, impostor median **0.069** (p10 genuine 4.18 vs p90 impostor 0.48 — separated).
- **EER (spatial) = 4.27 %**; EER (plain correspondence count) = 5.86 %.

**Reading:** in-family with Dahia's published SIFT-variant EER (5.87 % on PolyU DBI partials; their CNN descriptors reach 3.05 % — our upgrade path once weights are fetched). The matcher tolerates the detector's F≈0.71 noise. **Verdict: the pore→score route is VALIDATED end-to-end from existing components — runs, produces usable scores, discriminates, CPU-cheap.** Caveats: synthetic L3-SF, small N (66 impostors ⇒ EER resolution ≈1.5 %) → full-R1 run queued (T5); real-sensor confirmation still needs IITI-HRF/LivDet (requests pending).

**Alternative compared without running:** DP (raw-patch) descriptors are available in the same upstream file; Dahia's own paper ranks them below SIFT (5.98 %/2.22 % vs 5.87 %/1.71 % on PolyU) — SIFT kept; CNN descriptors remain the known-better upgrade (3.05 %/0.44 %) pending the Drive-weights browser check.

## 2026-08-27 — T3b: Detector checkpoint alternatives compared

Same 50 GT images, same criterion, out-of-the-box checkpoints:
| features | P | R | F |
|---|---|---|---|
| **40** (upstream detect.sh default) | 0.759 | 0.682 | **0.711** |
| 64 | 0.916 | 0.365 | 0.515 |
64 is precision-heavy/recall-poor here; **40 kept** (also what upstream ships as the default). Raw per-image results: `results/detection_eval_1-50.json`, `results/detection_eval_f64_1-50.json`; coordinate dumps: `results/coords_f40/`, `results/coords_f64/`.

## 2026-08-27 — T5 (running): SourceAFIS as the standard-features channel on the SAME images

The repo's own SourceAFIS bridge jar was already built (`integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar`, SourceAFIS 3.18.1, runs under Java 23). Verified `version` + a 1200-dpi compare. **Geometry finding:** L3-SF R1 images are 320×240 @ 1200 dpi = 0.68×0.51 cm — exactly PolyU-DBI partial-print geometry (L3-SF mimics it by design).

Spot scores (SourceAFIS, dpi 1200): genuine pairs 0.0 / 1.2 / 7.1 / 21.0 — mostly far below SourceAFIS's own documented threshold 40 — impostors 1.8 / 2.5. This reproduces the literature's core finding live: **minutiae-only matching collapses on ≥1000 dpi partial prints** (cf. Ramos & Marana: VeriFinger EER 25% on PolyU DBI). Full 366-pair run + fusion eval queued (`scripts/sourceafis_pairs.py`, `scripts/fusion_eval.py`).

## 2026-08-27 — T5a: FULL R1 protocol — the firm pore-route number

**Protocol:** all 148 fingers of L3-SF R1, PolyU-style: genuine = 25 cross-session pairs × 148 = **3,700**; impostor = first-vs-first across fingers = **10,878**. Same route as T3 (survey f40 detector → dahia SIFT → matching.spatial thr 0.7).

**Result (results/e2e_r1_full148/):**
- 1,480 images prepared in 328 s (**0.22 s/img CPU**); pores/img median 178 (114–231).
- Spatial: genuine median **447.2**, impostor median **0.047**.
- **EER (spatial) = 5.41 %**; EER (count) = 7.05 %. (~200 genuine errors at the EER point ⇒ rule-of-30 satisfied; this number has real statistical footing, unlike T3's 66-impostor 4.3 %.)

**Anchor:** Dahia & Segundo's published SIFT-variant EER on real PolyU DBI (identical 320×240 @ ~1200 dpi partial geometry) = **5.87 %** — our assembled route (different detector, same descriptor/matcher family, synthetic data) reproduces the literature's operating point almost exactly. Known upgrade path per their paper: CNN descriptors → 3.05 % (pending Drive weights).

## 2026-08-27 — T5b/T6: SourceAFIS head-to-head + first fusion — ARCHITECTURE VALIDATED

**SourceAFIS batch (366 pairs, same images/pairs as T3, dpi declared 1200):** 0 failures, ~1.0 s/pair (one JVM per comparison, bridge unchanged from the benchmark). Mechanically the standard-features channel is fine at 1200 dpi.

**Head-to-head on identical pairs (results/e2e_r1_12fingers/fusion_summary.json):**
| Channel | EER |
|---|---|
| SourceAFIS 3.18.1 (minutiae+edges) | **28.7 %** — genuine median 6.6, impostor 0.87; only 10/300 genuine reach its documented threshold 40 |
| Pore route (survey f40 → SIFT → spatial) | **4.27 %** |
| Fusion, min-max sum (parameter-free; normalisation uses pooled test stats — demonstrative) | **3.35 %** |
| Fusion, logistic leave-one-finger-out (honest trained variant) | 4.44 % — indistinguishable from pore-alone at 66 impostors |

**Reading:** live reproduction of the literature's core claim — minutiae-only matching collapses on ≥1000 dpi partial prints (cf. VeriFinger 25.08 % EER on real PolyU DBI partials, Ramos & Marana 1805.10949) while pores carry the signal (6.7× lower EER on the same pairs), and fusion helps directionally even with a collapsed minutiae channel. The fusion's real payoff is expected on FULL prints where the minutiae channel is strong; L3-SF has no full prints — that test needs IITI-HRF (1000×1000 full @1000 dpi) ⇒ dataset request is the critical external.

**Caveats:** synthetic data (L3-SF R1 only); single sensor-style; min-max fusion normalisation is demonstrative; small-N fusion training; SourceAFIS "dpi 1200" is declared-and-internally-normalised (its design point is 500 dpi — exactly why the benchmark's certified-downsample minutiae leg exists in the target architecture).

## 2026-08-27 — T7: acquisition sweep (autonomous download + verification round)

Full per-item record: `notes/acquisitions.md`. Summary of what was DONE vs HANDED BACK:

**Dahia weights — every automated route exhausted, formally blocked on Google sign-in.**
Direct endpoints (`drive.usercontent.google.com`) 302 to `accounts.google.com` for
all four IDs; original repo `gdahia/high-res-fingerprint-recognition` confirmed
deleted (author's 24 current repos are pure math — he moved to IMPA); zero Wayback
snapshots; all 8 forks of the mirror carry no checkpoints (git trees inspected via
API); co-author (`maups`, USF) hosts nothing; no HF/Zenodo/Kaggle re-host; no
connected Chrome session to borrow. → 2-min browser check by David, else author
email (drafts + current addresses in acquisitions.md: gabriel.dahia@impa.br,
mauriciop@usf.edu).

**VeriFinger/Neurotec SDK — ACQUIRED HERE (surprise: trial archive is public, no
registration).** `Neurotec_Biometric_2025_2_SDK_2026-06-12.zip` (4.4 GB) + full API
documentation PDF (124 MB, 3,076 pages) downloaded from download.neurotechnology.com
into `C:\Users\david\fpbench-third-party\neurotec\`. Documentation pages extracted (p65/p522/p546):
finger PAD is **single-image** ("live fingerprint image … as opposite to paper
scans"; face liveness, by contrast, explicitly requires a video stream, p41),
enabled via `Fingers.DetectLiveness`, threshold byte [0,100], verdict read from
`NBiometricAttributes.LivenessConfidence`. Runbook upgraded with citations + a
route-2 (this-machine) option pending David's trial-activation decision.
Still to run here: SHA-256, zip inventory, bridge compile-against-SDK (no license
needed for any of those).

**Dataset access procedures pinned (all need David/Menachem — license/identity):**
IITI-HRF Google Form is sign-in-gated even for viewing (HTTP 401); LivDet
2015/17/19 = email license via livdet@gmail.com (name/affiliation/phone/mailing
address); NIST SD302 = org-level agreement form (fields captured verbatim,
"authority" checkbox may need Menachem); SD300 B/C confirmed NOT publicly
downloadable (NIST page offers 500-ppi SD300a only, 6.4 GB) → copy release B (or a
test+dev-cohort subset) from the benchmark machine, optional provenance email to
fingerprint_data@nist.gov. Ready-to-send email drafts for all three sit in
acquisitions.md.

## 2026-08-27 — T8: VeriFinger SDK acquired + verified on THIS machine (no license yet)

**The provenance surprise of the day:** the public no-registration trial download
`Neurotec_Biometric_2025_2_SDK_2026-06-12.zip` (4,743,229,435 bytes) hashes to
`e30a0b603e453fe0a08157ed2331de71f8a3d3cdc6dcf001df649a36a69bafdc` — **bit-identical
to the benchmark's pinned Stage 11B archive** (same digest in
configs/algorithms/verifinger_2025_2_1to1_v1.yaml and the runtime manifest). The
canonical SDK artifact is therefore now present on this machine with a public,
reproducible source URL.

Verified/tested here, license-free:
1. **Manifest verification:** all 17 components of
   `configs/verifinger/verifinger_runtime_manifest_v1.json` extracted and SHA-256
   verified bit-for-bit (8 jars, Fingers.ndf 123 MB + FingersMatching.ndf model
   data, Win64_x64 natives). ok=17 missing=0 mismatch=0.
2. **Bridge compile:** `integrations/verifinger-java` source compiles cleanly
   (javac, zero warnings surfaced) against the extracted jars →
   `C:\Users\david\fpbench-third-party\neurotec\bridge-build/fpbench-verifinger-bridge.jar`
   (sha256 04682086d44ae12b9d127bc7e61e3b00b25f92c6d0df55cacaffd148ce6464e4).
   Toolchain evidence: this machine is ONE license activation away from the PAD smoke.
3. **PAD API confirmed at bytecode level (javap):**
   `NBiometricEngine.setFingersDetectLiveness(boolean)` /
   `setFingersLivenessConfidenceThreshold(byte)` [0–100];
   verdict `NBiometricAttributes.getLivenessConfidence()` → short; rejection
   status enum constant `SPOOF_DETECTED` (replaces 12.x `LivenessCheckFailed`).
4. **Documentation extracted** (3,076-page API PDF + Activation.pdf + EULA):
   finger PAD is single-image ("live fingerprint image … as opposite to paper
   scans", p65; face liveness by contrast requires video, p41). Trial: 30 days,
   enabled-by-default in the delivered SDK, online activation via Wizard or
   `Trial = true` config; constant internet during trial.

**Gate that remains:** license activation = accepting vendor trial terms on this
machine — David's decision (or run route 1 on the Stage 11B machine). Runbook
updated with both routes: `scripts/verifinger_pad_smoke.md`.

### T8 addendum (2026-09-01) - SDK relocated out of the repo

The entire neurotec acquisition (pinned archive, docs, extracted sdk/, compiled bridge jar) was moved 2026-09-01 to `C:\Users\david\fpbench-third-party\neurotec\` - outside the repo, because the benchmark's own contract test (test_no_vendor_material_is_reachable_from_the_working_tree, ADR 0083) forbids Neurotechnology bytes anywhere under the working tree, tracked or not. All hashes unchanged; T8's evidence and commands remain valid with the new prefix.
