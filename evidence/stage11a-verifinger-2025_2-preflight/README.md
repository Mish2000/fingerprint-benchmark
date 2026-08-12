# Stage 11A — VeriFinger 2025.2 artifact and API preflight qualification

## Outcome

```text
VERIFINGER_PREFLIGHT_PASS          17 of 17 gates, 0 blockers
selected_candidate                 neurotechnology_verifinger_2025_2_1to1
opens_stage_11b                    true
```

Eight gates were settled by reading the pinned artifact. Nine were settled by
running it: one bounded qualification pass against an activated 30-day trial, on
fixtures that are not SD300, producing 12 qualification scores and zero benchmark
scores.

Nothing in this directory is a score value, a threshold, a fingerprint image, a
template, a licence byte or a credential. What it holds is descriptions: URLs and
what they returned, filenames, byte counts, digests, sentences from documents
that are themselves pinned by digest, and the equalities and counts a run
produced.

## The candidate

```text
candidate                 neurotechnology_verifinger_2025_2_1to1   (provisional)
implementation_origin     VENDOR_OFFICIAL_SDK
product                   VeriFinger 2025.2 SDK, Neurotechnology
production algorithm id   not frozen — that is Stage 11B's to freeze
```

## The gate matrix

| # | Gate | Settled by |
| ---: | :--- | :--- |
| 1 | `OFFICIAL_ARTIFACT_ACQUISITION` | the artifact |
| 2 | `RUNTIME_IDENTITY` | the artifact **and** the run |
| 3 | `RESEARCH_USE_PERMISSION` | the artifact |
| 4 | `ARTIFACT_CLOSURE` | the artifact |
| 5 | `CANONICAL500_INPUT_ROUTE` | the artifact |
| 6 | `EXTRACTION_PROFILE` | the run |
| 7 | `REPRESENTATION_PROFILE` | the artifact |
| 8 | `MATCHER_PROFILE` | the artifact and the run |
| 9 | `RAW_SCORE_ROUTE` | the artifact |
| 10 | `PAIR_ORIENTATION` | the run |
| 11 | `SELF_SEMANTICS` | the run |
| 12 | `SCORE_DETERMINISM` | the run |
| 13 | `FAILURE_SEMANTICS` | the run |
| 14 | `NETWORK_DEPENDENCY` | the artifact |
| 15 | `RUNTIME_FEASIBILITY` | the run |
| 16 | `LICENSE_CAPACITY` | the run |
| 17 | `TRAINING_PROVENANCE` | the artifact |

All seventeen `PASS`. The conjunction is unweighted: there is no arrangement in
which sixteen would have been enough.

## What the artifact settled

* **The artifact is exact.** `Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`,
  4,743,229,435 bytes, SHA-256 `e30a0b60…`, from Neurotechnology's own download
  host with no form, no account and no approval step.
* **The manual cannot drift.** The separately downloaded documentation PDF is
  byte-for-byte the copy inside the archive — `ae8acd23…` both times.
* **The route the research preferred is a different product version.** The
  vendor's Python packages are published at **2025.1**. That number decided the
  route, not a preference.
* **Stage 8E permits execution.** `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`, with
  intended-use permission `ESTABLISHED`.
* **The dependency closure is complete.** All 8,702 archive members hashed,
  6,796,855,547 bytes. `Fingers.ndf` (122,945,738 B) and `FingersMatching.ndf`
  (4,242,028 B) ship inside; nothing is fetched at first use.
* **`canonical_500` enters unchanged.** PNG is in the official input domain,
  resolution is required on a fingerprint image, minutiae are in 500 DPI units.
  No crop, no resize, no rotation, no enhancement.
* **The representation is the vendor's proprietary template.** ISO and ANSI are
  export formats; MINEX is a separate matching scenario.
* **One scalar raw score, with no threshold in it.** Higher is more similar, on
  the vendor's own claimed-FAR scale (`score = -12·log₁₀(FAR)`). The threshold is
  a separate engine property, and upstream's tutorial reads the score under
  `MATCH_NOT_FOUND` as well as under `OK` (docs/adr/0102).
* **The network is for licensing**, not for computation (docs/adr/0103).
* **No SD300 overlap evidence.** `NO_EVIDENCE_FOUND`, never converted into
  `PROVEN_ABSENT`.

## What the run settled

