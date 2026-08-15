# Stage 15A — fingerprints-matching 0.1.0 over the canonical 500 ppi SD300 comparisons

`FINGERPRINTS_MATCHING_CANONICAL500_RAW_COMPLETE`. The fifth algorithm ran the
same 6,000 pairs, in the same order, over the same pixels as SourceAFIS, NBIS,
flx and VeriFinger.

**Read the score split before anything else. 389 of the 6,000 outcomes are
scores, and 367 of those are SELF comparisons that return exactly 1.0 by
construction. Twenty-two comparisons of two different prints produced a
number.** The stage passes the criterion it was given — the result set is
score-bearing — and that criterion turns out to be a much weaker statement here
than it was for the four algorithms before it.

## What ran

```
prepset_be560e047991                      the same 3,000 canonical 500 ppi PNGs
      |
      v
fingerprints_matching_subprocess          one frozen interpreter, held open
      |
      v
FingerprintsMatching.fingerprints_matching(image_path1, image_path2)
      |
      v
6,000 stored raw outcomes                 immutable, and never a threshold

run_c2910aafb6cc / plan_ce5faa7041d4 / resultset_4450d95f4f30
```

Aligned against `run_4c59fa02a6ab`: the same pair manifest `ee4d942e…`, the same
cohort `sd300_50_subjects_test_22f8d52a7478`. Nothing here selects a cohort,
generates a pair or writes a PNG.

Left is the first argument and right is the second, fixed. `match` returns
`sum(best) / len(minutiae1)`, so the first argument sets the denominator and the
two orderings are different questions. The qualification measured
`score(A,B) = 0.37683434` against `score(B,A) = 0.37012762` on the same pair;
that asymmetry is not a defect, it is what makes the argument order part of the
algorithm's identity (docs/adr/0109).

## What came out

```
6,000 comparison attempts   6,000 stored outcomes   0 missing   0 duplicate
  389 scores
5,611 algorithmic failures      0 infrastructure failures
12,000 logical extractions   6,000 match invocations
```

| outcome | rows | |
|---|---:|---|
| score, SELF | 367 | **all exactly 1.0** |
| score, genuine | 22 | 0.0 – 0.019550922 |
| `CONVEXITY_DEFECTS_REFUSED_CONTOUR` | 5,610 | no score |
| `NO_FEATURES_ON_FIRST_SIDE` | 1 | no score |

The SELF column is 1.0 and can only ever be 1.0. A SELF comparison extracts the
same file twice, every minutia matches itself at distance zero and angle zero,
`match_score` returns 1.0 for each, and the sum divided by the count is 1. Those
367 rows say the extractor ran on 367 of the 3,000 canonical images. They say
nothing about whether this matcher can distinguish two fingers, and the marker
counts them separately so they cannot be read as though they did.

The 5,610 `CONVEXITY_DEFECTS_REFUSED_CONTOUR` rows are the algorithm declining a
print. `cv2.convexityDefects` refuses a contour whose convex-hull indices are not
monotonous, which is what an Otsu-binarised fingerprint's ridge structure
produces, and the route has no path around it. That is a property of this
algorithm meeting real fingerprints — it was observed identically on every real
print tested during qualification, from two independent vendors' sample sets, and
under five different OpenCV 4.x releases. It was counted, not fixed.

**No failure was recorded as a score of zero.** Zero is a value this matcher
genuinely returns — two of the 22 genuine scores are 0.0 — and conflating it with
"did not run" would have put a fabricated similarity into the benchmark
(docs/adr/0127).

**No infrastructure failure was recorded at all.** A missing prepared file, a
dead worker or a response that was not a number would each have stopped the run
rather than becoming a 6,001st kind of biometric outcome.

## What this does and does not establish

It establishes that the route executes reproducibly at benchmark scale over
canonical inputs, that its failures are deterministic and honestly classified,
and that 22 comparisons of different prints produced a raw number.

