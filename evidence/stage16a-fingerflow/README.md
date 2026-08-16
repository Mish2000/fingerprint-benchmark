# Stage 16A — FingerFlow 3.0.1 as an Algorithm 5 candidate

`FINGERFLOW_ROUTE_CLOSURE_FAIL`, at G2 of 7. The artifact is complete, free,
self-service and loadable. The route from an image to a confidence is not
closed, and closing it would mean fpbench choosing four things that move the
score.

FingerFlow is **not** Algorithm 5, and the slot stays open.

## Why the route, and not the scores

Stage 15A is the reason this stage asks the structural question first and stops
there. `fingerprints-matching` produced a complete, deterministic, internally
consistent result set over the same 6,000 comparisons — and its
image-to-features route collapses on a single degenerate contour, deterministically,
on valid prints. No score distribution diagnosed that. The mechanism did.

So Stage 15A's outcome stands exactly as published, its raw results are
untouched, and the reason it did not fill the slot is recorded as
`STRUCTURAL_EXTRACTION_ROUTE_FAILURE` — never as low genuine scores, never as
poor discrimination, and never as worse than another matcher. Its scores were
not read to choose a successor; FingerFlow was already named as the reserve
candidate in Stage 15A's own selection record, under a policy that predates any
result from either.

## G1 — the artifact: PASS

Everything the route needs is published, and nobody has to be asked for any of
it.

```
fingerflow 3.0.1              PyPI, MIT           wheel d256c135…  sdist f73ad527…
github.com/jakubarendac/fingerflow @ a0a53259     tag v3.0.1
9 checkpoints                 1,611,110,764 bytes  SHA-256 for every one
```

Upstream publishes **no digests of its own**, which is why these exist: without
them "the CoarseNet weights" names a file nobody can check.

**Two of the nine README links are dead.** CoarseNet and FineNet answer HTTP 404
from Google Drive on `/uc`, on `/file/d/` and on `drive.usercontent` alike. Both
are also published on Dropbox in the same README, and both Dropbox links serve.
The acquisition record therefore names the locator that actually served each
file. Concluding `SELF_SERVICE_ARTIFACT_INCOMPLETE` from the first dead link
would have published a fact about a URL and called it a fact about the candidate
(docs/adr/0129).

The bytes were checked to be models rather than error pages: all four `.h5`
files are valid HDF5, `CoreNet.weights` carries a darknet header
(major 0, minor 2, rev 5), and `Matcher(30, VerifyNet-30.h5)` loads its weights
and returns a scalar.

**The runtime closure is honest about what it is.** Upstream pins
`tensorflow==2.5.1`, `numpy==1.19.5` and `opencv-python==4.5.3.56`; TensorFlow
2.5 stops at CPython 3.9 and none of the three install on any Python this project
runs. The declared floor is unbounded, so a resolve today gives TensorFlow 2.20
and Keras 3 — a different Keras major from the one these weights were serialised
under. The closure is recorded as `RESOLVED_AT_ACQUISITION_FROM_UPSTREAM_DECLARED_FLOORS`
and explicitly **not** as contemporary with the artifact, which is the rule
Stage 15A's OpenCV pin follows and this one cannot satisfy (docs/adr/0125).

## G2 — the inference route: FAIL

The package answers both ends of the route completely and neither end is in
question.

```
canonical_500 PNG
  -> preprocess_image_data          BGR2GRAY, crop to a multiple of 8      package
  -> CoarseNet + FineNet            candidate minutiae and scores          package
  -> ClassifyNet                    the class column                       package
  -> CoreNet (YOLOv4)               core boxes and scores                  package
  -> [x, y, angle, score, class] + [x1, y1, x2, y2, score, w, h]

  ->  ????????????????????????????  NOT IN THE PACKAGE

  -> enhance_minutiae_points        drop x,y, append 5 neighbour distances package
  -> Matcher.verify                 -> float confidence                    package
```

`MINUTIAE_FEATURES = 9` and `MINUTIA_NEIGHBORS = 5` fix the matcher's input at
six columns: the extractor's five plus one distance to the core. So the shape of
the missing middle is known exactly. What it should contain is not.

That construction exists only in two repository scripts, and **they disagree**:

| | `generate_encodings_for_matching.py` | `visualise_feature_vector.py` |
|---|---|---|
| minutiae retained | 30 | 20 |
| below that count | no guard at all | explicit refusal |
| selection | `nsmallest` | `sort_values`, all rows |
| rotation | mandatory 90° clockwise | none |
| runs as written | no — returns a name it never assigns | no — extractor calls commented out |

