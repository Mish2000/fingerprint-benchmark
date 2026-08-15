# Stage 14A — Griaule GBS Fingerprint SDK minimal artifact/route preflight

## The question

> Can an official, current Griaule GBS Fingerprint SDK package be obtained, with
> the trial that is distributed with it, and does that package define a complete
> authoritative route from `canonical_500` to a single-fingerprint template and a
> native 1:1 similarity score — with no crop, resize, threshold or score
> transform chosen by fpbench?

Four gates answer it, in a frozen order, and the run stops at the first gate that
does not pass.

This is an artifact and API preflight only. It activates nothing, executes
nothing that produces a score, and builds no bridge.

## What is different about this stage

It is small on purpose, and the smallness is the decision (docs/adr/0123).

Stage 12A defined ten gates, a qualification harness and thirteen documents for
Innovatrics IDKit, and reached gate one — Innovatrics does not license SDKs for
academic evaluation. Stage 13A defined ten gates, thirteen documents, a compiled
C++ bridge and a harness for Neurotechnology FingerCell, went further — the
archive was fetched, hashed, unpacked and compiled against — and reached gate
three, where the trial entitlement never arrived. Neither candidate produced a
single comparison.

Both times the work that settled the stage was small and came first, and the work
thrown away was large and came before it. So Stage 14A inverts the order: ask the
questions that could disqualify the candidate, and build the harness only if they
pass.

## The four gates

```text
G1  OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS    can we get it, with its trial?
G2  DIRECT_CANONICAL500_INPUT_ROUTE       can our image enter it unmodified?
G3  SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE    can we get a raw scalar score out?
G4  SCORE_AFFECTING_ROUTE_CLOSURE         is anything left for us to invent?
```

Every gate after G1 is a question about delivered bytes, so — unlike Stage 13A,
where a training-provenance search needed no runtime and could be answered out of
order — **every non-passing state stops the run**. There is nothing to ask around
a package nobody holds.

## Five gate states, and three of them are not verdicts

Griaule is the first candidate where a vendor wait and a chore of our own are the
same gate at different moments, so both vocabularies are live at once
(docs/adr/0121):

```text
vendor or external dependency outstanding
    -> PENDING_ACCESS

local action not yet performed
    -> ACTION_REQUIRED

authoritative attempt or inspection disproved viability
    -> FAIL
```

Only `PASS` and `FAIL` are final, and only those two produce a marker. The two
non-final outcomes — `GRIAULE_PREFLIGHT_PENDING_ACCESS` and
`GRIAULE_PREFLIGHT_INCOMPLETE` — are refused by the marker class outright.

The distinction matters because the two middle states look identical from outside
and mean opposite things. Publishing an unsent request as a vendor wait would be
an unearned slur on a vendor nobody contacted.

## Where the stage stands

**`GRIAULE_PREFLIGHT_INCOMPLETE`. G1 is `ACTION_REQUIRED`; G2–G4 are
`NOT_REACHED`. No marker exists.**

Every official Griaule route was retrieved on 2026-08-15 and none of them serves
the package: the SDK documentation page with every link on it enumerated, the
documentation site's complete page index, the corporate site's download path, the
corporate contact page, and the support knowledge base including a search of its
articles. The vendor's own installation instructions begin *after* the file is in
hand, and the only outbound routes to the vendor are two e-mail addresses.

The package is available from catalogue sites, a reseller, a document mirror and
a host advertising a licence bypass. All four are recorded as **seen and refused**
rather than omitted.

So acquisition needs a request, and the request has not been sent. That is our
move, not Griaule's.

## What the documentation says, and why none of it settles a gate

