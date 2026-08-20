# ADR 0139 — one writer wins a file, and the loser is told

## Status

Accepted.

## Context

Every store in this repository wrote a file the same way:

```python
if path.exists():
    raise ResultConflictError(...)
...
tmp = path.with_suffix(path.suffix + ".tmp")
pq.write_table(stamped, tmp, compression="zstd")
tmp.replace(path)
```

That sequence is atomic against a crash. Against a second writer it fails twice
over, and the second failure is the serious one.

The temp name is a pure function of the target, so two writers of the same file
write into each other's scratch copy. And the existence check is a check, not a
reservation: both writers pass it, both call `replace()`, the last one wins —
and the first one *returns normally*. A caller is told its result was stored
while the bytes on disk belong to somebody else. In a controlled reproduction one
writer reported success for score `1.0` and the file held `2.0`.

`ResultStore.write_raw_result` is where it matters most, because a raw result is
the atom of every downstream claim. The same shape appeared in nine other stores
and in `write_json`, which every JSON document in the workspace goes through.

The repository already had the right instinct — the comment above the guard in
`write_raw_result` says raw results are immutable and cites ADR 0009. The guard
just could not enforce it.

## Decision

**Reserve the name with an operation the filesystem serialises, and report which
side of the race you were on.**

`fpbench.core.atomic_write` is the single primitive:

* `unique_temp_path` names the scratch file after the process, a per-process
  random token and a counter, so no two writers can collide on it.
* `publish_*` creates the final name with `os.link` — falling back to
  `O_CREAT | O_EXCL` where hard links are unavailable — so exactly one writer
  succeeds. The loser re-reads the winner's bytes and compares digests,
  returning `ALREADY_IDENTICAL` when they agree and raising
  `PublishConflictError` when they do not.
* `replace_*` keeps replace-if-present semantics for documents that are *meant*
  to be regenerated, and differs from the old idiom only in the unique temp.

Choosing between the two is a statement about the artefact, not about the
caller. Immutable per-item artefacts publish: raw results, calibration
documents, canonical image blobs. Derived bodies that a guarded `ensure_*` may
legitimately rewrite replace — and their *manifest* publishes, so the manifest
is what serialises the writers and a loser re-applies the fingerprint comparison
the guard already performed.

Two details that are not incidental:

**The temp name is 17 characters and is not derived from the target's.** Windows
still enforces a 260-character path limit for these APIs, and the workspace
layout — `results/<run>/decisions/<set>/evaluation-views/<kind>/` — reaches it.
Appending a uniqueness token to an already-deep name made scratch files
unopenable; a short fixed-width name is shorter than the `<name>.tmp` it
replaces for every parquet body in the workspace.

**Evidence bytes are LF on every platform.** The evidence writers translated
`\n` to `os.linesep` to match the old text-mode `write_json`. Those bytes are
compared against the committed copy and, in several stages, hashed into a
marker, so the translation made one document into two depending on which machine
wrote it. `.gitattributes` now pins `evidence/**` and every path inside a stage's
`_SOURCE_FILES` to `eol=lf`, and
`tests/contract/test_source_fingerprints_are_pinned.py` fails if a fingerprinted
path is added without the pin.

## The one file that could not change

`fpbench.core.serialization` is inside Stage 8A's `_VERIFIER_AUTHORITY_PATHS`,
which its published verifier requires to be byte-identical to
`verifier_source_commit`. Fixing `write_json` in place turns a committed
evidence gate red.

The established response in this repository is a sibling module rather than a
widened allowlist — Stage 8B, 8D and 8E each added one — so `write_json` and
`publish_json` live in `fpbench.core.json_io`, which re-exports `to_plain` and
`read_json` from the pinned module unchanged. Every caller outside the seven
pinned paths imports from there; the pinned writer's only remaining caller is
`storage/modern_matcher_store.py`, which is pinned too.

## Consequences

* A losing writer now raises where it used to return. That is the point, and it
  will surface harness bugs that were previously invisible.
* `publish_*` needs the temp and the target on one filesystem. They are
  siblings, so this holds by construction.
* `write_json` output is byte-identical to the pinned writer's on a POSIX
  checkout, and now identical on Windows too, where the old writer emitted
  `\r\n`.

## Alternatives

**A lock file per target.** More moving parts, and a stale lock is a new failure
mode with no natural owner. `os.link` needs no cleanup because the winner's file
*is* the record of who won.

**Keep the existence check and document the race.** The check reads as a
guarantee at every call site. A comment saying it is not one would be read by
whoever wrote the comment.
