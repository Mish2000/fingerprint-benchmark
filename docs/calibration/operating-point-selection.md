# Operating-point selection

How one boundary is chosen, exactly, from labelled development scores.

## The rule

> Of the boundaries whose observed impostor match rate does not exceed the
> target, take the one that admits the most impostor evidence.

That is the entire objective. It is fixed before any score is read, and there is
no second one: genuine performance at the chosen boundary is *measured* and
recorded, never searched over. A selector that tried many rules and kept the one
with the best FNMR would be fitting the development set rather than applying a
policy to it (docs/adr/0080).

Everything in the selection is defined over the impostor population: the
candidates, the admissibility test, the permissiveness ordering and the
tie-break. The mated population is read exactly once, at the end, to count what
the chosen boundary does to it.

## Step by step

1. Refuse the inputs, if they are refusable — role first, then protected
   identities, then the binding's agreement with the results, then the required
   populations. All of this happens before a score is read.
2. Build every candidate boundary the observed scores can express.
3. Count, for each, how many impostor comparisons it would call a match.
4. Discard every candidate whose rate exceeds the target.
5. Of what remains, take the most permissive.
6. If two survivors produce *literally the same decisions*, take the canonical
   one: inclusive comparator first, then Decimal ordering of the threshold.

## Candidates come from the impostor data

For a higher-is-better matcher, and for each distinct score `s` that a **scored
cross-subject impostor** comparison produced:

```
score >= s
score >  s
```

and for a lower-is-better matcher:

```
score <= s
score <  s
```

**Mated scores generate no candidate.** A value that only a genuine comparison
ever produced cannot become a threshold, because a boundary standing there was
placed by the population the rule is not allowed to optimise for. This is not a
hypothetical — see *One objective* below.

That family is **closed over the quantity being constrained**: `>= min` admits
every impostor and `> max` admits none, so both extremes of the impostor rate are
reachable without inventing a number no comparison ever produced. A boundary
*below* the lowest impostor score is deliberately unreachable: the only reason to
move there is to admit more mated comparisons.

The alternative — placing a boundary "just above `0.4`" by adding an epsilon — is
a scale assumption. `0.4 + 1e-9` is a different boundary on a `[0, 1]` scale than
on a `[0, 10000]` one, and on some scales it is not a different boundary at all.
Algorithms 4 and 5 are not yet identified and neither are their scales.

## One objective

Both sides below share impostors `1, 2, 3, 4` under a ceiling of one in four, so
`>= 4` admits one impostor and `>= 3` admits two:

| mated scores | correct answer | what a selector drawing candidates from *all* scores did |
|---|---|---|
| `5, 6, 7` | `>= 4` | `>= 4` |
| `2.5, 3.5, 100` | `>= 4` | `>= 3.5` |

`3.5` is a number no impostor comparison ever scored. It won because it admitted
the same single impostor as `>= 4` while accepting one more *mated* comparison,
which made it look more permissive. The genuine population had chosen the
threshold.

Restricting the candidates fixes half of it; the permissiveness ordering has to be
restricted too, or a mated score can still break a tie between two boundaries that
admit identical impostor evidence.

## Rates are exact integers

A target is a numerator and a denominator, never a float. Every comparison of two
rates is a cross-multiplication over Python's unbounded integers:

```
a/b <= c/d      is evaluated as      a*d <= c*b
```

This is not fastidiousness. With a target of one in three and ten thousand
impostor comparisons, the boundary that admits 3,333 satisfies it and the one
that admits 3,334 does not — and in binary floating point those two comparisons
can come out the same. `0.001` is also not one thousandth.

Targets are reduced to lowest terms, so `1/1000` and `2/2000` are one protocol
with one fingerprint. Observed counts are reduced nowhere: one impostor match in
a thousand comparisons is not two in two thousand, and an operating point records
both numbers as counts.

A target is bounded by `[0, 1]`. `0/1` (admit no impostor) and `1/1` (admit every
impostor) are both legal; `5/4` is refused, because it constrains nothing.

## The comparator is half the answer

