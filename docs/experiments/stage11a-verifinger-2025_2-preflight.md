# Stage 11A — VeriFinger 2025.2 artifact and API preflight qualification

## The one question

> Does an official, exact VeriFinger 2025.2 artifact let fpbench take
> `canonical_500` in and get a reproducible raw 1:1 score out, with every
> externally selectable behaviour that can affect that score defined by
> Neurotechnology rather than invented here?

The answer today is **not yet, and nothing is wrong**. Eight of seventeen gates
passed on the artifact's own bytes, nine are waiting on one bounded qualification
run, and there are zero blockers.

That is a corrected verdict. This stage first published
`VERIFINGER_PREFLIGHT_FAIL` — the same verdict string it would have used if the
score had turned out to be non-deterministic — when what had actually happened
was that nobody had activated a 30-day trial. There is now a third gate status
and a third outcome, and the difference is enforced: a gate awaiting an action
carries no blocker, an incomplete marker carries no failure class, and only a
real `FAIL` stops the run (ADR 0104).

## Why this stage looks different from Stage 10B

Stage 10B preflighted the id3 Finger SDK and stopped at its acquisition gate. The
vendor issues its archive and its activation key together, after a request a
person makes and a vendor accepts, and nobody had walked that route. Eight of ten
gates were therefore questions about an archive that did not exist, and the
honest thing to publish was that nobody had looked.

Neurotechnology publishes a URL. It answers HTTP 200 with the bytes, with no
form, no account and no approval step in front of it. Repeating Stage 10B's shape
here would have meant publishing "unresolved" for questions that were one
transfer away from an answer — so Stage 11A acquires, and acquisition is its
first real act (ADR 0100).

The consequence runs through the whole stage. Every recorded fact carries a
**source class**, and the observation type refuses an artifact-class statement
whose locator is a URL:

```text
OFFICIAL_DOWNLOAD_PAGE        a page, which can change tomorrow
TRANSFER_METADATA             what the server sent, and what arrived
PINNED_SDK_ARCHIVE            bytes inside an archive pinned by digest
PINNED_DOCUMENTATION          the manual that ships with those bytes
OFFICIAL_SAMPLE_IN_ARCHIVE    upstream's own code, in the same archive
```

## What was acquired

| Artifact | Bytes | SHA-256 |
| :--- | ---: | :--- |
| `Neurotec_Biometric_2025_2_SDK_2026-06-12.zip` | 4,743,229,435 | `e30a0b60…` |
| `Neurotec_Biometric_SDK_Documentation.pdf` | 124,277,015 | `ae8acd23…` |

Both from `download.neurotechnology.com`, both verified against the length the
server declared. Seven fields are pinned before anything is imported: the locator
category, the filename, the size, the digest, the date, the declared version and
the target platform. Signed URLs, tokens and machine identifiers are not evidence
and the acquired-artifact type has no field one could sit in.

**The documentation is a separate artifact, and it is provably the right one.**
The standalone PDF and the copy inside the archive have the same digest, so the
manual this stage cites cannot drift away from the runtime it describes.

## The route decision, settled by a version number

The research that preceded this stage expected the vendor's Python packages to be
the better route: they bundle their own native libraries and are described as
recommended for research. The artifact decided otherwise. Those packages are
published at **2025.1**, and this stage is named for 2025.2. Runtime files from
two distributions are never mixed, so the main SDK archive is the route, and the
Python distribution is recorded as a rejected route with its version beside it.

A second consequence follows from opening the archive: the main SDK ships C, C++,
.NET and Java bindings and **no Python binding at all**. A future integration
would drive it the way this project already drives SourceAFIS — through a Java
bridge — and the runtime-identity document publishes `python_package_version` and
`python_abi` as null with that reason attached, rather than leaving two fields of
the specification silently unanswered.

## What five gates established

**Identity comes out of the binaries.** Five native libraries carry
`ProductVersion 2025, 2, 0, 0` in their own version resources; `Revision.txt`
declares revision `20260612`; the licence agreement is headed *VeriFinger
2025.2*; upstream's own tutorial declares `2025.2.0.0`. Four independent
statements inside the pinned bytes. The one field a running engine would add —
a version string emitted by a loaded library — is published as *not read* rather
than quietly counted.

**Stage 8E permits execution.** The licence agreement and the activation guide
inside the archive were read, and Stage 8E's own engine returned
`ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` with intended-use permission
`ESTABLISHED`. Five restrictions are recorded and respected — no redistribution,
no sublicensing, a commercial licence for deployment, notice retention,
non-commercial trial use — and none of them touches one person running one
program on one machine.

Stage 8E's vocabulary has no member for a proprietary commercial SDK licence.
`NON_COMMERCIAL` is the narrowest member that is true of the *trial* route
acquired here, it is published beside
`COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT` so both halves are
visible, and Stage 8E was not edited to add a member (ADR 0099).

**The closure is complete.** All 8,702 archive members were decompressed and
hashed — 6,796,855,547 bytes. The fingerprint algorithm's data files ship inside:
`Fingers.ndf` (122,945,738 bytes) and `FingersMatching.ndf` (4,242,028). Nothing
is downloaded at first use, no accelerator is required, and no further
proprietary service takes part. There is no `.pth` to demand from a black-box
commercial matcher, and the record says so rather than leaving a gap.

**`canonical_500` enters unchanged.** PNG is in the official input domain,
resolution attributes are required on a fingerprint image, minutiae are expressed
in 500 DPI units — which is what the benchmark already produces — and upstream's
1:1 tutorial sets a file name and verifies. All seven refused preprocessing steps
stay refused. Segmentation and quality processing happen inside the pinned
binaries, where fpbench has no external choice about them and therefore needs no
account of the mathematics.

## What nine gates are waiting for

