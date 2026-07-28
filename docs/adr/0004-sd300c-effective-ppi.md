# 0004 — SD300C is used at 2000 ppi despite its metadata

## Status

Accepted. Implemented in `fpbench.datasets.sd300.ppi_policy` and
`fpbench.datasets.sd300.validation`.

## Context

A full check of all 58,305 PNG files across the three delivered releases,
reading the `pHYs` chunk directly from each header, found:

| Release | Files | Filename PPI correct | `pHYs` agrees | Values found |
|---|---|---|---|---|
| SD300A | 19,435 | 19,435/19,435 | 19,435/19,435 | 500 only (19,685 px/m) |
| SD300B | 19,435 | 19,435/19,435 | 19,435/19,435 | 1000 only (39,370 px/m) |
| SD300C | 19,435 | 19,435/19,435 | **9,320/19,435** | 2000 (78,740) and **5080 (200,000)** |

10,115 SD300C files declare 5080 ppi where the release, the directory name and
the file name all say 2000.

The metadata is what is wrong, not the images. The evidence is geometric:

* All 10,115 affected files are **exactly 2x** the pixel dimensions of the
  corresponding SD300B (1000 ppi) images — 10,115 of 10,115. A true 5080 ppi
  scan would have to be 5.08x.
* Interpreting them at 5080 ppi shrinks the physical card block by a factor of
  exactly 2.540 = 5080/2000. For `00001000_plain_13`, releases A and B both put
  the block at 3.196in x 1.890in; the SD300C header would make it
  1.258in x 0.744in, which is not a physically possible fingerprint card block.

5080 is the scanner's optical resolution leaking into the header.

The defect does not cluster by subject: 881 of 888 subjects are partially
affected and only 7 are fully affected, so it cannot be handled by excluding
subjects. It affects only *native* card-block scans — plain 13/14, plain 11/12
partially, roll 01-10 partially — while every `segmented` plain image
(FRGP 02-10) is clean.

## Decision

For SD300C, `pHYs` is ignored and the effective resolution is 2000 ppi.

* `EFFECTIVE_PPI` in `ppi_policy.py` is the single authoritative source, and it
  is *policy in code*, not a configuration value, so no experiment config can
  quietly reinterpret the release.
* The declared value is still recorded per image as `metadata_ppi`, and every
  affected file carries the `metadata_ppi_anomaly` code in its `anomalies`
  field.
* The anomaly is a **warning**, not an error: the release remains usable and is
  the project's only 2000 ppi source.
* An undeclared resolution — anything that is neither 2000 nor the documented
  5080 — is an **error**, so a new, different defect cannot hide behind this
  one.

Source files are never rewritten. NIST's delivery stays byte-identical to what
was received, and the checksum manifests continue to verify.

## Alternatives

**Repair the files in place.** Rejected: it destroys the ability to verify the
delivery against NIST's checksums, and it makes the analysis unreproducible for
anyone who obtains SD300 independently.

**Exclude the affected files.** Rejected: 10,115 of 19,435 files, spread across
almost every subject, would gut the release for no benefit — the images
themselves are sound.

**Trust `pHYs` and treat the images as 5080 ppi.** Rejected: it is
demonstrably false, and it would corrupt any resolution-dependent step.

## Consequences

* Any downstream resampling (2000 -> 500 ppi, for instance) must take its input
  resolution from `effective_ppi`, never from the file.
* Third-party tools that read `pHYs` themselves — some matchers do — may
  misinterpret SD300C images. Adapters that pass a file path rather than a
  decoded array must be checked for this, and may need to write a corrected
  temporary copy. This is an adapter-level concern and is not solved here.
* Reporting SD300C results should note the defect, since a reader reproducing
  the work from a fresh NIST delivery will hit it too.

## Escalation

If NIST issues a corrected SD300C, `EFFECTIVE_PPI` does not change — only the
anomaly disappears, and `test_c_carries_exactly_the_known_ppi_defect` in
`tests/integration/test_sd300_release.py` starts failing, which is the intended
signal that the data on disk is no longer what this ADR describes.
