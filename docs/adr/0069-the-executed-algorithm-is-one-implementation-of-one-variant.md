# 0069 — The executed algorithm is one implementation of one variant

*Status: Accepted — 2026-08-05, stage 8B*

## Context

It would be natural to write "DeepPrint" in the results table. It would also be
wrong in three separate ways at once.

The code is not DeepPrint's. It is `fixed-length-fingerprint-extractors` at
commit `7accfca1`, written by the authors of the BIOSIG 2023 benchmarking
study, independently reimplementing the DeepPrint architecture family. ADR 0066
already refuses to accept a paper reimplementation as the upstream algorithm.

The weights are not DeepPrint's either. They are one checkpoint,
`best_model.pyt`, whose structure identifies the `TexMinu_512_without_localization`
variant: a 256-dimensional texture branch and a 256-dimensional learned-minutia
branch, no localization network, no pose input. DeepPrint as published has a
localization stage. Calling this "DeepPrint" would credit it with a component
this artifact does not contain.

And the route is not upstream's. The transform from a canonical 500 ppi gray8
PNG to a `[1, 299, 299]` tensor is a decision this project made, because
upstream has no dataset-independent loader — its image loaders branch by
SFinGe, FVC2004, MCYT and NIST SD4. ADR 0064 already says preprocessing is part
of the algorithm, which means the route we execute is partly ours.

## Decision

The algorithm identity is

```
algorithm_id: flx_deepprint_texminu_512_without_localization
```

and it names the implementation, the variant and the absent localization. It is
never abbreviated to "DeepPrint" in evidence, in code, or in a results table.

The full identity of what actually runs is the combination of six things, and
all six are fingerprinted separately so that any one of them can move without
being mistaken for another:

```
flx source identity            commit + archive SHA-256
exact checkpoint identity      filename + size + SHA-256 + variant
fpbench preprocessing profile  fpbench_canonical500_to_flx299_squarepad_v1
pinned runtime profile         flx_cpu_linux_x86_64_v1
fpbench adapter version        flx_pytorch_subprocess v1
score serialization profile    ieee_scalar_to_decimal17_v1
```

Provenance travels with the identity: `implementation_origin` is
`independent_reimplementation`, the upstream study is cited as Rohwedder et al.,
BIOSIG 2023, and the relationship is stated in words rather than implied by a
name.

No local decision of ours may be presented as a property of the original
DeepPrint or of the `flx` authors. The square-padding parity rule, the
interpolation flags, the inference batch rule and the Decimal serialization are
all `fpbench` decisions, and the evidence attributes them to this project.

## Alternatives considered

**Call it "DeepPrint (reimplementation)".** Still leads with a name that
belongs to different code and different weights, and hides which of six
variants ran.

**Call it "flx".** Names the repository but not the variant. `flx` ships
`Tex`, `Minu`, `TexMinu`, `LocTex`, `LocMinu` and `LocTexMinu`; four of them
would produce a different representation from the same repository.

**Report the paper's published numbers alongside ours.** Different cohorts,
different protocol, and in this case a training-provenance conflict that
Stage 8A recorded and did not resolve. Comparing them would invite the reader
to treat two incomparable measurements as one.

## Consequences

The identifier is long and will look pedantic in a table header. That is the
intended trade: a reader who sees it cannot mistake this for the published
DeepPrint result, and a reader who sees "DeepPrint" would.

Any future stage that swaps the checkpoint for another `flx` variant, or adds
the localization branch, is a different algorithm with a different id — not a
new version of this one.
