# V2 acquisitions — status, evidence, and exact human steps

Date: 2026-08-27. Goal: obtain every missing external for V2 (weights, datasets,
SDK), autonomously where possible. Rule applied throughout: nothing counts as
"available" until it is downloaded, verified, and exercised by a real test here.

## Status board

| # | Item | Autonomous result | Next actor | Where it lands |
|---|------|-------------------|-----------|----------------|
| 1 | Dahia pretrained weights (4 files) | **Blocked: Google sign-in wall** — every route exhausted (see A) | **David** (2-min browser check) or email to authors (draft below) | `V2/third_party/dahia-weights/` |
| 2 | IITI-HRF | Request form found; **form itself requires Google sign-in to view** | **David** (fill form) | `V2/data/iiti-hrf/` |
| 3 | LivDet 2015 (+2017/2019) | Procedure confirmed: email-based license | **David** (send email, draft below) | `V2/data/livdet2015/` etc. |
| 4 | NIST SD302 | Request form + fields fully documented; org-level agreement | **David** (+ possibly Menachem: "authority" checkbox) | `V2/data/sd302/` |
| 5 | NIST SD300 B/C | **Not publicly downloadable** (NIST page offers SD300a 500 ppi only, 6.4 GB). B/C already exist in the project's own delivery on the benchmark machine | **David** (copy from benchmark machine; optional NIST provenance email, draft below) | `V2/data/sd300/` |
| 6 | VeriFinger SDK | **Downloaded + fully verified here**: archive is bit-identical to the pinned Stage 11B artifact (SHA e30a0b60… match); 17/17 manifest components verified; bridge compiled; PAD API confirmed in bytecode | **Trial activation = David's call** (vendor terms) — then the PAD smoke runs here | `C:\Users\david\fpbench-third-party\neurotec\` |

Everything below records what was tried, the evidence, and the exact follow-up.

---

## A. Dahia pretrained weights — every automated route exhausted

The four Google Drive files (detection, description-CNN, small-FCN, Su-detector)
are the only copies in existence that we know of. What was tried today:

1. **Direct download endpoints** (`drive.usercontent.google.com/download?id=…`
   and `drive.google.com/uc?export=download`): all four IDs 302-redirect to
   `accounts.google.com/v3/signin` — Google demands an authenticated session
   even to see the file. This is not a "file deleted" page; the files may still
   exist behind the wall.
2. **gdown** (earlier session): same wall.
3. **Original repo**: `gdahia/high-res-fingerprint-recognition` is deleted
   (verified via GitHub API — his 24 current repos are math/teaching only;
   he moved fields to IMPA). No Wayback snapshot of the repo exists.
4. **All 8 forks of the mirror** (`xiaochengcike/high-res-fingerprint-recognition`):
   git trees inspected via API — none contains checkpoint files; no releases.
5. **Co-author's site/repos** (`maups`, Univ. of South Florida): no fingerprint
   weights hosted.
6. **Open web / HF / Zenodo / Kaggle**: no re-host found.
7. **Your connected Chrome**: no Chrome extension instance is connected to this
   account, so I could not try your logged-in Google session myself.

### → David, do this (2 minutes)
Open these four links in your normal browser (signed into any Google account):

1. detection: https://drive.google.com/uc?id=1U9rm_5za2kRU2FsviCe-qrZoouwUGyzI
2. **description CNN (the prize)**: https://drive.google.com/uc?id=16GiLG7xBj64SOjCJwlCfbBcb-DORzYg1
3. small FCN detector: https://drive.google.com/uc?id=15GRs23KQVc_yhJzL1fVzZ8uI4-U-xqcg
4. Su detector: https://drive.google.com/uc?id=1Qb1s7g1kcMYPdkOoUjXOlc6iNn1cCrHq

Outcomes:
- **Download starts** → we win. Put the files (likely `.tar.gz` or a folder of
  TF checkpoint files: `*.index`, `*.data-00000-of-00001`, `*.meta`) under
  `V2/third_party/dahia-weights/<detection|description|fcn|su>/`.
- **"You need access" page** → do NOT click "Request access" yet; instead send
  the author email below (the owner account is likely orphaned, so a request
  click may go nowhere).
- **"File does not exist"** → files are gone forever; the author email is the
  only remaining route.

### → Fallback: email the authors (draft)
To: `gabriel.dahia@impa.br` (owner of the deleted repo; now at IMPA)
Cc: `mauriciop@usf.edu` (co-author Maurício Pamplona Segundo, USF)

