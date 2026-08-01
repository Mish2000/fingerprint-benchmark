# Native versus canonical 500 ppi paired comparisons

One JSON and one Markdown file per paired comparison, named by its
`paired_evaluation_id`.

The current hardened comparison is `pairedeval_ba790ca1e900` (schema 2), derived
from source commit `d000fb1d9f0f23ed3a96fe5ec7e89e3fc41aa13a`. Schema 2 binds
each row to the exact execution status and failure code on both sides. Ready
status is granted only after the stored policy and every publication artefact
have been rebuilt from both source chains and compared with the frozen files.
The earlier schema-1 comparison remains here as historical evidence.

## What these prove

That the same 6,000 comparisons were run twice under two image preparation
paths, joined pair by pair on `pair_id`, and that everything that moved between
them is reported as a transition count or an exact rate difference — never as a
verdict.

The SD300A control is the load-bearing one. SD300A arrives at 500 ppi, so its
canonical preparation is an identity: the same pixels, the same build, the same
threshold. All 2,000 of its comparisons reproduced exactly — equal score, equal
status, equal decision, with no rounding tolerance. A comparison whose control
failed cannot be finalised, so a receipt in this directory is also a statement
that the control held.

## What these are not

Not a statement that 500 ppi is better or worse than 1000 or 2000 ppi. Not a
statement that downsampling helps or harms. Not a causal claim about resolution
— the canonical path changes the entire preparation pipeline, not only the
resolution (docs/adr/0036).

No ROC, no EER, no significance test, no confidence interval. No general or
population false-match rate; the negative set here is closed-set and
same-subject, which is a sanity check and nothing more (docs/adr/0030).

## Reading the rates

Every rate appears as the two integers it was computed from, and every
difference as an exact reduced fraction. A difference appears only where both
sides covered the same rows.

Where they did not, the difference column says `not comparable` and means it.
The per-run conditional mated FNMR is the case to look at: 460/1468 against
493/1472 is two rates over two different populations of fingers, and subtracting
them would produce a number that describes nothing. The common-eligible mated
FNMR immediately above it is the fair comparison, over the 1,468 units both runs
found eligible (docs/adr/0038).

## What is not here

No pair id, job id, subject, finger, image id, filename, path, raw score or
per-pair delta. The 6,000-row per-pair table those aggregates were computed from
stays in the workspace, where it is verified on every read and published to
nobody.
