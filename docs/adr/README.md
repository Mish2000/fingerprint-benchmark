# Architecture Decision Records

Every decision that would be expensive to reverse, or that a reader of the code
would otherwise have to reconstruct, is written down here. A decision that
lives only in a conversation or in someone's head is not a decision the project
can be held to.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-protocol-from-adapters.md) | The protocol is independent of the algorithm | Accepted, implemented |
| [0002](0002-minimal-adapter-contract.md) | Adapters must implement `compare`, nothing more | Accepted, implemented |
| [0003](0003-decision-outside-adapter.md) | Thresholds are applied outside the adapter | Accepted, partly implemented |
| [0004](0004-sd300c-effective-ppi.md) | SD300C is used at 2000 ppi despite its metadata | Accepted, implemented |
| [0005](0005-immutable-raw-results.md) | Manifests and raw results are immutable | Accepted, implemented |
| [0006](0006-self-failure-semantics.md) | An operational failure is not a non-match | Accepted, implemented |
| [0007](0007-no-algorithm-branching-in-runner.md) | No algorithm-specific branching outside adapters | Accepted, implemented |
| [0008](0008-non-mated-pairing-strategy.md) | Impostor pairs shift the finger within a subject | Accepted, implemented |
| [0009](0009-one-immutable-result-per-job.md) | One immutable result file per job | Accepted, implemented |
| [0010](0010-adapter-context-excludes-ground-truth.md) | An adapter is told nothing about the comparison | Accepted, implemented |

"Not yet implemented" means the decision is agreed and binding on the code that
will implement it, but that code is out of scope for the current stage.

ADR 0003 is *partly* implemented: raw scores are stored without any threshold
and the score direction travels with every result, which is the half that had
to exist before results could be written. The `DecisionPolicy` that consumes
them arrives with the decision layer.

## Format

```
# Title

## Status
## Context      what problem forced a choice?
## Decision     what did we choose?
## Alternatives what else was considered, and why not?
## Consequences what does this cost, and what does it buy?
```
