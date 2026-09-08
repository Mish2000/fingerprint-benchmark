# Working in fpbench

This is the shared working guide for coding agents. It routes you to the
repository's sources of truth; it does not replace their contracts or evidence.

## Find the governing sources

- Start with [README.md](README.md) for current high-level state and the project map.
- Use [the ADR index](docs/adr/README.md) to locate established architectural and
  research decisions and their rationale, including decisions awaiting implementation.
- Follow [architecture guidance](docs/architecture/) and the relevant subsystem
  documents under `docs/`; [experiment documentation](docs/experiments/) supplies workflows.
- Check `configs/`, `src/fpbench/`, `integrations/`, and `evidence/` for concrete
  definitions, implementation and published state; `workspace/` holds local research artifacts.
- Treat tests, verifiers and publication/finalization checks as executable authority
  for enforced invariants. Find entry points in `Makefile`, `scripts/` and `.github/workflows/`.
- If sources disagree, surface the discrepancy with the relevant paths; do not
  silently select the interpretation that makes the task easiest.

## Before implementation

- Read the nearest relevant contracts and regression tests, and recent corrections
  affecting that subsystem. Read selectively; verify assumptions from artifacts.
- Before changing experiment semantics, algorithm identity, scoring or evaluation,
  package responsibilities, dependency boundaries, or evidence/finalization behavior,
  locate and inspect the governing ADR and implementation contract.
- An apparent implementation requirement is not permission to change an established
  invariant. If the task conflicts with a frozen contract, surface the conflict
  before implementing the conflicting change.
- For integrations, follow [adding an algorithm](docs/architecture/adding-an-algorithm.md),
  [research integration](docs/architecture/research-adapter-integration.md), and
  [conformance](docs/architecture/adapter-conformance.md). If shared runner, storage
  or decision semantics seem to need changes, first document whether this exposes
  a missing extension point or a genuine contract change; preserve extension boundaries.

## Preserve experiment meaning

- The harness owns cohort selection, pair generation and experiment semantics.
  Adapters must not choose what runs, alter the protocol, or learn pair ground truth
  ([ADR 0001](docs/adr/0001-separate-protocol-from-adapters.md)).
- Keep shared infrastructure algorithm-agnostic and preserve package dependencies;
  consult `tests/unit/test_import_boundaries.py` and the integration contracts.
- Infrastructure must not silently change biometric meaning through preprocessing,
  DPI, score transforms, failure mapping or thresholding. Algorithm identity covers
  the full route; decisions belong outside adapters. Never substitute a score for
  an operational failure; inspect the route's failure contract.

## Research stages and evidence

- Before stage work, read `evidence/README.md`, the stage's README and publication/finalization contract.
  Identify predecessor bindings, frozen configs, source closures and generated documents.
- Preserve sealed/finalized evidence and hash-bound sources under the stage contract.
  Never hand-edit finalization artifacts or re-freeze/republish just to make checks pass:
  downstream evidence binds the old fingerprints. Corrections require the stage's explicit
  supersession/reissue procedure and publisher, accounting for downstream bindings.
- Source closures cover ordinary shared harness files, too. Before edits (including prose
  or line endings), inspect `.gitattributes`, `tests/contract/test_source_fingerprints_are_pinned.py`,
  the Stage 8A/8B/8C sets in `tests/contract/test_pinned_verifier_sources_are_untouched.py`,
  and Stage 21B's closure in `src/fpbench/stage21b/source_freeze.py`.
- This public repository is for [personal educational research](docs/policy/research-only-purpose.md).
  Follow [artifact handling](docs/policy/third-party-artifact-handling.md): commit acquisition
  code/provenance, never upstream code/archives, weights/checkpoints, runtime bundles,
  datasets, fingerprint images or embeddings. Keep licence/credential material out of Git,
  public evidence and CI ([ADR 0098](docs/adr/0098-id3-secrets-and-license-material-never-enter-public-evidence.md)).
- Distinguish implementation, qualification and raw-execution work from biometric
  evaluation wherever the stage contract does; completion of one does not authorize another.
- Read sealed [Stage 21A](evidence/stage21a-final-baseline-evaluation-protocol/) and
  [Stage 21B](evidence/stage21b-cross-subject-baseline-expansion/) evidence as predecessor bindings.
  Cross-roster score reading and final evaluation belong to `src/fpbench/final_baseline/`; follow the
  [final-baseline runbook](docs/experiments/final-baseline-pipeline-runbook.md).

## V2 boundary

[V2/README.md](V2/README.md) describes exploratory high-resolution research support,
not authority to modify or reinterpret the frozen baseline or publish final benchmark claims.
Before future-method work, inspect Stage 21A's
[test reservation](evidence/stage21a-final-baseline-evaluation-protocol/high-resolution-test-reservation.json)
and [ADR 0079](docs/adr/0079-calibration-data-must-be-development-not-evaluation.md).
Do not train or tune parameters/thresholds on reserved test data, or treat another
resolution of the same physical cards as an independent development set.

## Verification

- Run the narrowest relevant tests during development. Before declaring a general
  change complete, run `make test` and the appropriate subsystem suites. Follow
  [README Setup](README.md#setup), `pyproject.toml` and workflows for environment activation,
  marker prerequisites and required-runtime/skip behavior before selecting tests.
- Research runs must meet their clean-source/revision requirements ([ADR 0017](docs/adr/0017-research-runs-pin-fpbench-source-revision.md));
  do not commit in a checkout while a research run is active.
- For documentation/publication changes, run `make publication-hygiene` (or its
  listed pytest command). Use the stage's verifier and publication checks after permitted
  stage/evidence changes; CI success does not override a failed repository verifier.
- Offline Stage 21 checks are `python scripts/stage21a_freeze.py --verify` and
  `python scripts/stage21b.py verify`; these verify evidence without running matchers.
  For a published final-baseline report, run `python scripts/final_baseline.py verify`.
- Report external/acquisition or unavailable-runtime failures separately from
  semantic/contract failures; a blocked fetch does not prove an algorithm failed.

## Documentation and scope

- Update README when current state, supported capability, the architecture map,
  major stage status or a deliberate omission changes, respecting evidence bindings.
- Register new published stages in `src/fpbench/experiments/publication_registry.py`;
  preserve `stage_registry.py`, which is in Stage 21A's frozen source closure.
- Follow the ADR index policy for expensive-to-reverse architectural/research decisions;
  do not leave their rationale only in commit messages, conversations or code comments.
- Keep changes within the requested task: avoid speculative refactors, unrelated
  cleanup, historical terminology rewrites and changing frozen semantics for convenience.
- Keep this root guide the single shared instruction source; `CLAUDE.md` imports it.
  Do not duplicate README/ADR content or add nested guides, rules, skills or hooks
  without a demonstrated repository need.
