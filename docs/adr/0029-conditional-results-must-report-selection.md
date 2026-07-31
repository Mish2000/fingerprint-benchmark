# 0029 — A SELF-conditional result is published only with its selection fraction

## Status

Accepted. Implemented in `ConditionalOutcomeCounts` and enforced by the metric policy
loader's refusal of `retain_exclusion_reasons: false`.

## Context

[ADR 0024](0024-conditional-mated-evaluation-requires-both-self-matches.md) fixed the
conditional view: the same 1,500 mated comparisons, included only where the finger passed
both SELF tests, with the excluded rows kept in the file so the rule stays auditable.

Publishing a rate over that view raises a problem the view itself does not have. Consider:

> Under SELF-conditional reporting, the mated non-match fraction was 1/1,480.

It reads as a strong result. It is uninterpretable. The same sentence is true, and means
something completely different, if the conditional set held 12 comparisons instead of
1,480 — and a reader has no way to tell which, because the number that would tell them is
in a different table, or a different file, or nowhere.

The failure mode is worse than mere incompleteness, because the two numbers move
together. A stricter SELF condition removes exactly the fingers most likely to fail the
mated comparison, so the conditional rate improves *by construction* as the selection
shrinks. A conditional result without its selection fraction is a knob that makes any
matcher look arbitrarily good.

And the exclusions are not one category. A finger excluded because a SELF comparison
returned `NON_MATCH` is a measured failure. A finger excluded because a SELF comparison
crashed is an absence of measurement. Collapsing them would repeat, one layer up, the
error [ADR 0006](0006-self-failure-semantics.md) exists to prevent.

## Decision

**A conditional result is published together with its selection fraction and both
exclusion counts, or it is not published.**

`ConditionalOutcomeCounts` holds all of it in one record — `total_rows`, `included_count`,
`excluded_ineligible_count`, `excluded_undetermined_count`, and the outcome breakdown of
the included rows — with invariants tying them together. There is no way to obtain the
conditional outcomes without also having the selection.

`plain_roll_mated_conditional_selection_rate` is a metric in its own right, with
denominator `ALL_ATTEMPTS` over the conditional family: included rows over *all* mated
rows. It is the only denominator in the stage that spans excluded rows, and that is
deliberate — it is the number that says how much of the population survived.

The policy file carries `retain_exclusion_reasons: true`, and the loader **refuses the
file** if it is false. It is a refusal rather than a setting.

The report's conditional table carries eleven columns — total rows, included, both
exclusion counts, the three included outcomes, and all three rates — so the selection and
the result cannot be separated by copying a row.

**The report may show the unconditional and conditional results side by side, and may not
call the difference an improvement.** Section 7 says so in the prose: "A conditional rate
over a different population is a different measurement from the unconditional one above
— not the same measurement improved."

## Alternatives

**Publish the conditional rate with the selection in a footnote.** Footnotes do not travel.
The number does.

**Publish only the unconditional result.** Discards the supervisor's protocol, which asks
for both, and discards a genuinely useful question: how does the matcher do on prints it
can at least recognise as themselves?

**Drop the excluded rows from the view.** Smaller, tidier, and unauditable. "Which pairs
did you leave out?" is the first question a reviewer asks.

**Merge the two exclusion reasons.** Would report a crashed comparison as a finger that
failed, which is the one error this project has been most careful about.

## Consequences

* The conditional table is the widest in the report, and every column in it is load-bearing.
* A conditional rate over an empty included set renders as
  `undefined (0 included decided attempts)` rather than as `0.0000%` — an empty selection
  is a reportable outcome, not a perfect score.
* Comparing the two mated results is possible and explicitly framed as a change of
  population.
* No causal or superiority claim is made between them in stage 5B, and the report says so
  in section 10.
