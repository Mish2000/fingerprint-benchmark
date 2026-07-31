# Canonical 500 ppi SourceAFIS run receipts

One committed file per canonical run, named by its `run_id`.

## What a receipt proves

Execution completeness and provenance: the same 6,000 comparisons as the native
run, over a named and fingerprinted canonical input set, with a pinned SourceAFIS
runtime and a clean committed fpbench revision. It records how many results were
stored, how many scored, how many were algorithmic failures, and the structural
counts by release and by protocol stage.

## What a receipt deliberately does not contain

No raw score. No MATCH or NON_MATCH. No SELF eligibility. No metric. No
native-versus-canonical difference. No subject, image or pair id. No path. No
template.

## What a receipt does not claim

That the canonical run's scores are better than, worse than, or the same as the
native run's. Stage 6A applies no threshold, computes no metric, reads no native
score and produces no paired conclusion. It establishes that 6,000 scores exist
over inputs whose identity is provable — which is what stage 6B needs in order to
ask the question honestly.

The related preparation receipt, under `evidence/sd300-canonical500-images/`,
proves the input set those scores were produced from.