It does not establish a matcher with usable coverage. Twenty-two genuine scores
against roughly 5,900 from each of the four algorithms already in the benchmark
is not a basis for comparison, and this directory publishes no rate, no
distribution and no ranking that would suggest otherwise. Whether a common
calibration phase is worth opening on this roster is a judgement for that phase,
made with these counts in front of it — which is exactly why the counts are
published and the rates are not (docs/adr/0128).

## The runtime this rests on

The package is 4,492 bytes and its runtime is not. Every pixel operation is an
OpenCV call, `opencv-python` is declared with no version bound, and the contours
`findContours` returns are the feature extractor's only input — so OpenCV's exact
version is part of the algorithm's identity, not packaging detail.

Under the current OpenCV 5.0.0.93, which is what an unpinned `pip install`
resolves to, the route does not run at all: `convexityDefects` returns a
differently shaped array and every image raises `TypeError`. The pin is chosen by
a rule fixed before it was resolved — the release current when the artifact was
published on 2023-04-04 — and never by which version yields more scores
(docs/adr/0125).

```
python 3.12.13      numpy 1.26.4      opencv-python 4.7.0.72 (cv2 4.7.0)
```

Both published distributions were fetched from PyPI and both SHA-256 matched the
values frozen in code before anything was downloaded. The environment is built
with `--no-index` from a local wheelhouse and never reaches the network again.
Every one of the 6,000 results carries the same runtime manifest fingerprint.

Nothing published here is a vendor byte, a licence, a credential or a machine
path. There is no vendor: the package is MIT, and acquisition needed nobody's
permission — which is the whole reason this candidate exists (docs/adr/0126).

## Stage 14A is not what this supersedes it with

Griaule was never contacted. `stage-14a-finalization.json` does not exist, its
`acquisition-status.json` still publishes `request_sent: false`, and nothing in
this stage edited a byte of it. `predecessor-selection.json` records
`stage14a_final_outcome: NONE`.

What changed is this project's criterion, not a verdict on Griaule: after three
consecutive Algorithm 5 stages ended at a vendor, self-service acquisition and
runnability without vendor action became hard requirements. That is a statement
about fpbench, and turning an unfinished investigation into a `FAIL` would have
manufactured a vendor position that does not exist (docs/adr/0104, docs/adr/0121).

## What is deliberately not here

No mean, no median score, no histogram, no ROC, no EER, no FMR, no FNMR, no
accuracy, no failure *rate*, and no statement about which algorithm is better.
Stage 15A produces raw outcomes; a threshold, a calibration and a metric are later
layers over these stored scores.

The package's README suggests 0.9 separates same-finger from different-finger.
That is upstream's guidance to its own users. It is recorded because it exists,
and it is not this benchmark's threshold.

## The files

| file | what it is |
|---|---|
| `predecessor-selection.json` | what this supersedes, and the rule that made it |
| `artifact-runtime-identity.json` | G1 — both published digests and the frozen closure |
| `upstream-route-contract.json` | G2 — the route, parsed from the installed module |
| `qualification.json` | G3 — determinism, orientation and the failure probes |
| `canonical-run-binding.json` | G5 — the reference run and what was reused |
| `result-integrity.json` | G6 — the counts, and the failure breakdown |
| `stage-15a-finalization.json` | the marker |
| `run_c2910aafb6cc.json` | the shared engine's own research receipt |

The run definition, the plan and the result set stay in the engine's structure
and are not copied out under a Stage 15A name.

## Verifying it

Evidence only — no package, no OpenCV, no frozen runtime, no dataset, no
workspace:

```bash
make stage15a-evidence
```

The contract itself, with nothing installed:

```bash
make stage15a-contract
```

Reproducing the run needs the wheelhouse and SD300; neither is in CI. The
documented invocation is
[docs/experiments/fingerprints-matching-canonical500-raw.md](../../docs/experiments/fingerprints-matching-canonical500-raw.md).
