# NBIS 5.0.0 — source, build and certification

This directory holds everything that decides **which NBIS produced a score**: the
lock over NIST's two archives, the build script, the (empty) patch series, and a
standalone verifier. It holds no NBIS source and no NBIS binary — those live
outside the working tree, by design.

The route this stage certifies is one identity, end to end:

```
gray8 PNG at 500 ppi  ->  MINDTCT 5.0.0  ->  XYT  ->  BOZORTH3 5.0.0  ->  raw score
```

See `docs/algorithms/nbis-mindtct-bozorth3.md` for what that identity means, and
`docs/architecture/nbis-build-provenance.md` for why the build is pinned the way
it is.

## The only acceptable source

NIST NBIS **Release 5.0.0** and NIST NBIS **Test 5.0.0**, from NIST's own
distribution. Not an Ubuntu or Debian package, not a PPA, not a GitHub fork, not
a third-party Docker image, not a binary from anywhere else. Third-party
packaging is useful for *reading* — it is often the clearest explanation of how
the upstream build works — and it is never the source a result is attributed to.

## First-time setup

NIST distributes NBIS behind an acknowledgement, so the first acquisition is done
by a person rather than by a script. Obtain both archives, then record what you
obtained:

```bash
python integrations/nbis/build.py seal \
    --release /path/to/nbis-release-5.0.0.zip --release-url "<the URL you used>" \
    --tests   /path/to/nbis-tests-5.0.0.zip   --tests-url   "<the URL you used>"
```

`seal` computes SHA-256 and size **from the bytes on disk**. It never copies a
digest from a web page, a package index or a mirror, and it refuses to touch an
entry that is already sealed. Commit `nbis-5.0.0.lock.json` afterwards: from that
point on every fetch, every build and every stored result is checked against it.

Changing a URL without changing the bytes is a separate, documented update.
Changing the bytes is a new review — it is never waved through by re-running
`seal`.

## Building

```bash
python integrations/nbis/build.py fetch     # download exactly the locked archives
python integrations/nbis/build.py build     # compile them. No network at all
python integrations/nbis/build.py test      # NIST's own suite + PNG/PPI probes
python integrations/nbis/build.py inspect   # where lock, cache and builds stand
```

`fetch` verifies size and SHA-256 before anything is kept, and has no fallback
mirror. `build` cannot reach the network and will not accept a substitute
archive. Sources are extracted into a fresh directory under
`~/.cache/fpbench/nbis` (override with `FPBENCH_NBIS_CACHE`) — never into `src/`,
never into `integrations/`, never into the working tree. Every archive entry is
inspected first: an absolute path, a `..`, a symlink, a hard link, a device node
or a FIFO refuses the whole archive.

The result is a self-contained directory:

```
build/nbis-5.0.0/<build-id>/
├── bin/
│   ├── mindtct
│   └── bozorth3
├── build-inputs.json
└── nbis-build-manifest.json      <- written by `test`, not by `build`
```

Nothing is installed to `/usr/bin`, `/usr/local/bin` or `PATH`, and the adapter is
never given a bare command name. `<build-id>` is a digest over the two archives,
the patch series, this build script, the compiler and the flags, so the same
inputs always land in the same directory and different inputs never collide.

### Why `test` writes the manifest

The manifest carries the official test summary, `png_support_compiled`,
`direct_gray8_png_verified` and `png_ppi_policy` — none of which is known until
the suite and the probes have run. Writing it at the end of `build` would mean a
manifest can exist for an uncertified build, and the adapter would then have to
distrust the one document it depends on. So `build` stops with
`build-inputs.json`, and `test` is what completes the directory. A compiled but
uncertified build is visibly unusable rather than quietly usable.

This is a deliberate deviation from a literal reading of the spec's section 8,
which describes the finished layout. The finished layout is exactly as specified.

## No behavioural patches

`patches/series.json` is empty, and the fingerprint of that emptiness is in every
build manifest. Build **flags** may move — install prefixes, include paths,
`-fcommon`, compiler choice, static linking, `--without-X11` — because they decide
where things go and how they link.

These may not move at all in stage 7B:

```
mindtct/src/lib/mindtct/*.c      LFS parameters       minutiae sorting
bozorth3/src/lib/**/*.c          quality computation  score computation
                                 minutiae filtering   XYT format, defaults
```

If NBIS 5.0.0 cannot be built without changing C that affects, or might affect,
behaviour: **stop**. Do not label the change portability, do not continue to a
run, and bring it to review on its own.

`-march=native`, `-mtune=native`, `-ffast-math`, LTO and profile-guided
optimisation are refused by the build script rather than merely left out, because
an operator exporting one in their shell would otherwise change what a certified
build is.

## Linking

NBIS's own libraries, libpng and zlib are linked statically into both tools. Only
platform base libraries — libc, libm, the dynamic loader, the compiler runtime —
may remain dynamic, and `build.py test` records the exact set in the manifest.
A dynamic dependency on libpng, on zlib, on any NBIS library, on anything under a
build directory or under `/usr/local` is refused: it would mean the score depends
on whatever the machine happens to have installed rather than on the pinned
bundle.

## Verifying later

```bash
python integrations/nbis/verify_build.py build/nbis-5.0.0/<build-id>
```

Re-checks the manifest signature, both executables' digests and sizes, the locked
archive digests, the patch series and this build script. CI runs it after every
cache restore, because a cache is somewhere else's copy.

## What is confirmed on first run

`RELEVANT_TEST_TOOLS` in `build.py` names the directories of NIST's Test 5.0.0
package that cover MINDTCT, BOZORTH3 and the image formats they depend on. The
discovery **fails loudly** when it finds none of them and prints the package's
actual layout, rather than reporting an empty suite as a pass. Confirm the list
against the real package the first time the suite runs, and change it in that one
place.
