# 0017 — A research run includes the exact clean fpbench source revision in its environment fingerprint

## Status

Accepted. Implemented in `fpbench.core.provenance_models`,
`fpbench.provenance.software` and `fpbench.provenance.environment`.

## Context

A run already pins everything anyone would name first: the pair manifest, the cohort,
the algorithm and adapter versions, the machine, the execution profile, the seed. Two
runs whose fingerprints agree were meant to be the same experiment.

They can still produce different numbers. Between the pair manifest and the stored
result sits several thousand lines of Python that nothing in the run identity covers:

* how a request is serialised for the bridge, and therefore what the algorithm receives;
* how a failure is classified — a change to `failure_mapping.py` turns the same event
  from `MATCHING_FAILED` into `NO_SCORE`, and the denominators of a later metric move
  with it;
* what counts as an existing result during resume, and therefore whether a job is
  re-executed or skipped;
* what goes into `adapter_metadata`, which is the evidence a validator checks;
* what the audit considers an error.

None of that changes the adapter's version, the jar's digest or the machine. A change
to any of it is invisible in the current run identity, which means two genuinely
different bodies of evidence can land in the same directory and be indistinguishable
afterwards.

## Decision

**A research run captures the fpbench source revision, and folds it into the
environment before the run is derived.**

Concretely:

* `capture_software_provenance(repository_root, require_clean)` reads the commit and
  the working-tree state from git, plus the interpreter and the versions of the two
  third-party packages that touch persistence (`pyarrow`, `PyYAML`).
* `build_research_environment(...)` returns a *new* `EnvironmentReport` carrying those
  facts under `fpbench.source.*` and `fpbench.package`. The environment fingerprint is
  already inside the run fingerprint, so nothing about `RunDefinition` changes and every
  existing check that compares environments keeps working.
* **A research run requires a clean working tree.** `git status --porcelain` must be
  empty, untracked files included.
* Resuming a run under a different commit is a `ResearchPreflightError`. The original
  commit must be checked out, or a new run prepared.

There is no override, and that is the part worth defending. The obvious escape hatch —
record `source_tree_clean: false` and carry on — produces a receipt that names a commit
the run did not use, plus an unrecoverable delta. A year later nobody can reconstruct
what ran. "Commit it first" costs thirty seconds; the alternative costs the evidence.

Ordinary development is not held to this. `require_clean=False` reports whatever it
finds, including a tree with no git metadata at all, because the test suite has to run
inside a source distribution and a unit test is not evidence.

## Alternatives

**Record the revision without requiring cleanliness.** Rejected above: a dirty tree
makes the recorded revision misleading rather than merely incomplete.

**A `--force-dirty` flag for convenience.** Rejected. A flag that exists is a flag that
gets used at 2 a.m., and the resulting run is indistinguishable from a clean one
afterwards except for a boolean nobody re-reads.

**Hash the source tree instead of using git.** It would work without git and would
cover uncommitted edits honestly. Rejected because a content hash is not *recoverable*:
`git checkout <sha>` reproduces the code, `sha256 = a1b2...` does not.

**A new field on `RunDefinition`.** Rejected as redundant: the environment fingerprint
already reaches the run fingerprint, so this would be a second thing to keep in step
for no additional guarantee.

## Consequences

* Every commit produces a new `run_id`, **including a documentation-only commit.** This
  is intended and is the cost of the guarantee: the harness cannot tell which lines of
  a diff could change a result, so it treats them all as if they could.
* A long run must be executed from one commit. In practice: prepare, execute in as many
  sittings as needed, finalize, *then* commit the receipt.
* The receipt names a commit that a reader can check out, which is what makes the rest
  of the chain reproducible rather than merely recorded.
* CI and development are unaffected: nothing outside the research entry points requires
  a clean tree.
