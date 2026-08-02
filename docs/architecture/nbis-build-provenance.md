# How an NBIS build becomes citable

"We used NBIS 5.0.0" is not a provenance statement. Two machines can compile the
same release with different compilers, different flags and different libpng copies
and get tools that behave differently — and nothing in a run would say so.

This page describes the chain that turns a directory of compiled C into something
a score can be attributed to.

```
NIST Release 5.0.0 + Test 5.0.0
        ↓  seal        digests recorded from the bytes, once, by a person
nbis-5.0.0.lock.json
        ↓  fetch       downloaded, verified, kept only if it matches
verified archives in a cache outside the repository
        ↓  build       extracted safely, compiled, no network
build/nbis-5.0.0/<build-id>/bin/{mindtct,bozorth3}
        ↓  test        NIST's own suite + PNG and PPI probes
nbis-build-manifest.json      signed, and only now does a build exist
        ↓  materialize
runtime bundle: three files, content-addressed
        ↓
every stored result
```

## The lock

`integrations/nbis/nbis-5.0.0.lock.json` records, for each of NIST's two archives:
the version, that the source is NIST's own distribution, the URL it was obtained
from, its SHA-256 and its size.

It ships **unsealed** — `url` and `sha256` are `null`. NIST distributes NBIS behind
an acknowledgement, so the first acquisition is done by a person, and the digest is
then computed **from the bytes on disk**:

```bash
python integrations/nbis/build.py seal \
    --release <archive> --release-url "<the URL you used>" \
    --tests   <archive> --tests-url   "<the URL you used>"
```

Never copied from a web page, a package index or a mirror. An entry that already
carries a digest is **never re-sealed**: a change in the bytes NIST published is a
review with its own argument, not a command re-run. A URL change that does not
change the bytes is a separate, documented update.

Until the lock is sealed, no NBIS research run can be prepared at all — the
integration refuses, and there is a test that says so.

## No silent download

`fetch` requires a sealed lock, verifies size and SHA-256 into a quarantine file
and only then moves it into the cache. There is no mirror, no fallback host and no
retry against a different URL.

`build` **cannot reach the network**: the only `urllib` import in the script is
local to `command_fetch`, and a test asserts it. It will not accept a substitute
archive, and it re-verifies the cached digests every time.

Third-party packaging — a distribution package, a PPA, a GitHub fork, somebody's
Docker image — is useful for *reading*, and is never the source a result is
attributed to.

## Safe extraction

Every archive entry is inspected before anything is written. An absolute path, a
`..`, a drive letter, a symlink, a hard link, a device node or a FIFO refuses the
**whole archive**; partial extraction of a hostile archive is not a state this
project is willing to be in.

Extraction happens in a fresh directory under `~/.cache/fpbench/nbis` (override
with `FPBENCH_NBIS_CACHE`) — never into `src/`, never into `integrations/`, never
into the working tree. An extracted upstream tree inside the working copy would
make every research command refuse to run for having a dirty tree, and would put
100 MB of third-party C where a reviewer expects this project's code.

## No behavioural patch

`patches/series.json` is empty, and the fingerprint of that emptiness is in every
build manifest.

Build **flags** may move, because they decide where things go and how they link:
install prefixes, include paths, `-fcommon`, compiler choice, static linking,
`--without-X11`. Behaviour may not:

```
mindtct/src/lib/mindtct/*.c      LFS parameters       minutiae sorting
bozorth3/src/lib/**/*.c          quality computation  score computation
                                 minutiae filtering   XYT format, defaults
```

If NBIS 5.0.0 cannot be built without changing C that affects, or might affect,
behaviour: the stage stops. The change is not labelled portability, the run does
not proceed, and it goes to review on its own.

`-march=native`, `-mtune=native`, `-ffast-math`, LTO and profile-guided
optimisation are **refused by the script**, in the constants and in the ambient
environment, rather than merely left out.

## Linking

NBIS's own libraries, libpng and zlib are linked statically into both tools. Only
platform base libraries may remain dynamic — libc, libm, the dynamic loader, the
compiler runtime — and the exact set is recorded in the manifest.

A dynamic dependency on libpng, on zlib, on any NBIS library, on anything under a
build directory or under `/usr/local` is refused: it would mean the score depends
on whatever the machine happens to have installed rather than on the pinned
bundle. If one is genuinely needed, the correct response is to extend the runtime
bundle so the exact library is a pinned asset — and to review that before
continuing.

## The build manifest

`nbis-build-manifest.json` records everything that could move a score:

```
schema_version, nbis_version
source_archive_sha256 / size          test_archive_sha256 / size
patchset_fingerprint                  build_script_fingerprint
target_os, target_architecture
compiler_id, compiler_version, compiler_target
cflags, cppflags, ldflags
mindtct_version_output                bozorth3_version_output
png_support_compiled                  direct_gray8_png_verified
png_ppi_policy
mindtct_sha256 / size                 bozorth3_sha256 / size
dynamic_dependencies                  official_test_summary
manifest_fingerprint                  created_utc
```

`manifest_fingerprint` covers all of it except itself and `created_utc`, so two
builds from identical inputs fingerprint identically and a tampered field is
visible immediately.

**No path is stored anywhere in it.** No home directory, no repository path, no
cache path, no user name, no hostname — those are facts about a machine, and a
manifest that carried one would leak it into the runtime bundle and from there
into published evidence. The model refuses a field that looks like a path.

### It is written by `test`, not by `build`

The manifest carries the official test summary and the two PNG verdicts, none of
which is known until the suite and the probes have run. Writing it at the end of
`build` would let a manifest exist for an uncertified build, and the adapter would
then have to distrust the one document it depends on.

So `build` stops with `build-inputs.json`, and `test` completes the directory. A
compiled but uncertified build is visibly unusable rather than quietly usable.
This is a deliberate deviation from the spec's section 8, which describes the
finished layout — and the finished layout is exactly as specified.

## What the official tests have to say

`test` runs every NIST Test 5.0.0 suite relevant to MINDTCT, BOZORTH3 and the
image formats they depend on. Acceptance needs **both**:

```
failed_tests == 0
executed_tests == discovered_tests
```

Discovery **fails loudly** when it recognises no relevant directory, and prints the
package's actual layout, rather than reporting an empty suite as a pass. Golden
output is never edited to make a test pass.

`RELEVANT_TEST_TOOLS` in `build.py` is the one thing confirmed against the real
package on first run, and it is changed in that one place.

## Who checks, and when

| when | what |
|---|---|
| `build.py test` | the manifest is checked against the very files it describes before it is written |
| `verify_build.py` | manifest signature, both digests and sizes, the locked archives, the patch series, the build script |
| CI, after a cache restore | the same, because a cache is somebody else's copy |
| research preflight | all of the above, *before* an adapter exists — an uncertified build is a `ResearchPreflightError`, never an unavailable environment |
| `validate_environment` | version, signature, digests, PNG verdicts, test result, platform, and both tools' version probes |
| before every comparison | one `stat` per pinned file; a change is `RuntimeDriftError` and fatal to the invocation |
| after the executor stops | the bundle's full digest again |

The build id itself is a digest over the two archives, the patch series, the build
script, the compiler and the flags — so the same inputs always land in the same
directory, different inputs never collide, and a rebuild that changed nothing is
recognised as the same build.

Two certified builds present with no choice made is an **error**, not a coin toss.
Picking the newest would let a rebuild silently change which executables a run was
attributed to; the operator names one with `FPBENCH_NBIS_BUILD_DIR`.
