# Final-baseline execution and reporting runbook

Audience: the operator of the machine that holds the workspace, SD300, the
built adapter runtimes and the licences. Goal: produce
`evidence/final-baseline-tar-far-frr/final-baseline-report.md` — the
frozen six-method TAR/FAR/FRR comparison that says which baseline performed
best at FAR ≤ 1%, 0.1% (primary) and 0.01%.

One command always tells you where you are and what to do next:

```bash
python scripts/final_baseline_pipeline.py status
python scripts/final_baseline_pipeline.py next
```

Trust the stages' own refusals. Every error message names the broken
precondition; nothing is retried blind, everything is resumable. Never edit
anything under `evidence/`, never delete anything under `workspace/`.

## 0. Preconditions (five minutes)

1. Project environment active (the same one that ran stages 7–20;
   `environment.yml` pins it — Python 3.11+, pyarrow, PyYAML, openjdk 17).
2. `git pull` this branch; `git status` must be **clean** — Stage 21B refuses
   to run over an uncommitted tree.
3. `FPBENCH_SD300_ROOT` set as for previous stages.
4. Verify the frozen protocol on THIS machine:

   ```bash
   python scripts/stage21a_freeze.py --verify
   ```

   If it fails with "source fingerprint no longer describes tree", one file is
   a stale CRLF checkout from before its `.gitattributes` pin. Fix is local
   and safe — re-smudge the named file, for example:

   ```bash
   rm configs/protocols/sd300_50_subjects.yaml && git checkout -- configs/protocols/sd300_50_subjects.yaml
   ```

   then verify again. Nothing committed changes.

## 1. Adapter configs (once, machine-local, never committed)

Each of the six Stage 21B runs takes `--adapter-config <file>`: a small JSON
envelope around the exact adapter configuration this machine already used for
the algorithm's legacy canonical run:

```json
{
  "schema_version": "1",
  "algorithm_id": "<roster id>",
  "adapter_id": "<adapter id from the roster>",
  "adapter_config": { "...the same keys the legacy run's adapter used..." }
}
```

Roster ids → adapters (from `evidence/stage21a-…/baseline-roster.json`):

| algorithm_id | adapter_id |
|---|---|
| `sourceafis_java` | `sourceafis_java_subprocess` |
| `nbis_mindtct_bozorth3` | `nbis_mindtct_bozorth3_subprocess` |
| `flx_deepprint_texminu_512_without_localization` | `flx_pytorch_subprocess` |
| `verifinger_1to1` | `verifinger_java_subprocess` |
| `nbis_mindtct_mcc_sdk_v2` | `nbis_mindtct_mcc_sdk_v2_subprocess` |
| `nbis_mindtct_openafis_capacity_extended` | `nbis_mindtct_openafis_capacity_extended_subprocess` |

Keep these files **outside git** (e.g. `workspace/private/adapter-configs/`)
— they contain machine paths; Stage 21B never publishes them. Then write one
mapping file for the pipeline, e.g. `workspace/private/adapter-configs.yaml`:

```yaml
sourceafis_java: workspace/private/adapter-configs/sourceafis.json
nbis_mindtct_bozorth3: workspace/private/adapter-configs/nbis.json
flx_deepprint_texminu_512_without_localization: workspace/private/adapter-configs/flx.json
verifinger_1to1: workspace/private/adapter-configs/verifinger.json
nbis_mindtct_mcc_sdk_v2: workspace/private/adapter-configs/mcc.json
nbis_mindtct_openafis_capacity_extended: workspace/private/adapter-configs/openafis.json
```

Do not guess the inner `adapter_config` keys: run the preflight and let it
tell you what is missing or wrong —

```bash
python scripts/stage21b.py preflight --algorithm sourceafis_java --adapter-config workspace/private/adapter-configs/sourceafis.json
```

Repeat per algorithm until every preflight prints a clean report. Preflight
writes nothing.

**VeriFinger first.** `verifinger_1to1` needs the activated licence and the
running Neurotechnology licensing service, exactly as Stage 11B did, for the
whole run — at Stage 11B's measured 2–4 s per comparison, 73,500 comparisons
is roughly two to three days of wall clock. Start it before the slower-burning
trial clock becomes a problem, and keep the machine online. The other five
routes are much faster.

## 2. Execute the six cross-subject runs (Stage 21B)

Either let the pipeline drive everything that remains:

```bash
python scripts/final_baseline_pipeline.py run --adapter-configs workspace/private/adapter-configs.yaml
```

