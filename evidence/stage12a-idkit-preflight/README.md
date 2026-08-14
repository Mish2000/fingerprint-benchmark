# Stage 12A — Innovatrics IDKit acquisition refusal and fail-fast preflight

## Outcome

```text
IDKIT_PREFLIGHT_FAIL
```

On 2026-08-14 an Innovatrics Business Development representative explicitly
declined to provide an IDKit SDK licence because the intended use is academic,
research-only, non-commercial benchmarking. This is an official access refusal,
not an inference from a missing download. The run failed at G1 and left G2-G10
`NOT_REACHED`.

```text
acquisition_status             ACCESS_REFUSED
vendor_response_received      true
vendor_response_date          2026-08-14
vendor_channel                VENDOR_SALES
package_obtained              false
license_offered               false
is_pending                    false
is_refusal                    true
blocker                       ACCESS_REFUSED_BY_VENDOR
failure_class                 VENDOR_ACCESS_REFUSED
opens_stage_12b               false
reopens_algorithm_5_search    true
```

The evidence keeps only that categorical summary. It does not contain the email,
the representative's identity or an address. The final
`stage-12a-finalization.json` binds the finding to the exact published bytes.

Nothing here is a score, a threshold, a template, a fingerprint image, a licence
byte or a credential. What it holds is descriptions: locators and what they said,
digests, published vocabularies, and the questions a delivered package will be
asked.

## The candidate

```text
candidate_id                      innovatrics_idkit_fingerprint_1to1  (provisional)
implementation_origin             VENDOR_OFFICIAL_SDK
algorithm_slot                    algorithm_5
implementation_version            UNRESOLVED_UNTIL_PACKAGE
production_algorithm_id_frozen    false
preferred_target_platform         windows/x86_64  (provisional)
```

The vendor's learning portal currently publishes material for **IDKit SDK 7.6**.
That is an indication of what to look for and nothing more; the binding version
is the one the delivered package reports about itself. `7.6` appears nowhere in
this stage's frozen identity (docs/adr/0110).

## Predecessor

```text
stage11b_outcome                  VERIFINGER_CANONICAL500_RAW_COMPLETE
stage11b_finalization_fingerprint 3d271490edda9e3e9d066485c2d93e82e2eceb4556668df7d65a8207e591684c
stage8e_policy_fingerprint        c08648dece292603eb9d4b6fff0b3412523af0730da59141b6e7a32ee02540e8
```

Stage 11B finished Algorithm 4 over 6,000 canonical comparisons and opened the
search for Algorithm 5. Stage 12A binds that marker by fingerprint and edits
nothing under Stage 11A's or Stage 11B's evidence, and it applies Stage 8E's
frozen policy rather than re-opening it.

## The gate matrix

| Gate | Status |
| :--- | :--- |
| G1 `ACQUISITION_ACCESS` | **FAIL** |
| G2 `PACKAGE_RUNTIME_IDENTITY` | not reached |
| G3 `RESEARCH_USE_AND_LICENSE` | not reached |
| G4 `CANONICAL500_INPUT_ROUTE` | not reached |
| G5 `SINGLE_FINGER_EXTRACTION_PROFILE` | not reached |
| G6 `SINGLE_FINGER_MATCHER_RAW_SCORE` | not reached |
| G7 `SCORE_AFFECTING_SETTINGS_CLOSURE` | not reached |
| G8 `PAIR_SELF_DETERMINISM_FAILURES` | not reached |
| G9 `WORKLOAD_RUNTIME_FEASIBILITY` | not reached |
| G10 `TRAINING_PROVENANCE` | not reached |

Ten gates, no sub-gates. `NOT_REACHED` is not a pass and not a soft failure: the
run stopped on the vendor refusal, so every later question was never asked.

**Blocker: `ACCESS_REFUSED_BY_VENDOR`.** It classifies access for this stated use
case and says nothing about IDKit's biometric quality.

Cost of reaching this conclusion: **zero package bytes**, zero licence
activations, zero runtimes, zero SD300 reads, zero scores.

## What was actually walked

| Route | Outcome |
| :--- | :--- |
| the public developer portal | no IDKit package offered |
| the vendor's public repositories | no IDKit package offered |
| the legacy customer CRM | retired by the vendor |
| the current customer portal | authentication required |
| the learning portal | a course, not a download |
| a request to vendor sales or support | refused by vendor on 2026-08-14 |

The sixth route supplied the decisive finding. No alternative sales contact,
reseller or artificial commercial reframing will be used to route around the
vendor's stated policy.

Three categories of non-vendor route were found and refused on provenance:
software-catalogue sites, reseller storefronts and third-party mirrors of vendor
documents. A package whose chain of custody does not run to the vendor is a
package nothing can pin, whatever its digest turns out to be.

