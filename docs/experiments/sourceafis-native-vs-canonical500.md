# The native versus canonical 500 ppi paired comparison

`configs/comparisons/sourceafis_native_vs_canonical500_v1.yaml`

## What it is

The third artefact of stage 6B, and the only one that mentions both runs. The
first two — the canonical decision set and the canonical metric set — are
standalone: each describes one chain and never looks at the other. This one
joins them, pair by pair, on `pair_id`.

It is a separate artefact with its own identity rather than a section appended
to either report, because a comparison is a claim about two things and can be
wrong in ways neither input is (docs/adr/0036). Deleting it leaves both
evaluations intact and still publishable.

## What it may say

Transitions and exact rate differences. Nothing else.

- Three-valued transition matrices (MATCH / NON_MATCH / UNDECIDABLE) for PLAIN
  SELF, ROLL SELF, unconditional mated, common-eligible mated and negative
  sanity, per release and pooled.
- The SELF eligibility transition matrix.
- Score-direction counts: how many comparisons scored lower, equal or higher on
  the canonical side. Counts only — no mean, no median, no distribution.
- Each rate as the two integers it was computed from, on both sides, with the
  difference as an **exact reduced fraction** where one is legitimate.

## What it may not say

No ROC, no EER, no significance test, no confidence interval, no bootstrap, no
McNemar. No general or population false-match rate. No claim that one resolution
is better than another, and no causal claim of any kind. The report's closing
section states all of this in its own words, and the policy at
`configs/comparisons/policies/sourceafis_native_vs_canonical500_paired_v1.yaml`
refuses to load if it is edited to permit any of them.

The comparison also isolates a **preparation pipeline**, not a resolution. The
canonical path resamples externally to 500 ppi before SourceAFIS sees anything;
the native path hands SourceAFIS the delivered image and lets it deal with the
ppi itself. Those are two pipelines, not two resolutions of one pipeline.

## The subtraction rule

Two rates may be subtracted only when their denominators cover the same rows.
This is the single most load-bearing rule in the stage, so it is enforced by the
model rather than by a footnote: every observation stores a
`ComparabilityStatus`, and `PairedRateObservation` refuses to be constructed
with a difference when that status is `DIFFERENT_SELECTION` or `UNDEFINED`
(docs/adr/0038).

That is why the report carries two mated FNMRs. The **common-eligible** one is
conditioned on the 1,468 units both runs found eligible and is subtractable. The
**per-run conditional** one is conditioned on each run's own eligible set — 1,468
against 1,472 — and prints `not comparable` in the difference column, because
the two numbers describe different populations of fingers.

## The SD300A control

SD300A is delivered at 500 ppi, so its canonical preparation is an identity: the
same pixels, through the same build, at the same threshold. Every one of its
2,000 comparisons must therefore reproduce exactly — equal raw score, equal
result status, equal decision, with no rounding tolerance anywhere.

This is a hard acceptance condition, not a diagnostic. `derive` and `finalize`
both abort on a single mismatch, before any aggregate is written. A comparison
whose control failed cannot be finalised at all, because if identical input did
not reproduce, nothing downstream of it means what it says.

## Running it

Every id in the config is pinned exactly — ten of them, five per side. There is
deliberately no "latest": a comparison that resolved its own inputs would
silently become a different comparison the next time either chain was
re-derived, while continuing to cite the same evidence file.

The paired evaluation id is derived from the derivation commit, so `prepare`,
`derive` and `finalize` must all run against the same committed tree. Committing
between them produces a new definition and a new comparison.

```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 prepare
```
```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 derive
```
```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 status
```
```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 finalize
```
```bash
python -m fpbench.experiments.sourceafis_native_vs_canonical500 show
```

`finalize` re-derives the whole comparison from the two chains and compares it
against what is stored, rather than checking the stored artefacts for internal
consistency. The report is re-rendered and required to be byte-identical. The
finalization marker is written last, after the receipt has been re-derived and
re-verified.

## What is published

Two files under `evidence/sourceafis-native-vs-canonical500/`, written
byte-identically or not at all: the sanitised JSON receipt and the Markdown
report.

The receipt carries identities, the control audit's counts, the aggregate
transition counts and each rate as an integer pair. It may not carry a pair id,
a job id, a subject, a finger, an image id, a filename, a path, a raw score, a
per-pair delta or a template — half of that is dataset inventory, and the rest
is the raw material of exactly the per-pair narrative this stage refuses to
tell. `require_sanitised_paired_receipt` checks this rather than trusting the
builder, and runs again before either file is written.

## What stays in the workspace

The per-pair table itself: 6,000 rows, each with both job ids, both result
hashes, both decision hashes, both outcomes, the score relation and the exact
decimal delta. It is the evidence the aggregates were computed from and it is
verified on every read, but it is not committed and it is not published.