> Subject: Trained models from high-res-fingerprint-recognition (pore description CNN)
>
> Dear Dr. Dahia, Dear Prof. Pamplona Segundo,
>
> We are using your pore detection + description pipeline ("Automatic dataset
> annotation to learn CNN pore description for fingerprint recognition",
> arXiv:1809.10229) in an academic fingerprint-benchmark project. The GitHub
> repository survives via mirrors, and we have reproduced the SIFT-descriptor
> pipeline end to end, but the four pretrained-model Google Drive links in the
> README now require sign-in and appear inaccessible (the original account
> seems inactive).
>
> Would you be able to share the trained models again — in particular the pore
> description CNN checkpoint (README link id 16GiLG7x…), and ideally also the
> detection/FCN checkpoints? Any hosting works for us (Drive, Dropbox, e-mail
> attachment; the checkpoints were small). We use them for non-commercial
> research only, consistent with the repository's CC BY-NC-SA license, with
> full citation of your papers.
>
> Thank you for the excellent work — the pipeline reproduces beautifully.
>
> Best regards,
> David Even Haim

### What I will run when the weights arrive (already planned)
```bash
# 1) integrity: list checkpoint tensors without running anything
uv venv V2/env/tf --python 3.11
uv pip install --python V2/env/tf "tensorflow==2.16.2" "numpy<2"
V2/env/tf/Scripts/python - <<'EOF'
import tensorflow as tf
for p in ["V2/third_party/dahia-weights/description", "V2/third_party/dahia-weights/detection"]:
    ck = tf.train.latest_checkpoint(p)
    print(p, ck, [n for n,_ in tf.train.list_variables(ck)][:8])
EOF
# 2) smoke: descriptors for one L3-SF image via a TF1-compat driver (to write:
#    V2/scripts/dahia_cnn_descriptors.py — builds their description net with
#    tf.compat.v1, restores checkpoint, patch extraction at detected pores)
# 3) meaningful test: rerun the full R1 protocol with CNN descriptors replacing
#    SIFT; compare EER against the validated 5.41% SIFT baseline (expected ~3%)
```

---

## B. IITI-HRF (real 1000-dpi, full + partial prints) — form is sign-in-gated

- Page: https://pria-iiti.github.io/IITI-HRF/ — confirmed: access "exclusively
  through the Google Form"; contents: IITI-HRFP 6,400 partial (320×240),
  IITI-HRFC 6,400 complete (1000×1000), extended sets 9,536 each; ~149
  subjects, 1000 dpi.
- Form: https://forms.gle/GZhvBvYGJQgtfifN8 → redirects to
  `docs.google.com/forms/d/e/1FAIpQLSfKlJ0EKgSjtMm7KHcw4uBO-Kz5u0TU5BG_oloD8n2NGlrr5A/viewform`
  which returns **HTTP 401 without a Google login** — I cannot even read the
  questions from here.

### → David, do this (5 minutes)
1. Open https://forms.gle/GZhvBvYGJQgtfifN8 signed into Google.
2. Expect the usual academic-dataset questions: name, email, affiliation,
   supervisor/PI (use Menachem), intended use, agreement to cite + research-only
   terms. Answer for our project: "evaluation of pore-based high-resolution
   fingerprint recognition in an academic benchmark".
3. You should receive a download link (typically Drive/OneDrive) by email.
4. Unpack to `V2/data/iiti-hrf/` keeping their folder names
   (e.g. `IITI-HRFP/`, `IITI-HRFC/`, `…-E/` variants).

### What I will run when it arrives
```bash
# integrity: file counts must match 6400/6400/9536/9536; image geometry check
V2/env/pore/Scripts/python - <<'EOF'
import cv2, glob
for d, n, wh in [("IITI-HRFP",6400,(240,320)), ("IITI-HRFC",6400,(1000,1000))]:
    fs = glob.glob(f"V2/data/iiti-hrf/{d}/**/*.*", recursive=True)
    im = cv2.imread(fs[0], 0); print(d, len(fs), im.shape, "expect", n, wh)
EOF
# smoke: pore detector on 10 IITI images -> pore counts/overlays (real-sensor check)
# meaningful: full-print protocol — pore channel vs SourceAFIS vs fusion on
#   IITI-HRFC test split (the missing full-print fusion number, ~22k genuine pairs)
```

---

## C. LivDet 2015 / 2017 / 2019 — email-based license, single address

- Confirmed on livdet.org (registration page) and sites.unica.it/livdet:
  request by email to **livdet@gmail.com**, providing *Name, Affiliation, Email
  Address, Phone Number, Mailing Address*; a license agreement to sign comes
  back; 2017/2019 handled by the same PRA-Lab pipeline (their old
  livdet.diee.unica.it host is dead — cert now points at the new UNICA sites).
