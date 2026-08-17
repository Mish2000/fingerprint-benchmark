#!/usr/bin/env python
"""fpbench Stage 18A — SecuGen FDx SDK Pro minutiae extraction, in batch.

This is a transcription of OpenAFIS's own ``data/extract.py`` at the pinned
commit ``3ae1c757c6dafea977a33ef51380e37f1715e626``, not a SecuGen pipeline of
our own design. Every choice below that can move a template is upstream's:

.. code-block:: text

    Image.open(input_file).resize((300, 400), Image.LANCZOS)   aspect ratio ignored
    SGFPM_Init(..., SG_DEV_FDU05)                              HU20, a 300x400 sensor
    SGFPM_SetTemplateFormat(..., TEMPLATE_FORMAT_ISO19794)
    SGFingerInfo(FingerNumber=SG_FINGPOS_UK, ViewNumber=0,
                 ImpressionType=SG_IMPTYPE_LP, ImageQuality=0)
    SGFPM_CreateTemplate -> SGFPM_GetTemplateSize -> exact ISO bytes

Two of those are wrong on their face and are kept anyway. The resize to 300x400
distorts the aspect ratio of every canonical fpbench image, and a rolled
impression is still declared ``LIVE_SCAN_PLAIN``. Stage 18A is a reference for
the route the OpenAFIS author published, not for the SecuGen pipeline we would
have designed, so neither is corrected here.

WHAT IS ALLOWED TO DIFFER

Plumbing only, and each one is named in the route contract:

* the DLL is loaded from an explicit directory rather than the process CWD,
  through ``os.add_dll_directory`` (upstream's ``ffi.dlopen('sgfplib')`` assumes
  the DLLs were copied next to the script);
* one process handles many images instead of one process per image, because
  upstream's ``extract.bat`` spawns a Python interpreter 3,000 times;
* a failure is reported as a status line instead of a raised exception, because
  Stage 18A must record a failed image and keep going.

The SDK handle is still created, initialised and terminated **once per image**,
exactly as ``extract.bat`` produces by construction. Nothing is carried between
images.

PROTOCOL

stdin, one job per line, tab separated::

    image_id \t input_image_path \t output_template_path

stdout, one result per line, tab separated::

    image_id \t status \t template_bytes \t extract_us \t detail

``status`` is ``OK``, ``IMAGE_FAILED`` (the raster could not be read or
converted) or ``EXTRACTION_FAILED`` (an SDK call returned non-zero); ``detail``
carries the failing call and its return code. ``template_bytes`` is 0 on any
failure, and no output file is written.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import numpy
from cffi import FFI
from PIL import Image

# Verbatim from upstream extract.py, which took it from sgfplib.h. Trimmed of
# nothing and added to only where the batch driver needs a symbol upstream's
# single-shot script never had to name.
CDEF = """
typedef unsigned char BYTE;
typedef unsigned short WORD;
typedef unsigned long DWORD;
typedef void* HSGFPM;

enum SGFDxDeviceName
{
   SG_DEV_UNKNOWN = 0,
   SG_DEV_FDP02 = 0x01,
   SG_DEV_FDU02 = 0x03,
   SG_DEV_FDU03 = 0x04,       // Hamster Plus
   SG_DEV_FDU04 = 0x05,       // Hamster IV
   SG_DEV_FDU05 = 0x06,       // HU20
   SG_DEV_FDU06 = 0x07,       // UPx
   SG_DEV_FDU07 = 0x08,       // U10
   SG_DEV_FDU07A = 0x09,	  // U10-AP(A)
   SG_DEV_FDU08 = 0x0A,	      // U20A
   SG_DEV_FDU08P =0x0B,	      // U20-AP, reserved
   SG_DEV_FDU06P = 0x0C,      // UPx-P
   SG_DEV_FDUSDA = 0x0D,      // U20-ASF-BT (SPP/Serial)
   SG_DEV_FDUSDA_BLE = 0x0E,  // U20-ASF-BT (BLE)
   SG_DEV_FDU08X = 0x0F,      // U20-ASFX (USB), reserved
   SG_DEV_FDU09 = 0x10,       // U30, reserved
   SG_DEV_FDU08A = 0x11,	  // U20-AP(A)
   SG_DEV_FDU09A = 0x12,	  // U30-AP(A)
   SG_DEV_AUTO = 0xFF,
};

enum SGFDxTemplateFormat
{
   TEMPLATE_FORMAT_ANSI378 = 0x0100,
   TEMPLATE_FORMAT_SG400   = 0x0200,
   TEMPLATE_FORMAT_ISO19794 = 0x0300,
   TEMPLATE_FORMAT_ISO19794_COMPACT = 0x0400,
};

