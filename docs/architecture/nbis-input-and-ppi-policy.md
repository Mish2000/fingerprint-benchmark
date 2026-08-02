# What NBIS is given, and at what resolution

The whole of stage 7B's input design comes down to two questions that had to be
measured rather than assumed:

1. does MINDTCT read an 8-bit greyscale PNG directly?
2. does it care what resolution the PNG declares?

Both are properties of a *build*. Answering them from documentation, from a
distribution's packaging notes, or from what everybody knows about NBIS would put
an unverified assumption underneath every score this route produces.

## The measurements

`python integrations/nbis/build.py test` runs both, on the build it is about to
certify, and refuses to write a build manifest unless they come out as this route
requires. The same probes run again in `tests/integration/test_nbis_upstream.py`
against the certified build, so a build restored from a CI cache is re-measured
rather than trusted.

### PNG capability

Seven images, one raster:

| image | required outcome |
|---|---|
| 8-bit greyscale, `pHYs` 500 | accepted, XYT written |
| 8-bit greyscale, no `pHYs` | accepted, XYT written |
| 16-bit greyscale | refused |
| 8-bit truecolour | refused |
| 8-bit indexed colour | refused |
| corrupt PNG body | refused |

A build that accepts any of the bottom four is not certified. The adapter refuses
them too, before the subprocess starts, and records `INPUT_INVALID` — but a build
that quietly converts them is not the build this stage certified, and the
difference matters if anyone ever runs MINDTCT by hand.

`png_support_compiled` and `direct_gray8_png_verified` in the build manifest are
these verdicts, and the adapter refuses a manifest without both.

### PPI behaviour

Three images with **byte-identical pixel data** and three different declarations:

```
pHYs saying 500 ppi
pHYs saying 1000 ppi
no pHYs chunk at all
```

Identical XYT output ⇒ the metadata is ignored and NBIS's 500 ppi default applies.
The manifest records:

```
png_ppi_policy: metadata_ignored_default_500
```

Different output ⇒ **the stage stops**. The 500-ppi-only route was designed around
metadata being ignored; if it is not, the design is wrong and is redesigned around
what the official build actually does. The policy is never written from memory
(docs/adr/0047).

Because the answer is "ignored", the adapter deliberately does **not** read the
`pHYs` chunk either. A check there would reintroduce the dependency the
measurement removed, and would then disagree with MINDTCT on a file whose header
lies.

## Why 500 ppi and nothing else

SD300 ships three resolutions, and SourceAFIS runs natively on all three because
it is told each image's effective resolution and scales accordingly
(docs/adr/0016). NBIS is different in a way that is easy to miss:

**MINDTCT's spatial parameters are pixel counts.** The window sizes, block sizes
and direction-map geometry of the LFS extraction are fixed in pixels. A resolution
value reaches the computation later, where it scales the minutia reliability
calculation — it does not rescale the analysis.

So running the same finger at 500 ppi and at 2000 ppi is not one experiment
carried out at two scales. It is two different analyses of two different rasters,
and the numbers are not two measurements of the same quantity.

The route is therefore **defined at 500 ppi**. The adapter refuses any other
`effective_ppi` before any subprocess starts, there is no configuration key that
changes it, every stored result records `effective_ppi=500`, and the validator
refuses a result that says otherwise. Three independent places, because this is
the assumption that would be most expensive to get wrong.

Native 1000 and 2000 ppi remain a legitimate future experiment. They need their
own argument about what pixel-fixed parameters mean at those scales, and they
would be a different `dpi_policy` — therefore a different algorithm identity.

## Where the pixels come from

Stage 6A's canonical preparation (`prepset_be560e047991`, transform profile
`canonical_gray8_500ppi_lanczos3_v1`) produces one 8-bit greyscale 500 ppi PNG per
participating image, with its own identity, its own receipt and its own
finalization marker (docs/adr/0031, docs/adr/0033). Every algorithm is handed the
same artefacts.

The NBIS adapter copies one of those, byte for byte, into the job's own directory
and hands it to MINDTCT:

```
PreparedImage.local_path  ->  <work>/left-input.png   (byte-for-byte)
                          ->  <work>/right-input.png
```

and proves the copy is the source before using it: the staged file's SHA-256 and
size must equal what the prepared image records. No re-encoding, no greyscale
conversion, no contrast change, no resize, no crop, no rotation, no WSQ, no JPEG,
no PGM, no IHead (docs/adr/0048).

The copy exists for one reason only: an adapter may not hand a tool a path outside
the directories it was given.

## Drift, and why it is not a comparison failure

If a prepared artefact's bytes no longer hash to what the preparer recorded, the
adapter raises `PreparedImageDriftError` rather than recording a failure. That is
not a property of this pair — it means the input set changed after preflight
approved it, so every result already written is attributable to something that is
no longer there. The runner re-raises it unrecorded and the invocation ends
(docs/adr/0033, docs/adr/0018).

An image of the *wrong shape*, by contrast, is an ordinary recorded failure. It is
a fact about the input set, and a run of 6,000 comparisons must not die on one of
them (docs/adr/0013).
