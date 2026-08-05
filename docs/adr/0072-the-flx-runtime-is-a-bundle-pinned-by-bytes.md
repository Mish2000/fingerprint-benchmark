# 0072 — The flx runtime is a bundle, pinned by bytes

*Status: Accepted — 2026-08-05, stage 8B*

## Context

Stage 8A recorded `DEPENDENCY_VERSIONS_NOT_LOCKED` and
`RUNTIME_MANIFEST_NOT_DEFINED` against this artifact. Upstream's
`requirements.txt` names fourteen packages and pins none of them, including
`torch` and `torchvision` — the two that decide what a float is.

A learned matcher's output is a function of its runtime in a way a minutiae
matcher's is not. A different MKL, a different thread count, a different
convolution kernel and the last bits move. "We installed torch" is not a
description of anything reproducible.

Three sub-problems came with it. Installing `torch` from PyPI pulls the CUDA
runtime — several gigabytes of GPU libraries into a profile that has no device
and must never acquire one. A `python -m venv` bootstraps its own `pip` and
`setuptools`, so the installed set is never exactly the locked set. And the
checkpoint is 835 MiB of weights we have no right to redistribute
(docs/adr/0068).

## Decision

The runtime is a **bundle** outside the repository, and the repository holds
only what identifies it.

```
configs/flx/flx_runtime_lock_v1.txt      in git: every wheel, version, size, SHA-256, index
<bundle>/wheels/                         the wheels themselves
<bundle>/venv/                           installed from those wheels, hashes required
<bundle>/source/…tar.gz                  the pinned archive, SHA-256 60fa2c88…
<bundle>/source/tree/                    exactly the six files the worker imports
<bundle>/checkpoint/best_model.pyt       SHA-256 2683a044…, never committed
```

The lock is simultaneously a machine-readable manifest and valid pip input. It
is installed with `--require-hashes --no-index --no-deps --find-links`, so pip
resolves nothing at install time and refuses any wheel whose bytes differ.

Torch and torchvision come from `https://download.pytorch.org/whl/cpu`. The
same versions on PyPI carry the CUDA dependency chain.

The venv is created `--without-pip` and installed into from outside, so the
runtime contains exactly the thirteen locked distributions and nothing else.
That is what makes "the installed runtime is the lock" a checkable claim rather
than a claim with two known exceptions: `RuntimeLock.verify_installed` fails on
an unpinned distribution as loudly as on a missing one.

Threads are pinned to one, in the environment and in torch, before any numeric
work starts. `set_num_interop_threads` is only honoured before the interop pool
exists, so it happens immediately after import rather than at model load, where
it would have silently left the machine's core count inside the identity.

The bundle is reproducible from things that are in git — the lock, the archive
digest, the build script — with one exception, the checkpoint, which must be
supplied locally and is verified by size and digest before it is copied in and
again after.

## Alternatives considered

**A `requirements.txt` with `==` pins.** Pins a version, not the bytes. The
same version can be rebuilt, re-uploaded or served differently, and a version
pin cannot tell.

**Install into the project's own environment.** Puts torch, and its CUDA chain
if PyPI is used, into every test run and every unrelated command. The worker's
dependency surface must be exactly the locked set, and a shared environment
cannot promise that.

**Commit the wheels.** 218 MiB of binaries in git to avoid a download that the
lock already makes verifiable.

**Keep the checkpoint in the repository.** Not ours to redistribute, and
Stage 8B's binding refuses to record it as committed.

**Vendor the whole upstream source tree.** The archive digest already covers
everything; extracting only the six imported files keeps the executed surface
small and enumerable, and the archive is re-verified on every load anyway.

## Consequences

Building the runtime needs the network exactly twice — `lock` and `fetch` —
and both are explicit, human-run commands that write down what they got.
Everything after that is offline, and qualification runs with the socket layer
sealed.

Editing the lock is editing the algorithm's identity: its SHA-256 is inside the
runtime manifest, which is inside every representation's provenance.

A GPU profile is future work with a different `runtime_profile_id`, a different
lock and a different set of measurements. It cannot be reached by editing this
one.