enum SGImpressionType
{
   SG_IMPTYPE_LP =	0x00,		// Live-scan plain
   SG_IMPTYPE_LR =	0x01,		// Live-scan rolled
   SG_IMPTYPE_NP =	0x02,		// Nonlive-scan plain
   SG_IMPTYPE_NR =	0x03,		// Nonlive-scan rolled
};

enum SGFingerPosition
{
   SG_FINGPOS_UK = 0x00,		// Unknown finger
   SG_FINGPOS_RT = 0x01,		// Right thumb
   SG_FINGPOS_RI = 0x02,		// Right index finger
   SG_FINGPOS_RM = 0x03,		// Right middle finger
   SG_FINGPOS_RR = 0x04,		// Right ring finger
   SG_FINGPOS_RL = 0x05,		// Right little finger
   SG_FINGPOS_LT = 0x06,		// Left thumb
   SG_FINGPOS_LI = 0x07,		// Left index finger
   SG_FINGPOS_LM = 0x08,		// Left middle finger
   SG_FINGPOS_LR = 0x09,		// Left ring finger
   SG_FINGPOS_LL = 0x0A,		// Left little finger
};

typedef struct tagSGFingerInfo {
    WORD FingerNumber;           // FingerNumber.
    WORD ViewNumber;             // Sample number
    WORD ImpressionType;         // impression type. Should be 0
    WORD ImageQuality;           // Image quality
} SGFingerInfo;

