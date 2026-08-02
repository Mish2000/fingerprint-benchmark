# NBIS 5.0.0 — MINDTCT into BOZORTH3

The second algorithm in this benchmark. One route, one identity, no options.

```
canonical gray8 PNG at 500 ppi
        ↓  byte-for-byte copy
     MINDTCT 5.0.0            (no -b, no -m1)
        ↓  XYT: x y theta quality, one minutia per line
     BOZORTH3 5.0.0           (no options at all)
        ↓
   one non-negative integer
```

| | |
|---|---|
| `algorithm_id` | `nbis_mindtct_bozorth3` |
| `adapter_id` | `nbis_mindtct_bozorth3_subprocess` |
| `adapter_version` / contract | `1` / `1` |
| `implementation_version` | `5.0.0` |
| score direction | higher is better |
| deterministic | yes, proved on the build |
| input | 8-bit greyscale PNG, effective 500 ppi |
| runtime assets | `mindtct`, `bozorth3`, `nbis-build-manifest.json` |
| certified platform | Linux x86_64 |

## Why the whole route is one identity

MINDTCT decides what a minutia is, where it is, which way it points and how
reliable it is. BOZORTH3 compares two lists of those. Almost every decision that
could move a score is made by the extractor, and a descriptor labelled `bozorth3`
would let two runs against different MINDTCT builds share an identity — and every
artefact derived from it — while comparing different templates
(docs/adr/0046, docs/adr/0014).

The runtime bundle carries **three** files for the same reason. Either executable
can change a score, and the build manifest is what says those executables are the
ones NIST's own tests were run against (docs/adr/0042).

## Why canonical 500 ppi only

MINDTCT's spatial parameters are fixed pixel counts; a resolution value reaches
the computation late, where it scales minutia reliability rather than rescaling
the analysis. So the same finger at 500 and at 2000 ppi is not one experiment at
two scales — it is two analyses of two rasters.

And the certified build **ignores the PNG's declared resolution**: three images
with identical pixels and `pHYs` chunks saying 500, 1000 and nothing at all
extract to byte-identical XYT. That is measured by `build.py test` and re-measured
by the upstream test suite; if it ever comes out differently the stage stops
rather than the policy being written from memory (docs/adr/0047).

Native SD300B and SD300C are therefore **not supported by this route in v1**. The
comparison this project can make is over the shared canonical 500 ppi input set,
which is what stage 6A built it for. See
[nbis-input-and-ppi-policy.md](../architecture/nbis-input-and-ppi-policy.md).

## Why the PNG is copied and not converted

Most NBIS pipelines begin by converting to WSQ or PGM. Every conversion is a place
where the experiment changes without saying so — WSQ is lossy, a PGM round-trip
depends on a library version, a greyscale conversion depends on whose
coefficients were used. NBIS 5.0.0 reads PNG directly, and this project verifies
that on the build before relying on it.

So the prepared artefact is copied byte for byte into the job's own directory and
handed to MINDTCT unchanged, and the staged copy's digest is checked against the
prepared image's before it is used. **There is no WSQ fallback**: a build without
PNG support is not certified (docs/adr/0048).

## Why there is no `-b`, no `-m1` and no `-T`

`mindtct -b` contrast-boosts the image before extraction. A run under it is a
different algorithm, not a variation of this one: its scores are not comparable
with the stored ones and its threshold is not transferable.

`bozorth3 -T` is worse than a knob — it filters which scores are printed at all,
so a run under it is not a raw-score run. The missing rows would be
indistinguishable from comparisons that never happened.

Neither is configurable. `boost`, `m1`, `threshold`, `max_minutiae`,
`min_minutiae`, `reverse_match`, `average_directions`, `cache_templates` and
`persist_templates` are all refused as unknown configuration keys. BOZORTH3's own
defaults — 150 maximum and 10 minimum minutiae — are recorded in the identity and
never passed on a command line (docs/adr/0049).

`left` is the probe and `right` is the gallery, fixed. BOZORTH3's documentation
says its scores are not necessarily symmetric, so the reverse direction is never
run and the two are never averaged, maximised or minimised.

## Why a score of 0 is a success

