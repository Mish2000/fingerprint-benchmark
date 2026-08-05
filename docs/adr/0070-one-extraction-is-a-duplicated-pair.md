# 0070 — One extraction is a duplicated pair

*Status: Proposed — needs review — 2026-08-05, stage 8B*

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
operation otherwise. Measured on the pinned runtime with random weights, they
are, at one thread and at twenty-four, and row 0 of a batch of two also equals
row 0 and row 2 of a batch of three.

`describe_operation()` publishes the rule, so a reader of a Stage 8C score can
see what produced it.

## Alternatives considered

**Call the sub-modules directly and normalize ourselves.** Requires
reimplementing the branch head — exactly the "local reimplementation presented
as upstream" that ADR 0066 exists to prevent — and the reimplementation would
be untested against an upstream that cannot run to compare against.

**Run the stem once at batch one and duplicate only into the texture branch.**
Saves roughly half the arithmetic and buys inconsistency: the two branches
would then see different batch shapes, so any batch-dependent kernel choice
would apply to one branch and not the other. The saving is not needed; see
below.

**Pad the batch with a different image.** Makes one extraction depend on an
unrelated input, which is precisely what an extraction must not do.

**Report `FLX_CONTRACT_FAILED` and stop.** The artifact works; it simply has no
batch-of-one path. Failing the stage over a batch shape would discard a
functioning route for a reason that has nothing to do with its representations.

## Consequences

Every extraction costs two forward rows instead of one. Measured with random
weights on the pinned single-threaded runtime, one extraction takes 0.773 s,
which projects to 2.58 hours for the 12,000 extractions of a full Stage 8C run
against a frozen budget of 24 hours. The doubling is affordable and was
measured before the rule was frozen, not after.

Spec section 17.6 asks whether a single image's representation is stable across
single-image, batch-of-one and in-batch positions. Batch-of-one does not exist
here, so the qualification records that comparison as `not_applicable` rather
than inventing an API for it, and instead proves position-invariance inside a
multi-image batch.

**Open for the supervisor.** This is a workaround for an upstream defect, and
it changes what "one extraction" means. The alternative worth weighing is
patching the single line upstream and recording the patch as part of the source
identity — which trades an unmodified artifact for a simpler contract. That
choice is deliberately not made here.
