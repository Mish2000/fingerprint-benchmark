# Stage 12A — Innovatrics IDKit active acquisition and artifact/API preflight

## What this stage decides

Not "how do we integrate IDKit". One question:

```text
does an official, current Innovatrics IDKit package give fpbench a complete,
upstream-authoritative and reproducible route from canonical_500 to a raw 1:1
fingerprint score, without fpbench inventing preprocessing, extractor settings,
matcher settings or a score transformation?
```

Three outcomes, and all three are complete answers:

```text
IDKIT_PREFLIGHT_PASS             ->  opens Stage 12B
IDKIT_PREFLIGHT_FAIL             ->  opens a search for a different Algorithm 5
IDKIT_PREFLIGHT_PENDING_ACCESS   ->  opens nothing; nothing was found either way
```

Stage 11A and Stage 11B stay closed and belong to VeriFinger 2025.2 as Algorithm
4. Stage 11B's marker opened the search for Algorithm 5; Stage 12A binds its
fingerprint as a predecessor and edits nothing under either evidence directory
(docs/adr/0107).

## The outcome

```text
outcome:                       IDKIT_PREFLIGHT_FAIL
acquisition_status:            ACCESS_REFUSED
blocker:                       ACCESS_REFUSED_BY_VENDOR
failure_class:                 VENDOR_ACCESS_REFUSED
opens_stage_12b:               false
reopens_algorithm_5_search:    true
```

| # | Gate | Status |
| ---: | :--- | :--- |
| G1 | `ACQUISITION_ACCESS` | **FAIL** |
| G2 | `PACKAGE_RUNTIME_IDENTITY` | not reached |
| G3 | `RESEARCH_USE_AND_LICENSE` | not reached |
| G4 | `CANONICAL500_INPUT_ROUTE` | not reached |
| G5 | `SINGLE_FINGER_EXTRACTION_PROFILE` | not reached |
| G6 | `SINGLE_FINGER_MATCHER_RAW_SCORE` | not reached |
| G7 | `SCORE_AFFECTING_SETTINGS_CLOSURE` | not reached |
| G8 | `PAIR_SELF_DETERMINISM_FAILURES` | not reached |
| G9 | `WORKLOAD_RUNTIME_FEASIBILITY` | not reached |
| G10 | `TRAINING_PROVENANCE` | not reached |

Cost: zero package bytes, zero licence activations, zero runtimes, zero SD300
reads, zero scores. The final marker binds this result to the published evidence.

## Why this is now a failure rather than pending

On 2026-08-14 an Innovatrics Business Development representative explicitly
stated that Innovatrics does not participate in academic or research-only
evaluations and does not provide SDK licences for non-commercial benchmarking.
The evidence records that category and date without copying the email, naming the
representative or publishing an address.

That reply resolves the state as `ACCESS_REFUSED`. It is the exact finding for
which `ACCESS_REFUSED_BY_VENDOR` and `VENDOR_ACCESS_REFUSED` exist. `PENDING`
remains valid for an unanswered request, but it no longer describes this one
(docs/adr/0108).

The acquisition state machine is partitioned so that the difference cannot be
blurred:

```text
pending    NOT_ATTEMPTED  PORTAL_ACCESS_REQUIRED  REQUEST_SENT  REQUEST_PENDING
refusal    ACCESS_REFUSED  PACKAGE_UNAVAILABLE_FOR_TARGET
possession PACKAGE_OBTAINED
```

Only the two refusal states can fail G1. This run now occupies one of them, and
possession remains false.

## What was actually walked

Five public routes on 2026-08-13 — the public developer portal, the vendor's
public repositories, the legacy customer CRM (retired by the vendor), the current
customer portal (a sign-in page), and the learning portal (a course, not a
download). The sixth route, vendor sales, returned the explicit refusal on
2026-08-14. No alternative sales contact, reseller or artificial commercial
reframing will be used to route around it.

Three categories of non-vendor route were found and refused on provenance.

## Questions deliberately left unreached

The earlier design identified the following technical risks. G1 ended the
candidate before any of them could be tested, so they remain questions rather
than IDKit findings and the qualification machinery is not being revised.

**A consolidated multi-finger score (G5, G6).** IDKit organises fingerprints into
user records, and a record holding several fingers is scored by summing
per-position maxima. That is not a single-finger similarity and cannot be
recovered from one. Each compared record must hold exactly one fingerprint, or
both gates fail.

**A raw score behind a threshold (G6).** A decision is not a score, and neither
is a score the API surrenders only above a threshold. The obvious workaround —
setting the threshold to zero to make the numbers appear — is refused by name:
that is a decision layer with its knob turned down, and this benchmark's decision
layer belongs to a later stage.

**A hidden score-affecting default (G7).** A knob whose value and default are
both unknown is a hidden default, and the honest response is to fail rather than
publish a profile called frozen. Values come from the delivered runtime, from
version-matched documentation, or from the official sample; never from a value
that produced fewer failures on this project's fingerprints.

**An input route fpbench would have to invent (G4).** The benchmark holds PNGs
and IDKit is described as taking BMP or raw. A deterministic lossless decode into
the identical gray8 matrix, fed to the official raw-buffer API, is permitted
exactly as far as every pixel is proved identical. A crop, a resize, a rotation
or an enhancement is not.

## What exists in code, and what does not

| Built | Not built |
| :--- | :--- |
| `stage12a_idkit_identity` — the frozen vocabulary | a production `FingerprintAlgorithmAdapter` |
| `stage12a_idkit_observations` — routes walked, statements retrieved | a canonical experiment configuration |
| `stage12a_acquisition` — the state machine and the store readers | the 6,000-comparison runner |
| `stage12a_qualification` — the harness, its engine protocol, the fake SDK | a `ResultSet`, a threshold, a calibration, a metric |
| `stage12a_preflight` — the ten gates and the documents | any production algorithm id |
| `stage12a_finalization` — the marker, the publisher, the boundary audit | |

The qualification harness is the part that would normally not exist yet. It does,
because Stage 11A spent days of a 30-day trial discovering that its harness would
not compile. Here the driver sits behind a four-method protocol, a fake engine
implements it, and CI drives every pass — both orientations, SELF from two
extractions, a real process restart, three provoked failures — on every run with
no package and no licence (docs/adr/0111).

The fake can never answer a gate. Every record carries an engine kind and the
preflight reads only `DELIVERED_SDK`.

## Running it

```bash
make stage12a-status
```

```bash
make stage12a-acquire
```

```bash
make stage12a-qualify-fake
```

```bash
make stage12a-contract
```

None of them fetches anything, activates anything, or needs a package.

## Final routing

Stage 12B stays closed. The failure reopens the Algorithm 5 search: the id3 Finger
SDK request remains under vendor review in the background, while Neurodactyl is
the next active candidate. That work is a separate preflight, not a continuation
or reframing of the refused IDKit request.
