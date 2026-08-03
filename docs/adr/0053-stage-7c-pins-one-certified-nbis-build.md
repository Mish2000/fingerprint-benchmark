# 0053 — Stage 7C names one certified NBIS build and refuses to guess

*Status: Accepted — 2026-08-03, stage 7C*

## Context

An NBIS build id is a digest over the two locked NIST archives, the (empty) patch
series, `integrations/nbis/build.py`, the target platform and the compiler's own
identity and version. It is machine-specific by construction and cannot be
committed, so a machine that has built NBIS twice has two certified builds under
`build/nbis-5.0.0/`.

This project already has exactly that. Stage 7B certified `371409be18a6`, built
with `gcc-9`; the same sources under the distribution's default `gcc-13` produce
`658f9f54a8f2`. Both pass NIST's own test suite and reproduce NIST's reference
`.xyt`, `.min` and score output byte for byte. They are still different runtimes,
and 6,000 results attributed to the wrong one would be attributed to executables
that never ran.

`fpbench.experiments.nbis_research.resolve_build_directory` already refuses to
choose between two builds, and falls back to the single build when there is only
one. That fallback is right for the certification suite, which asks "does the
build on this machine hold up?". It is wrong for a research run, where the answer
has to be the same on every machine and in six months.

## Decision

**Stage 7C names one build id in its configuration and requires the path to be
passed explicitly.**

```yaml
build:
  nbis_build_id: 658f9f54a8f2
  build_root: build/nbis-5.0.0
```

```python
prepare_nbis_canonical500_run(
    ...,
    development_overrides={
        "build_directory": Path("build/nbis-5.0.0/658f9f54a8f2")
    },
)
```

* Omitting `build_directory` is a `ConfigurationError` that names the expected
  path. There is no default, no "newest", no first-in-lexicographic-order and no
  environment variable — `FPBENCH_NBIS_BUILD_DIR` does not appear in the stage 7C
  module at all.
* A directory whose name is not `658f9f54a8f2` is refused, including the stage 7B
  build `371409be18a6`. A different build is a different runtime and needs a
  different run.
* The build is verified *before* anything else touches it: the manifest is read
  and checked against both executables, against the sealed source lock, against
  the patch series and against the current `build.py` and `verify_build.py`. An
  uncertified build is a `ResearchPreflightError`, not an unavailable
  environment — there is no research reading of "we pinned a build nobody
  certified".

**And then the bytes are pinned again.** The engine materialises the three files
into a content-addressed runtime bundle (`nbis_mindtct_executable`,
`nbis_bozorth3_executable`, `nbis_build_manifest`), the run records the bundle's
fingerprint, and the pinned adapter is built only from the bundle's own paths.
Editing a file in the build directory after preparation cannot change what runs;
editing one in the bundle is a `RuntimeDriftError` that aborts the invocation.

## Alternatives considered

**Reuse `resolve_build_directory`.** Its single-build fallback is the whole
problem: a machine that has cleaned `build/` and rebuilt would silently pin a
different runtime, and the run would look identical from the outside.

**Take the build id from `FPBENCH_NBIS_BUILD_DIR`.** An environment variable is
not reviewable, does not appear in a diff, and is exactly the kind of state that
differs between the terminal that prepared a run and the one that resumed it.

**Record the build id after the fact, from the manifest.** That records what
happened rather than requiring what was intended, which is the difference between
provenance and a check.

**Pin the stage 7B build `371409be18a6` for continuity.** Tempting, since it is
the one the certification narrative describes. But the compiler is not part of
what NBIS *is*; both builds reproduce NIST's reference output, and the
distribution's default compiler is the one CI uses and the one a reader can
reproduce without being told which `gcc` to install.

## Consequences

Reproducing stage 7C's run needs the certified build to be rebuilt from the same
lock with the same compiler on the same target, which is what
`integrations/nbis/build.py build` followed by `... test` does and what the build
manifest records. A different compiler produces a different build id and a
different, equally valid run — with its own identity.

The build directory lives under `build/`, which is git-ignored. The evidence
therefore carries the three asset digests and the build manifest fingerprint
rather than the files, which is the same rule docs/adr/0018 applies to every
external runtime.

Running stage 7C on a machine without that build is impossible rather than
approximate, and the error says which build to make.
