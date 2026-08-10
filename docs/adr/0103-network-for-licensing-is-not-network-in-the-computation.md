# Network for licensing is not network in the computation

## Status

Accepted, implemented.

## Context

Neurotechnology states plainly that a constant internet connection is required
while its SDKs are being evaluated. Read quickly, that looks like a
reproducibility disaster: a benchmark whose numbers depend on a network is a
benchmark whose numbers can change without anything in the pinned package
changing.

Read carefully, it is two different claims wearing one sentence, and only one of
them would be fatal:

```text
the network validates a licence          →  the algorithm is here
the network computes part of the score   →  the algorithm is somewhere else
```

The second is fatal because a server-side matcher can be updated by its owner at
any time. The pinned archive would still hash the same, the evidence would still
verify, and the scores would quietly belong to a different algorithm. No digest
in this repository would move.

The vendor also sells server-side components — a Matching Server, an Image
Processing Service — so the question is not hypothetical for this product line.
It has to be answered for the specific route being qualified.

## Decision

The network gate answers one question — what is the connection *for*? — and it
answers it from pinned notices and from the structure of the artifact, never by
experiment.

For this route the answer is `LICENSE_VALIDATION_ONLY`. The licence agreement
inside the pinned archive defines Internet Activation as storing a licence file
locally which allows the component to run *on that computer* after a licence
check, needing a connection briefly at least once in seven days. The extraction
and matching components are native libraries in the archive, the fingerprint data
files they load are beside them, and the vendor's server-side components are
separately licensed and are not part of the 1:1 route.

Where the answer is `PARTICIPATES_IN_BIOMETRIC_COMPUTATION`, or cannot be
established, the blocker is `REMOTE_COMPUTATION_IDENTITY_UNRESOLVED` and it is a
reproducibility blocker rather than an inconvenience — unless the remote service
can itself be pinned, which is a different and much harder claim.

**No bypass experiment.** The obvious test — pull the network out and see whether
matching still works — is refused. It is an attempt to observe behaviour outside
the licensed configuration, it is close to the circumvention the agreement
prohibits, and it answers a narrower question than the one asked. Documentation,
supported diagnostics and ordinary operation only.

## Alternatives

**Treat any network requirement as disqualifying.** Simple, and it would exclude
essentially every commercial SDK for a licensing mechanism rather than for
anything about its algorithm.

**Test it by disconnecting.** Refused above.

**Defer the question to the runtime stage.** It is cheap to answer here from the
notices already pinned, and expensive to discover later: finding out after 6,000
comparisons that some of them were computed elsewhere would invalidate the run.

## Consequences

The gate passes on artifact evidence, and the reason is recorded in a form a
later reader can check: a clause from an agreement pinned by digest, plus the
observation that the components and their data files are local.

It also leaves a real operational condition on any future run, and the stage
records it rather than filing it as harmless: a licence check that must succeed
at least once every seven days means a long run can be interrupted by a network
outage. That is an availability property of the route, not a property of its
scores — and knowing which of the two it is was the point.
