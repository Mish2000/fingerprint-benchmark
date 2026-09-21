# Published stage history

This index connects the completed baseline and the candidate investigations
to their original evidence. Each outcome describes its own stage at closure;
it is not a fresh qualification of an external service or runtime.
For the current scope and setup, start with the [README](../README.md).

The [full chronological README before the presentation update](https://github.com/Mish2000/fingerprint-benchmark/blob/fd3e9b1a50c47e182ece70c991204c9246ce65fc/README.md)
remains in Git history. Its historical instructions should be read in that context.

## Foundations: phases 1 through 7B

The early work established dataset inventories, frozen pair protocols, resumable
execution, SourceAFIS integration, separate decision/evaluation layers and the
shared canonical 500 PPI image pipeline. NBIS was then built from the official
archives and checked against NIST reference outputs.
The [evidence index](../evidence/README.md), [architecture decisions](adr/README.md)
and [NBIS integration guide](../integrations/nbis/README.md) retain the details.

## Stage 7C — NBIS canonical raw execution

Published outcome: `stage_7c_finalization`.

[Evidence and original scope](../evidence/nbis-canonical500-raw/).

## Stage 8A — Modern matcher selection

Published outcome: `NO_MODERN_MATCHER_READY`.

[Evidence and original scope](../evidence/stage8a-modern-matcher-selection/).

## Stage 8B — FLX runtime qualification

Published outcome: `FLX_RAW_SCORE_EXECUTION_READY`.

[Evidence and original scope](../evidence/stage8b-flx-runtime-qualification/).

## Stage 8C — FLX canonical raw execution

Published outcome: `FLX_CANONICAL500_RAW_READY`.

[Evidence and original scope](../evidence/flx-canonical500-raw/).

## Stage 8D — Calibration infrastructure

Published outcome: `CALIBRATION_INFRASTRUCTURE_READY`.

[Evidence and original scope](../evidence/stage8d-calibration-infrastructure/).

## Stage 8E — Research purpose and third-party artifact policy

Published outcome: `RESEARCH_ONLY_THIRD_PARTY_POLICY_READY`.

[Evidence and original scope](../evidence/stage8e-research-only-policy/).

## Stage 9A — FLARE qualification

Published outcome: `FLARE_FULL_ROUTE_BLOCKED`.

[Evidence and original scope](../evidence/stage9a-flare-artifact-qualification/).

## Stage 10A — Fourth-algorithm candidate audit

Published outcome: `ALGORITHM4_PREFLIGHT_NO_SURVIVOR`.

[Evidence and original scope](../evidence/stage10a-algorithm4-candidate-preflight/).

## Stage 10B — id3 Finger SDK qualification

Published outcome: `ID3_FINGER_SDK_PREFLIGHT_FAIL`.

[Evidence and original scope](../evidence/stage10b-id3-finger-sdk-preflight/).

## Stage 11A — VeriFinger qualification

Published outcome: `VERIFINGER_PREFLIGHT_PASS`.

[Evidence and original scope](../evidence/stage11a-verifinger-2025_2-preflight/).

## Stage 11B — VeriFinger canonical raw execution

Published outcome: `VERIFINGER_CANONICAL500_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage11b-verifinger-canonical500-raw/).

The published execution is `run_a76145fb5ab2` with plan
`plan_c32e4b7b0c8a`. Adapter median 1,804 ms.
These are historical execution identifiers and aggregate timing, not a new run.

## Stage 12A — Innovatrics IDKit qualification

Published outcome: `IDKIT_PREFLIGHT_FAIL`.

[Evidence and original scope](../evidence/stage12a-idkit-preflight/).

## Stage 13A — FingerCell qualification

Published outcome: `FINGERCELL_PREFLIGHT_FAIL`.

[Evidence and original scope](../evidence/stage13a-fingercell-preflight/).

## Stage 14A — Griaule acquisition and qualification

Published outcome: `GRIAULE_PREFLIGHT_INCOMPLETE`.

[Evidence and original scope](../evidence/stage14a-griaule-preflight/).

## Stage 15A — fingerprints-matching package execution

Published outcome: `FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage15a-fingerprints-matching/).

## Stage 16A — FingerFlow route audit

Published outcome: `FINGERFLOW_ROUTE_CLOSURE_FAIL`.

[Evidence and original scope](../evidence/stage16a-fingerflow/).

## Stage 17A — fingerprintMatcher score-contract audit

Published outcome: `FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL`.

[Evidence and original scope](../evidence/stage17a-fingerprintmatcher/).

## Stage 18A — SecuGen and OpenAFIS private reference

Published outcome: `SECU_GEN_OPENAFIS_PRIVATE_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage18a-secugen-openafis-reference/).

## Stage 19A — MINDTCT and OpenAFIS composition

Published outcome: `MINDTCT_OPENAFIS_CANONICAL500_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage19a-mindtct-openafis/).

## Stage 19B — OpenAFIS capacity extension

Published outcome: `MINDTCT_OPENAFIS_CAPACITY_EXTENDED_CANONICAL_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage19b-openafis-capacity-extended/).

## Stage 20A — MCC SDK route qualification

Published outcome: `MINDTCT_MCC_SDK_V2_ROUTE_PASS`.

[Evidence and original scope](../evidence/stage20a-mcc-sdk-preflight/).

## Stage 20B — MINDTCT and MCC SDK execution

Published outcome: `MINDTCT_MCC_SDK_V2_CANONICAL_RAW_COMPLETE`.

[Evidence and original scope](../evidence/stage20b-mindtct-mcc-canonical500-raw/).

## Stage 21A — Final comparison protocol freeze

Published outcome: `FINAL_BASELINE_EVALUATION_PROTOCOL_READY`.

[Evidence and original scope](../evidence/stage21a-final-baseline-evaluation-protocol/).

## Stage 21B — Cross-subject execution

Published outcome: `FINAL_BASELINE_CROSS_SUBJECT_RAW_RESULTS_READY`.

[Evidence and original scope](../evidence/stage21b-cross-subject-baseline-expansion/).

## Stage 21C — Final six-route comparison report

Published outcome: `FINAL_BASELINE_TAR_FAR_FRR_REPORT_READY`.

[Evidence and original scope](../evidence/final-baseline-tar-far-frr/).

The [final TAR/FAR/FRR report](../evidence/final-baseline-tar-far-frr/final-baseline-report.md)
is the comparison result. The [runbook](experiments/final-baseline-pipeline-runbook.md)
distinguishes offline evidence verification from execution with private inputs.

## Separate V2 development work

[The L3 bridge pilot](../V2/experiments/l3_bridge_v1/README.md) and
[P2 scale-repair study](../V2/experiments/l3_bridge_scale_repair/README.md)
are separate development experiments. Their conclusions do not change the
frozen Stage 21A–21C baseline or establish a new official external system.
