# Stage 10B — id3 Finger SDK candidate preflight and access qualification

## Outcome

```text
ID3_FINGER_SDK_PREFLIGHT_FAIL
```

A complete result. Stage 10B decides whether the id3 Finger SDK can enter fpbench
as Algorithm 4 — not whether id3 is a good matcher, and not whether to implement
it. The answer here is no, the gate is named, and what would lift it is written
down (docs/adr/0094).

Nothing in this directory is a score, a threshold, a fingerprint image, a licence
byte or a credential. What it holds is descriptions: URLs and the status codes
they returned, a commit SHA, digests, sizes, published class members, and
sentences from a vendor's own pages.

## The candidate

```text
candidate_id            id3_finger_sdk_1to1        (provisional)
implementation_origin   VENDOR_OFFICIAL_SDK
product                 id3 Finger SDK, id3 Technologies
public version          4.5.0
```

No production `algorithm_id` is frozen. A final identity has to carry the exact
SDK version, the models, the extractor profile, the matcher profile and the
runtime, and none of those exists before a package does (docs/adr/0097).

## The gate matrix

| Gate | Status |
| :--- | :--- |
| 1 `PRODUCT_IDENTITY` | PASS |
| 2 `ACQUISITION_ACCESS` | **FAIL** |
| 3 `PACKAGE_IDENTITY` | not reached |
| 4 `INPUT_DOMAIN` | not reached |
| 5 `EXTRACTION_PROFILE` | not reached |
| 6 `MATCHER_PROFILE` | not reached |
| 7 `RAW_SCORE_ROUTE` | not reached |
| 8 `WORKLOAD_FEASIBILITY` | not reached |
| 9 `TRAINING_PROVENANCE` | not reached |
| 10 `LOCAL_SMOKE` | not reached |

`NOT_REACHED` is not a pass and not a soft failure. It records that the candidate
had already stopped, so the question was never asked. Those documents carry the
gate, the reason, whatever was observed incidentally before the stop — labelled
as observations, never as conclusions — and the requirements the gate would have
applied.

Cost of reaching this conclusion: **zero package bytes**, zero model bytes, zero
licence activations, zero runtimes, zero SD300 reads, zero scores.

## The blockers

| Code | Affects |
| :--- | :--- |
| `ID3_PACKAGE_NOT_OBTAINABLE` | the delivered SDK package |
| `ID3_LICENSE_NOT_OBTAINABLE` | an activated licence |
| `LICENSE_WORKLOAD_CAPACITY_UNRESOLVED` | the evaluation quota against the frozen workload |

All three are at Gate 2, and all three are about **access**, not about terms.
Nothing here says id3's licence forbids research use; that question was not
reached and is Stage 8E's to answer when a component exists (docs/adr/0095).

## The decisive question

> Does this project hold an exact, licensed, operable copy of the id3 Finger SDK
> that defines a complete 1:1 route from `canonical_500` to a raw score?

```text
NO
```

The vendor publishes no self-service download. Its own samples state that the SDK
archive and the activation key are issued together, after a request has been
accepted, and that the library checks a licence file before any other call. No
request has been made from this project. The advertised evaluation is 30 days
with `Limited API calls` and a single platform — a limit with no number, and no
statement of which operations consume it — so the quota could not have been
checked against the frozen workload even with a package in hand.

## The files

| File | What it holds |
| :--- | :--- |
| `candidate-identity.json` | the provisional identity, the ten gates, the frozen workload, the non-goals, and the Stage 10A predecessor |
| `public-product-observations.json` | every vendor page read, the pinned official samples, and the six locators that did not resolve |
| `access-qualification.json` | the acquisition route, what this machine holds, the runtime target that was not locked, and the Stage 8E position |
| `license-capability-report.json` | the advertised evaluation, the frozen workload, and the cost under each metering semantics |
| `sdk-package-manifest.json` | `NOT_REACHED`, with the identity fields a delivered package would have to carry |
| `model-artifact-manifest.json` | `NOT_REACHED`, with the transitive inventory that could not be closed |
| `input-domain-contract.json` | `NOT_REACHED`, with the `canonical_500` route and the constructions fpbench refuses to invent |
| `extraction-profile.json` | `NOT_REACHED`, with the seven fields a profile must freeze |
| `matcher-profile.json` | `NOT_REACHED`, with all five published options and their absent documented defaults |
| `score-contract.json` | `NOT_REACHED`, with the raw-score requirements and the SELF rule |
| `training-provenance.json` | `NOT_REACHED`, with what the vendor discloses and the SD300 overlap status |
| `runtime-smoke.json` | `NOT_REACHED`, with the twelve steps the smoke would have run |
| `preflight-report.json` | the verdict, gate by gate, every blocker, and the acceptance conditions |
| `stage-10b-finalization.json` | the marker |

## What resolved

* The product is identified and distinguished from four things it is not: the
  vendor's separate MicroFinger product, any MINEX submission, the samples
  repository itself, and any third-party wrapper.
* The vendor's official samples are pinned at commit `75d02adc`, release
  `4.5.0.0`, with four files cited by SHA-256. No byte of them is stored here.
* Five documentation locators this stage was written against answer HTTP 404.
  They are published with their status codes rather than replaced by the pages
  that did resolve, and the reference tree that resolves today is versioned and
  titled with one version — not the mixture of two the flat layout carried.
* Seven score-affecting settings — five matcher options and two extractor models
  — have no documented default anywhere public. That count is published as 7.
* The public single-image sample performs no detection and no ROI extraction,
  while the product page's headline sample does both because it starts from a
  four-finger slap. Two routes exist; which one the delivered package documents
  for a single finger is a question for the delivered package.
* SD300 overlap status would be `NO_EVIDENCE_FOUND` — which is not
  `PROVEN_ABSENT`, and is never converted into it.

## What was deliberately not done

```text
no package request          no activation           no SD300 read
no licence bypass           no trial reset          no crop invented
no production adapter       no threshold            no calibration
no 6,000 comparisons        no metrics              no fusion chosen on accuracy
```

No credential appears anywhere in this directory, and the finalization verifier
refuses to publish if one does — by key name or by value shape (docs/adr/0098).

## What opens

```text
opens_stage_10c:          false
opens_candidate_search:   true
```

The Algorithm 4 slot stays empty. A failure on access and quota is legitimate and
final for the route as it stands, and the response is another candidate — never a
workaround (docs/adr/0095).

One act would reopen this stage, and it belongs to a person rather than to a
program: the maintainer requests an evaluation or developer licence from the
vendor in their own name, receives the archive and the key, and re-runs the
stage. Eight gates become answerable for the first time at that point, and none
of them is answered in advance here.