Ten questions stand between a canonical image and a confidence. **Six close on
upstream authority. Four do not.**

| question | authority |
|---|---|
| which core is selected | single unambiguous implementation |
| how minutiae are ordered | single unambiguous implementation |
| how nearest-minutiae selection works | single unambiguous implementation |
| how coordinates are made core-relative | single unambiguous implementation |
| whether angles are transformed | single unambiguous implementation |
| what happens if no core is detected | single unambiguous implementation |
| **how many minutiae are retained** | **fpbench would have to choose** |
| **whether rotation belongs to inference** | **fpbench would have to choose** |
| **what happens below the required count** | **fpbench would have to choose** |
| **which VerifyNet precision and checkpoint** | **fpbench would have to choose** |

The six that close, close properly. The core is the detection with the maximum
score, taken at its bounding-box centre — the same function character for
character in both scripts. Minutiae are ordered ascending by distance to that
core. Coordinates never reach the model at all: `enhance_minutiae_points` drops
columns 0 and 1, so the only core-relative quantity is the scalar distance.
Angles pass through untouched. No core detected is an explicit refusal both
scripts state and return from.

The four that do not are the four that move the score:

- **How many minutiae.** 30 in the encoding generator, 20 in the visualiser, 40
  in the recount script — a precision with no published checkpoint at all — and
  30 in the README's usage example against 20 in the only script that actually
  calls the matcher. The README offers "the more minutiae points the higher
  precision", which ranks the options without choosing one.
- **Rotation.** The only surviving image-to-features function rotates 90°
  clockwise unconditionally, inside a loop that feeds each rotation back as the
  next input — four rotations of one image, as four training rows. There is no
  non-rotating variant: the commented-out branch calls
  `load_image_and_extract_minutaie_points`, a function defined nowhere in the
  file. It was deleted, not disabled.
- **Below the required count.** One script has no guard, so a short vector
  reaches a model whose input shape is fixed. The other refuses explicitly. Under
  this stage's own failure split those are opposite classifications of the same
  input — one is a refusal the result set records, the other is a route defect
  that disqualifies the candidate (docs/adr/0131).
- **Which VerifyNet.** Five checkpoints published, none marked default, and
  precision is not separable from the retained count: the model's input is
  `(precision, 9, 1)`, so choosing one chooses the other.

**No experiment was run to break any of these ties.** Picking the alternative
that produces more or better scores would choose the algorithm's route out of the
evaluation data (docs/adr/0132).

## G3–G7 — not reached

The score contract is written down anyway, because it is the half that was in
good order: `Matcher.verify(anchor, sample)` returns one scalar, higher is more
similar, the final layer is a sigmoid, and there is no threshold inside
`verify`. What G2 established is that there is no defined feature vector to hand
it.

Nothing else ran. **No adapter was frozen, no SD300 image was opened, and no
comparison was executed.**

## What this opens

```
outcome                        FINGERFLOW_ROUTE_CLOSURE_FAIL
blocker                        UPSTREAM_INFERENCE_ROUTE_NOT_CLOSED
algorithm_5_established        false
reopens_algorithm_5_search     true
opens_common_calibration       false
fallback_candidate             null
```

`fallback_candidate` is `null` on purpose. Stage 15A named this candidate as its
reserve and there is no further reserve to name. Selecting the next one is
research this stage did not do, and inventing a name here would look like a
decision that was never made.

## Files

| file | what it settles |
|---|---|
| `predecessor-selection.json` | why Stage 15A did not fill the slot — mechanism only |
| `artifact-runtime-identity.json` | G1: nine checkpoints, their digests, the closure |
| `upstream-inference-route.json` | G2: ten questions, six settled, four not |
| `score-contract.json` | G3: what a score would have been |
| `qualification.json` | G4: the protocol and the failure split, not reached |
| `canonical-run-binding.json` | G6: the run that would have happened, not reached |
| `result-integrity.json` | G7: no result set, and the four acceptance conditions |
| `stage-16a-finalization.json` | the marker |

Reproduce G1 and G2 with `make stage16a-acquire`, `make stage16a-artifacts` and
`make stage16a-route`; verify the committed evidence with `make stage16a-evidence`,
which needs no artifact store, no runtime and no dataset.
