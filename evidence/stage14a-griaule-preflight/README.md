# Stage 14A — Griaule GBS Fingerprint SDK artifact and route preflight

**Outcome: `GRIAULE_PREFLIGHT_INCOMPLETE`. No finalization marker exists, and that
is the correct state.**

This stage asks one question, and it asks it before any code is written against
the candidate:

> Can an official, current Griaule GBS Fingerprint SDK package be obtained, with
> the trial that is distributed with it, and does that package define a complete
> authoritative route from `canonical_500` to a native 1:1 similarity score —
> with no crop, resize, threshold or score transform chosen by fpbench?

Four gates, eight documents, no bridge, no adapter, no execution.

## Why this stage is small

Stage 12A and Stage 13A each defined ten gates and published thirteen documents.
Both ended at the first one. Innovatrics refused an evaluation licence outright;
FingerCell's archive was obtained, hashed and compiled against, and its trial
entitlement never arrived. Two full preflight harnesses were built for candidates
that could not be executed at all.

So the order here is inverted on purpose: acquisition and route viability are
tested first, and the harness is built only if they pass (docs/adr/0123).

## The four gates

| # | Gate | Status |
|---|------|--------|
| 1 | `OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS` | `ACTION_REQUIRED` |
| 2 | `DIRECT_CANONICAL500_INPUT_ROUTE` | `NOT_REACHED` |
| 3 | `SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE` | `NOT_REACHED` |
| 4 | `SCORE_AFFECTING_ROUTE_CLOSURE` | `NOT_REACHED` |

Every gate after G1 is a question about delivered bytes, so nothing can be
answered around a package nobody holds. The run halts at G1 and the rest are
published `NOT_REACHED` rather than guessed at from the vendor's documentation.

## What G1 found

Every official Griaule route was retrieved on 2026-08-15 and **none of them
serves the package**:

- the SDK documentation page, with every link on it enumerated — its installation
  section begins *after* the file is in hand ("you must have one of the following
  versions… to install the SDK, double-click on the file"), and the only outbound
  routes to the vendor are two e-mail addresses;
- the documentation site's own complete page index — documentation, no packages;
- the corporate site's download path, probed directly — it does not exist;
- the corporate contact page — a form and telephone numbers, no mention of an
  SDK, a trial, an evaluation or a download;
- the support knowledge base — an FAQ, guides and a request form, no downloads
  section, and a search of its articles returns nothing at all for the SDK.

The package is available from software-catalogue sites, a reseller, a document
mirror and a download host advertising a licence bypass. All four are recorded in
`acquisition-status.json` as **seen and refused** rather than omitted, because an
evidence trail that quietly left them out would not show that they were declined.

So acquisition needs a request, and the request has not been sent. That is
`ACTION_REQUIRED`, not `PENDING_ACCESS`: nothing is waiting on Griaule, because
nobody has asked them yet. Publishing this as a vendor dependency would imply a
silence that does not exist (docs/adr/0121).

## What this stage does not claim

The vendor's documentation states a 90-day bundled trial, a 500 × 500 extraction
limit with larger images cropped, a `GrExtract`/`GrVerify` API with
`GrSetVerifyParameters`/`GrGetVerifyParameters` beside it, a default threshold of
20 and a default rotation tolerance of −1. Every one of those is recorded in
`package-manifest.json` as an **indication only**.

None of them settles a gate. The page is undated, targets a Windows generation
two releases old, and documents a migration from a 2009 product. What it says a
default is worth is not what a delivered engine was constructed with
(docs/adr/0110). In particular:

- **G2 is genuinely open.** A crop the extractor performs on a full image it was
  handed is algorithm behaviour and is fine. A crop the *caller* is required to
  perform first is fpbench choosing which part of the finger the algorithm sees,
  and that is a hard reject. The documentation does not say which of the two the
  API requires (docs/adr/0124).
- **G3 is genuinely open.** "The threshold is the minimum score needed to state
  that two fingerprints do match" is equally consistent with an API that returns
  the score and one that returns only the comparison. Only a delivered header
  settles it.

The candidate therefore carries `implementation_version:
UNRESOLVED_UNTIL_PACKAGE`. Griaule publishes three build names and no version
number, so there is no number to freeze even if freezing one from a page were
allowed.

## The documents

| File | What it answers |
|------|-----------------|
| `predecessor-binding.json` | what this stage is a successor to, and what it may never read |
| `acquisition-status.json` | G1 — every official route walked, and where acquisition stands |
| `package-manifest.json` | G1 — what the package turned out to be, or nothing |
| `research-use-trial.json` | G1 — what the delivered terms and bundled trial permit |
| `input-route.json` | G2 — how a canonical image would reach the extractor |
| `score-contract.json` | G3 — the raw 1:1 score, or the reason there is none |
| `route-closure.json` | G4 — every knob that could reach the score, and its authority |
| `preflight-report.json` | the whole run, and what it does and does not say |

`stage-14a-finalization.json` is absent by design. A marker is a finalization,
and only `GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_PASS` and
`GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL` are final. The publisher refuses to write
one under `GRIAULE_PREFLIGHT_PENDING_ACCESS` or `GRIAULE_PREFLIGHT_INCOMPLETE`,
and a test proves the refusal.

## Bindings

| Stage | Fingerprint | Why |
|-------|-------------|-----|
| 13A | `b24bdb672926abfb5dd5a9e03a4c3aab39f51488d9a5413092adef392d99871d` | the predecessor: `FINGERCELL_PREFLIGHT_FAIL` / `OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED`, which reopened the Algorithm 5 search |
| 11B | `3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c` | Algorithm 4's 6,000 published outcomes. Bound and never read |
| 8E | `c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8` | the third-party research-use policy, reused and not reopened |

## What happens next

1. Send one official request, in the maintainer's own name, through a route the
   vendor publishes, stating that the use is academic, research-only and
   non-commercial.
2. G1 moves to `PENDING_ACCESS` and the outcome to
   `GRIAULE_PREFLIGHT_PENDING_ACCESS`. Still no marker.
3. A delivery moves G1 to a package that is hashed and inspected here, and G2–G4
   become answerable.
4. A refusal, or a confirmation that no package is available for this use, is the
   only thing that turns this into `GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL`.

If all four gates pass, Stage 14B is a single stage: a bounded non-SD300 runtime
qualification, and if it is clean, the production adapter over the same frozen
route and the 6,000 canonical raw outcomes.

## What this stage did not do

No trial was activated. No score, template or image was produced. No SD300 image
byte, pair manifest or score was read. No prior algorithm's scores were consulted.
No adapter, registry entry, experiment config, threshold, calibration or metric
exists. No vendor byte and no credential entered this repository.
