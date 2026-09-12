# Bounded P2 ridge-scale repair

This local continuation preserves the [first L3 pilot](../l3_bridge_v1/README.md)
and its 100 images / 250 pairs. See [ADR 0142](../../../docs/adr/0142-l3-scale-repair-is-a-separate-development-variant.md).
It is development work outside Stage 21A–21C. Per-image and pair results stay
private; this directory contains only code, tests, configuration and the protocol.

The changes are exactly:

1. `ridge.py` changes `90.0 - degrees(orientation)` to
   `degrees(orientation) - 90.0` in the versioned tile estimator.
2. The target is the median of reliable corrected estimates on the original
   Experiment 004 TRAIN partition: 440 images, 88 groups. Verify the original
   split, training protocol, hashes and image membership; create no new split.
3. P2R keeps [0.2,1.5]; P2R-wide declares [0.2,3.0] as secondary sensitivity.
   A rotation-only target-34/[0.2,1.5] policy is preprocessing diagnosis only.

The upstream source is `fingerprint-new-method@732099d9faef124bd030be564c1e751faf1e9c72`,
`src/fingerprint_new_method/experiment004_transfer.py`, SHA-256
`5e0f499b55781b6b744de88e6007b4ea0063733d1bea55b473454e9d92a5d2fc`.
The helper imports are read-only. There is no global function replacement.
The tile regression proves the AST difference is exactly the rotation expression.
[OpenCV's rotation convention](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html)
and direct synthetic gratings supply the geometric check; biometric outcomes
are not a substitute for that check.

Seed40401, its original SHA-256, threshold .72, NMS 2, normalization, CLAHE,
tiling, SIFT on original native pixels, matcher, lag window 5–64, minimum 5
tiles and MAD/median <= .25 remain unchanged. No scale clipping or fallback
is permitted. Corrected estimates are computed once per TRAIN/development image
and saved before any new detector inference.

## Local execution

Use the existing P2 and pore environments from the v1 private `local.json`.
No acquisition, training, new environment or external biometric upload is needed.
The review input's `verify_ridge_rotation.py` must first be run using
`--source-file` against the actual local source. Keep its JSON and a comparison
of the supplied versus actual AST digests. A mismatch is disclosed; matching
local/excerpt functions and pinned source bytes are checked separately.

The output must be a new ignored directory under `workspace/`. Before preparation
it contains the review inputs, probe JSON, source comparison JSON and a
`preserved_files.json` map of absolute private predecessor/source/evidence paths
to SHA-256. The original output is never written to. With `<P2_PYTHON>`,
`<LOCAL>`, `<PRIOR>` and `<OUT>` resolved from the existing configuration:

```text
<P2_PYTHON> -B -m pytest V2/experiments/l3_bridge_scale_repair/test_numerical.py -q
<P2_PYTHON> -B V2/experiments/l3_bridge_scale_repair/execute.py prepare --local <LOCAL> --prior <PRIOR> --out <OUT>
<P2_PYTHON> -B V2/experiments/l3_bridge_scale_repair/execute.py run --local <LOCAL> --out <OUT>
<P2_PYTHON> -B V2/experiments/l3_bridge_scale_repair/readout.py --out <OUT>
<P2_PYTHON> -B V2/experiments/l3_bridge_scale_repair/execute.py verify --local <LOCAL> --out <OUT>
<P2_PYTHON> -B V2/experiments/l3_bridge_scale_repair/readout.py --verify --out <OUT>
```

Set `FPBENCH_L3_METHOD_DIR` for direct numerical-test invocation. Ordinary
dependency-free regressions are `tests/unit/test_l3_bridge_scale_repair.py`.
Preparation also runs numerical checks before estimating TRAIN.

The current task explicitly requests no commits. Preparation archives actual
working bytes in `source_snapshot.zip`, with `source_snapshot.json` and
`implementation.patch`. The base commit is not misrepresented as executed
source. The snapshot must remain unchanged during estimation and inference.
All writes refuse replacement of completed artifacts. A failed precondition is
diagnosed rather than overwritten or silently resumed under different code.

`preprocessing_manifest.json` binds the new target only to TRAIN, the estimator
and the unchanged checkpoint. `scale_audit.csv` retains original versus corrected
tile counts, periods, MAD/median, coherence where available, factors and reasons
under all three policies. Original coherence was not stored and is not invented.

Workers receive aliases, image hashes and saved scale estimates, without pair
truth. Wide executes each eligible image and pair physically once. Primary
eligibility is retained independently; only eligible byte-identical templates
and pair results are reused with explicit hash-bound links. Every route retains
250 outcomes. Original P1/P2/R records are checked and reused without inference.

## Private readout

`scores_comparison.csv` contains 1,250 rows with consistent opaque aliases,
pair IDs, kind, route, score/status/reason and identity links. It contains no
image, weight, template or descriptor. `summary.json` and `readout_he.md`
report coverage and the preregistered descriptive 1%/5% FAR points for P1, R,
P2R and P2R-wide. Original P2 is primarily coverage/failure context.

Atomic ties use `score >= cut`. Maximize TA subject to FAR, then minimize FA,
then maximize cut; accept-none is explicit. TA/50, FA/200 and (50-TA)/50 retain
the full attempt population. Failures are separate operational nonacceptance,
not matcher rejections. Missing scored classes make comparison unsupported.
These cuts are descriptive only; no operating threshold or claim of superiority,
FAR=.1%, external evaluation or independent binomial uncertainty follows.

`demo.html` uses exactly the v1 examples frozen before the repair, with original
local image references and optional pore/correspondence overlays. It never
selects new examples by success. Keep the page and review bundle local.
Delivery ends this experiment regardless of coverage; do not expand or tune.
