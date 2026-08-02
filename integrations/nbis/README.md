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

## The lock, and what is in it

The lock is **sealed**. Both archives were obtained from NIST's own distribution
index (`https://www.nist.gov/itl/iad/ig/nigos.cfm`), which links them from
`nigos.nist.gov/nist/nbis/`:

| | url | sha256 | size |
|---|---|---|---|
| release | `.../nbis_v5_0_0.zip` | `0adf8ab0…92c3` | 52,595,795 |
| tests | `.../test_v5_0_0.zip` | `5a1e0f7c…ff00` | 400,099,537 |

`seal` computed both digests **from the bytes on disk**. It never copies a digest
from a web page, a package index or a mirror, and it refuses to touch an entry
that is already sealed — so re-running it cannot quietly change what a manifest
was issued against.

Changing a URL without changing the bytes is a separate, documented update.
Changing the bytes is a new review.

To seal a fresh checkout (only needed if the lock is ever reset):

```bash
python integrations/nbis/build.py seal \
    --release /path/to/nbis_v5_0_0.zip --release-url "<the URL you used>" \
    --tests   /path/to/test_v5_0_0.zip --tests-url   "<the URL you used>"
```

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

The **execute bits** an archive stores are restored, because `ZipFile.extractall`
drops them and NBIS's build runs `./setup.sh` as a program. Strictly additive,
and only the three execute bits: an archive gets to say "this is a program",
never "this is set-user-id", and never "this file is read-only" — which would
stop zlib's own `configure` from rewriting its own header.

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
the patch series, this build script, the compiler and the setup options, so the
same inputs always land in the same directory and different inputs never collide.

## The compiler, and the flags

**One compiler, probed, invoked and recorded.** `CC` chooses it and `cc` is the
default; either way the name is resolved to an absolute path *before* it is
probed, so the version banner in the manifest came from the file that built.
NBIS makes that harder than it sounds — `setup.sh` compiles its endianness probe
with a literal `gcc`, and `rules.mak` assigns `CC := $(shell which gcc)` — so a
shim directory holding `gcc` and `cc` goes in front of `PATH` *and* `CC=` is
passed to every `make`. All three then resolve to the same compiler.

**The flags are NBIS's own.** `rules.mak` defines

```
CFLAGS := -O2 -w -ansi -D_POSIX_SOURCE $(ENDIAN_FLAG) $(NBIS_JASPER_FLAG) \
          $(NBIS_OPENJP2_FLAG) $(NBIS_PNG_FLAG) $(ARCH_FLAG)
```

so passing `CFLAGS=` on the make command line would **replace that whole line**,
silently dropping `-D__NBIS_PNG__` and building the one thing this route cannot
do without. This script therefore overrides `CC` and nothing else, and reads the
flags back out of the generated `rules.mak` — by asking make, not with a regex —
so the manifest records what the compiler actually received.

`-fcommon` is the one flag that may be added, and only when the compiler needs
it: GCC 10 changed its default to `-fno-common` and NBIS 5.0.0 predates that.
Whether it is needed is **measured** — two translation units with the same
tentative definition, linked — rather than inferred from a version number.

Both compilers on hand have been built and certified, and both reproduce NIST's
reference output byte for byte:

| compiler | `-fcommon` added | build id |
|---|---|---|
| GCC 9.5.0 | no | `371409be18a6` |
| GCC 13.3.0 | yes, by measurement | `658f9f54a8f2` |

That is why CI does not pin a compiler: the measurement handles it, and the build
id covers the compiler, so a different one is a different build and says so.

Three `setup.sh` switches, all in the build id, all about what is *included*
rather than about what MINDTCT decides:

| switch | why |
|---|---|
| `--without-X11` | only `pcasys`'s viewer uses it, and it is a dependency on whatever X the machine has |
| `--without-OPENJP2` | JPEG 2000 input support, which needs `cmake` to build. This route reads PNG only, and a codec it never calls is not worth a build tool that has nothing to do with fingerprints. `NBIS_PNG_FLAG` is separate and untouched — and the PNG capability probe refuses the build if that ever stops being true |
| `--64` | NBIS defaults to a 32-bit build on a cross-capable toolchain |

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

