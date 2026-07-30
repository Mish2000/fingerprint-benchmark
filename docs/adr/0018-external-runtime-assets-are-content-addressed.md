# 0018 — External executables are copied into immutable, content-addressed runtime bundles

## Status

Accepted. Implemented in `fpbench.core.runtime_models`,
`fpbench.storage.runtime_bundle_store` and the SourceAFIS adapter's research mode.

## Context

[ADR 0015](0015-sourceafis-uses-stateless-java-bridge.md) put the jar's SHA-256 into the
environment fingerprint, which sounds sufficient and is not. The digest is computed once,
during preflight; what is stored afterwards is a *path*:

```
integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar
```

That is Maven's output directory. One `mvnw package` replaces the file, at the same
path, with different bytes — and every subsequent comparison in a running job would
execute the new jar while the run manifest went on claiming the old digest. Nothing in
the harness would notice, and no reader of the results could ever find out.

The 24-comparison pilot could live with this. A 6,000-comparison run that takes hours,
executed in sittings on a developer's machine while that machine is also used to build
things, cannot.

## Decision

**Before a research run starts, every external executable it needs is copied into an
immutable bundle identified by its contents.**

```
workspace/runtime/bundles/<bundle_id>/
├── bundle.json
└── assets/fpbench-sourceafis-bridge.jar
```

`bundle_id` is `runtime_<12 chars>` of a digest over the adapter id, the materialisation
policy, and each asset's role, filename, SHA-256, size and media type. It excludes the
source path, the workspace, the creation time and the file permissions — so the same jar
built on another machine six months later materialises to the same id, and a jar that
differs by one byte lands somewhere else and can never be confused with it.

Four rules make the copy worth trusting:

* **Copy, never link.** No symlink, and specifically **no hardlink**: a hardlink shares
  an inode with the build output, so `mvnw package` writing in place would rewrite the
  "immutable" asset too. The whole point is to stop depending on a path nobody controls.
* **Verify the copy, not the source.** The digest is computed over the bytes as they are
  written and compared against the bytes as they were read; the file is flushed, fsynced
  and atomically renamed into place. A truncated copy never becomes an asset.
* **The manifest is written last.** `bundle.json` marks a bundle complete. A crash
  between assets leaves a visibly unfinished directory rather than a manifest describing
  files that were never written.
* **No overwrite and no repair.** A bundle whose contents no longer match its fingerprint
  is *reported*. Silently restoring the file would destroy the evidence that something
  replaced it.

Verification then runs at two different costs, for two different questions:

| When | What | Question answered |
|---|---|---|
| before and after each executor invocation | full SHA-256 of every asset | are these still the bytes we pinned? |
| before every single comparison | `stat`: existence, regular file, size, device, inode, `mtime_ns` | has the file been replaced since preflight? |

Re-hashing 27 MB before each of 6,000 comparisons would add real time for no new
information; a `stat` costs nothing and catches a replacement. The gap between them —
an in-place write that changes neither size nor mtime — is closed by the full digest
afterwards.

**Runtime drift is fatal, and is never a comparison failure.** `RuntimeDriftError` is
re-raised unrecorded by the runner, stops the executor immediately, and writes no result
for the job it was detected on. No completion, no result set and no receipt may be
written for that run; it needs a new bundle and a new run.

## Alternatives

**Keep hashing the path each time.** Cheaper to implement and still wrong: it detects
the swap only at the next preflight, after an unknown number of results were produced by
the wrong jar.

**Commit the jar to the repository.** A 27 MB binary nobody can review, in a repository
whose entire premise is that everything is built from source and verified rather than
trusted.

**Trust the read-only permission bit.** Applied, and treated as a courtesy rather than a
guarantee — it makes an accidental overwrite awkward. On a filesystem that ignores it, or
against a process running as the owner, it stops nothing. The digest is the guarantee.

**Record drift as a per-comparison failure and continue.** Rejected outright. It would
imply the run is otherwise sound when what actually happened is that nothing after that
point can be attributed. It would also put an infrastructure event into the failure
taxonomy that a later stage uses as *data* about fingerprints
([ADR 0006](0006-self-failure-semantics.md)).

## Consequences

* A research run cannot execute the build output. The adapter refuses a `bridge_jar`
  that is not inside a bundle directory.
* Rebuilding the jar between two sittings of the same run stops the run — correctly. The
  new jar is a new bundle, a new environment fingerprint and a new run.
* The workspace grows by one copy of each pinned executable per distinct build. That is
  the price, and it is small next to a 113 GB dataset.
* The mechanism is not SourceAFIS-specific. NBIS will need `mindtct` and `bozorth3`
  binaries pinned the same way, and the bundle model already takes several assets.
