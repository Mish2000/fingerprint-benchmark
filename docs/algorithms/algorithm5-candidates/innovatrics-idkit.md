# Innovatrics IDKit — Algorithm 5 candidate record

```text
candidate_id            innovatrics_idkit_fingerprint_1to1   (provisional)
implementation_origin   VENDOR_OFFICIAL_SDK
vendor                  Innovatrics
publicly advertised     IDKit SDK 7.6 (a course listing, not a package)
implementation_version  UNRESOLVED_UNTIL_PACKAGE
outcome                 IDKIT_PREFLIGHT_FAIL
stopped at              G1, ACQUISITION_ACCESS
acquisition_status      ACCESS_REFUSED
failure_class           VENDOR_ACCESS_REFUSED
```

## What it is

A commercial fingerprint SDK for 1:1 verification and 1:N identification, built
on Innovatrics' own proprietary fingerprint templates. It is scanner-independent,
works from images rather than from a particular capture device, and exposes a
similarity score separately from the match decision — which is the shape this
benchmark needs.

Nothing in this record is a judgement about the product. It is a mature
commercial matcher from a vendor with a long record in the field.

## Why it is not admissible today

Not because of a measured property of the algorithm. Because the vendor
explicitly refused SDK access for this project's use case.

Innovatrics distributes the IDKit SDK through its customer portal. Five official
routes were walked on 2026-08-13:

| Route | What was found |
| :--- | :--- |
| the public developer portal | documents the platform and toolkit products; IDKit is not listed, and nothing is downloadable |
| the vendor's public repositories | samples and integrations for the onboarding and face products; no IDKit |
| the legacy customer CRM | serves a notice that it has been retired, and points at the current portal or a sales representative |
| the current customer portal | a sign-in page; no unauthenticated download and no self-registration observed |
| the learning portal | a course about IDKit SDK 7.6, and an email address |

The sixth route was completed on 2026-08-14. An Innovatrics Business Development
representative explicitly stated that the company does not participate in
academic or research-only evaluations and does not provide SDK licences for
non-commercial benchmarking. The record keeps this categorical summary and date,
not the correspondence, the representative's identity or an address. G1 therefore
fails with `ACCESS_REFUSED_BY_VENDOR` (docs/adr/0108).

Three categories of non-vendor route exist and are refused on provenance:
software-catalogue sites (some offering 1.x and 2.x-era builds), reseller
storefronts, and third-party mirrors of vendor documents. A package whose chain
of custody does not run to the vendor is a package nothing can pin.

## What the public material would have required us to check

Nine statements were retrieved from Innovatrics' own support material. None of
them freezes a value: the support articles are undated, name an `IEngine_*` API
from an older generation than 7.6, and point at a portal the vendor has since
retired. They remain untested questions because G2-G10 were not reached
(docs/adr/0110).

**The structural risk — the one that could disqualify this candidate.** IDKit
organises fingerprints into user records, and a record holding several fingers is
scored by grouping similarities by finger position, taking the maximum within
each position and summing those maxima across positions. That is not a
single-finger similarity and cannot be recovered from one. If the delivered API
can only be driven through records, each compared record must hold exactly one
fingerprint — and if that cannot be guaranteed, gates G5 and G6 fail.

**The input risk.** IDKit is described as accepting BMP or raw images, in memory
or in files. This benchmark holds 8-bit greyscale PNGs at 500 PPI. If the
delivered package does not read PNG, the permitted route is a deterministic
lossless decode into the identical gray8 matrix and then the official raw-buffer
API — with every pixel proved identical, and never a crop, a resize, a rotation
or an enhancement. The decoder that would do it is written, and the contract
suite round-trips it.

**The orientation.** The matcher is documented as not commutative. There is
nothing to normalise: `pair.left → probe` and `pair.right → gallery` are frozen,
both orderings are run once in qualification to publish that they can differ, and
no maximum or average of them enters a score (docs/adr/0109).

**The score.** Described on a scale normalised roughly by `-10·log10(FAR)`, with
the decision resting on a threshold the integrator chooses. A vendor scale that
is already a transformation of a claimed FAR is still a raw score and is passed
through untouched; what is refused is a second transformation by fpbench, and
reading scores by pushing the threshold to zero.

**The resolution.** DPI is described as affecting extraction rather than
matching, as needing to be correct before extraction, and as remembered by the
resulting template. Input images are described as internally resampled to 500 dpi
— which at 500 PPI in is a resample to the resolution the image already has, and
is the vendor's processing rather than ours.

**The licence.** Required, machine-bound, generated through the portal or a
documented REST interface. Nothing about it is bypassed, and the qualification
harness is compiled and proved against a fake engine before any licence is
generated, so that a time-limited clock is not spent on build errors
(docs/adr/0111).

## Final disposition

`ACCESS_REFUSED` is now the finding. Stage 12B stays closed and the Algorithm 5
search reopens. This project will not seek another sales contact, a reseller or a
commercial reframing to route around the stated policy. IDKit is removed from the
active candidate list.

## Where the record lives

`evidence/stage12a-idkit-preflight/` — eleven derived documents and the final
`IDKIT_PREFLIGHT_FAIL` marker.
