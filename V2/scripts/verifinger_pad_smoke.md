# VeriFinger PAD smoke test — runbook

**Status 2026-08-27 (updated):** the trial SDK archive is now ON this machine —
`C:\Users\david\fpbench-third-party\neurotec\Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`
(downloaded directly from Neurotechnology, no registration; contains VeriFinger
2025.2) plus the full 124 MB API documentation PDF. What is still missing here
is a **license**: running PAD needs either (route 1) the Stage 11B machine's
already-activated trial, or (route 2) activating a fresh 30-day trial on this
machine — a vendor-terms decision reserved for David. Nothing below needs SD300.

**Question this answers (decisive for the V2 liveness architecture):** does
`Fingers.DetectLiveness=true` produce a liveness verdict/confidence for a
**single stored PNG** with no scanner attached — or does the engine refuse
stored images for PAD?

## What the shipped 2025.2 documentation now confirms (extracted 2026-08-27)
From `Neurotec_Biometric_SDK_Documentation.pdf` (pages cited):
- **p65 (Fingerprint Attributes table):** "Liveness — `Fingers.DetectLiveness` —
  It is possible to check if **live fingerprint image is used, as opposite to
  paper scans**, etc. `Fingers.LivenessConfidenceThreshold` can be used to
  customize which minimal liveness value is still considered live fingerprint."
  → PAD is an attribute computed on the image, listed alongside Quality /
  TooWet / TooDry — no device or video requirement anywhere in the finger docs.
- **p546 (NBiometricEngine reference):** `FingersDetectLiveness` — "Enable
  fingerprint presentation attack detection. Examples of attacks: silicone
  fingerprint." `FingersLivenessConfidenceThreshold` is a byte, **range
  [0, 100]**.
- **p522:** the verdict is read back per finger from
  `NBiometricAttributes.LivenessConfidence` (byte) — "presentation attack
  detection confidence value" — next to `Quality` and `Status`.
- **Contrast, p41:** *face* liveness explicitly "requires a stream of
  consecutive images (usually a video stream)". No such sentence exists for
  fingers → single stored PNGs are the intended finger-PAD input. (Still to be
  confirmed by execution, not assumed.)
- Delivered defaults (pinned by the benchmark's bridge from Stage 11A):
  `Fingers.DetectLiveness=false`, `Fingers.LivenessConfidenceThreshold=0` —
  with threshold 0 nothing gets rejected, so the smoke reads the raw
  confidence first, then tests thresholded rejection.

## Status upgrade 2026-08-27, after the acquisition sweep (validation-log T8)

Everything short of the license now EXISTS AND IS VERIFIED on this machine:
- Archive `C:\Users\david\fpbench-third-party\neurotec\Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`
  — SHA-256 `e30a0b60…bafdc` = **bit-identical to the benchmark's pinned
  Stage 11B archive** (configs/verifinger/verifinger_runtime_manifest_v1.json).
  The public trial download IS the canonical pinned SDK.
- All **17 runtime-manifest components verified bit-for-bit** after extraction
  to `C:\Users\david\fpbench-third-party\neurotec\sdk/` (8 classpath jars, Fingers.ndf +
  FingersMatching.ndf model data, Win64 natives).
- The benchmark's bridge **compiles cleanly** against these jars →
  `C:\Users\david\fpbench-third-party\neurotec\bridge-build/fpbench-verifinger-bridge.jar`
  (sha256 04682086…64e4).
- Exact Java API surface confirmed by `javap` on the shipped bytecode:
  `NBiometricEngine.setFingersDetectLiveness(boolean)`,
  `NBiometricEngine.setFingersLivenessConfidenceThreshold(byte)` [0–100],
  per-finger verdict `NBiometricAttributes.getLivenessConfidence()` → short,
  and rejection status `NBiometricStatus.SPOOF_DETECTED` (2025.2's name; the
  old `LivenessCheckFailed` from MegaMatcher 12.x is gone).
- Trial terms extracted from the shipped `Activation.pdf` (p7/p9/p23/p38):
  30-day trial, **trial mode is enabled by default in the SDK as delivered**,
  activation via Activation Wizard (Windows) or manual config `Trial = true`;
  constant internet connection required while the trial runs.

## Choose a route first
- **Route 1 — Stage 11B machine (no new license):** use the activated trial
  there; follow the procedure as written.
- **Route 2 — this machine (needs David's explicit go-ahead, ~15 min):**
  run the Activation Wizard from the extracted SDK in Trial mode (or the
  manual `Trial = true` config), keep internet up, then run the freshly built
  `bridge-build/fpbench-verifinger-bridge.jar` with the natives dir on
  `java.library.path`. Activation = accepting Neurotechnology's trial terms
  for this machine — that acceptance is David's decision to make.
- Read the finger's attributes after extraction: the number we want is
  `getLivenessConfidence()` (short, PAD confidence).

## Procedure (~30 minutes)
1. Copy `integrations/verifinger-java` to a scratch dir **outside** the
   benchmark tree (this is a V2 experiment, not a Stage 11B rerun).
2. In `VeriFingerBridge.java`: the `EXPECTED_DEFAULTS` table pins
   `{"Fingers.DetectLiveness", "false"}` / `{"Fingers.LivenessConfidenceThreshold", "0"}`.
   In the scratch copy, after the defaults check, SET
   `Fingers.DetectLiveness = "true"` (leave the confidence threshold 0 first).
3. Feed any 500 ppi grayscale PNG of a real fingerprint (a canonical_500
   artifact, or any FVC-style sample). Record:
   - extraction `NBiometricStatus` (expect `OK`, or `LIVENESS_CHECK_FAILED`-class),
   - any liveness confidence attribute on the finger object
     (check `NFinger`/`NBiometricObject` attributes in the 2025.2 javadoc —
     search the shipped documentation for "LivenessConfidence"),
   - whether template extraction still succeeds.
4. Repeat with `Fingers.LivenessConfidenceThreshold = "50"` to see thresholded
   rejection behaviour on the same image.
5. Repeat for ~5 live-looking prints and, if available, any spoof-like image
   (even a photographed/printed fingerprint photo re-scanned) to see the score move.

## Interpretation
| Observation | Consequence for V2 |
|---|---|
| Confidence returned for stored PNGs, moves between images | **Primary liveness path confirmed** → plan LivDet 2015 (1000 dpi) APCER/BPCER validation next |
| Engine returns `OK` but no liveness attribute anywhere | Check javadoc for the correct property/attribute name; retry with `Fingers.LivenessConfidenceThreshold > 0` and look for `LIVENESS_CHECK_FAILED` |
| Engine refuses stored images for PAD (device-only error) | Vendor PAD drops out → fallback = retrained CNN on LivDet 2015/2017/2019 (see validation log T-PAD notes) |

## Record results
Append findings (statuses, attribute names, values per image) to
`V2/notes/validation-log.md` under a `T4 — VeriFinger PAD smoke` heading.
