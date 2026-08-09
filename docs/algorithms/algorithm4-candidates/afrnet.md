# AFR-Net — candidate record

*Stage 10A candidate. Verdict: `AFRNET_PREFLIGHT_FAIL`, at Gate 1.*

## The work

```text
S. A. Grosz and A. K. Jain, "AFR-Net: Attention-Driven Fingerprint Recognition
Network", IEEE Transactions on Biometrics, Behavior, and Identity Science,
vol. 6, no. 1 (2024) pp. 30-42, DOI 10.1109/TBIOM.2023.3317303
```

Preprint `arXiv:2211.13897`, v1 25 Nov 2022, v2 3 Dec 2022.

A hybrid of a CNN and a vision transformer that produces a fixed-length
embedding, with a spatial transformer for alignment and a published realignment
strategy that uses correspondences between local embeddings from intermediate
feature maps to re-score low-certainty pairs. The paper reports it beating
Verifinger v12.3 across intra-sensor, cross-sensor and latent-to-rolled
matching.

Nothing in this record is a judgement about the method. It is a strong paper.

## Why it is not admissible

No executable artifact attributable to the authors was located.

| | Found |
| :--- | :--- |
| author-supplied source | no |
| author-supplied checkpoint | no |
| author-supplied inference route | no |

Ten locations were searched on 2026-08-09 and each is recorded in
`evidence/stage10a-algorithm4-candidate-preflight/afrnet/source-discovery.json`
with what it returned:

| Location | Outcome |
| :--- | :--- |
| arXiv listing, both versions | paper only, no code link |
| the full paper text | nothing; the only GitHub reference is `timm`, a dependency |
| MSU Biometrics publication database | two entries, each linking arXiv and IEEE only |
| MSU Biometrics databases page | no mention |
| MSU Biometrics projects page | no mention |
| `github.com/groszste` | five repositories; the only fingerprint work is SpoofGAN |
| a group GitHub organisation | none exists |
| GitHub repository search | nothing related by either author |
| Papers with Code / Hugging Face | "No model linking this paper" |
| IEEE Xplore article page | **not readable from here** — recorded as unread, not as empty |

`not found` is not `proven absent`, and the record says so. What the gate needs
is a *found* author-supplied source and checkpoint, and neither was found.

## The reproduction that does exist, and why it is not this

`XiongjunGuan/JIPNet` ships `inference_AFRNet.py`, a working AFR-Net published
as a comparison baseline. Its route:

```text
image pair
    ↓
RidgeNet enhancement
    ↓
PFVNet AlignNet          <-- substituted for AFR-Net's own pose rectification
    ↓
AFRNet (input_size=224, num_classes=384, is_stn=True)
    ↓
0.2 x cosine(CNN half) + 0.8 x cosine(ViT half)
```

Its own authors describe the comparison models as reproduced from the
corresponding papers, adjusted in some cases for partial fingerprints, and their
paper states explicitly that the original pose rectification of DeepPrint,
DesNet and AFR-Net could not be performed on partial fingerprints, so AlignNet
was used instead — a substitution they mark with an asterisk in their own
tables.

A route with a substituted scoring-relevant component is a different algorithm.
Under docs/adr/0090 it is a candidate of its own:

```text
jipnet_authors_adjusted_afrnet_reimplementation
```

and never `afr_net`. Stage 10A does not consider it as AFR-Net, and it is
enumerated as *excluded evidence* so that the exclusion is visible rather than
silent.

## Facts recorded but not used as conclusions

**The published variant question.** The paper's headline results use the
realignment stage, reported as `AFR-Net†`; the base model is a distinct
configuration with its own numbers. Had the identity gate passed, Stage 10A
would have had to fix which of the two is the candidate before anything else.
It did not pass, so nothing was fixed.

**Input geometry.** The paper's Table 1 gives the network input as
`3 × 224 × 224`, and no PPI assumption is declared. This is recorded as a fact
about the paper; it is not a model input contract, because there is no released
model to contract with. The input-domain gate is `NOT_REACHED`.

**Training corpora**, from the paper's Table 2, recorded as observations under a
`NOT_REACHED` Gate 6:

```text
train       MSP, NIST SD 302, MSU Self-Collection, PrintsGAN, SpoofGAN,
            MSU Finger Photo and Slap, IIT Bombay Touchless and Touch-based,
            ManTech Phase 2, Synthetic Latent Prints, NIST SD 4
            — 1.3M images
validation  MSU Finger Photo and Slap, MSP Latent, NIST SD 302 — 3,814 images
```

SD300 overlap: `NO_EVIDENCE_FOUND`. NIST SD 302 is a different special database
and is not this project's evaluation cohort. Nothing was found in either
direction about SD300, and `NO_EVIDENCE_FOUND` is never converted into
`PROVEN_ABSENT`.

**A granted patent.** MSU records US patent 12,380,728, "Attention Driven
Fingerprint Recognition Network" (AFR-Net), granted 5 August 2025. Recorded as a
fact about the work's status. It is not the basis of any Stage 10A conclusion:
the reason this candidate fails is that there is no artifact, not that there is
a patent.

## What would change this

An implementation and a checkpoint published by Grosz and Jain, or by somebody
with the standing to release the originals. The gate re-runs against them and
nothing else in the preflight has to change.
