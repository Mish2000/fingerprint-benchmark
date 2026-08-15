# Stage 13A — Neurotechnology FingerCell 3.3 preflight

**Status: `FINGERCELL_PREFLIGHT_INCOMPLETE`. No finalization marker exists, and
that is the correct published state.**

One question:

> does the official FingerCell 3.3 SDK trial that Neurotechnology publishes today
> give fpbench a complete, reproducible and upstream-authoritative route from
> `canonical_500` to a native raw 1:1 similarity score, without fpbench inventing
> preprocessing, parameter tuning, merging, thresholding or a score
> transformation?

Ten hard gates answer it. Two are answered; eight are waiting on work this
project has not done yet.

| # | Gate | Status | Outstanding |
|---|------|--------|-------------|
| 1 | `OFFICIAL_ARTIFACT_ACQUISITION` | **PASS** | — |
| 2 | `PACKAGE_RUNTIME_IDENTITY` | **PASS** | — |
| 3 | `RESEARCH_USE_AND_TRIAL_OPERATION` | `ACTION_REQUIRED` | `TRIAL_NOT_ACTIVATED` |
| 4 | `CANONICAL500_INPUT_ROUTE` | `ACTION_REQUIRED` | `RUNTIME_NOT_EXERCISED` |
| 5 | `SINGLE_FINGER_EXTRACTION_PROFILE` | `ACTION_REQUIRED` | `SETTINGS_NOT_ENUMERATED` |
| 6 | `RAW_1TO1_SCORE_CONTRACT` | `ACTION_REQUIRED` | `SCORE_CONTRACT_NOT_OBSERVED` |
| 7 | `SCORE_AFFECTING_SETTINGS_CLOSURE` | `ACTION_REQUIRED` | `SETTINGS_CLOSURE_NOT_ESTABLISHED` |
| 8 | `PAIR_SELF_DETERMINISM_FAILURES` | `ACTION_REQUIRED` | `QUALIFICATION_NOT_RUN` |
| 9 | `FULL_WORKLOAD_FEASIBILITY` | `ACTION_REQUIRED` | `WORKLOAD_NOT_MEASURED` |
| 10 | `TRAINING_PROVENANCE` | `ACTION_REQUIRED` | `PROVENANCE_NOT_SEARCHED` |

**Only a failure stops the run.** A gate awaiting an action is recorded and the
run continues to the next one, so what is published here is the whole remaining
job rather than one next step. `NOT_REACHED` appears only after a real failure,
and there is none (docs/adr/0104).

## What `ACTION_REQUIRED` means, and what it does not

This is the distinction Stage 13A carries from its first day, and the reason its
gate vocabulary differs from Stage 12A's:

```text
local action not yet performed
    -> ACTION_REQUIRED

action actually performed and exposed an incompatibility
    -> FAIL
```

Every open gate here is `ACTION_REQUIRED` because **the trial has not been
activated and nothing has been executed**. Nothing has been found out about
FingerCell that counts against it. No blocker is raised,
no failure class is assigned, Stage 13B is not opened, and the Algorithm 5 search
is *not* reopened — because nothing has been decided.

There is no `PENDING_VENDOR` state here at all. Stage 12A needed one because an
Innovatrics representative had to answer an email before anything could happen.
Neurotechnology publishes a direct trial download, so every remaining question is
one this project answers for itself.

`ACTION_REQUIRED` is not a final outcome and produces no finalization marker. A
stage that is honestly half done looks half done here.

## What gate 1 established

The official trial archive was fetched from the vendor's own untokenized direct
locator and verified:

| Field | Value |
|-------|-------|
| product | FingerCell 3.3 |
| filename | `FingerCell_3_3_SDK_2021-10-13.zip` |
| size | 509,667,736 bytes |
| SHA-256 | `9ca7e275afa9e22cd6fa928b0273afbc447e49463f6f8259a3d5d39a555cde99` |
| vendor product revision | `20211013` |
| vendor revision hash | `394e593011b1b1dca288371e0af499198f4a77d1` |
| locator category | `VENDOR_DIRECT_DOWNLOAD` |

The delivered `Revision.txt` reports the same revision the vendor's public
release notes advertise, so the two agree rather than one being assumed from the
other.

The vendor revision hash is **not** a digest of anything this project computed.
It is 40 hexadecimal characters, which is close enough to a digest to be pasted
into one by accident, so the acquisition record refuses a declaration whose
`sha256` equals it (docs/adr/0113).

## What the archive settled, before anything was executed

Every fact below was read out of the delivered archive — a text file, a header,
a sample source or the shipped licence — and not out of a product page.

- **The score route.** `FingerCellMatch(handle, hReference, hCandidate, NInt*
  pScore)`. A native signed integer, written through an out-parameter, with no
  threshold anywhere near it.
- **The score direction.** The delivered C++ binding documents it: a bigger score
  means the fingerprints are more similar.
- **The extraction route.** `FingerCellExtract(handle, hImage, HNBuffer*)`. One
  image, one call, one template buffer. No record container, no multi-finger
  structure.
- **The template format.** The delivered enumeration is `Proprietary = 0`, then
  ISO and MOC. The proprietary format is the default and is what this stage
  compares.
- **The pair words.** The API's own parameters are `hReference` and `hCandidate`,
  so the frozen binding is `pair.left -> reference`, `pair.right -> candidate`.
  Stage 12A had planned probe/gallery for a different API; a protocol label is
  not carried over from another candidate (docs/adr/0119).
- **The official route.** The shipped verification tutorial obtains a licence for
  the component named `FingerCell` specifically, constructs one object, and
  prints the integer `Match` returns. It applies no threshold and makes no
  decision.
