# Final baseline TAR/FAR/FRR report

Final-baseline reporting is the reporting boundary of the comparison. It
reads the six accepted legacy plain↔roll mated result sets (identities sealed by
Stage 21A) and the six sealed Stage 21B cross-subject result sets — every hash
re-derived from the stored bytes — and publishes the report Stage 21A froze
before any cross-subject score existed: observed TAR, FAR and FRR at the
predeclared FAR targets 1%, 0.1% (primary) and 0.01%, per release and pooled,
for the primary all-attempt view and the secondary common-score view, plus the
separate native-documented-rules context table.

It creates no operational threshold, calibrates nothing, normalizes nothing,
interpolates nothing, and never compares a raw score across algorithms. A
score cut appearing in the report is an observed reporting boundary on one
algorithm's own scale, never an execution parameter.

## Evidence map

- `evaluation-inputs.json` — every verified identity the report reads: both
  predecessor finalization fingerprints, the twelve result-set identities,
  manifest hashes, config digests and operational counts
- `tar-far-frr-results.json` — the complete numeric results: both views, all
  scopes, all targets, rankings under the frozen ranking rule
- `native-documented-rules-context.json` — the contextual table's numbers
- `final-baseline-report.md` — the rendered report; the verifier re-renders it
  from the committed JSON and requires byte equality
- `final-baseline-finalization.json` — all-or-nothing PASS marker, written last

Operate it:

```bash
python scripts/final_baseline.py preflight
python scripts/final_baseline.py evaluate
python scripts/final_baseline.py publish --source-tree-clean-attested
python scripts/final_baseline.py verify
```

`verify` needs no workspace, dataset, runtime or score store.