DWORD SGFPM_Create(HSGFPM* phFpm);
DWORD SGFPM_Terminate(HSGFPM hFpm);
DWORD SGFPM_Init(HSGFPM hFpm, DWORD devName);
DWORD SGFPM_SetTemplateFormat(HSGFPM hFpm, WORD format);
DWORD SGFPM_GetMaxTemplateSize(HSGFPM hFpm, DWORD* size);
DWORD SGFPM_CreateTemplate(HSGFPM hFpm, SGFingerInfo* fpInfo, BYTE* rawImage, BYTE* minTemplate);
DWORD SGFPM_GetTemplateSize(HSGFPM hFpm, BYTE* minTemplate, DWORD* size);
"""

# Upstream's resize target, and the reason it is what it is: SG_DEV_FDU05 is the
# HU20, whose sensor is 300x400. Frozen. Changing either would change every
# template in the run.
SENSOR_WIDTH = 300
SENSOR_HEIGHT = 400


# The ISO/IEC 19794-2:2005 record header, as OpenAFIS's own parser reads it:
# 8 magic bytes, then big-endian totalLength/rfu/width/height/resX/resY.
ISO_MAGIC = b"FMR\x00 20\x00"
EXPECTED_RESOLUTION_PPCM = 197  # 500 dpi, which is what 197 ppcm rounds from


class ExtractionError(Exception):
    """An SDK call returned non-zero. Carries the call name and the code."""

    def __init__(self, call: str, code: int) -> None:
        super().__init__(f"{call}() returned {code}")
        self.call = call
        self.code = code


class GeometryError(Exception):
    """The template came back describing an image other than the frozen 300x400."""


def check_iso_geometry(template: bytes) -> tuple[int, int, int]:
    """Read the geometry back out of the template the SDK produced.

    This exists because ``SGFPM_Init(SG_DEV_FDU05)`` cannot succeed on a machine
    with no SecuGen driver module installed: it returns
    ``SGFDX_ERROR_DLLLOAD_FAILED_DRV`` (6), and the newer deviceless entry points
    are closed too — ``SGFPM_InitEx`` answers ``NO_LONGER_SUPPORTED`` (8) and
    ``SGFPM_InitEx2`` wants a SecuGen-issued licence file (501).

    The library extracts anyway, on its built-in 300x400 @ 500 dpi geometry, which
    is exactly the FDU05 geometry upstream selected by name. Rather than trust
    that, every template is read back and its declared dimensions checked. A build
    that quietly defaulted to some other sensor would fail here instead of
    producing 3,000 templates measured against the wrong ruler.
    """
    if len(template) < 20 or not template.startswith(ISO_MAGIC):
        raise GeometryError(f"not an ISO 19794-2:2005 record: {template[:8]!r}")
    width = int.from_bytes(template[14:16], "big")
    height = int.from_bytes(template[16:18], "big")
    resolution = int.from_bytes(template[18:20], "big")
    if (width, height) != (SENSOR_WIDTH, SENSOR_HEIGHT):
        raise GeometryError(f"template declares {width}x{height}, frozen route is {SENSOR_WIDTH}x{SENSOR_HEIGHT}")
    if resolution != EXPECTED_RESOLUTION_PPCM:
        raise GeometryError(f"template declares {resolution} ppcm, expected {EXPECTED_RESOLUTION_PPCM}")
    return width, height, resolution


def load_sdk(ffi: FFI, sdk_dir: Path, library: str):
    """Open sgfplib from an explicit directory, and make its companions findable.

    Upstream writes ``ffi.dlopen('sgfplib')`` and tells the reader to *copy the
    DLLs into the current directory*. That instruction is not incidental:
    ``sgfplib`` loads its algorithm and per-device modules with a plain
    ``LoadLibrary("sgfpamx.dll")``, which searches the process working directory
    and PATH — and neither ``os.add_dll_directory`` nor opening sgfplib by full
    path affects that search. Registering the directory alone gets sgfplib itself
    loaded and then fails at ``SetTemplateFormat`` with
    ``SGFDX_ERROR_DLLLOAD_FAILED_DRV``.

    So all three are done: the directory is registered, prepended to PATH, and
    made the working directory. That is upstream's arrangement, reached
    deliberately instead of by asking the operator to copy vendor binaries around.
    Job paths are resolved against the *original* working directory first, so
    moving the process does not change which files a job names.
    """
    sdk_dir = sdk_dir.resolve()
    if not sdk_dir.is_dir():
        raise SystemExit(f"no SDK directory at {sdk_dir}")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(sdk_dir))
    os.environ["PATH"] = str(sdk_dir) + os.pathsep + os.environ.get("PATH", "")
    os.chdir(sdk_dir)
    candidate = sdk_dir / f"{library}.dll"
    return ffi.dlopen(str(candidate) if candidate.is_file() else library)


def read_raster(path: Path) -> numpy.ndarray:
    """One image to the raw 8-bit buffer the SDK is handed.

    ``Image.open(...).resize((300, 400), Image.LANCZOS)`` is upstream's line,
    unchanged, including that it does not preserve the aspect ratio. The two
    additions are defensive rather than corrective: the image is forced to 8-bit
    greyscale (fpbench's canonical inputs already are, so this is an assertion
    that happens to be executable), and the array is made contiguous because the
    SDK reads it as a flat byte buffer.
    """
    with Image.open(path) as source:
        image = source.convert("L").resize((SENSOR_WIDTH, SENSOR_HEIGHT), Image.LANCZOS)
    raw = numpy.array(image)
    if raw.dtype != numpy.uint8:
        raise ValueError(f"expected 8-bit samples, got {raw.dtype}")
    if raw.shape != (SENSOR_HEIGHT, SENSOR_WIDTH):
        raise ValueError(f"expected {(SENSOR_HEIGHT, SENSOR_WIDTH)} samples, got {raw.shape}")
    return numpy.ascontiguousarray(raw)


def extract_template(ffi: FFI, lib, raw: numpy.ndarray) -> tuple[bytes, int]:
    """Upstream's call sequence, once, on a fresh handle.

    Create, Init, SetTemplateFormat, GetMaxTemplateSize, CreateTemplate,
    GetTemplateSize, Terminate — in that order, with upstream's arguments. The
    handle is terminated in a ``finally`` so a failure part-way through does not
    leak it into the next image.

    ``SGFPM_Init`` is called exactly as upstream calls it, and its return code is
    reported rather than raised on. On a machine with no SecuGen reader driver it
    answers 6 (``DLLLOAD_FAILED_DRV``) and extraction still runs at the library's
    built-in 300x400 @ 500 dpi geometry — which is the FDU05 geometry upstream was
    asking for by name. :func:`check_iso_geometry` verifies that from the emitted
    record, so the claim rests on the template rather than on the return code.

    Returns the template bytes and the ``SGFPM_Init`` code, so the caller can
    record which init path the run actually took.
    """
    handle = ffi.new("HSGFPM*")
    code = lib.SGFPM_Create(handle)
    if code != 0:
        raise ExtractionError("SGFPM_Create", code)
    try:
        init_code = lib.SGFPM_Init(handle[0], lib.SG_DEV_FDU05)

        code = lib.SGFPM_SetTemplateFormat(handle[0], lib.TEMPLATE_FORMAT_ISO19794)
        if code != 0:
            raise ExtractionError("SGFPM_SetTemplateFormat", code)

        max_size = ffi.new("DWORD*")
        code = lib.SGFPM_GetMaxTemplateSize(handle[0], max_size)
        if code != 0:
            raise ExtractionError("SGFPM_GetMaxTemplateSize", code)

        finger_info = ffi.new(
            "SGFingerInfo*",
            {
                "FingerNumber": lib.SG_FINGPOS_UK,
                "ViewNumber": 0,
                "ImpressionType": lib.SG_IMPTYPE_LP,
                "ImageQuality": 0,
            },
        )
        raw_image = ffi.cast("BYTE*", raw.ctypes.data)
        buffer = ffi.new("BYTE[]", max_size[0])
        code = lib.SGFPM_CreateTemplate(handle[0], finger_info, raw_image, buffer)
        if code != 0:
            raise ExtractionError("SGFPM_CreateTemplate", code)

        size = ffi.new("DWORD*")
        code = lib.SGFPM_GetTemplateSize(handle[0], buffer, size)
        if code != 0:
            raise ExtractionError("SGFPM_GetTemplateSize", code)

        template = bytes(ffi.buffer(buffer)[0 : size[0]])
        check_iso_geometry(template)
        return template, int(init_code)
    finally:
        lib.SGFPM_Terminate(handle[0])


def emit(image_id: str, status: str, size: int, micros: int, detail: str = "") -> None:
    print(f"{image_id}\t{status}\t{size}\t{micros}\t{detail}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sdk-dir", type=Path, required=True, help="directory holding sgfplib.dll and its companions")
    parser.add_argument("--library", default="sgfplib", help="library base name (default: sgfplib)")
    parser.add_argument(
        "--repeat",
        action="store_true",
        help="extract each image twice and report whether the two templates are byte-identical (determinism probe; writes the first)",
    )
    parser.add_argument("--identity", action="store_true", help="report the loaded runtime and exit without reading stdin")
    args = parser.parse_args(argv)

    # Captured before load_sdk moves the process into the SDK directory, so a job
    # line naming a relative path still means what the caller meant.
    origin = Path.cwd()

    ffi = FFI()
    ffi.cdef(CDEF)
    lib = load_sdk(ffi, args.sdk_dir, args.library)

    if args.identity:
        import PIL

        print(f"python\t{sys.version.split()[0]}")
        print(f"numpy\t{numpy.__version__}")
        print(f"pillow\t{PIL.__version__}")
        print(f"sdk_dir\t{args.sdk_dir.resolve()}")
        print(f"resize\t{SENSOR_WIDTH}x{SENSOR_HEIGHT}")
        print("resample\tLANCZOS")
        print("device\tSG_DEV_FDU05")
        print("template_format\tISO19794")
        # Report which init paths this build offers, so a run records the state of
        # the SDK it actually ran against rather than the state of the 2020 one.
        handle = ffi.new("HSGFPM*")
        lib.SGFPM_Create(handle)
        print(f"sgfpm_init_fdu05\t{lib.SGFPM_Init(handle[0], lib.SG_DEV_FDU05)}")
        lib.SGFPM_Terminate(handle[0])
        return 0

    for line in sys.stdin:
        line = line.rstrip("\n").rstrip("\r")
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            emit(fields[0] if fields else "?", "IMAGE_FAILED", 0, 0, "malformed job line")
            continue
        image_id, input_path, output_path = fields
        source = origin / input_path
        destination = origin / output_path

        started = time.perf_counter_ns()
        try:
            raw = read_raster(source)
        except Exception as error:  # noqa: BLE001 - any raster problem is one status
            micros = (time.perf_counter_ns() - started) // 1000
            emit(image_id, "IMAGE_FAILED", 0, micros, f"{type(error).__name__}: {error}")
            continue

        try:
            template, init_code = extract_template(ffi, lib, raw)
            detail = f"init={init_code}"
            if args.repeat:
                second, _ = extract_template(ffi, lib, raw)
                detail += ";" + ("identical" if second == template else "differs")
        except ExtractionError as error:
            micros = (time.perf_counter_ns() - started) // 1000
            emit(image_id, "EXTRACTION_FAILED", 0, micros, f"{error.call}={error.code}")
            continue
        except GeometryError as error:
            # Not an extraction failure: the SDK returned a template describing an
            # image the frozen route never asked for. Recorded separately so it
            # cannot be mistaken for a print the extractor declined.
            micros = (time.perf_counter_ns() - started) // 1000
            emit(image_id, "EXTRACTION_FAILED", 0, micros, f"geometry: {error}")
            continue
        except Exception as error:  # noqa: BLE001
            micros = (time.perf_counter_ns() - started) // 1000
            emit(image_id, "EXTRACTION_FAILED", 0, micros, f"{type(error).__name__}: {error}")
            continue

        micros = (time.perf_counter_ns() - started) // 1000
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(template)
        emit(image_id, "OK", len(template), micros, detail)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
