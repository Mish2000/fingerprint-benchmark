# flx runtime integration

Everything needed to execute one third-party inference route, and nothing that
belongs to the benchmark. This directory holds the build tooling and the
isolated worker. It holds no weights, no source archive, no biometric images
and no scores.

## What is pinned where

| Thing | Identity | Lives in |
| --- | --- | --- |
| Dependencies | `configs/flx/flx_runtime_lock_v1.txt` — 13 wheels by version, size, SHA-256 and index | git |
| Source | commit `7accfca1`, archive SHA-256 `60fa2c88…` | bundle |
| Imported source files | six files, digested individually in `fpbench.flx.artifacts` | git (digests) |
| Checkpoint | `best_model.pyt`, 875,770,140 bytes, SHA-256 `2683a044…` | bundle only, never git |
| Operational limits | `configs/flx/stage8b_flx_runtime_policy_v1.yaml` | git |

The bundle defaults to `~/.cache/fpbench/flx/flx_cpu_linux_x86_64_v1` and is
overridden with `FPBENCH_FLX_BUNDLE`.

## Building it

Two commands touch the network. Both are explicit and run rarely.

```bash
python integrations/flx/runtime/build_runtime.py lock
```

```bash
python integrations/flx/runtime/build_runtime.py fetch
```

`lock` re-resolves the CPU wheels and rewrites the lock file — review that diff
before committing, because the lock's SHA-256 is part of every representation's
identity. `fetch` downloads the pinned source archive and refuses anything
whose digest is not `60fa2c88…`.

The checkpoint is supplied locally, never downloaded here:

```bash
python integrations/flx/runtime/build_runtime.py stage-checkpoint --from /path/to/best_model.pyt
```

It is verified by size and SHA-256 before the copy and again after. A mismatch
leaves the bundle without a checkpoint rather than with a doubtful one.

Then, offline:

```bash
python integrations/flx/runtime/build_runtime.py build
```

`build` rehashes every wheel against the lock, refuses any wheel the lock does
not name, creates the venv `--without-pip`, installs with `--require-hashes
--no-index --no-deps`, extracts the six imported source files from the rehashed
archive, and verifies the whole bundle.

```bash
python integrations/flx/runtime/build_runtime.py verify
```

`verify` opens nothing it has not rehashed first, and is what runs before any
qualification.

## The worker

`worker/flx_worker.py` runs inside the bundle's venv, in its own process, and
is the only place torch is imported. It does not import `fpbench`: its
dependency surface is exactly the locked distributions plus the standard
library, which is what makes the runtime manifest complete.

It treats the checkpoint as untrusted input. Size and digest are checked before
the file is opened; it is loaded with `weights_only=True`, so no pickled object
can execute; the model is built from the pinned source rather than from
anything inside the checkpoint; and the state dict is loaded with
`strict=True`, with `loss_state_dict` and `optimizer_state_dict` the only
tolerated extra top-level keys, frozen before the file was ever opened.

Observed on the pinned runtime: the checkpoint loads as pure tensors, and
`DeepPrint_TexMinu(8000, 256, 256)` accepts its 1,170 state-dict entries with
**zero missing and zero unexpected keys** — 71,516,742 parameters, eval mode,
gradients off.

The worker seals the network after importing torch and before reading its first
request. Sealing first is not an option: `torch.hub` imports `urllib.request`,
which imports `ssl`, which executes `class SSLSocket(socket)` at import time —
replacing the socket class breaks that class definition and the runtime never
loads. So the connecting *methods* are replaced instead, along with
`urllib.request.urlopen` and `torch.hub`'s two download entry points, and every
refusal is counted.

## Line endings, and why two digests disagree

Stage 8A recorded per-file digests for five `flx` files, fetched over
`raw.githubusercontent.com` on a Windows host. Those digests do not match the
same files inside the pinned archive.

They are the same content. Measured, for all five: converting the archive bytes
to CRLF reproduces the Stage 8A digest exactly.

```
flx/models/deep_print_arch.py
  archive   15235 bytes  b2bfaa28…
  crlf      15695 bytes  cd47acea…   <- what Stage 8A recorded
```

The archive digest `60fa2c88…`, which Stage 8A also recorded, matches on the
nose — so the two records agree about what the source is. Stage 8B pins the
archive and the archive's own file digests, because those are the bytes Python
compiles. `tests/unit/test_stage8b_artifacts.py` re-derives the CRLF
relationship instead of asserting it, so the reconciliation cannot quietly
become false.

## Licensing

The checkpoint's licence is unresolved and stays that way. Executing it locally
is something the project owner instructed; it is not a licence finding, and no
document here says otherwise (docs/adr/0068). The checkpoint is not
redistributable, is never committed, and is never published.