| Statement | Where it matters | Why it is not an answer |
|---|---|---|
| a trial licence valid for 90 days is distributed with the SDK | G1 | "distributed with" is not "we can download it" |
| three builds — x86-64, x86, Linux — and no version number anywhere | identity | there is no number to freeze, hence `UNRESOLVED_UNTIL_PACKAGE` |
| extraction maximum 500 × 500; larger images are cropped | G2 | it does not say whether the *caller* or the *extractor* crops |
| `GrExtract`, `GrVerify`, `GrSetVerifyParameters`, `GrGetVerifyParameters` | G3, G4 | a call list is not a return-value contract |
| the threshold is the minimum score needed to state a match; default 20 | G3 | equally consistent with returning the score and with returning only the comparison |
| rotation tolerance, default −1 | G4 | proves the settings surface is not empty; the delivered value is another matter |
| BMP supported for image saving and loading | G2 | indicates a container adaptation may be needed, not which one |

The page is undated, targets Windows 7–10, and documents a migration from a 2009
product. It shapes every question here and settles none (docs/adr/0110).

## The two gates that are genuinely open

**G2 — who crops?** A crop the extractor performs on a full image it was handed is
algorithm behaviour, published as such. A crop fpbench must perform first is
fpbench choosing which part of each finger the algorithm sees, and it would enter
all 6,000 scores silently. That is a hard reject, `FPBENCH_PREPROCESSING_REQUIRED`
(docs/adr/0124).

One adaptation is permitted: a lossless decode into the container the delivered
API accepts, carrying 500 ppi in the container's own metadata — and only if every
pixel value is identical and the geometry is unchanged.

**G3 — score or decision?** If `GrVerify` exposes the similarity score, good. If
it exposes only a thresholded answer, `RAW_SCORE_ROUTE_UNAVAILABLE`, and sweeping
the threshold to reconstruct a score is not a remedy. The numeric type, the range
and the return semantics all come from the delivered header.

The upstream default threshold of 20 is recorded as an observation. It is never
applied, tuned or calibrated: this benchmark stores raw scores and derives every
decision in its own decision layer.

## The evidence

```text
evidence/stage14a-griaule-preflight/
├── README.md
├── predecessor-binding.json
├── acquisition-status.json      G1 — every route walked, and where we stand
├── package-manifest.json        G1 — what the package is, or nothing
├── research-use-trial.json      G1 — delivered terms and bundled trial
├── input-route.json             G2
├── score-contract.json          G3
├── route-closure.json           G4
├── preflight-report.json
└── stage-14a-finalization.json  PASS/FAIL only — absent today
```

## Running it

```bash
make stage14a-status
```

```bash
make stage14a-acquire
```

```bash
make stage14a-contract
```

`stage14a-documents` writes the eight documents; `stage14a-publish` writes the
marker too and refuses a non-final outcome.

## Bindings

| Stage | Fingerprint | Why |
|---|---|---|
| 13A | `b24bdb67…d99871d` | the predecessor: `FINGERCELL_PREFLIGHT_FAIL` / `OPERATIONAL_TRIAL_ENTITLEMENT_NOT_ESTABLISHED` |
| 11B | `3d271490…591684c` | Algorithm 4's 6,000 outcomes. Bound and never read |
| 8E | `c08648de…2540e8` | the research-use policy, reused and not reopened |

The boundary audit is baselined at `db9cfce2…`, the commit that republished Stage
13A's marker.

## What happens next

1. Send one official request, in the maintainer's own name, stating that the use
   is academic, research-only and non-commercial.
2. G1 → `PENDING_ACCESS`, outcome → `GRIAULE_PREFLIGHT_PENDING_ACCESS`. Still no
   marker.
3. A delivery → hash and inspect here → G2–G4 become answerable.
4. A refusal, or a confirmation that no package is available for this use, is the
   only thing that makes this `GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL`.

If all four gates pass, Stage 14B is one stage: bounded non-SD300 runtime
qualification, then — if clean — the production adapter over the same frozen
route and the 6,000 canonical raw outcomes. No separate readiness stage.

## What this stage does not do

No trial activation. No score-bearing execution. No determinism experiment. No
performance benchmark. No SD300 access. No prior algorithm's scores. No
`FingerprintAlgorithmAdapter`. No registry integration. No 6,000-pair run. No
threshold profile. No calibration. No metrics.

The list is published in `preflight-report.json` as `what_this_stage_does_not_do`,
so the boundary is checkable rather than promised.
