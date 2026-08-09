# JIPNet — candidate record

*Stage 10A candidate. Verdict: `JIPNET_PREFLIGHT_FAIL`, at Gate 2.*

## The work

```text
X. Guan, Z. Pan, J. Feng and J. Zhou, "Joint Identity Verification and Pose
Alignment for Partial Fingerprints", IEEE Transactions on Information Forensics
and Security, vol. 20 (2025) pp. 249-263, DOI 10.1109/TIFS.2024.3516566
```

Preprint `arXiv:2405.03959`. Official code `XiongjunGuan/JIPNet`, MIT licensed,
pinned here at commit `40d8445c5b3afa55b409ae3221377e54e3ace53f` (2026-04-16).
The archive was acquired twice from the same locator and came back
byte-identical.

A multi-task CNN–transformer hybrid that takes a *pair* of partial fingerprint
patches and predicts both a matching probability and their relative pose,
treating the two tasks as coupled rather than independent.

## Gate 1 — identity: PASS

```text
AUTHOR_OFFICIAL_IMPLEMENTATION
```

The paper's abstract names the repository; the repository's README calls itself
the official implementation of the paper. Author list, copyright headers and
citation all agree. This passed on its first reading.

The claim covers JIPNet only. The same repository's PFVNet, AFRNet, DesNet,
DeepPrint and A-KAZE routes are described by its own README as reproductions,
and are not covered.

## Gate 2 — input domain: FAIL

### The declared input

| | |
| :--- | :--- |
| geometry | 160 × 160 |
| channels | 1 |
| range | `[0, 1]` |
| normalization | `(255.0 - pixel) / 255.0` — inverted and scaled |
| declared PPI | **none** |

Sources, all at the pinned commit: `ckpts/JIPNet/config.yaml`
(`model_cfg.input_size: 160`), `inference.py` (`patch_size = 160`), all eight
shipped example images (exactly 160 × 160, 8-bit grayscale PNG), and the paper's
Figure 3 caption — "Paired fingerprint patches with the same shape are input,
specifically 160×160, 120×120, or 96×96 in this paper."

Section IV-A of the same paper describes the constructed evaluation patches as
160×160, **128**×128 and 96×96. The middle size differs between the two
statements; only 160×160 is reproduced by the released configuration. Recorded
rather than reconciled.

### What upstream does at inference time

```python
img1 = cv2.imread(osp.join(data_dir, f"{ftitle}_1.png"), 0)
img2 = cv2.imread(osp.join(data_dir, f"{ftitle}_2.png"), 0)
input1 = ((255.0 - img1) / 255.0)[np.newaxis, np.newaxis, :, :]
```

Read, invert, scale, forward. No crop, no resize, no size check. `cv2.resize`
appears nowhere in the repository.

### What upstream does elsewhere, and why it is not an inference route

The only full-fingerprint-to-patch function is `cut_patch`, in
`make_data/generate_patch.py` and in the training data loader. Neither is
imported by any inference script. The construction it belongs to:

```text
affine_pairs.py     align two impressions with VeriFinger
                    -> imports fptools.fp_verifinger, which is not in the
                       repository; the README states the script cannot run
                       because of licensing and the source cannot be released
        ↓
extract_mask.py     segment and erode a foreground mask
        ↓
generate_patch.py   sample a patch centre from the COMMON MASK OF THE PAIR,
                    sample a second centre on a ring around it,
                    rotate by a random angle in [-180, 180], then cut
```

Three properties make this unusable as a benchmark input route, and any one of
them would be enough:

1. **the crop is a property of the pair, not of the image.** Which window a
   fingerprint yields depends on which other fingerprint it is being compared
   with. A template that changes per comparison is not a template;
2. **it is random.** The centre and the rotation are sampled;
3. **its first step cannot run at all** without a commercial SDK the authors
   state they cannot release.

Promoting it anyway would produce `VeriFinger + an fpbench crop policy + JIPNet`,
which is not JIPNet (docs/adr/0092).

### Physical scale

