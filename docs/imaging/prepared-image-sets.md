# Prepared-image sets

A prepared-image set is the *input* every algorithm evaluated under one profile
receives. It is materialised once, verified, and reused unchanged
(docs/adr/0033).

## The four commands

```bash
python -m fpbench.experiments.sd300_canonical500_images prepare
```
```bash
python -m fpbench.experiments.sd300_canonical500_images materialize --max-new-images 500
```
```bash
python -m fpbench.experiments.sd300_canonical500_images status
```
```bash
python -m fpbench.experiments.sd300_canonical500_images finalize
```

They are separate because they answer to different failures.

`prepare` pins the transformation and the resampler, derives the exact image list
from the frozen pair manifest, reads and decodes all 3,000 sources, and writes
three files: the profile, the runtime and the **definition**. It produces no
image. A dirty working tree, an unpinned resampler, an unverified checksum or an
ambiguous PNG stops everything here, before the expensive part starts.

`materialize` transforms images in definition order and can be run as many times
as it takes. Each invocation captures the transform runtime on the way in and on
the way out and refuses to continue if it moved. Existing entries are fully
re-verified before being reused, never repaired.

`status` reports where the chain stands, re-deriving everything it reports. It
re-runs the pinned transform on every source by default. The diagnostic
`--no-recompute-pixels` switch is available for a faster partial check, but its
result cannot create or replace finalization evidence.

`finalize` re-reads every source and every artefact, re-runs all 3,000 pinned
transforms, and compares the action, dimensions, decoded pixels and encoded PNG
bytes. It writes a content-addressed transform audit, derives the set identity,
writes the manifest, the entries table, the summary and the sanitised receipt,
re-reads each of them, and only then writes the finalization marker. The receipt
and marker both bind the audit fingerprint. This is the only command that can
produce `PREPARATION_READY`.

## The definition, and why it exists

A set's fingerprint covers every entry hash, so it cannot exist until the last
image has been produced. That leaves a gap: between `prepare` and the last write
there is a body of work with no identity, and an interrupted materialisation
resumed under a different profile, runtime or image list would quietly become a
mixture.

The **preparation definition** closes it. Written first, it names exactly which
images will be produced and under what, and every later invocation checks itself
against it. Work in progress lives under `prepared-images/pending/<definition_id>/`;
a finished set lives under `prepared-images/<preparation_set_id>/`.

## Layout

```
workspace/prepared-images/
├── images/<first-two-sha-chars>/<encoded_sha256>.png
├── pending/<preparation_definition_id>/
│   ├── transform-profile.json
│   ├── transform-runtime.json
│   ├── preparation-definition.json
│   └── entries/<image_id>.json
└── <preparation_set_id>/
    ├── transform-profile.json
    ├── transform-runtime.json
    ├── preparation-definition.json
    ├── manifest.json
    ├── entries.parquet
    ├── preparation-transform-audit.json
    ├── preparation-summary.json
    ├── preparation-receipt.json
    └── preparation-finalization.json
```

The canonical PNGs sit at the workspace level rather than inside the set
directory, addressed by the digest of their own bytes. Two consequences, both
wanted: a set's id can be derived after the images exist without a rename or a
copy, and two sets that share an image share the bytes. The filename is the
digest and nothing else — an image id in a path is an inventory row.

## Status ladder

| Status | Means |
| --- | --- |
| `NOT_PREPARED` | no definition |
| `PROFILE_READY` | the transformation is pinned and the image list promised |
| `PARTIAL` | some promised images exist |
| `IMAGES_COMPLETE` | all of them do; nothing has checked them as a whole |
| `VERIFIED` | the manifest is on disk and the set re-verifies |
| `PREPARATION_READY` | the receipt and the marker hold too |
| `INVALID` | two artefacts contradict each other |

`INVALID` is not the bottom of the ladder — it is off it. Materialising more
images never fixes it; a new set does.

## Verification, at two depths

`verify_prepared_artifacts` checks everything reachable without the dataset: the
manifest, the profile, the runtime, the definition, every entry hash, the
ordered-entries hash, the set fingerprint, the receipt, the marker, and every
canonical PNG's bytes, container and decoded raster. A **run** uses this, before
and after each batch.

`verify_prepared_image_set` adds every source file: its digest against the
manifest, its container against the profile's input contract, its raster against
the entry's recorded source pixel hash, and a fresh execution of the pinned
transform. The fresh result must reproduce the action, dimensions, decoded
pixels and encoded PNG bytes recorded by the entry. It also requires an
authoritative source bundle that binds the dataset id, image-manifest hash,
protocol id, cohort id and fingerprint, pair-manifest hash, and exact ordered
image-id list to both the definition and the finished manifest. `status` and
`finalize` use this full check by default.

The stored transform audit accounts for all planned images, verified sources,
recomputed transforms and matching output identities. A self-consistent rewrite
of an output PNG, its entry and the surrounding fingerprints therefore still
fails against a fresh transform from the authoritative source.

The threat model is **accidental drift** — a set regenerated in another
terminal, a file touched by an image viewer, a Pillow upgrade — not an adversary
who mutates a file and restores it between two checks.

## Interruption and reuse

A materialisation resumes only under the same definition, the same transform
runtime, the same source commit, the same clean tree and the same source
manifests. A runtime that changed mid-way voids the set: it cannot be finished
by re-running, only replaced. A corrupt entry is reported, never repaired.

A set materialised for a superset of images serves a smaller experiment without
ceremony. A set missing an image a run needs stops that run at preflight — one
fault, not six thousand identical per-pair failures.

## What a receipt may say

`evidence/sd300-canonical500-images/<preparation_set_id>.json` carries
identities, fingerprints, counts by release, by source resolution and by
transform action, and total byte sizes.

It carries **no** image id, subject id, finger id, filename, path, per-image
hash or per-image dimension. SD300 is redistribution-restricted, and a list of
3,000 image ids is an inventory of it. The sanitisation is checked by
`require_sanitised_receipt` rather than left to whoever writes the builder next.
