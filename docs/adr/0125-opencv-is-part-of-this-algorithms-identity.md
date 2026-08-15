# OpenCV is part of this algorithm's identity

## Status

Accepted, implemented.

## Context

`fingerprints-matching` 0.1.0 is 4,492 bytes of pure Python. It declares two
dependencies and bounds neither:

```text
Requires-Dist: opencv-python
Requires-Dist: numpy
```

Every pixel operation the algorithm performs is an OpenCV call. `imread` decodes,
`cvtColor` greyscales, `threshold` with `THRESH_OTSU` picks the binarisation
level, and `findContours` produces the contour list that `convexHull` and
`convexityDefects` turn directly into the feature set. There is no intermediate
representation and no fallback: **the contours OpenCV returns are the feature
extractor's only input.**

So `pip install fingerprints-matching` does not install one algorithm. It
installs whichever feature extractor the resolver happened to pick that day, and
a benchmark that let that float could not reproduce its own results a month
later.

The version is not a theoretical concern here, and two measurements settled it.

Under **OpenCV 5.0.0.93** — what an unpinned resolution installs today — the
route does not run at all. `cv2.convexityDefects` returns a differently shaped
array, `defects[i, 0]` is a scalar rather than a 4-tuple, and every image raises
`TypeError` on the unpack. The package was published in April 2023 against the
OpenCV 4 shape contract, and OpenCV 5 broke it.

Across the whole **OpenCV 4 line** — 4.7.0, 4.8.1, 4.9.0, 4.10.0 and 4.11.0 were
each installed and run over the same sixteen non-SD300 images — the outcome was
byte-identical: the same images extracted, with the same feature counts, and the
same images were refused. So within the generation the route was written against,
the choice of point release did not move a single result.

That leaves the question of *which* version to pin, and it has a trap in it. The
obvious tie-breaker — pick whichever version produces the most scores — is fpbench
choosing a component of the algorithm by looking at what the algorithm then
produces. It is parameter fitting with extra steps, and it is exactly the thing
this benchmark refuses to do.

## Decision

**OpenCV's exact version is part of the algorithm's identity, is pinned, and is
chosen by a rule stated before it is resolved.**

The rule is contemporaneity with the artifact:

```text
opencv_generation_rule:
    CONTEMPORARY_WITH_ARTIFACT_PUBLICATION

fingerprints-matching 0.1.0   uploaded 2023-04-04
opencv-python 4.7.0.72        released 2023-02-22  <- the current release then
```

It reconstructs the runtime the author actually had, it is decidable from two
publication dates, and it cannot be influenced by a score because no score is
consulted to apply it.

numpy follows from that choice rather than being chosen: `1.26.4` is the only
numpy 1.x line that supports the reference interpreter *and* satisfies the
OpenCV 4.7 wheel's ABI. It is recorded as a derived pin, not an independent one.

The whole closure is frozen the way a vendor SDK would be — an exact
interpreter, an exact platform, an exact wheel per distribution, each with a
SHA-256, in a local wheelhouse, installed with `--no-index` into an environment
that never reaches the network again — and every one of the 6,000 stored results
carries the resulting `runtime_manifest_fingerprint`.

Two version strings are pinned for OpenCV and both are checked, because one
install reports two: the `opencv-python` distribution is `4.7.0.72` and the `cv2`
library it contains is `4.7.0`. Checking only one would let the other be
substituted.

## Alternatives

**Leave `opencv-python` unpinned, as the package does.** The route does not
execute at all under the current release, so this is not a choice between
reproducibility and convenience — it is a choice between a pinned algorithm and
no algorithm.

**Pin the newest OpenCV 4.x instead.** Defensible, and it would have produced
identical results on every image measured. It was not chosen because "newest
within the generation" is a weaker rule than "what it was written against": it
drifts every time a new 4.x appears, and it invites re-selection later.

**Pin whichever version yields the most usable scores.** Refused. That is
selecting a component of the algorithm from the algorithm's output, and no
statement of intent makes it something else.

**Vendor OpenCV into the repository.** 38 MB of third-party binary in a public
repository, against docs/adr/0083, to solve a problem a digest already solves.

## Consequences

The algorithm's identity is larger than its 4,492 bytes, and the evidence says so
out loud: `artifact-runtime-identity.json` publishes the interpreter, the
platform, both OpenCV strings, numpy, every wheel digest and the installed module
digests, under `opencv_is_part_of_algorithm_identity: true`.

Reproducing Stage 15A needs the wheelhouse, not just the package. That is the
correct cost, and it is the same cost every other algorithm in this benchmark
already carries.

A future OpenCV cannot silently change what Algorithm 5 means. It can only fail
the closure check, which stops the run.
