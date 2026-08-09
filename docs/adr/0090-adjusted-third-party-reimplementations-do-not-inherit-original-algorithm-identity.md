# 0090 — An adjusted third-party reimplementation does not inherit the original algorithm's identity

*Status: Accepted — 2026-08-09, stage 10A*

## Context

ADR 0066 established that no paper reimplementation is accepted as an upstream
algorithm. Stage 10A meets the harder version of that question, and it is harder
in a way that is easy to miss.

There exists a working, public, well-written AFR-Net. It is inside
`XiongjunGuan/JIPNet`, published by researchers of good standing as a baseline
for their own comparison. It loads a checkpoint, it runs, and it produces a
similarity score. It is not a sketch and it is not abandoned.

It is also not AFR-Net. Its own authors say so twice. Their README states that
the comparison models are reproduced from the corresponding papers and that some
were adjusted for partial-fingerprint scenarios. Their paper states that the
pose rectification used by DeepPrint, DesNet and AFR-Net could not be performed
as expected on partial fingerprints, and that PFVNet's AlignNet was substituted
in its place — a substitution they mark in their own results with an asterisk.

The temptation is precise and worth naming: fpbench needs a fourth algorithm,
a runnable AFR-Net exists, and the difference between it and the published one
could be recorded in a footnote. That footnote would then travel with numbers
labelled `afr_net`, and every reader downstream would take them for AFR-Net's.

## Decision

Implementation origin is classified from a closed vocabulary, per candidate:

```text
AUTHOR_OFFICIAL_IMPLEMENTATION      the paper's authors published this code
AUTHOR_OFFICIAL_RELEASE             the paper's authors published this artifact
THIRD_PARTY_REIMPLEMENTATION        somebody else implemented the paper
ADJUSTED_THIRD_PARTY_REIMPLEMENTATION   ... and changed a component
PAPER_RECONSTRUCTION                fpbench implemented the paper
UNKNOWN                             nothing was established
```

Only the first two are admissible for an Algorithm 4 candidate.

**A reimplementation is never published under the name of the algorithm it
reimplements**, with or without a qualifier attached to the run. The name is the
identity, and a qualifier in a footnote does not travel with a number.

**An adjusted reimplementation is a separate candidate with a separate name.**
If the AFR-Net inside JIPNet is ever wanted, it enters as:

```text
jipnet_authors_adjusted_afrnet_reimplementation
```

with a preflight of its own, and never as `afr_net`.

**A reproduction is not evidence for the original.** The existence of an
executable AFR-Net does not partially satisfy AFR-Net's identity gate. Stage 10A
enumerates it as *excluded evidence*, with the reason, so that the exclusion is
visible rather than silent.

## Alternatives

**Accept it with a qualifier in the algorithm id.** Rejected: this is the
`afr_net_jipnet_variant` shape. It is more honest than plain `afr_net` and still
wrong, because it implies the two are versions of one thing when a scoring
component was replaced.

**Accept it and record the difference in the evidence only.** Rejected outright.
Evidence is read by whoever goes looking; a name is read by everyone.

**Treat "adjusted" as a matter of degree and judge each case.** Rejected: the
degree is exactly what nobody can assess without reimplementing both and
comparing, which is the work being avoided.

## Consequences

AFR-Net cannot enter fpbench until its authors publish an implementation and a
checkpoint, or until somebody with the standing to do so releases one. That is a
real loss: it is a strong, well-evaluated method, and the vision-transformer plus
CNN combination would have added genuine diversity beside SourceAFIS, NBIS and
flx.

The adjusted reproduction stays available as a future candidate under its own
name. Nothing is thrown away; it is filed correctly.

The rule costs nothing when upstream is clean — JIPNet's identity gate passed on
its first reading, on two sentences that name each other.