```text
runtime identity   7 native modules loaded, each with its own version, read from
                   NModule.getLoadedModules() — not the JVM's version
platform lock      windows / x86_64 · Bin/Win64_x64 · Zulu 17.0.18
pair orientation   both orderings scored; score digests equal → symmetric here
SELF(A, A)         two independent extractions, a score, no representation reuse
determinism        identical at all three levels, including a process restart
failure semantics  all 6 classes provoked by controlled causes; none returned a
                   score
feasibility        7 end-to-end verify calls, ~2.29 s each, ~1 s startup, ~8 MB
                   heap, no accelerator
licence capacity   6,000 verification attempts project to ~3.8 hours, inside the
                   30-day window
```

**Every score-affecting setting now has an upstream provenance.** The manual
states a default for every `Faces.*` parameter and for no `Fingers.*` or
`Matching.*` one, so ten values were read off the constructed engine and recorded
as `DELIVERED_RUNTIME_DEFAULT` — an upstream authority, not a choice:

```text
extraction gate   TemplateSize LARGE · ExtractionScenario 0 · FastExtraction false
                  QualityThreshold 40 · MinimalMinutiaCount 10 · DetectTips false
                  DetectLiveness false · LivenessConfidenceThreshold 0

matching gate     MaximalRotation 180.0 · Matching.Scenario 0

authoritative     MatchingSpeed LOW, from verify-finger — and the delivered
sample            default turns out to be LOW as well
```

Defaults are read **before** anything is configured, so a value the authoritative
sample sets cannot be reported back as the vendor's own.

## The fixtures the run actually used

The synthetic ridge-like pair was **rejected by the extractor** (`BAD_OBJECT`),
so the run fell back to upstream's own sample fingerprints from inside the pinned
archive — the fallback the specification names for exactly this case
(spec section 39). Every summary in this evidence derives that from the record
rather than asserting "synthetic".

The samples stay in the local artifact store, are covered by the archive digest,
and are not in Git. No SD300 image, pair manifest or score was read.

## The trust boundary

The qualification record carries an `inputs_fingerprint` over the archive, every
component actually loaded, the Java harness, the Python driver and the fixture
version — and the validator **recomputes it and compares** before the record may
answer anything. A record produced by an earlier harness cannot close this stage.

Source digests are taken over newline-normalised bytes, so a Windows checkout
does not invalidate a run that nothing changed.

The record is also refused if it lacks a delivered value for any published
setting, if any value reads `UNREADABLE`, if any determinism level or failure
class is missing, if it claims a benchmark or SD300 score, if it exceeds the
64-score bound, or if it carries score values rather than digests.

## The files

| File | What it holds |
| :--- | :--- |
| `candidate-identity.json` | the provisional identity, the seventeen gates, the frozen workload, the provenance vocabulary and its refused answer |
| `acquisition-manifest.json` | what was fetched, from where, at what size and digest — and the route that was rejected |
| `artifact-manifest.json` | the closure over 8,702 members, the data files, the Java bindings |
| `runtime-identity.json` | the identity in the binaries, the platform lock, and the modules the process loaded |
| `third-party-usage-binding.json` | the Stage 8E observation, assessment and redistribution record |
| `input-domain-contract.json` | how `canonical_500` enters, and the seven constructions fpbench refuses |
| `extraction-profile.json` | the closed inventory, every value and its effective provenance |
| `representation-profile.json` | which representation is compared, and why not the interoperable one |
| `matcher-profile.json` | the matching inventory, and the one preset upstream chooses |
| `score-contract.json` | the settled raw-score contract |
| `pair-semantics.json` | orientation and SELF, and how scores are compared without publishing them |
| `determinism-report.json` | the three levels, and the network role |
| `runtime-feasibility.json` | what was measured, and the trial terms |
| `training-provenance.json` | what is undisclosed, and the SD300 overlap status |
| `preflight-report.json` | the verdict, gate by gate |
| `stage-11a-finalization.json` | the marker |

## What was deliberately not done

```text
no SD300 read           no benchmark score      no threshold
no licence bypassed     no trial reset          no calibration
no production adapter   no generic adapter      no metrics
no network experiment   no preset chosen on score distributions
no settings combined from two different upstream samples
```

One trial was activated, by the maintainer, through Neurotechnology's own
documented route. Twelve qualification scores exist and not one of their values
is published: the harness emits a SHA-256 per score and the driver compares
digests.

Not one vendor byte is in Git.

## What opens

```text
opens_stage_11b:         true
opens_candidate_search:  false
```

Stage 11B is the production integration: the generic adapter, a frozen
`AlgorithmConfig`, runtime qualification and raw-score execution readiness — and
still no threshold and no calibration.
