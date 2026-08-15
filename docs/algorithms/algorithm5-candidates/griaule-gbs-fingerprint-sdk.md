# Griaule GBS Fingerprint SDK — Algorithm 5 candidate

| | |
|---|---|
| `candidate_id` | `griaule_gbs_fingerprint_sdk_1to1` |
| `algorithm_slot` | `algorithm_5` |
| `implementation_origin` | `VENDOR_OFFICIAL_SDK` |
| `implementation_version` | `UNRESOLVED_UNTIL_PACKAGE` |
| `production_algorithm_id_frozen` | `false` |
| Stage | 14A, `GRIAULE_PREFLIGHT_INCOMPLETE` |

## Why this candidate

Stage 12A (Innovatrics IDKit) ended in a vendor refusal. Stage 13A
(Neurotechnology FingerCell 3.3) obtained the archive and could not establish a
trial entitlement. The Algorithm 5 slot is still open.

Griaule is worth asking about because its published product description matches
what this benchmark needs at the top level: fingerprint extraction plus one-to-one
verification, a trial licence distributed with the SDK, Linux and Windows builds
on x86 and x86-64, and a documented separation between a similarity score and the
threshold applied to it.

That separation is the thing. A matcher that returns only a match/no-match answer
is unusable here regardless of how good it is, because this benchmark stores raw
scores and derives every decision from its own protocol.

## Why the version is a sentinel

Griaule's documentation names three builds — `GBS Fingerprint SDK (x86-64)`,
`(x86)` and `(Linux)` — and publishes **no version number, no build number and no
release date** for any of them. The installation section assumes the reader
already has the file.

There is therefore no number to freeze even if freezing one from a page were
allowed, and it is not: only delivered bytes settle identity (docs/adr/0110). The
candidate carries `UNRESOLVED_UNTIL_PACKAGE` until a package is hashed here, and
a `PASS` marker that still carried the sentinel would fail to construct.

## Acquisition

**No official Griaule route serves the package.** Walked 2026-08-15:

| Route | Outcome |
|---|---|
| SDK documentation page (all links enumerated) | no package; two e-mail addresses |
| documentation site's complete page index | no package |
| corporate site `/downloads` and `/en/downloads` | do not exist |
| corporate contact page | a form and phone numbers; no SDK, trial or download |
| support knowledge base (+ article search for the SDK) | no downloads section; zero results |
| a named request to the vendor | **not sent** |

The support host answers automated clients with a 403 and serves a normal
knowledge base in a browser. It is recorded as retrieved by that means, not as
unreachable and not as absent (docs/adr/0122).

### Refused sources

The package *is* obtainable elsewhere, and none of it counts: software-catalogue
and freeware sites publishing 2007- and 2009-generation builds, a biometrics
reseller, a 2014 manual mirrored on a document-sharing site, and a download host
advertising the SDK together with a licence bypass. All four are recorded in the
evidence as seen and declined — the last one especially, because it is the first
result a naive search surfaces and an evidence trail that omitted it would not
show it had been refused.

No licence mechanism is bypassed, reset or worked around in this project at any
stage.

## The two open questions

### G2 — the 500 × 500 extraction limit

Capture supports up to 1280 × 1280 at 125–1000 DPI. Extraction states a maximum
of 500 × 500 and that *larger images are cropped*. The documentation does not say
who crops.

- extractor crops a full image it was handed → algorithm behaviour, fine
- caller must crop first → `FPBENCH_PREPROCESSING_REQUIRED`, hard reject

fpbench will not choose a crop origin, resize, pad, rotate, select a region of
interest, enhance or normalise (docs/adr/0124). A lossless container change into
BMP is permitted if every pixel value and the geometry survive it.

### G3 — score or decision

"The threshold is the minimum score needed to state that two fingerprints do
match. The default value is 20." That sentence is equally consistent with an API
that returns the score and one that returns only the comparison. `GrVerify`'s
actual return semantics come from a delivered header.

## Settings that cannot be missing

The public documentation proves at least two matcher parameters exist —
verification threshold (default 20) and rotation tolerance (default −1) — so an
inventory that never mentioned them would be visibly incomplete. Both defaults
are recorded as upstream observations; neither is applied or calibrated.

Notably, the previous generation's `SetExtractParameters`/`GetExtractParameters`
are listed as discontinued, which *suggests* a narrower extraction knob surface
than Stage 13A's candidate had. The delivered headers must confirm that rather
than inherit it.

## Status

`GRIAULE_PREFLIGHT_INCOMPLETE`. G1 `ACTION_REQUIRED`, G2–G4 `NOT_REACHED`, no
marker. Nothing has been established about Griaule — including that it is
unwilling, because nobody has asked yet.

See [`docs/experiments/stage14a-griaule-preflight.md`](../../experiments/stage14a-griaule-preflight.md)
and [`evidence/stage14a-griaule-preflight/`](../../../evidence/stage14a-griaule-preflight/).
