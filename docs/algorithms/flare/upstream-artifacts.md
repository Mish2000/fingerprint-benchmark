# FLARE — upstream artifacts

Everything the full route needs, described by what it is rather than by where it
sits. No byte of any of it is in this repository (docs/adr/0083).

## Source repositories

Two, and they are separate components with separate identities.

| | `Yu-Yy/FLARE` | `Yu-Yy/FLARE_ENH` |
| :--- | :--- | :--- |
| Role | FLARE-Align and FLARE-Desc | FLARE-Enh |
| Default branch observed | `master` | `master` |
| Pinned commit | `7d13ca727d55cf43642f9fe1e67df785091fd7c2` | `ee735b03669aa0d9e086b50c7d9b1771913a2ba4` |
| Archive size | 725,804 bytes | 33,181 bytes |
| Acquired | 2026-08-08 | 2026-08-08 |

A branch name is never used as an identity. `master` moved under this project
once already: the checkpoint-loading question that dominated the previous reading
of FLARE was answered by a commit that landed after that reading was written.
Exact digests are in `evidence/stage9a-flare-artifact-qualification/upstream-source-manifest.json`.

Both archives were acquired twice from the same locator and were byte-identical,
which is what makes a generated tarball usable as an identity here.

## Artifacts

Ten, of which four have an established identity and six do not.

| Artifact | Kind | Locator kind | Identity |
| :--- | :--- | :--- | :--- |
| FLARE source snapshot | source | HTTPS archive | established |
| FLARE_ENH source snapshot | source | HTTPS archive | established |
| `desc_configs.yaml` | configuration | in the source tree | established |
| `vq.yaml` | configuration | in the source tree | established |
| `desc_model.pth.tar` (FDD) | weights | Google Drive | **not established** |
| `VotingPose.pth` | weights | Google Drive | **not established** |
| `RegressionPose.pth` | weights | Google Drive | **not established** |
| `unetenh.pth` | weights | Google Drive | **not established** |
| `priorenh.pth` | weights | Google Drive | **not established** |
| `Prior.ckpt` | weights | Google Drive | **not established** |

### A Drive file id is a locator

Not an identity. Two downloads from the same link at different times cannot be
shown to be the same artifact by the link alone. The identity is the SHA-256 and
the exact size, and until an enrollment establishes them the artifact's
`identity_established` is false and Stage 8E's engine blocks it.

Rejected on acquisition, by structure and before hashing: an HTML page served
instead of a file, a zero-byte artifact, a truncated file, an unexpected archive,
an unexpected serialization format, a digest mismatch, a size mismatch.

### `Prior.ckpt` was found by traversal

It is in no README download list. `vq.yaml`'s `ckpt_path` names it, and
`VQFPEnhancer_PCNN.__init__` asserts on it and loads it before PriorEnh's own
weights are applied. There is no closed inventory of an artifact set until the
configuration has been traversed.

## Where they live

Outside the working tree, under `FPBENCH_THIRD_PARTY_ROOT` or, unset, under
`~/.cache/fpbench/third_party`:

```text
$FPBENCH_THIRD_PARTY_ROOT/
    flare/
        source/
        fdd/
        pose/
        enhancement/
```

The structure may change. Manifests hold no absolute path, so the same manifest
works on every machine and the repository still knows exactly which bytes it
expects.

## Licensing

Not decided here. Stage 8E owns the question and Stage 9A is one of its callers.

Both repositories carry a permissive `LICENSE` file — the unmodified Apache-2.0
text, identical in both — and a README that limits use to academic research and
educational purposes and prohibits commercial use. That is
`CONFLICTING_NOTICES`, recorded as such, with both documents cited by digest.
Stage 9A does not decide which governs; it asks whether every plausible reading
permits this project's exact operation, and both do.

The six checkpoints carry no notice this project has inspected. That is
`UNKNOWN` — nobody has looked — rather than `NO_LICENSE_FOUND`, which would
claim an inspection that has not happened. The project owner's risk acceptance
covers the licence position; the identity question is separate and is what
currently blocks them.

Details in
`evidence/stage9a-flare-artifact-qualification/third-party-usage-manifest.json`.
