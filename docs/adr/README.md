# Architecture Decision Records

Every decision that would be expensive to reverse, or that a reader of the code
would otherwise have to reconstruct, is written down here. A decision that
lives only in a conversation or in someone's head is not a decision the project
can be held to.

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-separate-protocol-from-adapters.md) | The protocol is independent of the algorithm | Accepted, implemented |
| [0002](0002-minimal-adapter-contract.md) | Adapters must implement `compare`, nothing more | Accepted, not yet implemented |
| [0003](0003-decision-outside-adapter.md) | Thresholds are applied outside the adapter | Accepted, not yet implemented |
| [0004](0004-sd300c-effective-ppi.md) | SD300C is used at 2000 ppi despite its metadata | Accepted, implemented |
| [0005](0005-immutable-raw-results.md) | Manifests and raw results are immutable | Accepted, implemented |
| [0006](0006-self-failure-semantics.md) | An operational failure is not a non-match | Accepted, not yet implemented |
| [0007](0007-no-algorithm-branching-in-runner.md) | No algorithm-specific branching outside adapters | Accepted, not yet implemented |
| [0008](0008-non-mated-pairing-strategy.md) | Impostor pairs shift the finger within a subject | Accepted, implemented |

"Not yet implemented" means the decision is agreed and binding on the code that
will implement it, but that code is out of scope for the current stage.

## Format

```
# Title

## Status
## Context      what problem forced a choice?
## Decision     what did we choose?
## Alternatives what else was considered, and why not?
## Consequences what does this cost, and what does it buy?
```
