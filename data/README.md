# Data

**No fingerprint imagery is stored in this repository.**

NIST Special Database 300 is distributed under terms agreed at the time of
delivery — the SD300 README states that users "shall adhere to all terms agreed
to upon obtaining SD 300". This repository therefore contains only code,
configuration, manifests and documentation. The images stay where NIST's
delivery was unpacked.

## Pointing the harness at your copy

Set an environment variable to the directory that contains `sd300a/`, `sd300b/`
and `sd300c/`:

```powershell
$env:FPBENCH_SD300_ROOT = "C:\fingerprint-datasets\NIST"
```

```bash
export FPBENCH_SD300_ROOT=/data/NIST
```

Expected layout, unchanged from the NIST delivery:

```
<root>/
├── sd300a/images/500/
│   ├── png/{plain,roll}/*.png
│   ├── checksum_500_png_{plain,roll}.csv
│   └── segmentation_coordinates_500.csv
├── sd300b/images/1000/...
└── sd300c/images/2000/...
```

Each release holds 19,435 images across 888 subjects.

## Verifying a delivery

NIST ships SHA-256 manifests beside every image directory. To check them:

```python
provider.verify_checksums("SD300A")
```

This hashes roughly 38 GB per release, so it is meant to be run once on
delivery, not per experiment.

## Known data quality issue

10,115 SD300C files declare 5080 ppi in their PNG headers while being 2000 ppi
images. The harness ignores the declaration and uses 2000; see
[ADR 0004](../docs/adr/0004-sd300c-effective-ppi.md) for the evidence and the
policy. Nothing in the delivery is modified.
