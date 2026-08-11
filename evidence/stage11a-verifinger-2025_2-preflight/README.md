# Stage 11A — VeriFinger 2025.2 artifact and API preflight qualification

## Outcome

```text
VERIFINGER_PREFLIGHT_INCOMPLETE
```

Eight of seventeen gates passed on the artifact's own bytes. Nine are waiting on
one bounded qualification run. **Zero blockers, and no failure class** — nothing
about VeriFinger has been found wanting.

That distinction is the point of this outcome existing. An earlier publication of
this stage said `VERIFINGER_PREFLIGHT_FAIL`, which was the same verdict string it
would have used if the score had turned out to be non-deterministic. What had
actually happened was that nobody had activated a 30-day trial (docs/adr/0104).

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
| 2 | `RUNTIME_IDENTITY` | action required |
| 3 | `RESEARCH_USE_PERMISSION` | PASS |
| 4 | `ARTIFACT_CLOSURE` | PASS |
| 5 | `CANONICAL500_INPUT_ROUTE` | PASS |
| 6 | `EXTRACTION_PROFILE` | action required |
| 7 | `REPRESENTATION_PROFILE` | PASS |
| 8 | `MATCHER_PROFILE` | action required |
| 9 | `RAW_SCORE_ROUTE` | **PASS** |
| 10 | `PAIR_ORIENTATION` | action required |
| 11 | `SELF_SEMANTICS` | action required |
| 12 | `SCORE_DETERMINISM` | action required |
| 13 | `FAILURE_SEMANTICS` | action required |
| 14 | `NETWORK_DEPENDENCY` | PASS |
| 15 | `RUNTIME_FEASIBILITY` | action required |
| 16 | `LICENSE_CAPACITY` | action required |
| 17 | `TRAINING_PROVENANCE` | PASS |

Four statuses, and the differences all matter. `PASS` and `FAIL` are findings.
`ACTION_REQUIRED` means a named person can make the question askable — it is not
a failure and carries no blocker. `NOT_REACHED` means the run stopped at a `FAIL`,
and nothing here did.

**Only a `FAIL` stops the run.** That is why gate 9 — the decisive one — is
published rather than hidden behind gate 6.

## What eight gates established

* **The artifact is exact.** `Neurotec_Biometric_2025_2_SDK_2026-06-12.zip`,
  4,743,229,435 bytes, SHA-256 `e30a0b60…`, from Neurotechnology's own download
  host with no form, no account and no approval step.
* **The manual cannot drift.** The separately downloaded documentation PDF is
  byte-for-byte the copy inside the archive — `ae8acd23…` both times.
* **The route the research preferred is a different product version.** The
  vendor's Python packages are published at **2025.1**. That number decided the
  route, not a preference.
* **Stage 8E permits execution.** `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION`, with
  intended-use permission `ESTABLISHED`, over the licence agreement and the
  activation guide inside the archive.
* **The dependency closure is complete.** All 8,702 archive members hashed,
  6,796,855,547 bytes. `Fingers.ndf` (122,945,738 B) and `FingersMatching.ndf`
  (4,242,028 B) ship inside. Nothing is fetched at first use.
* **`canonical_500` enters unchanged.** PNG is in the official input domain,
  resolution is required on a fingerprint image, minutiae are in 500 DPI units.
  No crop, no resize, no rotation, no enhancement.
* **The representation is the vendor's proprietary template.** ISO and ANSI are
  export formats; MINEX is a separate matching scenario.
* **One scalar raw score exists, with no threshold in it.** Higher is more
  similar, on the vendor's own claimed-FAR scale (`score = -12·log₁₀(FAR)`;
  48 is a claimed 0.01%). The threshold is a separate engine property, and
  upstream's own tutorial reads the score under `MATCH_NOT_FOUND` as well as
  under `OK`. A native transformed quantity is still a raw score
  (docs/adr/0102).
* **The network is for licensing.** Internet Activation is a licence check that
  lets the component run *on that computer*; the components and their data files
  are local (docs/adr/0103).
* **No SD300 overlap evidence.** `NO_EVIDENCE_FOUND`, never converted into
  `PROVEN_ABSENT`, and no score distribution was consulted to answer it.

## What nine gates are waiting for

One bounded qualification run, and three named preconditions:

```text
QUALIFICATION_RUN_NOT_PERFORMED     the run itself
TRIAL_LICENCE_NOT_ACTIVATED         the 30-day trial, activated once
JAVA_RUNTIME_NOT_AVAILABLE          a JDK 17 toolchain on this machine
RUNTIME_PLATFORM_NOT_LOCKED         the platform, fixed at activation
```

