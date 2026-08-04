# Stage 8A — modern matcher artifact qualification and selection

Final outcome: **`NO_MODERN_MATCHER_READY`**.

Stage 8A inspected the exact artifacts available for the three candidates that
were frozen before qualification.  It did not rank papers, read SD300, inspect
the existing SourceAFIS or NBIS results, execute any of the 6,000 benchmark
pairs, create an adapter or `ResultSet`, select a threshold, train, fine-tune,
reweight, calibrate, or compare biometric performance.

## Gate-first result

| Tier | Frozen candidate | Qualification status | Why it cannot proceed |
| --- | --- | --- | --- |
| A | `afr_net_official_artifact` | `ARTIFACT_INCOMPLETE` | The official paper was identified, but no official or author-supplied inference code, global/attention checkpoints, local-feature realignment pipeline, preprocessing, final comparator, or separate code/weights permissions were acquired. |
| B | `mgvit_official_artifact` | `ARTIFACT_INCOMPLETE` | The paper's code reference is a placeholder. No author artifact supplies the ViT checkpoint, minutiae-map generator/encoding, input fusion, preprocessing, or comparator. Substituting MINDTCT would create a new combined algorithm and was not allowed. |
| C | `flx_fixed_length_extractor` | `LICENSE_BLOCKED` | Source and an exact checkpoint were identified, but the weights licence and hold/execute permission are not established, dependencies are not version-locked, preprocessing has dataset-specific branches with no generic canonical-PNG route, and training provenance contains an unresolved conflict. |

Every mandatory gate is conjunctive.  Tier and the nine fixed tie-breakers are
considered only after all gates pass, so a high-tier paper cannot compensate
for missing executable material.  All three candidates were rejected by the
frozen selection policy; the reserve `id3_finger_sdk` was not activated.

## What was established for `flx`

The inspected author repository is commit
`7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13`.  The separately hosted checkpoint
is `best_model.pyt`, 875,770,140 bytes, SHA-256
`2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28`.
Checkpoint structure identifies
`DeepPrint_TexMinu_512_without_localization`: a 256-dimensional texture branch
and a 256-dimensional learned-minutia branch, each normalized independently
and both included in the direct one-to-one dot-product comparator.  No
pose input or localization branch is required by that exact variant; no
reweighting is applied, and no evaluation-cohort reweighting or paper-only
localization reconstruction was introduced.  The model configuration was
identified separately, while the runtime manifest remains missing.

Those static facts do not make the artifact runnable.  The unclear checkpoint
licence, unpinned runtime, non-general input route, unexecuted finite-score
check, untested SELF contract, missing offline bundle, absent operational
measurements and missing checkpoint-bound decision path remain explicit failed
gates.  Because static inspection failed, execution was forbidden: no smoke,
determinism or capacity result was invented from an unqualified runtime.
Source-code rights, checkpoint rights, third-party rights and upstream
training restrictions were reviewed as separate licence scopes; a source
licence was never treated as a checkpoint licence.

## Evidence authority

The publication contains exactly:

- `candidate-registry.json` — the pre-qualification candidate freeze;
- one `qualification-<candidate_id>.json` per frozen candidate;
- `selection-decision.json` — the gate-first policy applied to all reports;
- this README; and
- `stage-8a-finalization.json` — the last-written binding over every semantic
  fingerprint and every exact evidence-file SHA-256.

The reports publish metadata, hashes, licence conclusions and gate failures.
They do not publish model weights, proprietary source, licence keys, biometric
images, embeddings, representations, or observed raw scores.  The acquisition
manifests under `integrations/modern-matchers/manifests` remain the separate
commit-3 identities that the qualification reports embed and re-derive.

Re-verification is deliberately independent of benchmark workspaces:

```console
python -m fpbench.experiments.stage8a_modern_matcher_selection verify
```

The verifier reloads strict JSON, rejects duplicate or unknown fields,
re-derives the acquisition-bound qualification reports, applies the fixed
selection policy again, hashes the exact publication bytes, and fails closed
if any required artifact or evidence file is missing or changed.
Before reading production evidence it fixes registry, policy and acquisition
inputs to their exact repository paths, audits the Git diff from the Stage 7D
baseline, and rejects imports or path literals that could enter SD300, earlier
workspaces, or SourceAFIS/NBIS evidence.  A runnable candidate would also need
an embedded, identity-bound runtime probe with a fresh isolated-restart
attestation, exact runtime metadata, representation/score-profile bindings,
verified artifact size, and measurements against the limits frozen in the
selection policy.

## Next-stage gate

Because the outcome is not `MODERN_MATCHER_SELECTED`, Stage 8B is not opened.
Reconsidering id3 Finger SDK or VeriFinger requires an explicit new stage,
registry decision and legal/runtime qualification.  Stage 8A's requirements
and historical no-ready result are not relaxed retroactively.
