# 0096 — An evaluation licence must be shown to cover the frozen workload

*Status: Accepted — 2026-08-10, stage 10B*

## Context

id3 offers a free 30-day evaluation of the Finger SDK. The same product page
qualifies it with two phrases and no numbers:

```text
Limited API calls
Single platform
```

No public statement says which operations consume the quota. It could be
extractions, comparisons, model loads, or every API call including the licence
check. It could be a per-day figure or a total. None of that is public, and the
delivered licence documentation is inside a package that arrives only after a
vendor request.

The benchmark's workload, by contrast, has been fixed since the canonical
protocol was frozen:

```text
3,000 participating images
3,000 extractions          one per image
6,000 comparisons
+ a bounded allowance for the qualification itself
```

The tempting move is to obtain an evaluation licence and start, on the reasoning
that most of the run will probably fit and the rest can be dealt with when it
arrives. That reasoning has a specific failure mode: a quota exhausted at
comparison four thousand leaves two thousand comparisons that were never run.
The result is not a smaller experiment. It is not an experiment — every rate in
this project is a count over a named denominator, and a denominator that stopped
early is not the denominator that was declared.

There is a worse version of the same failure. A run that stops partway is
tempting to *report* partway, or to restart on a second evaluation licence, or
to trim the protocol to what the quota allowed. Each of those is a different
protocol reported under the name of this one.

## Decision

Licence capacity is a **hard gate**, settled before the first comparison.

**The workload is frozen first, and never trimmed to fit.** `FROZEN_WORKLOAD`
is a constant of the stage: 3,000 images, 3,000 extractions, 6,000 comparisons
and an upper bound of 200 qualification operations. The capacity question is
asked against that and against nothing else.

**Unresolved is a failure, not a caution.**

```text
LICENSE_WORKLOAD_CAPACITY_UNRESOLVED     -> FAIL
LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT   -> FAIL
```

A capacity nobody can state is a run nobody can plan, and the difference between
"we know it is too small" and "we cannot tell" does not matter to the run.

**The cost is published under every metering semantics it could have.** The
unknown is not the size of the run but which operations a quota counts, so the
evidence carries a table rather than a number:

```text
extraction_only               3,000
matching_only                 6,000
extraction_and_matching       9,000
every_api_call_upper_bound    9,200
```

That turns "we do not know whether it fits" into a single question a vendor can
answer, and it makes the arithmetic checkable once an answer exists.

**What may be published about a licence is a closed list.** `license_type`,
`enabled_module_names`, `expiry_category`, `remaining_days_category` and
`sufficient_for_declared_workload`. Everything else about a licence is either
irrelevant or a secret (docs/adr/0098).

**"Try it and see" is refused by name.** The evidence says so in as many words,
so that a later reader who is tempted finds the refusal rather than a silence.

## Alternatives

**Start the run and monitor the quota.** Rejected above. It converts a capacity
risk into a partial result, and a partial result cannot be published as a
result.

**Split the workload across several evaluation licences.** Rejected. Reactivating
to obtain more quota is a trial reset by another name, and a run spanning two
licences on two activations is not one run under one algorithm fingerprint
(docs/adr/0095).

**Reduce the benchmark for this algorithm.** Rejected. Four algorithms reported
over different comparison sets are four experiments, and the whole point of the
canonical pair manifest is that they are not.

**Treat an unresolved quota as a risk accepted by the owner.** ADR 0084 permits
owner risk acceptance for ambiguous upstream *rights*. A quota is not ambiguous
in that sense: it is a number nobody has looked up yet, and accepting it as a
risk would be accepting a partial run as an outcome.

## Consequences

Today's outcome is decided by this ADR as much as by the missing package: even
with an evaluation licence in hand, the capacity could not be checked against
the frozen workload from public information alone.

The gate is cheap to satisfy later. One statement in the delivered licence
documentation, or one question to the vendor, resolves it, and the arithmetic is
already published beside the workload it would be computed against.

The rule is not specific to id3. Any metered or time-limited component inherits
it, and the frozen workload it is measured against is the same one for every
algorithm in this benchmark.
