# Architecture Decision Records

Every decision that would be expensive to reverse, or that a reader of the code
would otherwise have to reconstruct, is written down here. A decision that
lives only in a conversation or in someone's head is not a decision the project
can be held to.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-protocol-from-adapters.md) | The protocol is independent of the algorithm | Accepted, implemented |
| [0002](0002-minimal-adapter-contract.md) | Adapters must implement `compare`, nothing more | Accepted, implemented |
| [0003](0003-decision-outside-adapter.md) | Thresholds are applied outside the adapter | Accepted, partly implemented |
| [0004](0004-sd300c-effective-ppi.md) | SD300C is used at 2000 ppi despite its metadata | Accepted, implemented |
| [0005](0005-immutable-raw-results.md) | Manifests and raw results are immutable | Accepted, implemented |
| [0006](0006-self-failure-semantics.md) | An operational failure is not a non-match | Accepted, implemented |
| [0007](0007-no-algorithm-branching-in-runner.md) | No algorithm-specific branching outside adapters | Accepted, implemented |
| [0008](0008-non-mated-pairing-strategy.md) | Impostor pairs shift the finger within a subject | Accepted, implemented |
| [0009](0009-one-immutable-result-per-job.md) | One immutable result file per job | Accepted, implemented |
| [0010](0010-adapter-context-excludes-ground-truth.md) | An adapter is told nothing about the comparison | Accepted, implemented |
| [0011](0011-immutable-deterministic-execution-plan.md) | Execution plans are immutable and deterministically derived | Accepted, implemented |
| [0012](0012-run-progress-is-derived.md) | Run progress is derived, never a stored counter | Accepted, implemented |
| [0013](0013-comparison-failure-does-not-invalidate-run.md) | A failed comparison does not make a run incomplete | Accepted, implemented |
| [0014](0014-algorithm-identity-describes-full-pipeline.md) | An algorithm identity names the complete pipeline | Accepted, implemented |
| [0015](0015-sourceafis-uses-stateless-java-bridge.md) | SourceAFIS runs in one stateless Java subprocess per comparison | Accepted, implemented |
| [0016](0016-sourceafis-receives-explicit-effective-dpi.md) | SourceAFIS receives the effective DPI explicitly | Accepted, implemented |
| [0017](0017-research-runs-pin-fpbench-source-revision.md) | A research run's identity includes its own clean source revision | Accepted, implemented |
| [0018](0018-external-runtime-assets-are-content-addressed.md) | External executables are copied into content-addressed runtime bundles | Accepted, implemented |
| [0019](0019-result-sets-have-independent-immutable-identity.md) | The ordered collection of result hashes has its own identity | Accepted, implemented |
| [0020](0020-research-finalization-follows-runtime-revalidation.md) | Research completion is external to batch execution | Accepted, implemented |
| [0021](0021-decision-profiles-are-immutable-and-external.md) | Thresholds and decisions are immutable derivations outside the adapter | Accepted, implemented |
| [0022](0022-decision-sets-bind-an-exact-result-set.md) | A decision set cites one exact result set and one exact profile | Accepted, implemented |
| [0023](0023-self-eligibility-is-profile-specific.md) | SELF eligibility is per release, per finger, per decision profile | Accepted, implemented |
| [0024](0024-conditional-mated-evaluation-requires-both-self-matches.md) | The conditional mated view needs both SELF decisions to match | Accepted, implemented |
| [0025](0025-same-subject-different-finger-is-a-sanity-check.md) | The cyclic impostor set is a sanity check, not an FMR experiment | Accepted, implemented |
| [0026](0026-metrics-name-their-denominators.md) | Every rate stores and names its exact numerator and denominator | Accepted, implemented |
| [0027](0027-attempt-and-decided-rates-are-separate.md) | Decision-conditional and attempt-level rates are separate metrics | Accepted, implemented |
| [0028](0028-pooled-metrics-sum-counts.md) | Pooled metrics sum counts across releases and divide once | Accepted, implemented |
| [0029](0029-conditional-results-must-report-selection.md) | A conditional result is published only with its selection fraction | Accepted, implemented |
| [0030](0030-negative-sanity-is-not-general-fmr.md) | The cyclic negative fraction is observed, never a false-match rate | Accepted, implemented |
| [0031](0031-canonical-resampling-is-shared-before-adapters.md) | Canonical resampling is experiment-wide; no adapter may implement its own | Accepted, implemented |
| [0032](0032-effective-ppi-controls-canonical-geometry.md) | Canonical geometry scales by manifest effective ppi, never by the file header | Accepted, implemented |
| [0033](0033-prepared-image-sets-are-immutable-reusable-evidence.md) | A prepared-image set is materialised once, content-addressed, verified and reused | Accepted, implemented |
| [0034](0034-pixel-and-encoded-identities-are-separate.md) | Raster identity and encoded-file identity are both retained | Accepted, implemented |
| [0035](0035-self-reuses-prepared-pixels-but-not-template-extraction.md) | SELF reuses one prepared artefact; independence is two extractions | Accepted, implemented |
| [0036](0036-paired-comparison-is-a-third-artefact.md) | A paired comparison has its own identity, under neither run | Accepted, implemented |
| [0037](0037-the-threshold-transfers-unchanged.md) | The documented threshold transfers to canonical inputs unchanged | Accepted, implemented |
| [0038](0038-conditional-rates-over-different-populations-are-not-subtracted.md) | Two rates over different populations are reported, never subtracted | Accepted, implemented |
| [0039](0039-adapter-contract-v1-remains-image-to-score.md) | The adapter contract stays two images to one score | Accepted, implemented |
| [0040](0040-research-orchestration-is-injected-not-algorithm-specific.md) | The research orchestration imports no algorithm | Accepted, implemented |
| [0041](0041-intermediate-templates-remain-adapter-local.md) | Templates are the adapter's working files, not a core model | Accepted, implemented |
| [0042](0042-runtime-bundles-support-multi-tool-pipelines.md) | A runtime bundle covers every tool that can change a score | Accepted, implemented |
| [0043](0043-two-stage-synthetic-adapter-proves-extensibility.md) | A synthetic two-stage adapter proves the contract before a real one tests it | Accepted, implemented |
| [0044](0044-research-evidence-is-algorithm-neutral-and-integration-bound.md) | Research evidence is algorithm-neutral and integration-bound | Accepted, implemented |
| [0045](0045-adapter-tools-own-files-and-process-trees.md) | Adapter tools own regular files and complete process trees | Accepted, implemented |
| [0046](0046-nbis-route-is-mindtct-plus-bozorth3.md) | The NBIS algorithm identity is MINDTCT and BOZORTH3 together | Accepted, implemented |
| [0047](0047-nbis-v1-runs-only-on-canonical-500ppi.md) | The NBIS route runs on canonical 500 ppi input only | Accepted, implemented |
| [0048](0048-nbis-input-is-direct-gray8-png.md) | MINDTCT is handed the prepared PNG, byte for byte | Accepted, implemented |
| [0049](0049-nbis-default-tool-options-are-part-of-identity.md) | The tool options this route does not pass are part of its identity | Accepted, implemented |
| [0050](0050-nbis-templates-remain-ephemeral.md) | NBIS templates live for one comparison and are then gone | Accepted, implemented |
| [0051](0051-nbis-full-run-reuses-sourceafis-canonical-pairs.md) | Stage 7C does not choose pairs; it reuses the canonical run's | Accepted, implemented |
| [0052](0052-stage-7c-publishes-raw-scores-only.md) | Stage 7C publishes raw scores, and nothing that interprets them | Accepted, implemented |
| [0053](0053-stage-7c-pins-one-certified-nbis-build.md) | Stage 7C names one certified NBIS build and refuses to guess | Accepted, implemented |
| [0054](0054-stage-7c-alignment-is-completion-authority.md) | Stage 7C alignment is part of completion authority | Accepted, implemented |
| [0055](0055-strict-threshold-comparators-preserve-legacy-profiles.md) | Strict comparators arrive under a second profile schema | Accepted, implemented |
| [0056](0056-decision-and-evaluation-orchestration-is-algorithm-neutral.md) | Decision and evaluation orchestration is algorithm-neutral | Accepted, implemented |
| [0057](0057-nbis-uses-nist-documented-score-greater-than-40.md) | NBIS decisions use NIST's documented score > 40 | Accepted, implemented |
| [0058](0058-cross-algorithm-operating-points-are-not-equated.md) | The two operating points are documented independently, not equated | Accepted, implemented |
| [0059](0059-unconditional-attempt-population-is-primary.md) | The unconditional attempt population is the primary analysis | Accepted, implemented |
| [0060](0060-cross-algorithm-comparison-never-subtracts-raw-scores.md) | A cross-algorithm comparison never touches raw scores | Accepted, implemented |
| [0061](0061-stage-8a-qualifies-artifacts-not-papers.md) | Stage 8A qualifies artifacts, not papers | Accepted, implemented |
| [0062](0062-modern-matcher-selection-does-not-read-sd300.md) | Modern matcher selection does not read SD300 or prior results | Accepted, implemented |
| [0063](0063-code-and-model-weights-have-separate-identities-and-licenses.md) | Code and model weights have separate identities and licences | Accepted, implemented |
| [0064](0064-preprocessing-is-part-of-the-algorithm.md) | Preprocessing is part of the algorithm | Accepted, implemented |
| [0065](0065-raw-score-readiness-does-not-imply-decision-readiness.md) | Raw-score readiness does not imply decision readiness | Accepted, implemented |
| [0066](0066-no-paper-reimplementation-is-accepted-as-an-upstream-algorithm.md) | No paper reimplementation is accepted as an upstream algorithm | Accepted, implemented |
| [0067](0067-a-stage-boundary-audit-covers-its-own-span.md) | A stage boundary audit covers its own span, not everything after it | Accepted, implemented |
| [0068](0068-local-execution-permission-is-not-a-licence-finding.md) | Local execution permission is not a licence finding | Accepted, implemented |
| [0069](0069-the-executed-algorithm-is-one-implementation-of-one-variant.md) | The executed algorithm is one implementation of one variant | Accepted, implemented |
| [0070](0070-one-extraction-is-a-duplicated-pair.md) | One extraction is a duplicated pair | Accepted, implemented |
| [0071](0071-the-stage-8b-transform-is-declared-not-inherited.md) | The Stage 8B transform is declared, not inherited | Accepted, implemented |
| [0072](0072-the-flx-runtime-is-a-bundle-pinned-by-bytes.md) | The flx runtime is a bundle, pinned by bytes | Accepted, implemented |
| [0073](0073-a-raw-score-is-a-decimal-and-is-never-clamped.md) | A raw score is a Decimal, and is never clamped | Accepted, implemented |
| [0074](0074-stage-8c-reuses-the-canonical-pair-and-input-authority.md) | Stage 8C reuses the canonical pair and input authority | Accepted, implemented |
| [0075](0075-logical-extractions-and-physical-forward-rows-are-different-counts.md) | Logical extractions and physical forward rows are different counts | Accepted, implemented |
| [0076](0076-stage-8c-publishes-no-score-distribution-or-decision.md) | Stage 8C publishes no score distribution or decision | Accepted, implemented |
| [0077](0077-stage-8c-finalization-binds-the-stage-8b-qualified-route.md) | Stage 8C finalization binds the Stage 8B qualified route | Accepted, implemented |
| [0078](0078-stage-8d-builds-calibration-infrastructure-without-calibrating.md) | Stage 8D builds calibration infrastructure without calibrating | Accepted, implemented |
| [0079](0079-calibration-data-must-be-development-not-evaluation.md) | Calibration data must be development data, not evaluation data | Accepted, implemented |
| [0080](0080-calibration-selects-native-score-boundaries-without-score-normalization.md) | Calibration selects native score boundaries, without score normalization | Accepted, implemented |
| [0081](0081-fpbench-is-personal-educational-research-only.md) | fpbench is personal educational research only | Accepted, implemented |
| [0082](0082-third-party-license-observation-is-separate-from-local-research-use.md) | A licence observation is separate from a local research-use decision | Accepted, implemented |
| [0083](0083-third-party-bytes-are-never-redistributed-by-fpbench.md) | Third-party bytes are never redistributed by fpbench | Accepted, implemented |
| [0084](0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md) | Ambiguous upstream rights may be risk-accepted without becoming a licence finding | Accepted, implemented |
| [0085](0085-stage-9-selects-the-full-flare-route.md) | Stage 9 selects the full FLARE route, not a runnable subset of it | Accepted, implemented |
| [0086](0086-flare-identity-is-fdd-d6-dualpose-dualenh-maxcosine.md) | The FLARE candidate identity is FDD D=6, dual-pose × dual-enhancement, max overlap-masked cosine | Accepted, implemented |
| [0087](0087-flare-score-affecting-upstream-gaps-must-not-be-guessed.md) | A score-affecting gap in the upstream sources is a blocker, not a decision for fpbench to take | Accepted, implemented |
| [0088](0088-flare-paper-route-and-public-code-must-resolve-to-one-transform-graph.md) | The paper route and the public code must resolve to one transform graph | Accepted, implemented |
| [0089](0089-algorithm-4-selection-requires-preflight-before-commitment.md) | Algorithm 4 is preflighted before it is committed to | Accepted, implemented |
| [0090](0090-adjusted-third-party-reimplementations-do-not-inherit-original-algorithm-identity.md) | An adjusted third-party reimplementation does not inherit the original algorithm's identity | Accepted, implemented |
| [0091](0091-benchmark-input-domain-compatibility-is-a-hard-candidate-gate.md) | Benchmark input-domain compatibility is a hard candidate gate | Accepted, implemented |
| [0092](0092-fpbench-does-not-invent-score-affecting-input-construction-to-admit-a-candidate.md) | fpbench does not invent score-affecting input construction to admit a candidate | Accepted, implemented |
| [0093](0093-algorithm-4-is-selected-only-among-hard-gate-survivors.md) | Algorithm 4 is selected only among hard-gate survivors, and never on reported performance | Accepted, implemented |
| [0094](0094-stage-10b-preflights-id3-before-algorithm-4-selection.md) | id3 is preflighted in a new stage, not added to Stage 10A | Accepted, implemented |
| [0095](0095-proprietary-access-and-research-use-are-separate-gates.md) | Operational access and research use are separate gates | Accepted, implemented |
| [0096](0096-evaluation-license-capacity-must-cover-the-frozen-workload.md) | An evaluation licence must be shown to cover the frozen workload | Accepted, implemented |
| [0097](0097-id3-extractor-and-matcher-defaults-are-part-of-algorithm-identity.md) | Extractor and matcher defaults are part of the algorithm's identity | Accepted, implemented |
| [0098](0098-id3-secrets-and-license-material-never-enter-public-evidence.md) | Licence material never enters public evidence or CI | Accepted, implemented |
| [0099](0099-stage-11a-qualifies-verifinger-from-the-artifact-itself.md) | Stage 11A qualifies VeriFinger from the artifact itself, not from vendor pages | Accepted, implemented |
| [0100](0100-preflight-acquires-when-upstream-publishes-a-direct-locator.md) | A preflight acquires when upstream publishes a direct locator | Accepted, implemented |
| [0101](0101-every-score-affecting-setting-carries-an-upstream-provenance.md) | Every score-affecting setting carries an upstream provenance, never an fpbench choice | Accepted, implemented |
| [0102](0102-a-native-transformed-score-is-a-raw-score.md) | A native transformed score is a raw score; fpbench converts nothing | Accepted, implemented |
| [0103](0103-network-for-licensing-is-not-network-in-the-computation.md) | Network for licensing is not network in the computation | Accepted, implemented |
| [0104](0104-a-preflight-that-was-not-run-is-not-a-preflight-that-failed.md) | A preflight that was not run is not a preflight that failed | Accepted, implemented |
| [0105](0105-one-upstream-sample-is-the-route-not-several.md) | One upstream sample is the route, not several | Accepted, implemented |
| [0106](0106-the-qualification-harness-must-be-able-to-reach-pass.md) | The qualification harness must be able to reach PASS, and must not overstate what it read | Accepted, implemented |
| [0107](0107-stage-12a-preflights-idkit-before-algorithm-5-selection.md) | Stage 12A preflights Innovatrics IDKit before Algorithm 5 selection | Accepted, implemented |
| [0108](0108-a-pending-acquisition-is-not-a-failed-candidate.md) | A pending acquisition is not a failed candidate | Accepted, implemented |
| [0109](0109-an-asymmetric-matcher-is-bound-by-protocol-not-normalised.md) | An asymmetric matcher is bound by protocol, not normalised | Accepted, implemented |
| [0110](0110-a-published-version-is-not-a-delivered-package.md) | A published version is not a delivered package | Accepted, implemented |
| [0111](0111-the-licence-clock-starts-after-the-harness-compiles.md) | The licence clock starts after the harness compiles | Accepted, implemented |
| [0112](0112-an-outstanding-action-is-not-a-failed-candidate.md) | An outstanding action is not a failed candidate | Accepted, implemented |
| [0113](0113-a-vendor-revision-hash-is-not-an-artifact-digest.md) | A vendor revision hash is not an artifact digest | Accepted, implemented |
| [0114](0114-a-sibling-product-runtime-never-answers-for-this-one.md) | A sibling product's runtime never answers for this one | Accepted, implemented |
| [0115](0115-the-bridge-compiles-before-the-trial-clock-starts.md) | The bridge compiles before the trial clock starts | Accepted, implemented |
| [0116](0116-the-binding-is-chosen-from-the-archive-not-in-advance.md) | The binding is chosen from the archive, not in advance | Accepted, implemented |
| [0117](0117-an-embedded-example-size-is-not-a-preprocessing-rule.md) | An embedded example size is not a preprocessing rule | Accepted, implemented |
| [0118](0118-settings-are-read-before-they-are-set.md) | Settings are read before they are set | Accepted, implemented |
| [0119](0119-pair-labels-come-from-the-api-under-test.md) | Pair labels come from the API under test | Accepted, implemented |
| [0120](0120-binary-metadata-asks-questions-the-runtime-answers.md) | Binary metadata asks questions the runtime answers | Accepted, implemented |
| [0121](0121-a-wait-and-a-chore-are-not-the-same-non-answer.md) | A wait and a chore are not the same non-answer | Accepted, implemented |
| [0122](0122-a-blocked-fetch-is-not-a-missing-route.md) | A blocked fetch is not a missing route | Accepted, implemented |
| [0123](0123-acquisition-is-tested-before-the-harness-is-built.md) | Acquisition is tested before the harness is built | Accepted, implemented |
| [0124](0124-a-vendor-internal-crop-is-algorithm-behaviour.md) | A vendor-internal crop is algorithm behaviour | Accepted, implemented |
| [0125](0125-opencv-is-part-of-this-algorithms-identity.md) | OpenCV is part of this algorithm's identity | Accepted, implemented |
| [0126](0126-self-service-acquisition-is-a-hard-requirement.md) | Self-service acquisition is a hard requirement for Algorithm 5 | Accepted, implemented |
| [0127](0127-an-upstream-refusal-is-an-outcome-not-a-rejection.md) | An upstream refusal is an outcome, not a rejection criterion | Accepted, implemented |
| [0128](0128-a-result-set-with-no-score-is-not-a-raw-matcher.md) | A result set with no score is not a raw matcher | Accepted, implemented |
| [0129](0129-a-dead-mirror-is-not-a-missing-artifact.md) | A dead mirror is not a missing artifact | Accepted, implemented |
| [0130](0130-a-candidate-is-not-replaced-because-of-its-scores.md) | A candidate is not replaced because of its scores | Accepted, implemented |
| [0131](0131-a-refusal-and-a-crash-are-different-outcomes.md) | A refusal and a crash are different outcomes | Accepted, implemented |
| [0132](0132-the-route-is-settled-by-authority-not-by-experiment.md) | The route is settled by authority, not by experiment | Accepted, implemented |
| [0133](0133-a-score-the-package-does-not-return-is-not-its-score.md) | A score the package does not return is not its score | Accepted, implemented |
| [0134](0134-a-reference-route-is-copied-not-improved.md) | A reference route is copied, not improved | Accepted, implemented |
| [0135](0135-the-translation-is-settled-from-source-not-from-scores.md) | The MINDTCT-OpenAFIS translation is settled from source, not from scores | Accepted, implemented |
| [0136](0136-a-modified-matcher-gets-its-own-identity.md) | A modified matcher gets its own identity, and an inertness proof | Accepted, implemented |
| [0137](0137-the-preference-is-frozen-before-the-scores-are-read.md) | The preference between two fifth methods is frozen before either is scored | Accepted, implemented |
| [0138](0138-the-adapter-is-handed-blinded-inputs.md) | An adapter is handed a per-run alias, not the catalogue's image id | Accepted, implemented |
| [0139](0139-one-writer-wins-and-the-loser-is-told.md) | One writer creates a file; the loser is told, never silently replaced | Accepted, implemented |
| [0140](0140-configuration-is-read-with-its-types.md) | Protocol configuration is read with its YAML types, and a cohort is checked | Accepted, implemented |

"Not yet implemented" means the decision is agreed and binding on the code that
will implement it, but that code is out of scope for the current stage.

ADR 0003 is *partly* implemented: raw scores are stored without any threshold
and the score direction travels with every result, which is the half that had
to exist before results could be written. The `DecisionPolicy` that consumes
them arrives with the decision layer.

## Format

```
# Title

## Status
## Context      what problem forced a choice?
## Decision     what did we choose?
## Alternatives what else was considered, and why not?
## Consequences what does this cost, and what does it buy?
```