An operating point carries a threshold **and** a comparator, because `>= 40` and
`> 40` disagree about every comparison that scored exactly 40. This is the same
distinction docs/adr/0055 forced into `DecisionProfile` schema 2 — SourceAFIS
documents "at least 40" and NIST documents "greater than 40", and reading either
as the other moves a boundary nobody moved.

```
threshold  = "40"        threshold  = "40"
comparator = GE          comparator = GT
```

are two different rules, and the calibration layer produces both.

## Ties are atomic

Because a boundary decides a *value*, comparisons with equal scores always
receive equal decisions. There is no random tie-breaking and no ordering by
`pair_id`.

The visible consequence is undershoot. Impostor scores `0.4, 0.4, 0.4, 0.7, 0.7`
under a ceiling of one in five:

| candidate | impostor matches | rate | inside 1/5? |
|---|---|---|---|
| `>= 0.4` | 5 | 5/5 | no |
| `>  0.4` | 2 | 2/5 | no |
| `>= 0.7` | 2 | 2/5 | no |
| `>  0.7` | 0 | 0/5 | yes |

so the answer is `> 0.7` and it admits nothing. One match in five would have
satisfied the ceiling and no boundary produces one.

Note what is *not* in that table. If the mated comparisons scored `0.9`, `>= 0.9`
is not a row: 0.9 is a mated-only value, and a threshold standing there would
have been placed by the genuine population.

## Two names for one threshold

Over impostor scores `{0.4, 0.7}`, the boundaries `>= 0.7` and `> 0.4` admit
exactly the same impostor. They are one threshold with two spellings, and the
canonical one is the inclusive form. This is a naming rule, not a decision rule:
whichever is chosen, every impostor is decided identically. It exists so that the
operating point has a stable identity.

The mated population is not consulted in the tie-break either. A rule that
preferred whichever spelling admitted more genuine comparisons would be a second
objective wearing a naming rule's clothes.

Exactly one inclusive boundary represents each non-empty accepted impostor set,
so the second tie-break key — Decimal ordering — is defensive rather than
load-bearing.

## Failures are not non-matches

A comparison that produced no score cannot be thresholded. It is:

* **excluded** from the candidate counting and from the target rate, and
* **recorded** in the operating point, separately, in three layers:

```
mated_attempts     = mated_scored     + mated_failures
impostor_attempts  = impostor_scored  + impostor_failures
mated_scored       = mated_matches    + mated_non_matches
```

The target rate is defined over *scored* comparisons, and the protocol says so in
a field (`target_population`) rather than leaving it to be inferred. A rate whose
denominator is implied is a rate nobody can check (docs/adr/0006,
docs/adr/0027).

An impostor population in which *every* comparison failed is refused outright. A
rate over an empty population is not a small rate; it is not a rate.

## No quality filtering

`quality_filtering` is `false` in v1 and a protocol that sets it true is refused.
Letting each algorithm discard the development prints it happens to find hard
would give each one a different development population under one protocol name,
and the protocol's whole purpose is that the population is shared. A
quality-aware calibration would be a new protocol, not a flag on this one.

## Determinism

The same fixture produces the same threshold, the same comparator, the same
counts and the same fingerprint after:

* an arbitrary reordering of the input rows — counting runs over a set of
  distinct values, and the tie-break is a fixed rule;
* a process restart — nothing is seeded, sampled or timed;
* a JSON round trip — scores and thresholds are written as strings and read as
  `Decimal`, so nothing passes through a double.

The operating-point fingerprint excludes its own id and `created_utc`, and
contains no path and no hostname. The same selection, run on two machines, is one
operating point.

## Verification re-derives

`verify_operating_point` does not read the stored answer back and compare it to
itself. It re-runs the whole selection from the labelled scores the operating
point cites and compares the threshold, the comparator, every count and the
identity.

Two kinds of disagreement are kept apart:

* the documents **do not belong together** — a different protocol, a different
  source binding — which raises, because there is nothing to verify against;
* the documents **disagree** — re-derivation produced a different answer — which
  is returned as a report with findings, because a qualification needs to say
  what disagreed.