- LivDet 2015 is the critical one: its **HiScan-PRO partition is the only
  public ≥1000-dpi live+spoof corpus** — required for ANY liveness number.

### → David, send this (draft)
To: `livdet@gmail.com`

> Subject: Dataset request — LivDet Fingerprint 2015 (and 2017, 2019)
>
> Dear LivDet organizers,
>
> I would like to request access to the LivDet Fingerprint datasets for
> academic research: LivDet 2015 (all sensors — we are particularly interested
> in the HiScan-PRO 1000-dpi partition), and if possible also LivDet 2017 and
> LivDet 2019 for cross-edition validation.
>
> We are evaluating fingerprint presentation-attack detection as part of a
> university research project on pore-based high-resolution fingerprint
> recognition with liveness detection, and will use the data for research
> only, with citation of the corresponding LivDet competition papers.
>
> Requested details:
> - Name: David Even Haim
> - Affiliation: [university + department + supervisor: Menachem …]
> - Email: davidevenhai@gmail.com  [prefer your university address if you have one]
> - Phone: [fill in]
> - Mailing address: [fill in]
>
> I am happy to sign the license agreement. Thank you very much!
>
> Best regards,
> David Even Haim

You will receive a license PDF to sign, then download links.
Place under `V2/data/livdet2015/` (and `livdet2017/`, `livdet2019/`).

### What I will run when it arrives
```bash
# integrity: per-sensor Training/Testing counts vs the LivDet 2015 paper's table
# smoke: pore detector on 5 HiScan-PRO live images (1000 dpi real-sensor pores!)
# meaningful #1: VeriFinger PAD (once licensed) over the full HiScan-PRO test
#   partition -> APCER/BPCER per ISO 30107-3 — the decisive PAD number
# meaningful #2 (fallback path): fine-tune a small CNN on LivDet training split
```

---

## D. NIST SD302 — request form documented; org-level agreement

- Request URL: https://nigos.nist.gov/datasets/sd302/request (reachable; the
  form asks — verbatim): *Organization Name; Organization Mailing Address
  (Lines 1–3); Organization Country; Point of Contact Name; Point of Contact
  E-mail Address; Point of Contact Telephone Number*, plus four mandatory
  checkboxes: authority to accept on behalf of the organization; acceptance on
  behalf of all members; acceptance of dataset terms; acknowledgment that a
  NIST employee reviews requests. A **time-sensitive download link is emailed**.
- One request covers all parts SD302a–i (fingerprint images are a–d).
- **1000-ppi content confirmed** (NIST TN 2007, p13 — the SD302 technical
  report): all auxiliary devices ran at 500 ppi **except J, Q and R, which
  captured at 1000 ppi**; the delivery additionally contains *properly
  downsampled 500-ppi versions* of those images (per NIST IR 7839 — the same
  certified-downsampling lineage as SP 500-306). That means SD302 hands us
  real operational 1000-ppi captures WITH their certified 500-ppi twins —
  exactly the native-resolution pore-channel + downsampled minutiae-channel
  input pair of the V2 architecture, from NIST itself.

### → David (and possibly Menachem), do this
Fill the form with the university as Organization and yourself as POC. Note the
first checkbox asserts you have **authority to accept for the organization** —
if that is not true for you, have Menachem submit or approve it explicitly.
When the link arrives, download parts **302a–d** (images; skip latent/EBTS
parts e–i unless free disk allows) to `V2/data/sd302/`. Watch disk: keep ≥20 GB
free on C:.

### What I will run when it arrives
```bash
# integrity: NIST deliveries ship SHA manifests -> verify every file
# survey: enumerate capture devices + native resolutions from the delivery docs;
#   identify the 1000-ppi capture subsets
# smoke: pore detector on the 1000-ppi subset samples; pore counts vs 500-ppi
# meaningful: cross-sensor pore-channel scores (sensor-diversity evidence)
```

---

## E. NIST SD300 releases B/C — not public; the project already owns a copy

- Verified today on the NIST SD300 page: the download section offers **SD300a
  only (500 ppi PNG, 6.4 GB)** via the same nigos request flow. The 1000/2000
  ppi scans (B/C) are described in the text but not offered.
- The benchmark project already possesses the full delivery (releases A/B/C) on
  the machine that runs fpbench (this laptop has none of it).

### → David, two actions
1. **Copy from the benchmark machine** (fastest, already-licensed route): copy
   release **B (1000 ppi)** — or just the 50-subject test cohort + up to ~100
   development subjects — into `V2/data/sd300/B/`. Release C (2000 ppi) is
   optional; disk on this laptop is the constraint (68 GB free at last check;
   full delivery is ~113 GB, so a subset is the right call).
