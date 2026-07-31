# 0027 — Decision-conditional and attempt-level rates are separate metrics

## Status

Accepted. Implemented in `fpbench.metrics.policy` (the catalogue) and enforced by
`MetricNumerator.NON_SUCCESS`'s restriction to genuine populations.

## Context

[ADR 0006](0006-self-failure-semantics.md) established that a comparison which produced
no score is `UNDECIDABLE` and never a non-match. Stage 5A carried that all the way into
the decision records: `decision` is null exactly when there was no score.

At the metric layer the question becomes sharper, because a rate needs a denominator and
there are exactly two defensible ones. For mated PLAIN–ROLL comparisons:

```
mated NON_MATCH                        mated NON_MATCH + mated UNDECIDABLE
------------------------------         -----------------------------------
mated MATCH + mated NON_MATCH          all mated attempts
```

The first answers "when the system produced an answer, how often was it wrong?" — a
property of the matcher. The second answers "how often did a genuine user fail to be
recognised?" — a property of the deployment, in which a crashed extraction is just as
much a failure to recognise somebody as a low score is.

Both are legitimate. Neither is a substitute for the other. And in the run this project
has just finished, **all 6,000 comparisons succeeded**, so the two numbers are identical.

That is the trap. A single blended metric would be provably correct today, ship, and
then start moving next year for reasons no one could name from the number — because the
day a template extraction fails, one of those denominators changes and the other does
not.

## Decision

**Every population is reported twice, under two separately named metrics, even when the
two coincide.**

The catalogue pairs them explicitly:

| Population | Decision-conditional | Attempt-level |
| --- | --- | --- |
| PLAIN SELF | `plain_self_match_rate_decided` | `plain_self_match_rate_attempt` |
| ROLL SELF | `roll_self_match_rate_decided` | `roll_self_match_rate_attempt` |
| Mated, unconditional | `plain_roll_mated_unconditional_fnmr_decided` | `plain_roll_mated_unconditional_non_success_rate_attempt` |
| Mated, SELF-conditional | `plain_roll_mated_conditional_fnmr_decided` | `plain_roll_mated_conditional_non_success_rate_attempt` |
| Negative sanity | `plain_roll_non_mated_sanity_match_rate_decided` | `plain_roll_non_mated_sanity_match_rate_attempt` |

The names carry the distinction: `_decided` and `_attempt` are suffixes on every metric
id, not adjectives in a caption.

**The attempt-level genuine metric is not called an FNMR.** `NON_MATCH + UNDECIDABLE` over
all attempts is an operational non-success rate. Calling it FNMR without a qualifier
would put a failed JVM into a quantity the literature reserves for a matcher's decisions.
`MetricNumerator.NON_SUCCESS` exists for exactly this sum and is defined nowhere else.

**`NON_SUCCESS` is refused over impostor populations.** For a mated comparison, a
non-match and a failure both mean "this finger was not recognised". For an impostor
comparison, a failure is not a near miss and their sum is not a quantity anyone can
interpret. `resolve` raises rather than computing it.

The report's operational section prints the undecidable counts beside every population,
so a reader can see for themselves that the two rates coincide *because nothing failed*
rather than because they are the same metric.

## Alternatives

**Report only the decision-conditional rate, with a failure count in a footnote.** This is
the common convention and it is where "we exclude failures to acquire" comes from. It
makes the operational answer unavailable to anyone who does not recompute it, and
footnotes do not survive into slides.

**Report only the attempt-level rate.** Conflates an algorithm's discrimination with an
integration's reliability. A matcher would be penalised for a container that ran out of
memory.

**One metric with a configurable failure policy.** The policy would live in a config
file, the number would keep its name across a change to it, and two reports with the same
metric id would mean different things. This is the failure ADR 0026 is about, wearing a
different hat.

**Emit the second only when failures exist.** A metric that appears and disappears is a
metric whose absence looks like a zero.

## Consequences

* Fourteen metrics rather than eight, and every table has two rate columns.
* In this run the paired values are numerically identical, and the report says why.
* A future run with extraction failures will show the two diverging, which is the
  signal the separation exists to preserve.
* `UNDECIDABLE` never enters a `_decided` denominator and always enters an `_attempt`
  one — checked per metric by re-resolving the enum, not by inspection.
