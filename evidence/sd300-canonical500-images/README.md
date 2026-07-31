# Prepared-image set receipts

One committed file per canonical input set, named by its `preparation_set_id`.

## What a receipt proves

That a shared canonical input set was materialised and verified: which transform
profile produced it, which pinned resampler evaluated that profile, which
dataset, cohort and pair manifest it covers, how many images it holds, how they
divide by release, by source resolution and by transform action, and which
fpbench commit was running.

Anyone holding a workspace can check the receipt against it: every number here is
re-derived from the entries during verification rather than believed.

## What a receipt deliberately does not contain

No image id, subject id, finger id, filename, relative path, per-image hash or
per-image dimension.

SD300 is redistribution-restricted — the delivery's own README requires users to
"adhere to all terms agreed to upon obtaining SD 300" — and a list of 3,000 image
ids is an inventory of it. The absence is enforced by
`fpbench.experiments.preparation_receipt.require_sanitised_receipt`, which
refuses to write a receipt carrying any of them, rather than being left to
whoever edits the builder next.

## What a receipt does not claim

Nothing about accuracy, resolution or any comparison. A canonical set is an
*input*. It proves every algorithm evaluated under it was handed the same pixels;
what that did to any score is a different stage's question.
