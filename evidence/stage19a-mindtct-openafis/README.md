# Stage 19A — MINDTCT → OpenAFIS, canonical raw integration

**Raw run: complete.** 6,000 expected, 6,000 stored, 0 missing, 1,576 s.

**Algorithm 5 established: not determined.** Three of section 20's four conditions
hold. The fourth — *"a substantial quantity of score-bearing comparisons between
different impressions"* — has no number in the requirement, and this stage does
not invent one. `cross_impression_sufficiency` is `UNDETERMINED` and the marker
publishes `algorithm_5_established: null`, which is not the same claim as `false`.

## What ran

```text
canonical SD300 image (500 ppi, native dimensions)
        ↓
NIST MINDTCT 5.0.0, build 658f9f54a8f2, no -b, no -m1
        ↓
XYT minutiae
        ↓
mechanical CSV translation (docs/adr/0135)
        ↓
OpenAFIS @ 3ae1c757, MatchSimilarity
        ↓
raw uint8_t score
```

Same prepared image set, same 6,000-row pair manifest, same order, same probe
side, no threshold, no transform, no decision, no calibration — and, unlike Stage
18A, **no resize of any kind**. The adapter meets the standard contract and the
driver calls only `descriptor` / `validate_environment` / `compare`.

## The result

| population | pairs | scored | % | min | median | max | zeros |
|---|---|---|---|---|---|---|---|
| plain_self | 1500 | 1369 | 91.3% | 78 | 100 | 109 | 0 |
| roll_self | 1500 | 73 | 4.9% | 86 | 100 | 104 | 0 |
| **plain_roll_mated** | 1500 | **73** | **4.9%** | 0 | **0** | **6** | 61 |
| plain_roll_non_mated | 1500 | 68 | 4.5% | 0 | 0 | 1 | 65 |
| **all** | **6000** | **1583** | **26.4%** | 0 | 100 | 109 | 126 |

Every one of the 4,417 failures is the same thing:

```text
OPENAFIS_TEMPLATE_FAILED_LEFT    1820
OPENAFIS_TEMPLATE_FAILED_RIGHT   2597
reason: minutiae_above_upstream_maximum   4417  (100%)
```

Zero MINDTCT failures. Zero invalid XYT. Zero match failures. Zero infrastructure
failures. The route does not break — it declines.

## Why: a capacity mismatch, not a defect

OpenAFIS declares `MaximumMinutiae = 128` in `lib/Template.h` and `Template::load`
refuses anything above it. MINDTCT on canonical 500 ppi SD300 finds:

| impression | median minutiae | max | above 128 |
|---|---|---|---|
| plain | 69 | 279 | 131 / 1500 (8.7%) |
| **rolled** | **205** | 373 | **1427 / 1500 (95.1%)** |

A rolled print carries more ridge area, so it carries more minutiae, so it does
not fit. That is a real limit of a real matcher meeting a real property of real
fingerprints — classified `ALGORITHMIC`, not `BLOCKING`, and the run is clean.

The obvious repair — keep the best 128 by quality — is **refused**. Choosing which
minutiae survive is a selection rule neither upstream project publishes, and the
resulting score would be fpbench's rather than what MINDTCT and OpenAFIS produce
between them (section 10, docs/adr/0135).

## The controlled matcher comparison

Algorithm 2 and Algorithm 5 run **the same MINDTCT binary from the same certified
build over the same images with the same flags**. They differ only in the matcher.
That makes this the cleanest comparison in the project — and it means Algorithm 5
is **not an independent fifth system** and must never be presented as one.

| | score-bearing | median | max |
|---|---|---|---|
| MINDTCT → BOZORTH3 | 6000 / 6000 | 158 | 1111 |
| MINDTCT → OpenAFIS | 1583 / 6000 | 100 | 109 |

Spearman rank correlation on the 1,583 pairs both scored: **0.264** — and that is
computed over a self-selected subset, because every pair Algorithm 5 could not
template is absent from it.

BOZORTH3 accepts the same high-minutiae templates that OpenAFIS refuses; its own
`max_minutiae` default of 150 is a working limit rather than a refusal. That is
the whole difference in coverage.

**Neither matcher is called better here.** The scales are unrelated, no common
operating point exists, and no threshold is applied anywhere.

## What the run does and does not establish about the route

**Does:** the composition executes end to end, deterministically, with no
implementation defect. `plain_self` at a median of 100 over 1,369 comparisons
shows the whole chain — extraction, translation, template construction, matching —
working.

**Does not:** confirm the angle convention against real cross-impression data.
`SELF` compares an image with itself and is invariant to the convention, so it
cannot test it. The only cross-impression populations are plain-versus-rolled, and
just 73 mated pairs survived the 128 bound — a small and *biased* sample, since a
pair only survives when **both** prints are unusually sparse.

The convention's justification is therefore the derivation, not the run: NBIS
`xytreps.c` and OpenAFIS `TripletScalar.cpp` agree on handedness, and an ISO→CSV
round-trip reproduces OpenAFIS's own ISO path exactly on twelve pairs
(`translation-contract.json`). That is a sound argument and it is not the same as
empirical confirmation on mated prints, which this dataset could not supply.

## Timings

Median per comparison 148.9 ms: MINDTCT 68.7 ms (left) and 118.1 ms (right), and
OpenAFIS matching 0.131 ms.

**`openafis_template_*_ms` measures two things and should be read with care.** It
sums fpbench's CSV render and OpenAFIS's own parse-and-triangulate time, so on a
side whose template was refused it reflects only the abandoned translation attempt
(hence a median of 0.006 ms on the right against 4.19 ms on the left). Splitting
the two is a change that would move `stage19a_source_fingerprint`, so it belongs
to a future run rather than to this published one.

## Files

| File | What it holds |
|------|---------------|
| `algorithm-identity.json` | the route, both halves pinned, and the shared-extractor statement |
| `translation-contract.json` | the four rules with the upstream source that settled each |
| `canonical-run-binding.json` | counts, coverage, per-stage cross-impression figures, timings |
| `matcher-comparison.json` | Algorithm 2 against Algorithm 5, with no verdict |
| `stage-19a-finalization.json` | the marker |

Scores live outside this repository. The documents here carry counts and
identifiers.

## Reproducing

```bash
make stage19a-smoke
make stage19a-run
make stage19a-diagnostics
```

Both binaries are Linux, so the run happens in the NBIS build distro. The
certified NBIS build and the OpenAFIS bridge are named explicitly; there is no
PATH lookup anywhere.
