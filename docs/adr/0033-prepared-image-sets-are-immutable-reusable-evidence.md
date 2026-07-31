# 0033 — A prepared-image set is immutable, content-addressed, reusable evidence

*Status: Accepted — 2026-07-31, stage 6A*

## Context

Once resampling moved out of the adapters (docs/adr/0031), the resampled images
became a thing with a lifetime. Two questions follow immediately.

Are they a build artefact — regenerated whenever convenient, like the SourceAFIS
jar in `target/` — or are they evidence?

And what stops the second algorithm evaluated under `canonical_500` from being
handed something subtly different from what the first one saw, six months later,
after a Pillow upgrade?

The runtime bundle store already answered the analogous question for
executables: copy once, address by content, verify before and after, never
repair (docs/adr/0018). The same reasoning applies here with more force, because
an input set is shared by *every* algorithm rather than pinned to one.

## Decision

A prepared-image set is **materialised once, content-addressed, verified, and
reused unchanged** by every algorithm evaluated under its profile.

- Each canonical PNG is written atomically, re-read from its final path, and
  filed under the SHA-256 of its own bytes. The filename is the digest and
  nothing else — never an image id or a subject id, because a directory listing
  of a restricted dataset is an inventory of it.
- Nothing is overwritten. Identical bytes arriving again are a verified no-op;
  different bytes under the same digest are a conflict, never a repair.
- No symlinks, and no hardlinks: an artefact that shares an inode with anything
  else is one a writer elsewhere can rewrite.
- The set's identity folds in every entry hash in materialisation order, plus
  the transform profile, the transform runtime, the pair manifest and the
  cohort. It excludes the wall clock and the output directory, so the same
  images materialised again tomorrow into a different workspace are the same
  set.
- A set is only `PREPARATION_READY` once a receipt and a finalization marker
  exist over a freshly re-verified chain. Everything before the marker is
  retryable; the marker is the only authority.
- Interrupted materialisation resumes only under the same definition, the same
  transform runtime and the same source commit. A runtime that changes mid-way
  voids the set: it cannot be completed by re-running, only replaced.

## Consequences

Reuse is free and safe. A second algorithm names the same
`preparation_set_fingerprint` and provably receives the same pixels; a set
materialised for a superset of images serves a smaller experiment without
ceremony.

Verification is genuinely expensive — the deep pass re-reads every source file
and re-hashes every artefact — so it is split in two. A run checks the artefacts
before and after each batch; `status` and `finalize` check the sources too. The
threat model is accidental drift (a set regenerated in another terminal, a file
touched by an image viewer), not an adversary who mutates a file and restores it
between two checks. That limit is stated rather than implied.

## Alternatives considered

**Regenerate on demand.** Cheap in storage and fatal to comparability: two runs
months apart would silently use two Pillow builds.

**Store the images inside the set directory.** The natural shape, and impossible
without a rename or a copy: a set's id is derived from its entry hashes and does
not exist until the last image is produced. Workspace-level content addressing
solves it and gives cross-set sharing for free.

**Trust the manifest.** A set that asserts its own correctness is not evidence.
Verification re-derives every entry hash, the ordered-entries hash and the set
fingerprint from the bytes on disk.
