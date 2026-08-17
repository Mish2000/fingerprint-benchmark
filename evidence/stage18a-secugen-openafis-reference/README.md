# Stage 18A — SecuGen → OpenAFIS, private reference raw run

**Outcome: `SECU_GEN_OPENAFIS_PRIVATE_RAW_COMPLETE`.** 3,000 templates, 6,000
stored outcomes, 0 missing, 0 failures of any kind.

This stage is **not** Algorithm 5 and its numbers are **not publishable**:

```text
algorithm_5_established  = false
opens_common_calibration = false
publication_eligible     = false
purpose                  = PRIVATE_REFERENCE_ONLY
```

It exists so that Stage 19A (MINDTCT → OpenAFIS, the real Algorithm 5 candidate)
starts with a working OpenAFIS build, a proven raw 1:1 score contract, and a
private sense of how OpenAFIS behaves when fed by an extractor its own author
demonstrated it against.

Every score lives outside this repository, under `$FPBENCH_PRIVATE_ROOT`. The
four documents here carry identifiers, counts and timings, and no score.

## Why the stage was built execution-first

Stages 15A through 17A each spent their effort on machinery a candidate never
reached the far side of. Stage 18A inverts that: the completion criterion is
arithmetic and nothing else.

```text
expected pair outcomes = 6000
stored pair outcomes   = 6000
missing                = 0
```

There is no minimum extraction coverage, no minimum number of scores, no minimum
mated coverage, no minimum variance and no minimum discrimination — and no
constant for any of them anywhere in the code. Five thousand failures and a
thousand scores would still have completed the stage, because the stage was built
to measure what the system does rather than to select it.

## What is comparable to the other four algorithms, and what is not

**Identical, by construction and checked before a run exists:** the prepared image
set (`prepset_be560e047991`), the pair manifest and its hash
(`ee4d942e…`) and its row order, which side is the probe, that the score is
stored as a raw integer with no transform and no threshold, and that a failure is
never stored as a zero.

**Not identical:** the input pixels. The frozen extraction route resizes every
image to 300×400 *without preserving the aspect ratio*, because that is the sensor
geometry upstream's helper declares. SourceAFIS, NBIS, flx and VeriFinger all
consumed the canonical 500 ppi images at their native dimensions (e.g. 381×891).
This is a real difference in what reached the algorithm, it is mandated by the
frozen route, and it is the main reason these numbers stay private.

## The route is upstream's, not ours

`integrations/secugen/extract_batch.py` is a transcription of
`data/extract.py` from `neilharan/openafis` at the pinned commit. Two of its
choices are wrong on their face and are kept anyway: the 300×400 resize distorts
every canonical image, and a *rolled* impression is still declared
`LIVE_SCAN_PLAIN`. Correcting either would have made this a reference for a
SecuGen pipeline fpbench invented, which is not what the stage is for.

The proof that the transcription is faithful is in `route-contract.json`:
extracting upstream's own `fvc2002/DB1_B/101_1.tif` through this route reproduces
the template upstream ships beside it to **179 of 180 bytes**, with an identical
header (300×400, 197 ppcm, 25 minutiae) and one angle byte differing by one —
consistent with a Pillow LANCZOS revision difference between 2020 and 12.3.0.

## What the machine forced, and what was refused

`SGFPM_Init(SG_DEV_FDU05)` returns `6` (`SGFDX_ERROR_DLLLOAD_FAILED_DRV`) on a
machine with no SecuGen reader: the per-device driver module ships with SecuGen's
*device driver* package rather than with the SDK. The library extracts anyway, on
its built-in 300×400 @ 500 dpi geometry — which is the FDU05 geometry upstream was
asking for by name. Rather than trust that, **every one of the 3,000 templates is
parsed back and its declared width, height and resolution checked** before it is
written; a template describing any other geometry is recorded as a failure and
never stored.