- **Merging exists and is refused here.** The API offers template merging. That
  is a real upstream scenario and a different quantity from a single-impression
  similarity, so refusing it is a deliberate protocol choice rather than an
  absence.
- **The terms.** The delivered licence grants use "for the purpose of designing,
  developing, testing and distributing", restricts reverse engineering,
  decompilation, disassembly, rental and transfer, and states no restriction on
  publishing measurements obtained with the SDK.
- **The trial.** 30 days, an explicit activation step, and a constant network
  requirement for trial products. Activation being a distinct act is what makes
  it possible to build and compile the bridge *before* any clock starts
  (docs/adr/0115).

## Which binding was selected, and why it is not Java

Java was the engineering preference going in — conditional on the archive
shipping a complete and suitable sample for it. The archive decided otherwise:

| Binding | Shipped | FingerCell sample |
|---------|---------|-------------------|
| C++ | yes | desktop sample **and** three tutorials, including 1:1 verification |
| Java | yes (`neurotec-fingercell.jar`) | **Android only** |
| .NET | yes (Framework and Standard) | **none** |

The only delivered Java sample targets Android, which is a different platform and
a different licensing route from the Windows/Linux x86-64 target this benchmark
runs on. C++ is the only binding that satisfies every selection criterion against
what this archive actually contains (docs/adr/0116).

## The same-vendor hazard, and where it stands

Algorithm 4 is VeriFinger 2025.2 — the same vendor. Both products ship modules
under the same naming convention, so a route that quietly reached the wrong
extractor would still produce numbers, and they would be Algorithm 4's numbers
published under Algorithm 5's name.

The static module closure of the FingerCell route is small and does not include
the general biometrics module that carries the vendor's other fingerprint engine:

```text
libFingerCell.so    the algorithm under test
libNMedia.so        image runtime
libNCore.so         common runtime
libNLicensing.so    licensing, for the FingerCell entitlement
```

Neither of those facts came from inspecting a vendor binary. The delivered
tutorial build files name those four libraries outright for the official 1:1
route, and the bridge this project linked records the same four as its own
dynamic dependencies. Stage 13A does not inspect compiled modules at all
(docs/adr/0120). The claim is confirmed once more against the loaded module set
when the bridge first runs.

Separately, a source-level guard proves no Stage 13A module imports the sibling
algorithm's adapter, bridge, runtime or published identity.

## What is already known to be harder than the specification assumed

The delivered C++ binding exposes typed accessors for exactly three properties:
`ImageQualityThreshold` (documented default 60), `MatchingAlgorithm` (documented
default 0) and `TemplateFormat`.

The delivered documentation describes more than three — the minutiae count limits
and a large-template switch among them — so the externally-selectable surface is
wider than the typed API.

So the settings closure cannot be built by ticking off the typed API. It has to
enumerate the properties of a constructed engine through the supported property
mechanism, **before** setting anything, because using a generic setter to "pin"
defaults before reading them destroys the evidence that they were the defaults
(docs/adr/0118). The closure covers what upstream makes externally selectable —
not implementation internals. That is why gate 7 is a question for the runtime
and not for the header.

## What has been built

The qualification bridge is written, compiled and linked against the delivered
headers and libraries, for `linux/x86_64`. It was **not run**: building obtains no
licence and loads no module, which is the whole point of doing it first
(docs/adr/0115). It is pinned into the inspection record by source fingerprint and
binary digest, so a later run cannot outlive the build that produced it.

Windows has no MSVC toolchain on this host, so the bridge targets the vendor's
Linux x86-64 build — one of the two platforms the trial is published for.

## What has not been done

Nothing has been activated, loaded or executed. Specifically:

- no trial has been activated and no licence has been requested;
- no vendor module has been loaded into any process;
- no template has been extracted and no score has been produced;
- no settings have been read off a constructed engine;
- no qualification run against the delivered SDK exists;
- no trial capacity or runtime cost has been measured;
- no training-provenance search has been performed — which is an outstanding
  action and is never published as evidence of an overlap.

## What this stage did not touch

- No SD300 image byte, pair manifest or score was read.
- No prior algorithm's scores were read — including Algorithm 4's, whose vendor
  is the same.
- No production adapter, registry entry, experiment configuration, result set,
  decision profile, threshold, calibration or metric was created.
- No vendor byte and no credential entered this repository. The archive and
  everything unpacked from it live in the local artifact store, outside the
  working tree.
- Stage 12A, Stage 11B and Stage 8E were bound by fingerprint and not edited.

## The documents

| File | Answers |
|------|---------|
| `predecessor-binding.json` | what this stage rests on and may not touch |
| `acquisition-manifest.json` | G1 — what was fetched and what it hashes to |
| `package-runtime-identity.json` | G2 — product, binding, runtime closure, contamination |
| `research-use-trial.json` | G3 — the delivered terms and the trial |
| `input-route.json` | G4 — how `canonical_500` reaches the extractor |
| `extraction-profile.json` | G5 — one image, one proprietary template |
| `score-contract.json` | G6 — the raw 1:1 integer score |
| `settings-closure.json` | G7 — every knob that can move a score |
| `qualification-run.json` | G8 — orientation, SELF, determinism, failure probes |
| `workload-feasibility.json` | G9 — whether 6,000 comparisons fit the trial |
| `training-provenance.json` | G10 — SD300 overlap |
| `preflight-report.json` | the whole run |
| `stage-13a-finalization.json` | **absent** — written only under PASS or a final FAIL |

## Reproducing this

```bash
make stage13a-status
```

The contract and evidence suites need no archive, no licence and no network:

```bash
make stage13a-contract
```

The checks that read the delivered archive are marked `fingercell_artifact` and
skip without it.
