# NBIS 5.0.0 over the canonical SD300 comparisons — raw-score evidence

Stage 7C. Experiment `nbis_canonical500_full_v1`.

The certified NBIS route — MINDTCT 5.0.0 into BOZORTH3 5.0.0 — run over exactly
the 6,000 comparisons and the 3,000 prepared 500 ppi images the canonical
SourceAFIS run `run_4c59fa02a6ab` was given.

## Files

| file | what it is |
| --- | --- |
| `research-receipt.json` | the sanitised proof of execution completeness and provenance |
| `research-finalization.json` | the immutable marker that the whole chain was re-verified |
| `stage-7c-finalization.json` | the last-written marker binding alignment to the research chain |
| `alignment-report.json` | the row-by-row proof that the inputs were the reference run's |
| `runtime-provenance.json` | the pinned runtime assets, build identity and reference chain |
| `operational-summary.json` | timings, counts and failure codes — no score statistic |
| `<run_id>.json` | the receipt again, under the name the engine publishes it by |

## What the evidence proves

That 6,000 comparisons were carried out by a named, certified build of a named
matcher, over a named and fingerprinted input set, from a clean committed
revision of this harness — and that the pairs and the prepared images were, field
by field, the ones the reference run used.

The alignment report is the part that is new at this stage. It compares:

* the two ordered pair-id sequences, position by position;
* every pair's release, protocol stage, ground truth, left image and right image;
* every prepared image's source digest, encoded digest, pixel digest, output
  width, height and resolution, transform action and entry fingerprint.

`is_clean` is true only at 6,000/6,000 pair ids, 6,000/6,000 pair semantics and
3,000/3,000 prepared entries with no issue. An alignment of all but one is a
failure (docs/adr/0051).

The complete expected experiment shape is inside alignment fingerprint
`d25b52159d251c2998bc55577d2e40f7a287d869b134dbe6aabbd3a3baa91686`.
`stage-7c-finalization.json` binds that fingerprint and the complete report
content hash to the run, result set, research receipt, research finalization and
reference identities. Its verifier commit is on `main`; the code that produced
the raw run remains reachable as Git ref `stage7c-run-source`.

## What the evidence deliberately does not contain

No raw score. No MATCH or NON_MATCH. No threshold. No SELF eligibility. No
metric. No mean, median or distribution of scores. No comparison with the
SourceAFIS scores. No subject, image or pair id. No path. No template, minutiae
list or XYT.

## What it does not claim

Nothing about which algorithm is better. SourceAFIS scores and BOZORTH3 scores
are numbers on two unrelated scales; they must not be subtracted, correlated or
thresholded against each other, and nothing here does
(docs/adr/0052).

What may be said about this run is:

> NBIS was run over the same 6,000 pair IDs and the same canonical prepared image
> set used by the canonical SourceAFIS run.

## Related evidence

* `evidence/sd300-canonical500-images/` — the input set these scores were
  produced from.
* `evidence/sourceafis-canonical500-full/` — the reference run whose comparisons
  these are.
* `integrations/nbis/README.md` — how the build was pinned, made and certified.
* `docs/experiments/nbis-canonical500-raw.md` — the full procedure.
