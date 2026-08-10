# VeriFinger 2025.2 — Algorithm 4 candidate record

```text
candidate_id            neurotechnology_verifinger_2025_2_1to1   (provisional)
implementation_origin   VENDOR_OFFICIAL_SDK
vendor                  Neurotechnology
declared version        VeriFinger 2025.2 SDK
verdict                 VERIFINGER_PREFLIGHT_FAIL
stopped at              gate 6, EXTRACTION_PROFILE
gates passed            5 of 17
```

## What it is

A commercial fingerprint identification SDK, in continuous development since
1998, shipped inside a single archive with four sibling Neurotechnology products.
It offers 1:1 and 1:N matching with builds for Windows, Linux, macOS, Android and
iOS, and bindings for C, C++, .NET and Java.

Its 1:1 route is the shape this benchmark needs, and — unlike every previous
candidate — that was confirmed by opening the package rather than by reading
about it. `NBiometricClient.verify(reference, candidate)` returns a status, and
the integer similarity score is read from the reference subject's first matching
result. The vendor's own tutorial reads that score under `MATCH_NOT_FOUND` as
well as under `OK`, so the number is not replaced by a decision.

Nothing in this record is a judgement about the product. It is one of the most
heavily evaluated fingerprint matchers in existence.

## Why it is not admissible today

Not because of the artifact, the licence, the input domain, the representation,
the score or the network. Because nine settings that change the score have no
recorded value.

The pinned 2025.2 manual publishes the complete set of externally selectable
fingerprint settings — the inventory is closed — and states a default for none of
them, while stating defaults for the face-side settings in the same tables. Two
values do have an upstream authority, because upstream's own tutorials set them
explicitly. The rest would have to be read off a constructed engine and recorded
as delivered runtime defaults, and that needs a licence nobody has activated.

```text
extraction, no upstream authority   FingersExtractionScenario
                                    FingersFastExtraction
                                    FingersQualityThreshold
                                    FingersMinimalMinutiaCount
                                    FingersDetectTips
                                    FingersDetectLiveness
                                    FingersLivenessConfidenceThreshold

matching, no upstream authority     FingersMaximalRotation
                                    MatchingScenario

settled by upstream                 FingersTemplateSize   = LARGE
                                    FingersMatchingSpeed  = LOW
```

## What the artifact established

| Question | Answer |
| :--- | :--- |
| Official artifact obtained? | yes — 4,743,229,435 bytes, SHA-256 `e30a0b60…` |
| Documentation pinned separately? | yes, and byte-identical to the copy inside |
| Exact identity? | `2025, 2, 0, 0` in five native libraries' own resources |
| Research use permitted? | `ALLOWED_UNDER_RESTRICTIVE_INTERSECTION` (Stage 8E) |
| Dependency closure? | complete — the two `.ndf` data files ship inside |
| `canonical_500` accepted? | yes — PNG, 500 ppi, no fpbench preprocessing |
| Representation? | the vendor's proprietary template; ISO/ANSI are exports |
| One scalar raw score? | yes — integer, higher is more similar, no threshold in it |
| Network in the computation? | no — licence validation only |
| SD300 development overlap? | `NO_EVIDENCE_FOUND`, never `PROVEN_ABSENT` |

The last four were read but not used: their gates were never reached, so they are
published as observations rather than as conclusions.

## The score

Upstream defines the matching score by its correspondence with a claimed false
acceptance rate, and publishes both the table and the formula:

```text
score = -12 * log10(FAR)          FAR as a fraction

FAR   100%   10%   1%   0.1%   0.01%   0.001%   0.0001%   0.00001%   0.000001%
score    0    12   24     36      48       60        72         84          96
```

This is a *native transformed score* and it is admissible as a raw score, because
the test is authorship rather than shape: it is the number the vendor's API
returns. fpbench performs no conversion in either direction, and the vendor's
recommended threshold of 48 belongs to a calibration stage or to nothing
(ADR 0102).

## What would move it

Activating the 30-day trial on one chosen platform — `Trial = true` in the
licensing configuration, start the licensing service, no serial number and no
personal information — then running a bounded qualification harness on fixtures
that are not SD300 and re-running the stage. Eleven gates become answerable at
that point.

Acquisition was this stage's to do. Activation is the maintainer's: it starts a
clock bound to one machine and excludes other licensed Neurotechnology products
on it (ADR 0099).

## What was not done

No licence activated, no trial reset, no protection mechanism touched, no network
experiment, no preset chosen from score distributions, no SD300 image read, no
adapter written, no threshold produced, no score published. Not one vendor byte
in Git.
