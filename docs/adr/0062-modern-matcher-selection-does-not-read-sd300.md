# 0062 — Modern matcher selection does not read SD300 or prior results

*Status: Accepted — 2026-08-04, stage 8A*

## Context

The modern matcher is intended for a later comparison on the project's
benchmark cohort. Choosing it after looking at that cohort would turn the test
data into selection data, even if the inspection used only a handful of images
or only an aggregate metric.

The same leakage can happen indirectly. Existing SourceAFIS and NBIS raw
results reveal which pairs and fingers are difficult. Prepared-image artifacts
reveal the exact evaluation inputs. Derivations reveal outcomes and eligible
subpopulations. Using any of them to prefer a candidate, tune a preprocessing
route, set a tolerance, choose an embedding branch or rescue a failed model
would optimize stage 8A against the evaluation workspace.

Artifact qualification does not require those inputs. Code, weights,
configuration, licences, synthetic smoke fixtures and runtime behavior are
enough to establish whether an implementation is complete and operational.

## Decision

Stage 8A selection is isolated from SD300 and from every earlier matcher result.
Its qualification and selection workflow must not read:

* the SD300 source images or metadata;
* `workspace/prepared/`;
* `workspace/results/`;
* `workspace/derivations/`;
* `evidence/sourceafis-*`; or
* `evidence/nbis-*`.

It does not run the canonical pair plan and does not produce a 6,000-pair
result set. The workspace gate proves those forbidden locations are not inputs
to stage 8A; the evidence documents record the assertion and bind it into
finalization.

Qualification may perform offline smoke, determinism and restart probes only
on non-biometric synthetic fixtures made for those checks. A fixture can prove
that the input contract, representation shape and comparator execute. It
cannot be used to rank biometric performance, derive a threshold or decide
which preprocessing looks best.

Candidate selection is derived solely from the frozen registry, exact artifact
manifests, hard-gate reports and frozen selection policy. First all failing
candidates are removed, then tier order applies, and only then do the nine
predeclared tie-breakers apply. No observation from SourceAFIS, NBIS or SD300 is
a selection feature.

This isolation remains binding when qualification fails. A missing general
input rule may not be repaired by seeing what makes SD300 load successfully,
and a nondeterminism tolerance may not be chosen by observing how much drift
would leave SD300 decisions unchanged.

## Alternatives considered

**Run a small SD300 pilot.** A smaller sample is still evaluation data. It would
make both candidate choice and any selected settings conditional on the cohort.

**Use only SELF comparisons.** SELF uses the same protected images and can still
select for image quality, preprocessing and failure behavior. It is not a
neutral operational fixture.

**Consult the existing SourceAFIS or NBIS failures without reading their
scores.** Failure locations are outcome information and would favor a candidate
because of its behavior on known hard cases.

**Use the papers' reported benchmark results to break ties.** Published results
are produced with different cohorts, protocols and often different artifacts.
The fixed tie-breakers deliberately concern provenance and integration
readiness, not incomparable accuracy claims.

## Consequences

Stage 8A cannot claim that a selected candidate is the most accurate on SD300.
It can claim only that any selection is the highest-priority frozen candidate
whose exact artifact passed every stated readiness gate. A no-ready outcome is
valid and must not trigger an evaluation-data search for a workaround.

A future benchmark run begins only after a candidate is qualified and selected
in an independent stage. Any future calibration must use a predeclared lawful
development cohort that is not SD300, and it must be a separate, explicitly
authorized stage.
