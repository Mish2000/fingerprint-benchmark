# VeriFinger 2025.2 — Algorithm 4 candidate record

```text
candidate_id            neurotechnology_verifinger_2025_2_1to1   (provisional)
implementation_origin   VENDOR_OFFICIAL_SDK
vendor                  Neurotechnology
declared version        VeriFinger 2025.2 SDK
verdict                 VERIFINGER_PREFLIGHT_INCOMPLETE
gates passed            8 of 17
gates awaiting action   9
blockers                0
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

## Why it is not admissible yet

**Not because anything is wrong with it.** No methodological blocker has been
found: not the artifact, not the licence, not the input domain, not the
representation, not the raw score, not the network role, not the provenance. This
candidate is the only one of the five with no adverse finding against it at all.

What is outstanding is one bounded qualification run. The pinned 2025.2 manual
publishes the complete set of externally selectable fingerprint settings — the
inventory is closed — and states a default for none of them, while stating
defaults for the face-side settings in the same tables. Ten score-affecting
values therefore have no upstream authority yet, and each becomes a
`DELIVERED_RUNTIME_DEFAULT` the moment somebody constructs the engine and reads
it.

Exactly one setting is settled, and only `verify-finger` settles it. Upstream's
tutorials configure the engine differently — the enrolment tutorial sets a
template size the verification tutorial never touches — so a profile taking one
value from each would be a configuration no upstream program has ever run
(ADR 0105).

```text
extraction gate, 8 outstanding      FingersTemplateSize
                                    FingersExtractionScenario
                                    FingersFastExtraction
                                    FingersQualityThreshold
                                    FingersMinimalMinutiaCount
                                    FingersDetectTips
                                    FingersDetectLiveness
                                    FingersLivenessConfidenceThreshold

matching gate, 2 outstanding        FingersMaximalRotation
                                    MatchingScenario

settled by the authoritative        FingersMatchingSpeed = LOW
sample, verify-finger
```

Each count is scoped to its own gate. A total is derived and labelled where it is
used, rather than one number standing for two scopes (ADR 0104).

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

All ten were asked and answered. Only a real blocker stops the run, so a gate
awaiting an action does not hide the gates after it — which is why the decisive
raw-score question is settled here rather than left unpublished behind an
unrelated chore (ADR 0104).

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
personal information — then `make stage11a-qualify` and re-deriving. Nine gates
become answerable at that point, and the next publication is either
`VERIFINGER_PREFLIGHT_PASS` or a technical blocker found by execution.

The harness exists: `integrations/verifinger-qualification/`, driven from
`fpbench.experiments.stage11a_qualification`. It sets only what `verify-finger`
sets, reads everything else, scores synthetic ridge-like fixtures that are not
SD300, and publishes no score value — it emits a SHA-256 per score and compares
digests.

Acquisition was this stage's to do. Activation is the maintainer's: it starts a
clock bound to one machine and excludes other licensed Neurotechnology products
on it (ADR 0099).

## Why the candidate search stays closed

There is nothing here to move on from. Every other candidate was refused for a
reason that would still be true tomorrow; this one is waiting on an afternoon.

## What was not done

No licence activated, no trial reset, no protection mechanism touched, no network
experiment, no preset chosen from score distributions, no SD300 image read, no
adapter written, no threshold produced, no score published. Not one vendor byte
in Git.
