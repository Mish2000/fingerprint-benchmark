# Stage 20A - MCC SDK v2.0 artifact, route, and score qualification

Stage 20A passes through the minutiae-only route. The official University of
Bologna MCC SDK v2.0 does **not** include a raster fingerprint extractor. Its
narrowest official baseline-MCC input is the in-memory
`CreateMccTemplate(width, height, resolution, Minutia[])` API, where a `Minutia`
contains only integer `X`, integer `Y`, and double-precision `Direction`.

The canonical route is therefore:

```text
canonical gray8 500 ppi
  -> NBIS MINDTCT 5.0.0 (no flags)
  -> mechanical XYT representation change
  -> official MCC SDK v2.0 baseline MCC, native SDK-optimal defaults
  -> raw System.Double similarity in [0,1]
```

The representation change preserves every minutia in MINDTCT order: x is direct,
y changes from bottom-left to upper-left by `image_height - y`, direction changes
units from degrees to radians, and quality is ignored because the SDK struct has
no quality field. There is no cutoff, top-N rule, sort, deduplication, crop,
resize, enhancement, rotation search, threshold, calibration, or score transform.

The runtime smoke used only three official sample-minutiae files. A fresh template
was built for every side, including SELF; both pair orders were checked; every
result was a finite native scalar. No SD300 image or prior algorithm result was
opened, and score magnitudes selected nothing.

## Four answers

1. Does MCC SDK include an image extractor? **NO**.
2. Exact input: `imageWidth`, `imageHeight`, `imageResolution`, and
   `MccSdk.Minutia[]` with `X`, `Y`, `Direction`; official ISO 19794-2:2011 and SDK
   text-file routes also exist.
3. Is there a raw native scalar similarity? **YES** - `System.Double`, `[0,1]`,
   higher means more similar.
4. Can canonical image -> MCC score be closed without choosing from SD300?
   **YES**.

Outcome: `MINDTCT_MCC_SDK_V2_ROUTE_PASS`. Stage 20B is open; no production
adapter and no 6,000-comparison run belong to this stage.
