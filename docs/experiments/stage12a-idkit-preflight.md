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
outcome:              IDKIT_PREFLIGHT_PENDING_ACCESS
acquisition_status:   PORTAL_ACCESS_REQUIRED
blockers:             none
failure_class:        none
marker:               not written, and correctly so
```

| # | Gate | Status |
| ---: | :--- | :--- |
| G1 | `ACQUISITION_ACCESS` | **PENDING** |
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
reads, zero scores.

## Why pending is not failure

Stage 10B published `ID3_FINGER_SDK_PREFLIGHT_FAIL` for a vendor nobody had
written to, and then had to explain in almost every document that the word *fail*
did not mean anybody had refused anything. Stage 12A does not repeat that.

`PENDING` belongs to exactly one gate — a check at import time enforces it — and
it is the only outcome that writes no marker. The marker model raises on the
pending outcome outright, and the publisher refuses before it gets there. A
marker is a finalization, and nothing about waiting for a vendor is final
(docs/adr/0108).

The acquisition state machine is partitioned so that the difference cannot be
blurred:

```text
pending    NOT_ATTEMPTED  PORTAL_ACCESS_REQUIRED  REQUEST_SENT  REQUEST_PENDING
refusal    ACCESS_REFUSED  PACKAGE_UNAVAILABLE_FOR_TARGET
possession PACKAGE_OBTAINED
```

Only the two refusal states can fail G1, and possession is never asserted: it is
produced by a package in the store that verifies against a declaration of what it
is and where it came from.

## What was actually walked

Five official routes on 2026-08-13 — the public developer portal, the vendor's
public repositories, the legacy customer CRM (retired by the vendor), the current
customer portal (a sign-in page), and the learning portal (a course, not a
download). The sixth, a request to the vendor in the maintainer's own name, has
not been made: correspondence with a vendor is a person-to-vendor exchange, and
it is not something a preflight performs on anybody's behalf.

Three categories of non-vendor route were found and refused on provenance.

## The decisive risks

Ordered by how likely each is to end this candidate.

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

## What happens when a package arrives

1. Place it in the local artifact store under `innovatrics-idkit/`, with a
   `package-declaration.json` naming the product, the family, the version, the
   build, the filename, the size, the digest, the delivery channel and the
   platform. G1 turns `PASS`.
2. Inspect it and write `package-inspection.json`: the binding selected, the
   runtime closure, the input route, the representation, every setting with its
   provenance, the score contract, the licence entitlement and the provenance
   search. G2 to G7 become answerable.
3. Write the adapter that implements `QualificationEngine` against the selected
   binding. Nothing about it is written in advance, because nothing may be
   assumed about which binding the package ships.
4. **Then** generate the licence, and run at most twenty comparisons. G8 and G9
   become answerable.
5. `make stage12a-documents`, commit, `make stage12a-publish`, commit.

Only a `PASS` opens Stage 12B, which would be the production integration and the
6,000 canonical raw outcomes — the same shape Stage 11B took for VeriFinger.
