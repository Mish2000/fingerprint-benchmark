# SecuGen minutiae extraction (Stage 18A)

A transcription of `data/extract.py` from `neilharan/openafis` at the pinned
commit — the helper the OpenAFIS author published for turning raster fingerprint
images into ISO/IEC 19794-2:2005 templates using SecuGen's FDx SDK Pro.

This is a Stage 18A private-reference component. It is **not** registered as an
fpbench adapter, and Stage 18A is not a production integration.

```bash
python extract_batch.py --sdk-dir /path/to/sdk --identity
cat jobs.tsv | python extract_batch.py --sdk-dir /path/to/sdk
```

`jobs.tsv` is `image_id \t input_image \t output_template` per line. Output is
`image_id \t status \t template_bytes \t extract_us \t detail`.

The SDK lives in the local artifact store outside this repository. **No vendor
binary is ever committed here.**

## What is upstream's and stays that way

```text
Image.open(...).resize((300, 400), Image.LANCZOS)   aspect ratio ignored
SGFPM_Init(..., SG_DEV_FDU05)                       HU20, a 300x400 sensor
SGFPM_SetTemplateFormat(..., ISO19794)
SGFingerInfo(FingerNumber=UK, ViewNumber=0, ImpressionType=LP, ImageQuality=0)
SGFPM_CreateTemplate -> SGFPM_GetTemplateSize -> exact ISO bytes
```

Two of these are wrong on their face and are kept anyway: the 300×400 resize
distorts every canonical fpbench image, and a *rolled* impression is still
declared `LIVE_SCAN_PLAIN`. Stage 18A is a reference for the route the author
provided, not for the SecuGen pipeline fpbench would have designed
(`docs/adr/0134`).

## What differs, and why

Plumbing only, and each one is recorded in the stage's `route-contract.json`:

- **The SDK directory becomes the working directory.** `sgfplib` loads its
  algorithm and per-device modules with a plain `LoadLibrary` by name, which
  searches the working directory — `os.add_dll_directory` does not affect that.
  Upstream's own instruction is "copy the DLLs into the current directory"; this
  reaches the same arrangement without moving vendor binaries around.
- **One process handles many images.** Upstream's `extract.bat` spawns an
  interpreter per image. The SDK handle is still created, initialised and
  terminated **once per image**, so nothing is carried between them.
- **A failure is a status line, not an exception.** Stage 18A must record a failed
  image and keep going.

## `SGFPM_Init` fails, and the geometry is verified instead of assumed

On a machine with no SecuGen reader attached, `SGFPM_Init(SG_DEV_FDU05)` returns
`6` (`SGFDX_ERROR_DLLLOAD_FAILED_DRV`): the per-device driver module ships with
SecuGen's *device driver* package, not with the SDK. The library extracts anyway,
on its built-in 300×400 @ 500 dpi geometry — which is the FDU05 geometry upstream
was selecting by name.

Rather than trust that, `check_iso_geometry` parses **every** template back and
checks its declared width, height and resolution before it is written. A template
describing any other geometry is recorded as a failure and never stored, so a
build that quietly defaulted to a different sensor cannot produce 3,000 templates
measured against the wrong ruler.

The two deviceless entry points were probed and **not** used: in v4.21
`SGFPM_InitEx` answers `8` (`NO_LONGER_SUPPORTED`) and `SGFPM_InitEx2` answers
`501` (`LICENSE_LOAD`) without a SecuGen-issued licence file. No licence check is
circumvented anywhere in this directory.

## Corroboration

Extracting upstream's own `fvc2002/DB1_B/101_1.tif` through this route reproduces
the template upstream ships beside it to **179 of 180 bytes** — identical header
(300×400, 197 ppcm, 25 minutiae), with one angle byte differing by one,
consistent with a Pillow LANCZOS revision difference between 2020 and 12.3.0.

## Runtime

Needs `cffi`, `numpy` and `Pillow` in a 64-bit interpreter. Stage 18A uses a
dedicated venv outside the repository so the benchmark environment's own
fingerprint does not move.
