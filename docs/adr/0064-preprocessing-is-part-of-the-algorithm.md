# 0064 — Preprocessing is part of the algorithm

*Status: Accepted — 2026-08-04, stage 8A*

## Context

Learned fingerprint models consume tensors, not the canonical gray PNGs used by
the experiment. The path between those forms can change the representation as
much as the network does: polarity, crop, padding, resizing, interpolation,
alignment, localization, contrast, normalization and channel layout all alter
the values seen by the checkpoint.

Research repositories often hide those choices in dataset loaders. One dataset
may be cropped with fixed coordinates, another resized after localization, and
a third selected by a dataset-name branch. Copying one branch because it happens
to accept an image would invent a general inference contract that upstream did
not define. Choosing a conventional ImageNet normalization or a plausible crop
would have the same problem.

If those choices remain outside the candidate identity, two integrations could
use the same source commit and checkpoint while computing different scores
under the same algorithm name.

## Decision

The algorithm qualified by stage 8A is the complete canonical-PNG-to-score
pipeline. Preprocessing is a fingerprinted part of that identity, not adapter
convenience.

A candidate preprocessing profile enumerates every operation between the
canonical input PNG and the model tensor, in execution order. It records at
least:

* grayscale conversion and polarity;
* crop, padding and resize geometry;
* interpolation rule;
* alignment and localization;
* contrast transformation and value normalization;
* channel creation or replication;
* tensor layout and numeric data type; and
* the value range presented to the model.

Each operation cites its authority: exact upstream code, upstream configuration
or upstream documentation. Defaults supplied by an image library are made
explicit where they can affect pixels. Changing an operation, parameter, order
or authority changes the preprocessing and qualification fingerprints.

The route must be usable for a generic canonical fingerprint image without
consulting dataset name, subject, label, ground truth or evaluation cohort. A
repository that contains only dataset-specific branches fails the preprocessing
gate until upstream identifies an SD300-independent general route. Stage 8A
does not choose a branch by trial on SD300.

A thin integration wrapper may decode the canonical file and call the complete
upstream path. It may not supply a missing crop, resize, normalization,
localization, alignment or minutiae-generation rule. Such a rule is algorithmic
work, not plumbing, and would need a separately named implementation candidate
under a new registry decision.

The same completeness rule applies to multi-branch models. The profile must
make clear which processed tensor reaches each texture, minutiae, CNN, ViT or
local-embedding branch and how the branch outputs are fused. Selecting only the
easy branch is not allowed unless upstream defines that branch as a standalone
model with its own checkpoint identity.

## Alternatives considered

**Adopt standard computer-vision preprocessing.** There is no universal
standard whose crop, interpolation and normalization can be presumed compatible
with an arbitrary fingerprint checkpoint.

**Tune preprocessing on SD300.** That leaks the evaluation cohort into algorithm
selection and gives the selected pipeline an undocumented, dataset-specific
identity.

**Treat preprocessing as an execution profile.** Resolution preparation shared
by the benchmark can remain an execution profile. Candidate-specific conversion
from that canonical artifact into the learned model's tensor changes what the
model computes and therefore belongs to the algorithm.

**Fingerprint only the resulting tensor.** That detects one observed output but
does not specify how to produce tensors for new images or expose dependence on
dataset labels and hidden defaults.

## Consequences

An otherwise complete checkpoint can fail qualification because its general
input contract is absent. That is intentional: guessing the contract would
produce reproducible bytes for an algorithm that upstream never specified.

For a passing candidate, reviewers can reconstruct every pixel-changing step,
and a later adapter remains thin. Tampering with normalization, geometry,
branch routing or tensor representation invalidates the qualification rather
than silently changing benchmark scores.