The largest single item is configuration. The manual's parameter tables state a
default for every `Faces.*` entry and for **no** `Fingers.*` or `Matching.*` one,
so ten score-affecting values have no upstream authority yet:

```text
extraction gate, 8    FingersTemplateSize, FingersExtractionScenario,
                      FingersFastExtraction, FingersQualityThreshold,
                      FingersMinimalMinutiaCount, FingersDetectTips,
                      FingersDetectLiveness, FingersLivenessConfidenceThreshold

matching gate, 2      FingersMaximalRotation, MatchingScenario

settled by upstream   FingersMatchingSpeed = LOW
```

Each count is scoped to its own gate; any total is derived and labelled where it
is used.

**Exactly one setting is settled, and only one sample settles anything.**
Upstream's tutorials configure the engine differently — the enrolment tutorial
sets a template size the verification tutorial never touches — so a profile
taking one value from each would be a configuration no upstream program has ever
run. Only `verify-finger`, the complete 1:1 program, counts (docs/adr/0105).

The rest are delivered runtime defaults: readable off a constructed engine in one
pass, and recorded as `DELIVERED_RUNTIME_DEFAULT` — an upstream authority, not a
choice.

## The qualification run

`integrations/verifinger-qualification/VeriFingerQualification.java`, driven by
`make stage11a-qualify`. It prepares a small installation from the pinned
archive, generates synthetic ridge-like fixtures at 500 ppi that are not SD300,
compiles against the pinned bindings, and runs twice in separate processes.

It sets only what `verify-finger` sets and *reads* everything else. **No score
value is written anywhere**: the pass emits a SHA-256 over each score and the
driver compares digests, so determinism across a restart is provable without a
number leaving the JVM.

Its record is validated before it answers anything — the archive digest it ran
against, the SD300 denial, the bound on how many fixtures it may score, a
delivered default for every published setting, all three determinism levels, and
every failure class. A hand-written file cannot close nine gates.

## The files

| File | What it holds |
| :--- | :--- |
| `candidate-identity.json` | the provisional identity, the seventeen gates, the frozen workload, the provenance vocabulary and its refused answer |
| `acquisition-manifest.json` | what was fetched, from where, at what size and digest — and the route that was rejected |
| `artifact-manifest.json` | the closure over 8,702 members, the fingerprint data files, the Java bindings |
| `runtime-identity.json` | the identity in the binaries, and the platform lock still outstanding |
| `third-party-usage-binding.json` | the Stage 8E observation, assessment and redistribution record |
| `input-domain-contract.json` | how `canonical_500` enters, and the seven constructions fpbench refuses |
| `extraction-profile.json` | the closed inventory, and its own eight outstanding values |
| `representation-profile.json` | which representation is compared, and why not the interoperable one |
| `matcher-profile.json` | the matching inventory, its own two outstanding values, and the one preset upstream chooses |
| `score-contract.json` | the settled raw-score contract |
| `pair-semantics.json` | the orientation and SELF rules, and how scores are compared without publishing them |
| `determinism-report.json` | the three levels, and the network role |
| `runtime-feasibility.json` | what would be measured, and the trial terms |
| `training-provenance.json` | what is undisclosed, and the SD300 overlap status |
| `preflight-report.json` | the verdict, gate by gate, every blocker, every outstanding action |
| `stage-11a-finalization.json` | the marker |

## What was deliberately not done

```text
no licence activated        no trial reset          no SD300 read
no licence bypassed         no network experiment   no preset chosen on scores
no production adapter       no generic adapter      no threshold
no calibration              no metrics              no 6,000 comparisons
no settings combined from two different upstream samples
```

No credential appears anywhere in this directory, and the finalization verifier
refuses to publish if one does — by key name or by value shape, checked twice.

Not one vendor byte is in Git. The stage carries its own guard over every tracked
file, by exact digest and by vendor artifact shape.

## What opens

```text
opens_stage_11b:         false
opens_candidate_search:  false
```

**The search stays closed on purpose.** No methodological blocker was found here.
Moving to another candidate while this one has an outstanding chore and no
adverse finding would abandon the strongest candidate so far for a reason nobody
could write down (docs/adr/0104).

One act moves this stage, and it belongs to a person rather than to a program:
activate the 30-day trial once, on the one platform this route locks to —
`Trial = true` in the licensing configuration and start the licensing service, no
serial number and no personal information — run `make stage11a-qualify`, and
re-derive.

Nine gates become answerable at that point, and the next publication is either
`VERIFINGER_PREFLIGHT_PASS` or a technical blocker discovered by execution.