2. **Optional provenance email** to `fingerprint_data@nist.gov` (POC listed on
   the SD300 page):

> Subject: SD300 1000/2000 ppi releases (B/C) — availability and terms
>
> Dear Fingerprint Data team,
>
> We hold a copy of the NIST SD300 delivery including the 1,000 and 2,000 ppi
> scans (releases B and C) obtained for an academic benchmarking project, and
> are extending the benchmark to pore-level (Level-3) features at ≥1000 ppi.
> The public SD300 page currently lists only the 500 ppi release (SD300a).
> Could you confirm (a) whether releases B/C are still distributed on request,
> and (b) that continued research use of an existing delivery, including
> publication of aggregate benchmark results, is consistent with the dataset's
> terms? Happy to file a new request via nigos.nist.gov if that is preferred.
>
> Best regards, David Even Haim

### What I will run when a B-subset arrives
```bash
# integrity: spot-check SHA-256 against the delivery manifest from the
#   benchmark machine; PNG headers must decode as 8-bit gray at 1000 ppi scale
# smoke + meaningful: pore detector over inked 1000-ppi rolled/plain crops ->
#   pore counts + detection plausibility on INK (the open "pores on ink" pilot
#   from the direction report; decides whether SD300-based pore evaluation is
#   viable at all)
```

---

## F. VeriFinger / Neurotec SDK — acquired here today (trial archive is public)

- Discovery: Neurotechnology's download page serves the trial archive
  **directly, no registration**:
  `https://download.neurotechnology.com/Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`
  (4.4 GB; contains VeriFinger 2025.2 — same version line the benchmark
  pinned) and `Neurotec_Biometric_SDK_Documentation.pdf` (124 MB). Both are
  downloading/downloaded into `C:\Users\david\fpbench-third-party\neurotec\`.
- **All done and verified (validation-log T8):** the downloaded archive is
  **bit-identical to the Stage 11B pinned archive** (SHA-256
  `e30a0b603e453fe0a08157ed2331de71f8a3d3cdc6dcf001df649a36a69bafdc` — matches
  configs/verifinger/verifinger_runtime_manifest_v1.json exactly). All 17
  runtime-manifest components verified bit-for-bit after extraction; the
  benchmark's Java bridge compiles cleanly against the extracted jars
  (`C:\Users\david\fpbench-third-party\neurotec\bridge-build/fpbench-verifinger-bridge.jar`); the
  finger-PAD API confirmed at bytecode level
  (`setFingersDetectLiveness`/`setFingersLivenessConfidenceThreshold`/
  `getLivenessConfidence`→short/`SPOOF_DETECTED`); docs + EULA + activation
  guide extracted. The PAD smoke is exactly ONE trial-activation decision away.

### → David, one decision + (maybe) 30 minutes
Running PAD on THIS machine requires activating a **30-day trial license**
(online activation; vendor terms — your call, I did not activate anything).
Two routes, either is fine:
- **Route 1 (no new trial):** run the existing runbook
  `V2/scripts/verifinger_pad_smoke.md` on the Stage 11B machine that already
  holds the activated trial + 4.7 GB pinned archive.
- **Route 2 (this machine):** say the word and I flip trial mode on in the
  freshly downloaded SDK per its activation docs and run the PAD smoke here
  (internet-connected activation; counts as accepting Neurotechnology's trial
  EULA for this machine).

### What I will run once a licensed engine exists (either machine)
```bash
# smoke: runbook scripts/verifinger_pad_smoke.md — set Fingers.DetectLiveness=true,
#   feed stored PNGs, record NBiometricStatus + liveness confidence
# meaningful: once LivDet 2015 arrives -> APCER/BPCER on HiScan-PRO partition
```

---

## G. Explicitly de-prioritized (recorded so nothing is silently dropped)

- **SD300a (500 ppi)**: no pore value; also behind the same org-agreement form. Skip.
- **PolyU HRF**: withdrawn by PolyU; only unofficial copies circulate — using
  them would poison the benchmark's provenance discipline. Not pursued.
- **MR-SF** (multi-resolution synthetic): Google Form, optional; only if the
  L3-SF→real-sensor gap turns out to matter after IITI-HRF arrives.
- **DMD++ / FLARE weights**: optional PAD baselines; research-only riders;
  revisit only after LivDet data exists.
- **HiScan-PRO scanner** (~$415): only if self-collected live/spoof captures
  become a requirement.