The two deviceless entry points were probed and **not** used: `SGFPM_InitEx`
answers `8` (`NO_LONGER_SUPPORTED`) in v4.21, and its successor `SGFPM_InitEx2`
answers `501` (`LICENSE_LOAD`) without a SecuGen-issued licence file. No licence
check was circumvented.

## The licence position, recorded rather than resolved

Section 2 of the requirements names one boundary that is not methodological, and
it did not clear. SecuGen's public SDK License Agreement §3(a) prohibits using the
SDK to process fingerprint images obtained from non-SecuGen devices — which is
what SD300 is — and §3(e) prohibits competitive benchmarking, which is what this
benchmark is. There is no research exemption, and the downloaded package ships no
EULA of its own. No authorization was obtained from the vendor.

The run went ahead as **`OWNER_RISK_ACCEPTED`**, on the repository owner's
explicit and recorded decision, because the run is private and unpublished and
waiting for a vendor response was judged incompatible with the schedule. No
licence check or protection measure was circumvented: the two deviceless entry
points were probed, found closed, and not used.

**This is the primary reason `publication_eligible` is false.** These numbers must
not appear in the supervisor's comparison table or in any published result. Stage
19A (MINDTCT → OpenAFIS) carries no vendor terms — NBIS is US Government public
domain and OpenAFIS is BSD-2-Clause — and is the publishable route.

## What the run found

Extraction succeeded on all 3,000 images (coverage 1.0), and every extraction was
byte-identical on a repeat — so one template per image, per section 10, with no
separate LEFT and RIGHT caches. All 6,000 comparisons returned a score; not one
pair reached any failure status.

The distributions are in the private diagnostic report. The one thing worth
recording here, because it shapes what Stage 18A is good for: **the SELF
populations behave and the cross-impression populations collapse.** `plain_self`
and `roll_self` sit at a median of 100, while `plain_roll_mated` has a median of 0
and a maximum of 7 against `plain_roll_non_mated`'s maximum of 3. OpenAFIS itself
is not the cause — on upstream's own FVC templates the same build scores 72
between two impressions of one finger. The 300×400 aspect-destroying resize is,
and it damages plain and rolled prints differently because their native aspect
ratios differ.

That is a finding about **the frozen route**, not about OpenAFIS and not about
MINDTCT.

## What Stage 19A may not take from this

Section 17 is a hard rule and the constants enforce it:

```text
which MINDTCT quality cutoff
how many minutiae to keep
which angle conversion correlates better
which coordinate scaling produces more similar scores
```

None of these may be chosen because they move these numbers. Stage 19A must be
derived from the MINDTCT and OpenAFIS specifications. Otherwise SecuGen becomes a
training target.

## No rates, and nowhere to put one

The diagnostic report computes coverage, histograms, per-population
distributions, quantization and timings. It has **no field** for TAR, FAR, FMR or
EER, and `build_diagnostic_report` has **no parameter** for a threshold — the
absence is structural, not a matter of discipline. The negative pairs in this
manifest are a same-subject different-finger sanity set, not an impostor
population drawn for estimation, so every rate over them would be a number with no
population behind it.

## Files

| File | What it holds |
|------|---------------|
| `openafis-identity.json` | the pinned commit, the licence, the files that fix the score contract, and the build's two recorded deviations from upstream's CMake |
| `route-contract.json` | the frozen extraction route, the four recorded deviations, the extractor runtime, and the determinism result |
| `private-run-binding.json` | identifiers, counts, coverage and timings for the private run — and no score |
| `stage-18a-finalization.json` | the marker |

## Reproducing

```bash
make stage18a-bridge FPBENCH_OPENAFIS_SOURCE=/path/to/openafis
make stage18a-run
make stage18a-diagnostics
```

`FPBENCH_SECUGEN_SDK_DIR` must point at the SDK directory holding `sgfplib.dll`
and `sgfpamx.dll`. No vendor binary and no score is ever written into this
repository.
