# id3 Finger SDK — Algorithm 4 candidate record

```text
candidate_id            id3_finger_sdk_1to1        (provisional)
implementation_origin   VENDOR_OFFICIAL_SDK
vendor                  id3 Technologies
publicly documented     Finger SDK 4.5.0
verdict                 ID3_FINGER_SDK_PREFLIGHT_FAIL
stopped at              gate 2, ACQUISITION_ACCESS
```

## What it is

A commercial fingerprint SDK offering capture, extraction, matching and liveness
detection, with bindings for C, C++, C#, Python, Java, Kotlin, Swift and Dart,
and builds for Windows (x86, x86-64), Linux (x86-64), macOS, Android and iOS.
Python and Linux/Windows x86-64 are what this project would use.

Its 1:1 route is exactly the shape this benchmark needs: one integer per
comparison, in 0..65535, with the match/no-match decision applied afterwards
through a separate threshold constant.

Nothing in this record is a judgement about the product. It is a mature,
independently evaluated commercial matcher.

## Why it is not admissible today

Not because of anything about the algorithm. Because this project does not have
it.

| | Present |
| :--- | :--- |
| delivered SDK package | no |
| activation key | no |
| activated licence | no |
| model artifacts | no |
| known quota | no |

The vendor's own samples state the route:

> a licence must be requested from id3 Technologies, and once the request is
> accepted the requester receives both a licence activation key and a ZIP archive
> containing the SDK itself

There is no download link and no self-service route. Activation binds an
activation key to a host hardware code and produces a licence file, and the
library's first call in every sample is a licence check, commented as required
before any other function of the SDK.

The free evaluation is advertised as 30 days, `Limited API calls` and `Single
platform`. The limit has no number and no public statement says which operations
consume it, while the frozen workload costs at most 9,200 metered operations.

```text
ID3_PACKAGE_NOT_OBTAINABLE
ID3_LICENSE_NOT_OBTAINABLE
LICENSE_WORKLOAD_CAPACITY_UNRESOLVED
```

All three are access findings. None of them is a statement about id3's licence
terms, which were not read for that purpose and are Stage 8E's question when a
component exists (docs/adr/0095).

## What the public record does say

Recorded as observations. The gates that would have used them were never reached.

**Single-finger route.** The official Python recognition sample, at commit
`75d02adc`:

```text
FingerImage.from_file(..., GRAYSCALE_8_BITS)
image.set_resolution(500)
FingerExtractor(minutia_detector_model=..., thread_count=4).create_template(image)
FingerMatcher().compare_templates(reference, probe)
```

No slap detection, no ROI extraction. The product page's headline sample does
both, because it starts from a four-finger slap. Two published routes exist and
this benchmark's inputs fit the second; which one the *delivered* package
documents for a single finger is a question for the delivered package.

**Resolution.** The sample comments that id3's processors use only 500 dpi images
and that anything else must be rescaled before use, and that omitting
`set_resolution` produces an "Invalid resolution" error during extraction.
`canonical_500` is already 500 ppi 8-bit grayscale, so no fpbench transformation
would be needed. That is a reason to expect gate 4 to pass, not gate 4 passing.

**Models.** At least an aligner and a minutia detector, downloaded separately
into a `models/` folder whose addresses live in the SDK's own developer guide —
which ships inside the package. The model set cannot be enumerated without the
package, let alone closed over by digest.

**Template families.** The vendor reports four fusions: MINEX only; MINEX with
minutia embeddings; MINEX with finger embedding; all three. It also recommends a
combination *by sensor size*. Choosing the variant with the better published
error rate would make this benchmark a report on a configuration chosen for its
numbers, and it is refused (docs/adr/0097).

**Defaults.** All five published matcher options and both extractor models are
score-affecting, and the class reference states a default for none of them. Seven
unresolved score-affecting defaults, published as seven.

**Provenance.** Public evaluation on FVC2000, FVC2002 and FVC2004, and MINEX
interoperable minutiae. Nothing public describes the training corpus. A
proprietary product is not asked to disclose one as a condition of entry; the
expected status is `PROPRIETARY_UNDISCLOSED` with SD300 overlap
`NO_EVIDENCE_FOUND`, which is never converted into `PROVEN_ABSENT`.

## What would make it admissible

The maintainer requests an evaluation or developer licence from the vendor, in
their own name, receives the archive and the activation key, and re-runs Stage
10B. That is a person-to-vendor exchange; it is not something the preflight
performs, and no credential from it enters this repository.

Eight gates become answerable at that point, and none is answered in advance
here. The full conjunction is published in `preflight-report.json`:

```text
exact official package exists          every extraction option frozen
licence actually usable                every matcher option frozen
quota covers the frozen workload       one threshold-free raw score
every required model known             SELF executable independently
canonical_500 enters unaltered         pair order understood
single-finger route authoritative      score restart-deterministic
                                       no SD300 consulted
```

If one of those is missing, id3 is not chosen.

## What is refused, whatever happens

No licence bypass, no trial reset, no crack, no third-party redistribution of the
package, and no reconstruction of the algorithm from its documentation. A failure
on access or quota is legitimate and final for the route as it stands, and the
response is another candidate.

## Sources

Every locator, its retrieval status and the date it was read are in
`evidence/stage10b-id3-finger-sdk-preflight/public-product-observations.json`,
including the five that answer HTTP 404.
