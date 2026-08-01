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
