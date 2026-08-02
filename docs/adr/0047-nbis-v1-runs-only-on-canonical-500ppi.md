# 0047 — The NBIS route runs on canonical 500 ppi input only

*Status: Accepted — 2026-08-02, stage 7B*

## Context

SD300 is delivered at three resolutions: SD300A at 500 ppi, SD300B at 1000, SD300C
at 2000. SourceAFIS is told the effective resolution of every image it is given
and scales its own analysis accordingly (docs/adr/0016), so it can be run natively
on all three. The obvious expectation is that NBIS can too.

Two facts say otherwise.

**MINDTCT's spatial parameters are in pixels.** The window sizes, the block sizes
and the direction map geometry of the LFS extraction are fixed pixel counts. A
resolution value reaches the computation late, where it scales the minutia
reliability calculation — it does not rescale the analysis. Running the same
finger at 500 and at 2000 ppi therefore is not the same experiment carried out at
two scales; it is two different analyses of two different rasters.

**A PNG's declared resolution may not reach MINDTCT at all.** Whether the `pHYs`
chunk is read, ignored, or overridden by a default is a property of the build, and
this project had no measurement of it — only an expectation.

Guessing either of these would put a wrong number in a thesis without anything in
the harness disagreeing.

## Decision

**The route is defined at 500 ppi, and nowhere else.** The adapter refuses a
prepared image whose `effective_ppi` is not 500, before any subprocess starts, and
records the rejection as `INPUT_INVALID`. There is no configuration key that
changes it: 500 is part of the algorithm identity, not a setting of it.

**The PPI policy is measured, not remembered.** `build.py test` extracts from three
PNGs with byte-identical pixel data and three different `pHYs` declarations — 500,
1000, and absent — and compares the XYT output:

* identical output ⇒ the metadata is ignored, NBIS's 500 ppi default applies, and
  the build manifest records `png_ppi_policy: metadata_ignored_default_500`;
* anything else ⇒ **the stage stops**. The route as designed does not exist, the
  policy is not written from memory, and the pipeline is redesigned around what
  the official build actually does.

The adapter refuses to run against a manifest claiming any other policy, and the
same probe is re-run against the real build in the upstream test suite.

Because the metadata is ignored, the adapter deliberately **does not read the
`pHYs` chunk** either. A check there would quietly reintroduce the dependency the
measurement removed.

## Consequences

The native SD300B and SD300C rasters are **not supported by this route** in v1.
The comparison this project can make between SourceAFIS and NBIS is over the
shared canonical 500 ppi input set (`prepset_be560e047991`), which is exactly what
stage 6A built that set for.

Running NBIS natively at 1000 or 2000 ppi remains a legitimate future experiment.
It needs its own argument about what the pixel-fixed parameters mean at those
scales, and it would be a different `dpi_policy` and therefore a different
algorithm identity.

Every stored NBIS result records `effective_ppi=500` and
`ppi_policy=nbis_png_default_500`, and the validator refuses a result that says
anything else — so a run that somehow escaped the input check is still caught
before a receipt is issued.

## Alternatives considered

**Pass the resolution to MINDTCT explicitly, as the SourceAFIS route does.**
MINDTCT has no such argument, and the value it does use internally does not
rescale the extraction.

**Resample inside the adapter.** That is exactly the shared preparation stage 6A
exists to do once, outside every adapter, with its own identity and its own
receipt (docs/adr/0031).

**Assume `pHYs` is ignored — every account of NBIS says so.** It very probably is.
"Very probably" is not a measurement, and the whole route rests on it.