or run algorithms individually (same thing, finer control):

```bash
python scripts/stage21b.py run --algorithm sourceafis_java --adapter-config <file>
```

Facts that matter while this runs:

- **Resumable.** Stop anything, rerun the same command; finished pairs are
  verified and skipped, never recomputed. A recorded algorithm failure stays.
- **Trial slice.** `run --limit 50` executes 50 pairs and leaves the run
  incomplete — use it to validate a route before committing days to it.
- **Two algorithms may run in parallel terminals** (they use disjoint run
  directories); never start the same algorithm twice at once.
- **Do not commit anything while runs are executing** — the runs are bound to
  the source revision they were prepared under.
- Progress lines show counts and timings only; no score values are printed.
  That is by design (scores may only be read by final-baseline reporting).

When all six show `SEALED` in `status`, publish the receipts:

```bash
python scripts/stage21b.py alignment
python scripts/stage21b.py publish
```

The repository's publication-registry contract requires every evidence
directory with a finalization marker to have a registry row. Stage 21B is
registered in `src/fpbench/experiments/publication_registry.py`, which extends
the registry frozen by Stage 21A. Keep `stage_registry.py` unchanged: its bytes
are signed by Stage 21A and bound into all six Stage 21B runs. The extension
contains:

```python
    PublishedStage(
        "21B",
        "evidence/stage21b-cross-subject-baseline-expansion",
        "stage-21b-finalization.json",
        "outcome",
        readme_heading="## Stage 21B",
    ),
```

Then commit and verify:

```bash
git add evidence/stage21b-cross-subject-baseline-expansion src/fpbench/experiments/publication_registry.py
git commit -m "Publish the Stage 21B cross-subject raw-result receipts"
python scripts/stage21b.py verify
python -m pytest tests/contract/test_stage_registry.py -q
```

## 3. Produce the final report

```bash
python scripts/final_baseline.py preflight     # re-verifies every score source; writes nothing
python scripts/final_baseline.py evaluate      # prints the pooled primary ranking (no evidence written)
python scripts/final_baseline.py publish --source-tree-clean-attested
```

Then commit, verify and push:

```bash
git add evidence/final-baseline-tar-far-frr
git commit -m "Publish the final baseline TAR/FAR/FRR report"
python scripts/final_baseline.py verify        # must pass on the committed tree
python -m pytest tests/unit/test_final_baseline_evaluation.py -q
git push
```

`publish` requires the tree to be clean and committed first (that is what the
attestation flag asserts); if you changed anything, commit before publishing.

## 4. What "done" looks like

- `python scripts/final_baseline_pipeline.py status` shows stages 21A and 21B
  verified and the final report published.
- `evidence/final-baseline-tar-far-frr/final-baseline-report.md`
  holds the requested result: per release and pooled, every method's
  observed TAR/FRR at FAR ≤ 1%, 0.1% (primary) and 0.01%, ranked by TAR with
  ties broken by roster order — plus the secondary common-score view, the
  contextual native-rule table (SourceAFIS ≥ 40, NBIS > 40), and the frozen
  disclosures. The pooled primary-target table is the headline answer to
  "which model did the best job".

## 5. Troubleshooting

| Symptom | Meaning / action |
|---|---|
| `Stage 21B refused: … working tree` | Commit or stash; the tree must be clean before preflight/run. |
| Preflight names a missing runtime asset | The adapter config points at the wrong path, or the runtime (NBIS build, FLX bundle in WSL, SDK jar/DLLs) moved. Fix the path; nothing was written. |
| VeriFinger run stops with licence errors | Licensing service stopped or trial lapsed. Restart the service / reactivate, rerun the same command — the run resumes. |
| A few `ALGORITHM_FAILURE` rows appear | Expected for some routes (the legacy runs had e.g. 81 VeriFinger extraction failures). Failures are recorded, kept in denominators, and never retried. |
| `alignment` refuses | The six runs disagree about the planned pairs — do not work around this; read the message, it names the run to inspect with `stage21b.py integrity`. |
| `final-baseline reporting refused: … sealed Stage 21B <field> does not match the verified Stage 21B publication` | The workspace holds a sealed run that differs from the published receipts (e.g. a superseded rerun). Use `stage21b.py supersede`/`publish` so evidence and workspace agree. |
| Any verifier fails on "source fingerprint" | Stale line-ending smudge — see step 0.4. |