## Final routing

IDKit is closed as a candidate. Stage 12B does not open; the failure returns the
Algorithm 5 selection to the next candidate. The id3 Finger SDK request remains
under vendor review in the background, and Neurodactyl is the next active
candidate.

## What the public material already tells us to check

Nine statements were retrieved from Innovatrics' own support material and are
recorded in `package-manifest.json` with their locators. **None of them freezes a
value.** They are the questions the package will be asked:

- IDKit generates the vendor's **proprietary** templates and does 1:1 and 1:N;
  the ANSI&ISO SDK is a different product. The delivered package has to resolve
  to the right family.
- IDKit is described as accepting **BMP or raw** images. The benchmark holds
  PNGs, so the route may have to be a lossless decode into the identical gray8
  matrix and then the official raw-buffer API — permitted only with every pixel
  proved identical, and never with a crop, a resize or an enhancement.
- **DPI is set before extraction** and a template remembers the DPI it was built
  under. Input images are described as internally resampled to 500 dpi, which at
  500 PPI in is a resample to the resolution the image already has, and is the
  vendor's processing rather than ours.
- A multi-fingerprint record is scored by **summing per-position maxima**. That
  is not a single-finger similarity and cannot be recovered from one, so each
  compared record must hold exactly one fingerprint.
- The matcher is **not commutative**. There is no symmetry to find and nothing to
  normalise: `pair.left → probe` and `pair.right → gallery` are frozen in
  advance, both orderings are run once to publish that they can differ, and
  neither a maximum nor an average of them ever enters a score (docs/adr/0109).
- The score and the decision **threshold are separate**, on a vendor scale
  described as roughly `-10·log10(FAR)`. A vendor scale is still a raw score;
  what is refused is a second transformation by fpbench, and reading scores by
  pushing the threshold to zero.
- A **template-size control** exists. It has to be found in the delivered package
  and recorded with its delivered value — not given a value from the internet.
- A **valid licence is required** and is machine-bound. Nothing about it is
  bypassed, and the harness is compiled before any licence is generated so that a
  time-limited clock is not spent on build errors (docs/adr/0111).

## What exists in code

| Built | Not built |
| :--- | :--- |
| the ten-gate state machine and its schemas | a production `FingerprintAlgorithmAdapter` |
| the acquisition state machine and store readers | a canonical experiment configuration |
| the qualification harness and its engine protocol | the 6,000-comparison runner |
| a fake SDK that proves the harness in CI | a `ResultSet`, a threshold, a calibration, a metric |
| the secret guard and the vendor-byte guard | any production algorithm id |

The fake SDK is asymmetric, deterministic, refuses a blank image with a status
rather than a score, and **can never answer a gate**: every qualification record
is stamped with its engine kind and only `DELIVERED_SDK` is read. A gate that
accepted the double would be a gate that passed on this project's own test code.

## The documents

| File | What it holds |
| :--- | :--- |
| `predecessor-binding.json` | what this stage rests on and may not touch |
| `acquisition-status.json` | every route walked and the categorical vendor refusal |
| `package-manifest.json` | the identity a delivery must carry, and the public observations |
| `research-use-license.json` | why Stage 8E has been asked nothing yet |
| `runtime-inventory.json` | the closure a delivered package would have to declare |
| `input-route.json` | how `canonical_500` would reach the extractor, and what stays refused |
| `fingerprint-route-profile.json` | the single-finger rule and the extraction settings |
| `score-contract.json` | what one comparison must return, and what fpbench does to it |
| `qualification-run.json` | the six required passes, the ceiling, and that no delivered SDK has run |
| `training-provenance.json` | `NOT_REACHED`, kept distinct from `NO_EVIDENCE_FOUND` |
| `preflight-report.json` | every gate, the outcome, and what it does not say |

`training-provenance.json` says `NOT_REACHED` rather than `NO_EVIDENCE_FOUND`.
"Nobody looked" and "we looked and found nothing" are different claims, and only
the second is evidence.

## What this stage did not do

```text
sd300_image_bytes_read        false
sd300_pair_manifest_read      false
sd300_scores_read             false
prior_algorithm_scores_read   false
production_adapter_created    false
benchmark_run_performed       false
threshold_produced            false
calibration_performed         false
metrics_produced              false
license_bypass_attempted      false
third_party_bytes_in_git      false
secrets_in_git                false
```

No SD300 byte, manifest or score was consulted, and neither were SourceAFIS's,
NBIS's, flx's or VeriFinger's. There is no reason for a candidate's preflight to
know how its predecessors did.

## Reproducing this

```bash
make stage12a-status
```

Everything above derives from committed source and requires no IDKit package.
A clean checkout, including every CI runner, produces exactly this outcome.
