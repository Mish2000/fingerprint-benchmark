# 0070 — One extraction is a duplicated pair

*Status: Accepted — 2026-08-05, stage 8B*

## Context

The pinned texture branch cannot process a batch of one.

`_Branch_TextureEmbedding.forward` ends with

```python
x = torch.nn.functional.normalize(torch.squeeze(x), dim=1)
```

For a batch of one the linear layer produces `[1, 256]`, `torch.squeeze`
removes the batch dimension to give `[256]`, and normalizing a one-dimensional
tensor along `dim=1` raises before any embedding exists. Measured against the
pinned runtime, torch 2.13.0+cpu:

```
input (1, 256) -> squeeze -> (256,)   -> normalize(dim=1) IndexError: Dimension out of range
input (2, 256) -> squeeze -> (2, 256) -> normalize(dim=1) ok (2, 256)

_Branch_TextureEmbedding  batch 1: IndexError
                          batch 2: ok, output (2, 256)
                          batch 3: ok, output (3, 256)
```

The minutia branch normalizes without squeezing first and accepts a batch of
one. So the artifact has no single-image path for one of its two branches, and
`DeepPrint_TexMinu.forward` therefore has none at all.

This is not a subtlety we can route around by choosing a different entry point.
The normalization lives inside the branch module, and the whole point of
building the model from pinned source (spec section 7.4) is that we do not
rewrite the parts we find inconvenient.

It is also a latent fault upstream rather than something about our inputs:
`get_dataloader_args(train=False)` uses `batch_size=32` without `drop_last`, so
any dataset whose size is one more than a multiple of 32 would hit it.

## Decision

One extraction feeds the identical preprocessed tensor twice, as a batch of
exactly two rows, through the unmodified upstream `forward`, and represents
row 0.

```
inference_batch_rows:  2
inference_batch_rule:  duplicate_pair_take_first_row
represented_row:       0
```

The rule is part of `flx_texminu_256x2_v1` and therefore part of the
representation identity, because what counts as "one extraction" is not an
implementation detail here.

The duplication is a checked invariant, not an assumption. Every extraction
asserts that the two rows are bitwise equal in both branches and fails the
operation otherwise. The real-checkpoint review exercised content and position
changes across five legal contexts using the frozen physical batch size of two:

```
A from [A, A] at row 0
A from [A, B] at row 0
A from [B, A] at row 1
A from [A, C] at row 0
A from [C, A] at row 1
```

Here A, B and C are distinct generated, non-biometric fixtures. All five
representations are bitwise identical in both branches. This proves that the
represented row does not depend on its legal position or the other legal batch
content.

An additional out-of-contract diagnostic used `[C, A, B]`, a physical batch
size the frozen route never executes. Relative to `[A, A]`, 103 texture values
differed by at most `1.4901161193847656e-08`, and 183 minutia values differed by
at most `2.9802322387695312e-08`. Deterministic algorithms and disabling oneDNN
did not remove that batch-shape drift. It is recorded here rather than hidden,
but it neither widens the zero tolerance nor becomes part of the executable
route's contract.

`describe_operation()` publishes the extraction rule, so a reader of a Stage
8C score can see what produced it. The diagnostic batch-context operation is
worker-internal and does not expand the adapter's six-operation public surface.

## Alternatives considered

**Call the sub-modules directly and normalize ourselves.** Requires
reimplementing the branch head — exactly the "local reimplementation presented
as upstream" that ADR 0066 exists to prevent — and the reimplementation would
be untested against an upstream that cannot run to compare against.

**Run the stem once at batch one and duplicate only into the texture branch.**
Saves roughly half the arithmetic and buys inconsistency: the two branches
would then see different batch shapes, so any batch-dependent kernel choice
would apply to one branch and not the other. The saving is not needed.

**Pad the batch with a different image.** Makes one extraction depend on an
unrelated input, which is precisely what an extraction must not do.

**Report `FLX_CONTRACT_FAILED` and stop.** The artifact works; it simply has no
batch-of-one path. Failing the stage over a batch shape would discard a
functioning route for a reason that has nothing to do with its representations.

## Consequences

Every extraction costs two forward rows instead of one. The authoritative
qualification shows that the doubling remains inside the frozen 24-hour budget
for the 12,000 extractions of a full Stage 8C run.

Spec section 17.6 asks whether a single image's representation is stable across
single-image, batch-of-one and in-batch positions. Batch-of-one does not exist
here, so the qualification records that comparison as `not_applicable` rather
than inventing an API for it, and proves position and content invariance inside
valid multi-image batches.

The workaround is accepted without patching upstream. The real-checkpoint proof
makes the represented row bitwise independent of position and content within
the only physical batch shape the route executes, while keeping the source
unmodified and the extraction rule explicit in the representation identity.
