# FLARE — score semantics

## The representation

Per branch, from `FDD.get_embedding`:

```text
descriptor   2D x 16 x 16  =  12 x 16 x 16  =  3072 scalars
mask          1 x 16 x 16  =                    256 scalars
```

with `D = 6`, which the paper's §IV and `desc_configs.yaml`'s `ndim_feat` agree
on.

The descriptor is `cat(feature_t, feature_m)` over the channel axis — the texture
branch first — and is then flattened in C order. So it is **channel-major**: 256
values for channel 0, then channel 1, and so on for twelve channels.

One fingerprint carries **four** descriptors and **four** masks, one per branch.

## The mask is continuous

`foreground` ends in a sigmoid, and the continuous matching path uses those
values directly: the mask multiplies the numerator and both denominator terms
without ever being compared against a threshold.

Thresholding exists only in the binary path (`-b`), with asymmetric cut-offs of
0.5 and 0.2, and that path is excluded from this identity. fpbench applies no
mask threshold of its own.

## The branch score

Transcribed from the continuous branch of `calculate_score`:

```text
tiled_a = numpy.tile(mask_a, (1, 12))     # the 256-value block, twelve times
tiled_b = numpy.tile(mask_b, (1, 12))

x12 = (tiled_a * f_a) @ (tiled_b * f_b).T
x1  = sqrt((tiled_a * f_a**2) @ tiled_b.T)
x2  = sqrt(tiled_a @ (f_b**2 * tiled_b).T)

score = x12 / (x1 * x2).clip(1e-3, None)
```

Four things a library cosine would get wrong:

1. the masks weight the numerator **and** both denominator terms;
2. each mask enters **linearly**, not squared;
3. the clip is on the **product** of the two terms, not on either factor;
4. the tiling repeats the whole 256-value block twelve times, so block `c` lines
   up with channel `c` of the channel-major descriptor. Getting that wrong would
   compare a mask cell against the wrong channel and still produce a plausible
   number.

The paper's Eq. 7 reads as written under binary masks. The implementation
generalises the same formula to the sigmoid mask by staying linear in each, and
that is the semantics this project freezes.

## Two properties worth knowing

**Symmetry.** Swapping the two fingerprints swaps `x1` and `x2` and leaves their
product, so the score is unchanged.

**Scale invariance in each mask.** Multiplying either mask by a positive constant
multiplies the numerator and the product of the denominator terms by the same
constant, so — while the clip does not bind — the score does not change. The
mask's absolute magnitude carries no information; only its spatial profile does.
That is another reason not to threshold it: a threshold discards exactly the part
that matters.

## Degenerate overlap

As the overlapping foreground vanishes the numerator goes to zero while the
clipped denominator holds at `1e-3`, so the branch score goes to zero and stays
finite. The behaviour is defined by the pinned source and needs no new policy
here — which matters, because inventing a failure rule for near-zero overlap
would have been a Stage 9A decision about somebody else's method.

## Fusion

```text
score = max over i in {0, 1, 2, 3} of branch_score_i
```

The paper's Eq. 8. The branch scores are diagnostics of one matcher, not four
algorithms; a future adapter returns the maximum and may report the winning
branch beside it:

```text
branch_scores:
    voting_unetenh
    voting_priorenh
    regression_unetenh
    regression_priorenh
winning_branch
```

A maximum does not depend on the order of its arguments, which is why the branch
order is not part of the algorithm and the branch count is.

## Direction

```text
HIGHER_IS_MORE_SIMILAR
```

A raw score, stored as it comes and never clamped (docs/adr/0073).
