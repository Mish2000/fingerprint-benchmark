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

## What "the manifest publishes" turned out to mean

Applying the decision store by store found three things the sentence above did
not settle. They are recorded here because each was decided once and then had to
be decided again in the next store.

**A set may be incomplete; it may never be mixed.** Publishing the manifest first
inverts the crash story: an interruption between the claim and the body leaves an
identity whose rows are missing, where the old order left rows nobody claimed.
That state is permitted, because it is *detectable* — same fingerprint, a
required file absent — and the writer that owns it may finish it. What is never
permitted is a directory holding one writer's manifest over another writer's
rows. `publish_set` takes **every** body path for exactly this reason.

**The check before the claim is load-bearing.** A claim cannot be given back, so
a manifest that names hashes and counts describing nothing must be refused
*before* it takes the name — otherwise a mis-derived set owns an identity that
can only ever be refused afterwards. Each multi-file store therefore checks its
inputs against its own manifest first, through the same function its verifier
uses on what it later reads back.

**`overwrite=True` is a separate path, not a flag on the same one.** `ManifestStore`
had one writer taking a boolean. Splitting it is what makes the refusal the
filesystem's: `overwrite=False` publishes create-if-absent and turns *both* ways
of losing — different bytes, and identical bytes — back into `ManifestExistsError`.
The second way is easy to miss: a manifest is stamped with `created_utc` at
one-second resolution, so two writers of the same rows inside one second produce
byte-identical files, and a store that only translated `PublishConflictError`
would have told both of them they had stored it.

## A claim is not the guarantee — corrected 2026-08-24

Publishing the manifest first stops two writers from interleaving. It says
nothing about what is on disk when the call *returns*, and the difference
between those two statements is where three further defects lived. Each was
found by review, fixed as the instance demonstrated, and followed by another
instance of the same class one layer down:

1. a body that was never checked against the caller's inputs at all;
2. a body checked against a fingerprint the caller supplied — so a genuine
   policy object carrying somebody else's document published;
3. a body checked on the branch that *writes* it and not on the branch that
   finds it already there — so replacing a stored body and re-publishing the
   correct set returned success.

All three are one shape, and the shape was in the API: `publish_set` returned a
`write_body` flag and left the verification to each of eight callers. A rule
every caller must remember is a rule that will be forgotten, and the third
defect is that fact demonstrated twice in one function.

So the flag is gone and the contract is one sentence:

> A public publish returns successfully only if, at a linearization point before
> it returns, the set on disk is the set the caller asked to publish.

On **every** outcome — fresh, retried, resumed, or racing — the manifest carries
this caller's fingerprint or it is a conflict; every body exists; every body
equals what the caller passed; and the whole set is re-read before returning. A
partial set with the same fingerprint may be finished, and finishing is not
repairing: what is present is verified *before* anything is created, so one body
missing and another disagreeing is a conflict rather than a completed set nobody
should trust. Nothing on disk is ever overwritten under the guise of recovery.

Two things this deliberately does not claim. It does not defend against another
process editing a file after the verification point — that needs a lock held
across the operation, which this repository does not take. And "equal" is
canonical, not byte-for-byte: a Parquet body is stamped with a wall clock and
some JSON bodies carry `created_utc`, both of which the fingerprints that give a
set its identity already exclude. Comparing bytes would make every legitimate
retry a conflict.

`tests/contract/test_every_set_publishes_the_set_it_verified.py` runs one table
of thirteen situations against all eight stores. Its oracle re-reads each body
and compares it to a snapshot taken at first publication — it never calls
`store.verify_*`, because the wrong set *passed* the store's verifier: the
verifier checks a set against its manifest, and one wrong publication had
written both.

## Consequences

* A losing writer now raises where it used to return. That is the point, and it
  will surface harness bugs that were previously invisible.
* `PairedEvaluationStore` no longer has nine public writers whose call order was
  the contract. `publish_paired_set` takes the whole comparison, because the
  order was unenforceable while any of them could be called alone.
* The static scan that enforces this (`tests/contract/`) follows calls inside a
  module — but only under `src/fpbench/storage/`. Resolved across the whole
  tree it matches every stage publisher in `experiments/`, and those write
  evidence markers, which this ADR deliberately puts in the `replace_*` class.
  Eighty-five exemptions would have emptied the test; the direct scan still
  covers the rest of the tree.
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
