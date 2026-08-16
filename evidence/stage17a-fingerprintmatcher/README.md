# Stage 17A — fingerprintMatcher 1.0.6 as an Algorithm 5 candidate

`FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL`, at G2 of 7. The package does not return
a score. It prints a verdict.

Nothing was installed, nothing was executed, and no SD300 image was opened. The
stage cost one file read, which is what its gate order was designed for.

## Why this stage is shaped differently

The three stages before it each built acquisition, runtime or route machinery for
a candidate that never reached it. Stage 16A froze 1.5 GB of FingerFlow
checkpoints, resolved a TensorFlow closure and wrote a route parser — and then
failed at its second gate. The machinery was not wrong; the order was.

So Stage 17A asks one question before it builds anything:

```
match_fingerprints(image1, image2)
    -> a native scalar, before any decision?
    -> a direction provable from the source?
```

If no, close. Everything else in this stage exists only to record that answer.

## G1 — the artifact: PASS

```
fingerprintMatcher 1.0.6      PyPI, MIT, pure Python, OS-independent
  sdist  3,008 bytes          50692faf63ca8bccb83ea8a2adfac7284e389b05bc19347c86a513a85f868411
  wheel  3,126 bytes          4491a191b6f874acdfe287fb47bff788d6b01c88e71d4c247e3fd7baceb2e5b2
  module 590edeae…            byte-identical in both distributions
```

**The authority is the distribution, not the repository.** The official GitHub
does not presently show `fingerprintmatcher.py` at its root, while PyPI
distributes a module that would actually execute. Both archives were opened and
their modules compared: a package whose two distributions ship different code has
no single answer to "what does it do".

One observation recorded without being a gate conclusion: the declared
dependencies are `opencv-python>=4.9.0` **and** `opencv-contrib-python`, which are
alternative builds of one `cv2` module and are not supported side by side. The
entry point calls `cv2.xfeatures2d.SIFT_create`, and on opencv-python 5.0.0 `cv2`
exposes `SIFT_create` at the top level with no `xfeatures2d` attribute at all.
The gate does not turn on this.

## G2 — the score contract: FAIL

Everything below is parsed out of the published module, not asserted:

| finding | value |
|---|---:|
| `return` statements carrying a value | **0** |
| the docstring's own `Returns:` | **`None`** |
| internal decision thresholds | **`match_ratio > 0.95`** |
| printed observables | 3 |
| the ratio that would have been a score | `match_ratio = len(match_points) / keypoints_count` |
| is that ratio returned | **no** |

The similarity ratio exists. It is computed, compared against a hard-coded
`0.95`, and discarded. In the matching branch a percentage of it is printed; in
the non-matching branch **no number is printed at all**. What the callable
publishes is a decision, announced as text, on a threshold its author chose.

Upstream's own README confirms it — the usage example is

```python
fingerprint_matcher.match_fingerprints("path/to/image1", "path/to/image2")
```

a bare statement, with nothing on the left of an `=`, because there is nothing to
capture.

Blocker: `BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT`, the first of this stage's four
immediate stop conditions.

**No score direction is published, and the marker refuses one.** The ratio is
transparently higher-is-more-similar, and writing that down would describe a
number the package never returns. `build_stage17a_finalization` raises if a
direction is present on a failed contract, and the evidence gate refuses
committed evidence that carries one.

**What was refused, each denied as a checked field in the marker:**

```
upstream_function_reimplemented   false   rewriting it to return match_ratio
stdout_parsed_for_a_score         false   scraping the printed percentage
score_reconstructed_by_fpbench    false   the general form of both
```

Scraping is worse than it looks: the percentage only prints *above* the author's
threshold, so the column would be null for every comparison the package called a
non-match. That is a decision with a decoration, not a score distribution
([ADR 0133](../../docs/adr/0133-a-score-the-package-does-not-return-is-not-its-score.md)).

## G3–G7 — not reached

The route gate asks whether every step from an image to a scalar belongs to
upstream. G2 established there is no scalar at the end of it, and a route to a
number that does not exist is not a route with a gap in it.

Recorded there without being a gate conclusion: the entry point *does* decode
both images with `cv2.imread` and build SIFT features itself, so fpbench would
not have had to supply preprocessing. True, and it does not rescue the stage.

Two hazards were also read while the function was open, and both are the class
[ADR 0131](../../docs/adr/0131-a-refusal-and-a-crash-are-different-outcomes.md)
names — an unhandled implementation exception on valid input, not a refusal:

- `for p, q in matches` — `knnMatch(k=2)` yields a shorter list for a query with
  fewer than two neighbours, and unpacking raises `ValueError`.
- `len(match_points) / keypoints_count` — no guard, so an image SIFT finds no
  keypoints in raises `ZeroDivisionError`.

## What this opens

```
outcome                        FINGERPRINTMATCHER_SCORE_CONTRACT_FAIL
blocker                        BOOLEAN_OR_THRESHOLD_ONLY_OUTPUT
algorithm_5_established        false
reopens_algorithm_5_search     true
opens_common_calibration       false
fallback_candidate             null
```

Five consecutive stages have now ended without a fifth algorithm — 12A, 13A and
14A at a vendor, 16A at missing documentation, and this one at a package that
makes the decision the benchmark exists to make itself.

The rule this leaves for the next candidate, to be checked before any acquisition
machinery: **read the entry point and confirm it returns a value.**

## Files

| file | what it settles |
|---|---|
| `artifact-identity.json` | G1: both distributions, one module, the dependency observation |
| `score-contract.json` | G2: the parse, and what the callable actually publishes |
| `upstream-route.json` | G3: not reached, and why that is not a gap |
| `stage-17a-finalization.json` | the marker |

Reproduce with `make stage17a-acquire`, `make stage17a-artifacts` and
`make stage17a-score`; verify the committed evidence with
`make stage17a-evidence`, which needs no artifact store and no network.
