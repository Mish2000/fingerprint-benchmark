# Stage 10A — Algorithm 4 candidate preflight qualification

## What this stage decides

Which, if either, of AFR-Net and JIPNet can enter fpbench as Algorithm 4:

```text
without an fpbench reconstruction
without invented preprocessing
without SD300 being consulted to make it fit
```

Two outcomes, and both are complete:

```text
ALGORITHM4_CANDIDATE_SELECTED
ALGORITHM4_PREFLIGHT_NO_SURVIVOR
```

There is no requirement anywhere in this project to have four algorithms. There
is a requirement not to publish a score attributed to a method the score did not
come from (docs/adr/0089).

Stage 9A stays closed and belongs to the FLARE route. Nothing in it is recycled
here.

## The outcome

```text
ALGORITHM4_PREFLIGHT_NO_SURVIVOR
```

Both candidates failed, at different gates, for unrelated reasons.

| | AFR-Net | JIPNet |
| :--- | :--- | :--- |
| `IDENTITY` | **FAIL** | PASS |
| `INPUT_DOMAIN` | not reached | **FAIL** |
| `ARTIFACTS` | not reached | not reached |
| `INFERENCE_ROUTE` | not reached | not reached |
| `SCORE_CONTRACT` | not reached | not reached |
| `TRAINING_PROVENANCE` | not reached | not reached |
| `RUNTIME_SMOKE` | not reached | not reached |

Cost of reaching that conclusion: **zero checkpoint bytes**, zero runtimes,
zero SD300 reads, zero scores.

## The two decisive questions

Asked in the form the stage was specified to answer them, and answered in one
word each.

> Does an original-author-supplied executable AFR-Net artifact set exist that
> defines the published verification score route sufficiently for fpbench?

```text
NO
```

Ten locations were searched: the arXiv listing and the full paper text, the MSU
Biometrics publication database, its databases and projects pages, the first
author's GitHub account, a group organisation, GitHub repository search, and the
code and model indexes. None yielded source or weights published by Grosz and
Jain. The paper contains no code-availability statement; its only GitHub
reference is `rwightman/pytorch-image-models`, a dependency. One location, the
IEEE article page, was not readable from here and is recorded as unread rather
than as empty.

> Can the exact released JIPNet checkpoint consume fpbench canonical500 full
> fingerprints through a published deterministic inference transformation,
> without fpbench inventing a partial-patch construction?

```text
NO
```

## Why AFR-Net fails

Three blockers, all at Gate 1.

| Code | What it says |
| :--- | :--- |
| `OFFICIAL_IMPLEMENTATION_NOT_FOUND` | no author-supplied source was located |
| `OFFICIAL_CHECKPOINT_NOT_FOUND` | no author-supplied weights were located |
| `THIRD_PARTY_REIMPLEMENTATION_ONLY` | the only executable AFR-Net is somebody else's reproduction |

The third is the one that matters, because it is the one that could have been
finessed. A working AFR-Net exists inside `XiongjunGuan/JIPNet`. Its authors
state that their comparison models are reproduced from the papers and that some
were adjusted for partial fingerprints; their paper states that the pose
rectification used by DeepPrint, DesNet and AFR-Net could not be performed and
that PFVNet's `AlignNet` was substituted, which they mark with an asterisk in
their own results. The public `inference_AFRNet.py` route is:

```text
RidgeNet enhancement
    ↓
PFVNet AlignNet
    ↓
AFRNet
    ↓
0.2 x cosine(CNN half) + 0.8 x cosine(ViT half)
```

A substituted alignment stage makes that a different algorithm. It stays
available as a candidate of its own, under the name
`jipnet_authors_adjusted_afrnet_reimplementation`, and never as `afr_net`
(docs/adr/0090).

MSU also records a granted US patent for AFR-Net. That is noted in the evidence
as a fact about the work's status and is not the basis of any conclusion here:
the reason is absence of an artifact, not the presence of a patent.

## Why JIPNet fails

Gate 1 passed on its first reading — the paper's abstract names the repository
and the repository's README calls itself the official implementation. Gate 2 is
where it stops, with three blockers.

| Code | What it says |
| :--- | :--- |
| `BENCHMARK_INPUT_ROUTE_UNRESOLVED` | no upstream authority converts a full fingerprint into the required patch |
| `FPBENCH_PREPROCESSING_CHOICE_REQUIRED` | closing the gap would mean fpbench choosing the crop |
| `INPUT_DOMAIN_INCOMPATIBLE` | as released, the model's input domain is not this benchmark's |

The findings, each from the pinned commit `40d8445c`:

* the official `inference.py` reads two images, inverts and scales them, and
  hands them to the model. No crop, no resize, no size check;
* `cv2.resize` appears **nowhere** in the repository;
* the only full-fingerprint-to-patch function is `cut_patch`, and it lives in
  `make_data/generate_patch.py` and in the training data loader. Neither is
  imported by any inference script;
* that construction samples the patch centre from the **common mask of an
  aligned genuine pair**. Which 160×160 window an image yields therefore depends
  on which other image it will be compared with — so a template would not be a
  template;
* it applies a rotation drawn uniformly from [-180°, 180°];
* its first step, `affine_pairs.py`, imports `fptools.fp_verifinger`, which is
  not in the repository. The README states the script cannot run because of
  licensing and that the source cannot be released.

The model would accept a differently shaped tensor. That is not the question
(docs/adr/0091).

## What was deliberately not done

Named in `candidate-set.json` and asserted by the marker:

```text
no production adapter        no threshold             no SD300 read
no AlgorithmConfig           no calibration           no crop optimisation
no 6,000 comparisons         no metrics               no model selection from performance
no DecisionProfile           no fine-tuning           no ranking of failed candidates
```

Author-reported accuracy was not read and did not enter any comparison. The two
papers report on different datasets under different protocols; comparing their
numbers would compare two experiments (docs/adr/0093).

## Recorded for later

Both candidates' training corpora were read while answering Gate 1, and are
published as **observations** under a `NOT_REACHED` Gate 6 — never as gate
conclusions.

SD300 overlap, for both candidates:

```text
NO_EVIDENCE_FOUND
```

which is not `PROVEN_ABSENT` and is never converted into it. AFR-Net trains on
NIST SD 302, SD 4 and SD 14; JIPNet trains on NIST SD14. Neither mentions SD300
in either direction.

If JIPNet is ever revisited, four datasets cannot serve as clean development
data for calibrating it without further overlap analysis, because the released
checkpoint was fitted on 95% of them (docs/adr/0079):

```text
NIST SD14, FVC2004 DB1_A, FVC2004 DB2_A, FVC2006 DB2_A
```

## Running it

```bash
make stage10a-status
```

```bash
make stage10a-contract
```

```bash
make stage10a-evidence
```

```bash
make stage10a-guard
```

`stage10a-documents` writes the twenty derivable documents and
`stage10a-publish` adds the marker against a clean tree — two commits, in that
order, as Stage 8E and Stage 9A published. There is no acquisition target,
because nothing was acquired for either candidate beyond the source archive the
identity gate rests on.

## What opens next

```text
opens_algorithm4_artifact_qualification: false
opens_candidate_search:                  true
```

The Algorithm 4 slot stays empty and a search for a third candidate opens. The
benchmark keeps its three executed algorithms — SourceAFIS, NBIS and flx — and
gains a written specification of what a fourth must satisfy.