No PPI is declared anywhere in the repository or the paper, and no statement
says one is unnecessary. The evaluation datasets do not share a resolution —
NIST SD14 and FVC2002 DB1_A at 500 ppi, FVC2004 DB2_A and FVC2006 DB2_A at 569
ppi — and no resampling to a common scale appears in the repository. A resize is
therefore not assumed physically neutral.

### The blockers

```text
BENCHMARK_INPUT_ROUTE_UNRESOLVED
FPBENCH_PREPROCESSING_CHOICE_REQUIRED
INPUT_DOMAIN_INCOMPATIBLE
```

The third says the released artifact does not fit this benchmark. It does not
say no future release could.

## Gates 3-7 — not reached

Nothing was downloaded, constructed or executed. What was noticed while reading
for Gates 1 and 2 is published as **observations** under `NOT_REACHED` gates,
labelled as observations and never as conclusions.

**Score.** `models/JIPNet.py` applies `torch.sigmoid` to the classification
output inside `forward`, so what leaves the network is already in `[0, 1]` with
higher meaning more similar; `inference.py` writes it out with nothing in
between. Direction and range look clean. What was *not* established is whether
`score(A, B)` equals `score(B, A)`: the classification head consumes the two
branches concatenated in a fixed order, nothing in the architecture symmetrises
them, and no upstream statement addresses it. Settling that means running the
released checkpoint both ways. fpbench may not average or maximise the two
orders without an upstream basis.

**Pose is not a score.** `align_pred` is a second output, written to a separate
line of the same file, and no upstream path lets it modify the classification
output.

**Artifacts.** The repository ships no weights. Every `ckpts/<model>/download.md`
points at a Google Drive folder — a place, not an identity. Whether
`encoder_bath.pth` is training-only or inference-required reads as training-only
from the released files (the README presents it under *Train*, the shipped
`configs/JIPNet.yaml` leaves `pretrain_cfg.encoder_pth` empty, and
`inference.py` constructs `JIPNet` without `encoder_pretrain_pth`) — but that is
a reading, and the question is settled by loading a checkpoint, not by reading
about one. It stays open.

**Runtime red flags.** `requirements.txt` pins `torch==2.1.2` alongside
`numpy==2.2.5`, which are not compatible, and a line reading `skimage==0.0`,
which is a placeholder package rather than scikit-image; the pinned set is not
installable as written. `inference.py` chooses its device conditionally but
loads the checkpoint with `map_location='cuda:0'` unconditionally and wraps the
model in `DataParallel` over `device_ids=[0]`, so CPU-only execution would need
an upstream change. No custom CUDA ops, no compiled extensions, no network
access.

**Training corpora**, from Table III, recorded as observations under a
`NOT_REACHED` Gate 6. Hybrid DB merges several datasets and splits them 95% / 5%
train / test with identities isolated between the halves:

```text
train & test   NIST SD14, FVC2004 DB1_A, FVC2004 DB2_A, FVC2006 DB2_A
test only      THU Small (in-house), FVC2002 DB1_A, FVC2002 DB3_A
```

The abstract names FVC2006 DB1_A where Table III and Figure 6(g) name DB2_A.
Recorded, because a future exclusion list has to name the right database.

SD300 overlap: `NO_EVIDENCE_FOUND`. No NIST special database numbered 300
appears in the paper or the repository, in either direction.

**Future development-dataset exclusions.** Should JIPNet ever be admitted, these
cannot serve as clean development data for calibrating it without further
overlap analysis, because the released checkpoint was fitted on 95% of them
(docs/adr/0079):

```text
NIST SD14, FVC2004 DB1_A, FVC2004 DB2_A, FVC2006 DB2_A
```

## What would change this

An upstream entry point that defines, deterministically and at inference time,
how an arbitrary full fingerprint becomes the input this checkpoint was released
for. The gate re-runs against it and nothing else in the preflight has to
change.

Alternatively, a different benchmark. JIPNet solves partial-fingerprint
verification well; fpbench does not pose that problem.
