# Stage 11A — VeriFinger 2025.2 artifact and API preflight qualification

## Outcome

```text
VERIFINGER_PREFLIGHT_FAIL
```

A complete result, and a different *kind* of result from Stage 10B's. That stage
failed because nobody held the package. This one holds it: 4.8 GB of official
Neurotechnology bytes were fetched, hashed and opened, five gates passed on what
was inside them, and the stage stopped at the sixth — on a question that needs a
running licensed engine rather than a reader.

Nothing in this directory is a score, a threshold, a fingerprint image, a
template, a licence byte or a credential. What it holds is descriptions: URLs and
what they returned, filenames, byte counts, digests, sentences from documents
that are themselves pinned by digest.

## The candidate

```text
candidate                 neurotechnology_verifinger_2025_2_1to1   (provisional)
implementation_origin     VENDOR_OFFICIAL_SDK
product                   VeriFinger 2025.2 SDK, Neurotechnology
production algorithm id   not frozen
```

## The gate matrix

| # | Gate | Status |
| ---: | :--- | :--- |
| 1 | `OFFICIAL_ARTIFACT_ACQUISITION` | PASS |
| 2 | `RUNTIME_IDENTITY` | PASS |
| 3 | `RESEARCH_USE_PERMISSION` | PASS |
| 4 | `ARTIFACT_CLOSURE` | PASS |
| 5 | `CANONICAL500_INPUT_ROUTE` | PASS |
| 6 | `EXTRACTION_PROFILE` | **FAIL** |
| 7–17 | representation, matcher, raw score, pair order, SELF, determinism, failure semantics, network, feasibility, licence capacity, provenance | not reached |

`NOT_REACHED` is not a pass and not a soft failure. It records that the candidate
had already stopped, so the question was never asked.

## The blocker

```text
HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED
failure_class:  EXECUTION_NOT_ESTABLISHED
```

Seven extraction settings — `FingersExtractionScenario`, `FingersFastExtraction`,
`FingersQualityThreshold`, `FingersMinimalMinutiaCount`, `FingersDetectTips`,
`FingersDetectLiveness`, `FingersLivenessConfidenceThreshold` — can each change
the template, and therefore the score, and none of them has a value with an
upstream authority behind it.

That is not because the settings are obscure. The inventory is *closed*: the
pinned manual publishes the complete set and this stage enumerated it. It is
because the manual's own parameter tables state a default for every `Faces.*`
entry — `Default: false`, `Default: 90 pixels`, `Default: ntsMedium` — and for no
`Fingers.*` or `Matching.*` entry. The absence is a property of the document.

The permitted way to close it is to read each value off a constructed engine and
record it as a `DELIVERED_RUNTIME_DEFAULT`. That needs a licensed engine, and no
licence has been activated from this project.

## What the artifact settled

Everything below was read out of bytes pinned by digest, not out of a web page.

* **The artifact is exact.** `Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`,
  4,743,229,435 bytes, SHA-256 `e30a0b60…`, from Neurotechnology's own download
  host with no form, no account and no approval step.
* **The manual cannot drift.** The separately downloaded documentation PDF is
  byte-for-byte the copy inside the archive — `ae8acd23…` both times — so every
  citation here describes the runtime beside it.
* **The route the research preferred is a different product version.** The
  vendor's Python packages, which the preceding research favoured because they
  bundle their own native libraries, are published at **2025.1**. Choosing the
  main SDK was decided by that number, not by preference.
* **The identity is in the binaries.** Five native libraries carry
  `ProductVersion 2025, 2, 0, 0` in their own version resources; the archive
  declares revision `20260612`; the licence agreement is headed *VeriFinger
  2025.2*. No version here came from a page.
* **The dependency closure is complete.** All 8,702 archive members were hashed,
  6,796,855,547 bytes in total. The fingerprint algorithm's two data files —
  `Fingers.ndf` at 122,945,738 bytes and `FingersMatching.ndf` at 4,242,028 —
  ship inside the archive. Nothing is fetched at first use, and no accelerator or
  external service is required.