BOZORTH3 returns 0 when a side has fewer than ten minutiae, and for two templates
that share no compatible structure. Neither is a failure, and neither may become
`NO_SCORE`: a comparison that produced no number did not score badly, it did not
score (docs/adr/0006).

An empty XYT is a valid template with no minutiae. MINDTCT finding nothing in a
print is a fact about the print.

What a 0 *means* biometrically is a question for the decision stage, applied later
to unchanged stored scores. There is no threshold anywhere in this route.

## Why no template is kept

Both sides are extracted independently on every comparison, including a SELF
comparison of one image against itself — SELF exists to detect the failures that
have nothing to do with cross-impression matching, and skipping an extraction
there would stop it detecting them.

Nothing survives the comparison. The two staged inputs, both XYT files and the
seven map files MINDTCT writes beside each of them are removed in a `finally`, on
success and on every failure alike. No template cache, no template store, no
published XYT — a template is a derived representation of a fingerprint, and
publishing 12,000 of them is a redistribution decision this stage has no reason to
make (docs/adr/0050, docs/adr/0041).

What is kept is `left_minutiae_count` and `right_minutiae_count`: one integer per
side.

## What a stored result records

```
pipeline=nbis_mindtct_bozorth3      mindtct_mode=default
nbis_version=5.0.0                  mindtct_contrast_boost=disabled
input_format=png                    mindtct_m1=disabled
input_depth=8                       bozorth3_mode=default_one_to_one
input_transport=byte_for_byte_copy  bozorth3_m1=disabled
effective_ppi=500                   bozorth3_threshold=none
ppi_policy=nbis_png_default_500     bozorth3_max_minutiae=150
probe_side=left                     bozorth3_min_minutiae=10

extraction_policy=independent_both_sides
template_cache=disabled
template_persistence=disabled

extraction_count=2                  (on success)
left_minutiae_count / right_minutiae_count   (once extraction completed)
```

and never a template, a minutiae list, a path, a threshold or a decision.

Timing is recorded per stage: `input_staging`, `left_extraction`,
`right_extraction`, `matching`, `cleanup` — only the stages that started.

## How a failure is recorded

| what happened | code / stage |
|---|---|
| the comparison's budget ran out | `TIMEOUT` / `TIMEOUT` |
| a tool could not be started | `DEPENDENCY_MISSING` / `ENVIRONMENT` |
| MINDTCT died on a signal | `PROCESS_CRASHED` / `EXTRACTION` |
| BOZORTH3 died on a signal | `PROCESS_CRASHED` / `MATCHING` |
| MINDTCT exited non-zero, ordinarily | `TEMPLATE_EXTRACTION_FAILED` / `EXTRACTION` |
| MINDTCT exited zero, XYT missing or unusable | `TEMPLATE_EXTRACTION_FAILED` / `EXTRACTION`, `output_kind=invalid_extractor_output` |
| BOZORTH3 exited non-zero, ordinarily | `MATCHING_FAILED` / `MATCHING` |
| BOZORTH3 exited zero without one integer | `NO_SCORE` / `MATCHING` |
| the input is not gray8 500 ppi PNG | `INPUT_INVALID` / `INPUT` |

The last two rows of the extraction pair share a code and are **not the same
event**. NBIS declining a print is data and does not block a receipt; NBIS
claiming success and writing an unreadable XYT is broken infrastructure and does.
The validator reads `output_kind` to tell them apart.

`TIMEOUT` is classified as an algorithmic outcome here rather than a defect:
MINDTCT's work is unbounded in the input, so a print it cannot finish is a
property of the print.

One shared budget covers the whole comparison — staging, both extractions and the
match — on a monotonic deadline. Three independent timeouts would let a
comparison take three times what the contract allowed.

## Running it

The build is obtained, verified and certified by
[integrations/nbis/README.md](../../integrations/nbis/README.md). Once a certified
build exists:

```bash
make nbis-verify BUILD=build/nbis-5.0.0/<build-id>
make nbis-contract
FPBENCH_NBIS_BUILD_DIR=build/nbis-5.0.0/<build-id> make nbis-upstream
```

The 6,000-comparison SD300 run is **stage 7C**. Stage 7B produced no run, no
decision set, no metric set and no biometric evidence of any kind — by design.
