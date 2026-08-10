# Stage 10B — id3 Finger SDK candidate preflight and access qualification

## What this stage decides

Not "how do we integrate id3". One question:

```text
does a package of the id3 Finger SDK exist here that is exact, legally and
practically operable for local research, and that defines a complete 1:1 route
from canonical_500 to a raw score with no score-affecting choice left to fpbench?
```

Two outcomes, and both are complete:

```text
ALGORITHM4_CANDIDATE_SELECTED     ->  opens Stage 10C
ID3_FINGER_SDK_PREFLIGHT_FAIL     ->  opens a candidate search
```

Stage 10A stays closed and belongs to AFR-Net and JIPNet. Its candidate set was
frozen before its result was known, and adding id3 to it after the fact would
change the research question after the answer was visible. Stage 10B binds Stage
10A's final fingerprint as a predecessor and edits nothing under its evidence
directory (docs/adr/0094).

## The outcome

```text
outcome:                  ID3_FINGER_SDK_PREFLIGHT_FAIL
failure_class:            OPERATIONAL_ACCESS_NOT_ESTABLISHED
id3_proven_unobtainable:  false
```

| # | Gate | Status |
| ---: | :--- | :--- |
| 1 | `PRODUCT_IDENTITY` | PASS |
| 2 | `ACQUISITION_ACCESS` | **FAIL** |
| 3 | `PACKAGE_IDENTITY` | not reached |
| 4 | `INPUT_DOMAIN` | not reached |
| 5 | `EXTRACTION_PROFILE` | not reached |
| 6 | `MATCHER_PROFILE` | not reached |
| 7 | `RAW_SCORE_ROUTE` | not reached |
| 8 | `WORKLOAD_FEASIBILITY` | not reached |
| 9 | `TRAINING_PROVENANCE` | not reached |
| 10 | `LOCAL_SMOKE` | not reached |

Cost: zero package bytes, zero model bytes, zero activations, zero runtimes,
zero SD300 reads, zero scores.

## The decisive question

> Does this project hold an exact, licensed, operable copy of the id3 Finger SDK
> that defines a complete 1:1 route from `canonical_500` to a raw score?

```text
NO
```

Three findings, each read from the vendor's own material:

**There is no self-service download.** The samples README states that a licence
must be requested from the vendor, and that once the request is accepted the
requester receives *both* an activation key *and* a ZIP archive containing the
SDK. Package and licence arrive together, through a person-to-vendor exchange.

**The library refuses everything before its licence check.** The vendor's Python
sample opens with `check_license` against a licence file, commented as required
before calling any function of the SDK. Without a licence there is no version to
read at runtime, no model to load, no template to create and no score.

**The evaluation quota is a phrase, not a number.** The product page offers a
free 30-day trial qualified by `Limited API calls` and `Single platform`. No
number accompanies the limit, and nothing public says which operations consume
it. The frozen run performs 12,000 extraction invocations and 6,000 matcher
invocations over 6,000 comparison attempts — two extractions per comparison,
Stage 8C's execution semantics — plus a bounded qualification allowance: 18,200
high-level biometric operations. What that costs in the licence's own unit is
not derived here, because "API call" is undefined; `sdk_metered_call_count`
stays `UNRESOLVED` until the vendor states what is metered (docs/adr/0096).

## Why acquisition is Gate 2 and not Gate 9

Every gate after it is a question about a delivered package: its exact version
and digest, its model set, its input route, its extraction and matcher profiles,
its score API, its determinism. None of them can be answered from a product page,
and answering them from one would be publishing a benchmark route this project
had never seen.

Placing acquisition second costs one reading and saves the rest of the stage.
This is the same ordering argument Stage 10A made for identity and input domain,
applied to the thing that differs about a commercial product (docs/adr/0089,
docs/adr/0094).

## Access is not research use

```text
ResearchUseDecision        may this project execute this component
                           under its declared purpose?          Stage 8E owns it

OperationalAccessDecision  does this project hold a working copy
                           and an active licence, today?        Stage 10B owns it
```

Both must be satisfied, and neither substitutes for the other. Nothing in this
stage says id3's terms forbid research use — that question was not reached, and
no component exists to assess. `research_use_opens_execution` is published as
`null` rather than `false`, because a `false` would read as a refusal nobody made
(docs/adr/0095).

No licensing subsystem was added. Stage 8E's engine, models and policy are
untouched, and no usage manifest was written at all: Stage 8E's own model refuses
a manifest with no components.

## What the public record did settle

Recorded as **observations**, never as gate conclusions, because the gates that
would have used them were never reached.

**Product identity.** id3 Finger SDK by id3 Technologies, publicly documented at
4.5.0, named by four locators and distinguished from four things it is not: the
vendor's separate MicroFinger product, any MINEX submission, the samples
repository itself, and any third-party wrapper.