* **`canonical_500` enters unchanged.** PNG is in the official input domain,
  resolution is required on a fingerprint image, minutiae are expressed in 500
  DPI units, and upstream's own 1:1 tutorial sets a file name and verifies. No
  crop, no resize, no rotation, no enhancement.
* **Stage 8E permits execution.** `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`, with
  intended-use permission `ESTABLISHED`, over the licence agreement and the
  activation guide inside the archive.

## What the artifact settled but the stage could not use

These were read and are published as observations rather than as gate
conclusions, because the gates that would have used them were never reached.

* **The raw score exists and has no threshold in it.** The manual defines the
  result as a similarity, higher meaning more similar, on a claimed-FAR scale it
  publishes anchors for (`score = -12 * log10(FAR)`; 48 is a claimed 0.01%). The
  threshold is a separate settable engine property, and upstream's own tutorial
  reads the integer score under `MATCH_NOT_FOUND` as well as under `OK`.
* **The representation is the vendor's proprietary template.** ISO and ANSI are
  export formats the enrolment tutorial writes only when asked; MINEX is a
  separate matching scenario.
* **The network is for licensing.** The agreement defines Internet Activation as
  a licence check that lets the component run *on that computer*; the components
  and their data files are local.
* **The trial is 30 days with no stated call quota** — an absence in the
  documentation, which is not read as permission.

## The files

| File | What it holds |
| :--- | :--- |
| `candidate-identity.json` | the provisional identity, the seventeen gates, the frozen workload, the provenance vocabulary and its refused answer |
| `acquisition-manifest.json` | what was fetched, from where, at what size and digest — and the route that was rejected |
| `artifact-manifest.json` | the closure over 8,702 members, the fingerprint data files, the Java bindings |
| `runtime-identity.json` | the identity in the binaries, and the fields no execution supplied |
| `third-party-usage-binding.json` | the Stage 8E observation, assessment and redistribution record |
| `input-domain-contract.json` | how `canonical_500` enters, and the seven constructions fpbench refuses |
| `extraction-profile.json` | the closed inventory, and the seven values with no upstream authority |
| `representation-profile.json` | which representation is compared, and why not the interoperable one |
| `matcher-profile.json` | the matching inventory, and the preset upstream chooses |
| `score-contract.json` | the raw-score requirements and what the manual establishes |
| `pair-semantics.json` | the orientation and SELF rules, and that neither was demonstrated |
| `determinism-report.json` | the three levels, and the network question |
| `runtime-feasibility.json` | what would be measured, and the trial terms |
| `training-provenance.json` | what is undisclosed, and the SD300 overlap status |
| `preflight-report.json` | the verdict, gate by gate, every blocker, the acceptance conditions |
| `stage-11a-finalization.json` | the marker |

## What was deliberately not done

```text
no licence activated        no trial reset          no SD300 read
no licence bypassed         no network experiment   no preset chosen on scores
no production adapter       no generic adapter      no threshold
no calibration              no metrics              no 6,000 comparisons
```

No credential appears anywhere in this directory, and the finalization verifier
refuses to publish if one does — by key name or by value shape, checked twice,
once over the objects and once over the published bytes.

Not one vendor byte is in Git. The stage carries its own guard over every tracked
file, by exact digest and by vendor name shape, and it refuses the repository if
one ever appears.

## What opens

```text
opens_stage_11b:         false
opens_candidate_search:  true
```

One act would move this stage, and it belongs to a person rather than to a
program: the maintainer activates the 30-day trial on one chosen platform —
`Trial = true` in the licensing configuration and start the licensing service, no
serial number and no personal information — runs the bounded qualification
harness on fixtures that are not SD300, and re-runs the stage.

Eleven gates become answerable for the first time at that point, and none of them
is answered in advance here.