## What the first real certification found

The build has been done. What follows is what running it actually showed, because
several of these contradicted what this project expected beforehand, and an
expectation that survives only because nobody measured it is not evidence.

### MINDTCT and BOZORTH3 reproduce NIST's own reference output

NIST's Test 5.0.0 ships, per image, a reference `.xyt`, `.min` and five reference
map files, and per BOZORTH3 invocation a reference score log. On the certified
build, **every one of them matches byte for byte**, across all ten test images and
all seven BOZORTH3 invocations.

That is the strongest statement stage 7B can make, and it is what makes the route
citable: this MINDTCT finds the minutiae NIST's MINDTCT found, and this BOZORTH3
computes the scores NIST's BOZORTH3 computed.

One field is masked, named in code: the ANSI/NIST `.mdt` container carries field
`14.005`, the **capture date**, which MINDTCT stamps with today's date. NIST's
golden says `20040930`. The five differing bytes are that date and nothing else;
the minutiae inside the same file are identical. Masking a field the format
defines as "now" is not weakening the comparison — comparing it would make the
comparison impossible rather than strict.

### The build accepts 16-bit and indexed-colour PNGs

This project expected MINDTCT to refuse them. It does not: NBIS 5.0.0 hands PNG
to libpng, which down-converts a 16-bit raster and expands a palette. Truecolour
and unreadable PNGs *are* refused.

The route is unaffected, and not by luck: the **adapter** refuses anything that is
not 8-bit greyscale before a subprocess exists (docs/adr/0048), and there are
tests on both sides of that. What the build tolerates is recorded in the manifest
as `png_formats_refused_by_build`, so the fact is attached to the build rather
than to somebody's memory. `rgb8` and `corrupt` remain acceptance conditions,
because those two would change the pixels being compared.

### The PPI probe came out as designed

Three PNGs with byte-identical pixels and `pHYs` chunks saying 500, 1000 and
nothing at all extract to byte-identical XYT. The declared resolution is ignored
and NBIS's 500 ppi default applies, so `png_ppi_policy` is
`metadata_ignored_default_500` (docs/adr/0047).

### Which official tests count

`RELEVANT_TEST_PACKAGES` is `mindtct` and `bozorth3`. The wider set was run during
certification and is not part of the acceptance condition, for reasons that are
about NIST's package rather than about this build:

| package | what running it showed |
|---|---|
| `imgtools` | 11 of 16 pass. `cwsq`, `dwsq`, `dwsq14`, `sd_rfmt`, `diffbyts` differ — WSQ codec output, a format this route never feeds to MINDTCT |
| `ijg` | all 5 pass |
| `an2k` | 6 of 9 pass. `histogen`'s golden embeds NIST's own build machine's paths (`c:/srcp4/projects/NBIS/…`) and is unreproducible anywhere; `chkan2k` and `rdimgwh` ship prose transcripts rather than comparable output |
| `jpeg2k` | not built (`--without-OPENJP2`) |

The route reads one format — 8-bit greyscale PNG, byte for byte — so WSQ, JPEG,
JPEG 2000 and ANSI/NIST are not "the image formats it depends on". PNG is, and
NIST ships no PNG test package, which is exactly why this build's PNG capability
and PPI behaviour are separate acceptance conditions.

### The version probes

`mindtct -version` prints `NBIS Non-Export Control Software Version: Release
5.0.0`. `bozorth3 -V` is not a flag BOZORTH3 has, so it prints a usage message —
which is still a perfectly stable identity probe, and that is all the check
claims: the binary answers the recorded question the recorded way.

### Linking

Both tools link only `libc`, `libm`, the dynamic loader and the vDSO. No libpng,
no zlib, no NBIS shared library. `-D__NBIS_PNG__` is in the recorded `cflags`.