**The single-finger route has two published shapes.** The product page's headline
sample is a slap: `detect_slap` → `extract_roi` → `create_template` →
`compare_templates`. The official Python recognition sample, at the pinned
commit, does none of that: it loads two images as 8-bit grayscale, sets each to
500 ppi, creates one template from each, and compares them. This benchmark holds
single already-segmented impressions, so it fits the second shape — and *which
route the delivered package documents for a single finger* is a question for the
delivered package, not for whichever branch looks reasonable (docs/adr/0092
applies here as it did to JIPNet).

**`canonical_500` needs no fpbench transformation.** The SDK's processors require
500 dpi and refuse anything else with an explicit resolution error; the canonical
profile already produces 500 ppi 8-bit grayscale. That is a reason to expect Gate
4 to pass. It is not Gate 4 passing.

**Seven score-affecting settings have no documented default.** Five matcher
options — `maximumRotation`, `minexOnly`, `minutiaPatchOnly`, `multiscaleMatch`,
`normalizedScores` — and two extractor models. The class reference documents what
each does and states no default for any. A value read from a delivered package
would be recorded as a `DELIVERED_SDK_DEFAULT`, a fact about that package, never
as a documented fact (docs/adr/0097).

**The raw score has the right shape.** `compareTemplates` is documented as
returning an integer in 0..65535, with the threshold applied afterwards through a
separate constant. That is exactly what this project needs — one integer per
attempt, no decision inside the route — and it is recorded as an observation,
because a contract is settled against the delivered package's own documentation
(spec section 8).

**Five cited locators no longer resolve.** The documentation pages this stage was
written against answer HTTP 404; the reference tree that resolves today is
versioned under `/v4/` and titled with a single version. Both facts are published
with their status codes, so a reader can tell a checked citation from a repeated
one.

## What is frozen even though nothing ran

**SELF semantics.** `SELF(A, A)` performs two independent extractions and
compares the two resulting templates. A template extracted once and compared with
itself is refused, and so is a maximum-score shortcut for equal inputs, and so is
any representation cache living between the two sides of a comparison. Frozen at
10B although the adapter that will obey it belongs to 10C, because a pairwise
matcher is where this is easiest to lose (docs/adr/0070).

**Pair order.** `score(A, B)` and `score(B, A)` are run on fixtures. If they
differ, the orientation the API defines is kept — never an average, never a
maximum.

**Determinism.** One integer, bit-identical within a process and after a restart.
Anything else is `SCORE_NONDETERMINISM_OBSERVED` and a failure.

**Zero is a score.** It is never used as a failure sentinel; a failure is carried
by an outcome.

**No threshold in the raw route.** Not `FingerMatcherThreshold`, not a vendor
recommendation, not an `is_match` derived from either.

## What this stage did not do

```text
no package request          no activation            no SD300 read
no licence bypass           no trial reset           no crop invented
no production adapter       no AlgorithmConfig       no 6,000 comparisons
no ResultSet                no threshold             no DecisionProfile
no calibration              no metrics               no fusion chosen on accuracy
```

`sd300_image_bytes_read`, `sd300_scores_read` and `sd300_pair_manifest_read` are
all false. Not even one image to check that it works.

## Secrets

A closed list of five publishable licence facts; a closed list of refused keys
checked at any depth; five refused value shapes checked against every published
string; the guard run twice, once over the objects and once over the published
bytes including the hand-written README; and publication stops rather than
redacting. No activation in CI and no credentials in CI (docs/adr/0098).

## Running it

```bash
make stage10b-status       # re-derive and print the gates, verdict and blockers
make stage10b-contract     # the frozen protocol, over synthetic fixtures
make stage10b-evidence     # verify the committed evidence
make stage10b-guard        # refuse if any id3 material is tracked here
make stage10b-artifacts    # the checks that need the SDK locally (skips without it)
```

Publication is two writes, as Stage 8D, 8E, 9A and 10A published theirs:

```bash
make stage10b-documents    # the thirteen derivable documents; commit them
make stage10b-publish      # the marker, against a clean tree; commit that
```

## What opens

```text
opens_stage_10c:                        false
stage_10c_reserved_for_this_candidate:  true
opens_candidate_search:                 true
```

The slot stays empty and the *number* does not move. Stage 10C is the id3
artifact and runtime integration a passing 10B would have opened, and it stays
reserved for id3 rather than being recycled for whatever comes next: a 10C that
had nothing to do with the 10B above it would make the history unreadable. The
next candidate preflight is a new stage number.

One act would reopen this stage, and it belongs to a person rather than to a
program: the maintainer requests an evaluation or developer licence from the
vendor in their own name — the package, the activation, the exact quota and
metering semantics, and confirmation that the planned research workload is
permitted — and re-runs the stage. Eight gates become answerable for the first
time at that point.

That request is not on the critical path. The next candidate preflight does not
depend on it and should not wait for it; if id3 answers quickly and the quota is
sufficient, this stage requalifies and 10C opens, and if it does not, no time was
lost.

If the request is not made, or is refused, the response is another candidate —
not a workaround.
