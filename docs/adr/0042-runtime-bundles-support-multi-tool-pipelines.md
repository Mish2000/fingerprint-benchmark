# 0042 — A runtime bundle covers every tool that can change a score

*Status: Accepted — 2026-08-01, stage 7A*

## Context

docs/adr/0018 established that a research run pins its executable by content:
the bytes are copied into an immutable, content-addressed bundle, and everything
downstream refers to the copy. `RuntimeBundleDefinition` was always plural — a
mapping of roles to assets — but with one algorithm shipping one jar, every
caller supplied exactly one role, and the code around it quietly narrowed to
match.

The narrowing was visible in four places. The run pointer recorded
`bridge_jar_sha256`. The receipt builder defaulted its primary role to
`sourceafis_bridge_jar`, imported from an adapter package. The adapter's drift
guard watched one file. And `require_unchanged` had no plural form at all.

A two-tool pipeline breaks all four. If MINDTCT and Bozorth3 are both pinned but
only one is watched, a rebuild of the unwatched one changes every subsequent
score while the run goes on claiming the original runtime — which is the exact
failure docs/adr/0018 exists to prevent, reintroduced one tool along.

## Decision

An integration **declares its runtime asset roles as a tuple**, however many
there are, and the whole set is treated as the runtime:

* the engine hands every declared asset to `RuntimeBundleStore.materialize`, so
  every one of them reaches `bundle_fingerprint`;
* a bundle that is missing a declared role, carries an undeclared one, or belongs
  to another adapter is refused — on creation *and* on every reload of a prepared
  run, because a bundle can be edited between invocations;
* `require_runtime_assets_unchanged(role → path, snapshot)` compares the role set
  first and then every file, so a role that appeared or vanished since preflight
  is drift even when the surviving files are untouched;
* drift in any single asset raises `RuntimeDriftError`. It is never recorded as
  a failed pair: the results already written were produced by something that is
  no longer there, which is a fact about the run rather than about one comparison.

`primary_runtime_asset_role` remains as an integration declaration and reaches
the integration fingerprint. New receipts record the complete
`runtime_asset_sha256s` mapping, not a selected executable. It is not the
runtime's identity: the bundle fingerprint covers every asset's role, filename,
digest, size and media type.

For a future NBIS integration that means: even if MINDTCT is nominated as the
primary asset, replacing Bozorth3 alone produces a different bundle, a different
run and a different environment fingerprint.

## Consequences

`fpbench.adapters.support.runtime_guard` is shared rather than SourceAFIS's own;
the old import path re-exports the same objects, so nothing that already worked
stopped working.

`fpbench.experiments.research_receipt` no longer imports an adapter package. New
receipts use the algorithm-neutral schema described by docs/adr/0044. The two
stored SourceAFIS receipts retain their legacy schema and fields byte-for-byte;
compatibility is a read path, not a generic field with an algorithm-specific
name.

The multi-asset path is exercised rather than assumed: a three-file bundle in
`tests/unit/test_runtime_guard_assets.py`, a two-executable route materialised
and run end to end in `tests/integration/test_algorithm_research_engine.py`.

## Alternatives considered

**One bundle per tool.** A run would then cite several runtimes and have to
define what it means for one of them to be valid and another not. One bundle,
one fingerprint, one answer.

**Watch only the primary executable.** Cheaper by one `stat`, and wrong: it makes
the guarantee depend on which tool somebody labelled primary.

**Re-hash every asset before every comparison.** Correct and far too slow — a
27 MB jar hashed 6,000 times adds real minutes for no new information. The full
digest runs before and after the executor; the per-comparison check is one
`stat` per asset (docs/adr/0018).
