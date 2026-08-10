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
3,000 participating images        the cohort, not an operation count
6,000 comparison attempts
12,000 extraction invocations     two per comparison, both sides independent
6,000 matcher invocations
+ a bounded allowance for the qualification itself
```

Twelve thousand rather than three thousand, and that number is not a choice made
here. It is Stage 8C's execution semantics, already published over the same
6,000 comparisons: every comparison extracts both of its sides afresh, and
`SELF(A, A)` extracts A twice rather than comparing one template with itself
(docs/adr/0070). A workload of 3,000 extractions would be a workload with a
representation cache in it, and this project does not have one.

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
is a constant of the stage: a 3,000-image cohort, 6,000 comparison attempts,
12,000 extraction invocations, 6,000 matcher invocations and an upper bound of
200 qualification operations — 18,200 high-level biometric operations in total.
The capacity question is asked against that and against nothing else, and the
constant refuses a workload whose extractions are not twice its comparisons.

**Unresolved is a failure, not a caution.**

```text
LICENSE_WORKLOAD_CAPACITY_UNRESOLVED     -> FAIL
LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT   -> FAIL
```

A capacity nobody can state is a run nobody can plan, and the difference between
"we know it is too small" and "we cannot tell" does not matter to the run.

**The logical workload is published; the metered call count is not derived.**
The two are different quantities and the evidence keeps them apart:

```text
logical_workload:
    comparison_attempts                              6,000
    extraction_invocations                          12,000
    matcher_invocations                              6,000
    qualification_high_level_operations_upper_bound     200

high_level_biometric_operations                     18,200

sdk_metered_call_count:                         UNRESOLVED
```

18,200 is a count of *biometric* operations. It is not an upper bound on API
calls and must never be published as one: id3 publishes no definition of an API
call, and an SDK that counts every method invocation also counts image
construction, resolution setting, model loading, extractor and matcher
construction and the licence calls themselves — none of them countable in
advance without knowing how often a process starts.

The conversion from the logical workload into the licence's own unit happens
once the vendor states what is metered, and not before. That turns "we do not
know whether it fits" into a single question a vendor can answer, and it makes
the arithmetic checkable the moment an answer exists.

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

The first version of this stage got the workload wrong in both halves — it
counted one extraction per participating image, which no execution here
performs, and it published a biometric-operation bound under the name of an
API-call bound. The contract suite passed throughout, because it asserted that
the code matched the constant rather than that the constant matched the
protocol. A contract test cannot catch a wrong premise it was written from; that
is what review is for.

The gate is cheap to satisfy later. One statement in the delivered licence
documentation, or one question to the vendor, resolves it, and the arithmetic is
already published beside the workload it would be computed against.

The rule is not specific to id3. Any metered or time-limited component inherits
it, and the frozen workload it is measured against is the same one for every
algorithm in this benchmark.