Gates 6 and 8 require two things each: a **closed inventory** of everything that
can change the score, and a **value with an upstream provenance** for each
score-affecting member of it. The inventories are closed. Ten values are not —
eight at the extraction gate, two at the matching gate, each count scoped to its
own gate rather than pooled into one ambiguous number.

```text
UPSTREAM_DOCUMENTED_DEFAULT        the manual states it
DELIVERED_RUNTIME_DEFAULT          a constructed engine reports it
OFFICIAL_SAMPLE_EXPLICIT           upstream's own working code sets it
UPSTREAM_EXPLICIT_RECOMMENDATION   upstream recommends it for this case

FPBENCH_CHOICE                     not a member, and cannot become one
```

The manual states a default for every `Faces.*` parameter and for no `Fingers.*`
or `Matching.*` one.

**Exactly one value has an authority, and only one sample supplies it.** An
earlier version of this stage took `FingersMatchingSpeed = LOW` from
`verify-finger` and `FingersTemplateSize = LARGE` from
`enroll-finger-from-image`. Those are different programs, configured differently:
the first never touches the template size and the second never touches the
matching speed. A profile holding both would be a configuration no upstream
program has ever run — carrying a label saying upstream chose it. Only
`verify-finger` counts now, and the observation type refuses a value from
anywhere else (ADR 0105).

`FingersMatchingSpeed` is exactly the trap the specification warns about: `Low`,
`Medium` and `High`, documented as an accuracy trade-off, one of which will
produce nicer distributions on any dataset. It is settled because **upstream's
own 1:1 tutorial sets it**, and the profile identity records that it is the
official-sample route rather than "the VeriFinger default" — the manual states no
default, and the two are not the same claim.

Passing on the inventory alone would publish a profile called frozen while most
of the settings that decide the score had no recorded value. That is the failure
the whole apparatus exists to prevent — but it is an unpaid chore rather than a
fault in the product, so the gates wait rather than condemning (ADR 0101,
ADR 0104).

## The qualification harness

`integrations/verifinger-qualification/VeriFingerQualification.java`, driven by
`fpbench.experiments.stage11a_qualification` and `make stage11a-qualify`.

It checks three preconditions by name — the artifacts, a JDK 17 toolchain, an
activated trial — and each maps to a pending action rather than to a guess. It
then prepares a small installation from the pinned archive, writes synthetic
ridge-like fixtures at 500 ppi that are not SD300, compiles against the pinned
bindings, and runs twice in separate processes because the third determinism
level is a fresh process and no program can perform that on itself.

It **sets only what `verify-finger` sets** and reads everything else, because a
harness that configured the engine the way this stage wished it were configured
would produce a record about a route nobody uses.

It **publishes no score value**. The Java pass emits a SHA-256 over each score;
the driver compares digests. Determinism across a restart is a string comparison,
and no number leaves the JVM.

Its record is validated before it answers anything: the archive digest it ran
against, the SD300 denial, a bound on how many fixtures it may score, a delivered
default for every published setting, all three determinism levels, and every
failure class. A hand-written file cannot close nine gates.

## What was read but not used

The gates after 6 were never reached, so what follows is published as
observations rather than as conclusions. It is recorded because a reader
comparing this stage with the next one needs to see what was already known.

**The raw score.** The manual defines the comparison result as a similarity,
higher meaning more similar, and publishes the correspondence with a claimed
false acceptance rate: `score = -12 * log10(FAR)`, tabulated from 0 at 100% to 96
at 0.000001%. The threshold is a separate settable engine property, and
upstream's own tutorial reads the integer score under `MATCH_NOT_FOUND` as well
as under `OK` — the number survives a negative decision.

A calibrated quantity is still a raw score, because the test is authorship and
not shape: it is the number upstream's API returns, and fpbench converts nothing
in either direction (ADR 0102). The vendor's recommended threshold of 48 is a
fact about the vendor's advice and belongs to a calibration stage or to nothing.

**The network.** A constant connection is required during evaluation, and the
agreement says what for: Internet Activation stores a licence file locally that
lets the component run *on that computer* after a licence check. The extraction
and matching components are native libraries in the archive and their data files
are beside them. Licensing, not computation — and the question was answered from
pinned notices, never by pulling the network out to see what happened (ADR 0103).

**The trial.** Thirty days, a constant connection, one platform, no simultaneous
use of licensed Neurotechnology products, and **no API-call quota stated
anywhere**. That last one is an absence in the documentation and is not read as
permission; whether 12,000 extractions and 6,000 matches fit inside thirty days
depends on a latency nobody has measured.

## What would move it

One act, and it belongs to a person rather than to a program.

```text
activate the 30-day trial on one chosen platform
   Trial = true in the licensing configuration, start the licensing service
   no serial number, no account, no personal information

run the bounded qualification harness on non-SD300 fixtures
   read each engine default and record it as DELIVERED_RUNTIME_DEFAULT
   score(A,B) and score(B,A); SELF(A,A) as two independent extractions
   the same pair at three determinism levels; each failure class
   import cost, extraction and matching latency, peak memory

re-run the stage
```

Eleven gates become answerable at that point. None of them is answered in advance
here, and the stage is built so that answering them is a re-run rather than an
edit.

The reason it is not done automatically is that activation is not acquisition.
Fetching published bytes touches nothing outside a directory; activation starts a
clock bound to one machine and excludes other licensed products on it. That is
the maintainer's decision (ADR 0099).

## Verifying it

```bash
make stage11a-evidence
```

No dataset, no vendor SDK, no licence, no network. The checks that need the real
4.8 GB carry the `verifinger_artifact` marker and run locally:

```bash
make stage11a-artifacts
```

Those are the ones that keep the record honest about the world rather than only
about itself — every digest this stage published is verified against the bytes it
names.
