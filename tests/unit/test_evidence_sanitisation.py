"""What the evidence sanitiser must catch, and what it must leave alone.

The second half matters as much as the first. A check that fires on every URL
in ``evidence/`` — and there are forty — is a check somebody switches off, and
then the real leak goes out with it.
"""

from __future__ import annotations

import pytest

from fpbench.core.evidence_sanitisation import (
    ARTIFACT_STORE_PLACEHOLDER,
    find_absolute_paths,
    redact_absolute_paths,
)

LEAKS = [
    "C:\\Users\\sirak\\.cache\\fpbench\\third_party\\verifinger-2025-2\\NCore.dll",
    "C:/Users/sirak/.cache/fpbench/third_party/verifinger-2025-2/NCore.dll",
    "/home/someone/.cache/fpbench/third_party/verifinger-2025-2/libNCore.so",
    "/Users/someone/Documents/notes.txt",
    "D:\\workspace\\results\\run_abcd\\raw\\job.parquet",
    "\\\\fileserver\\share\\artifact.dll",
    "/mnt/c/fingerprint-benchmark/workspace",
]

CLEAN = [
    "https://arxiv.org/abs/2211.13897",
    "https://github.com/XiongjunGuan/JIPNet/blob/40d8445/LICENSE",
    "https://download.neurotechnology.com/Neurotec_Biometric_2025_2.zip",
    "evidence/stage11a-verifinger-2025_2-preflight/runtime-identity.json",
    "src/fpbench/core/evidence_sanitisation.py",
    "Users of SD 300 shall adhere to all terms agreed to upon obtaining SD 300.",
    "NCore.dll",
    "sd300a_00002502_plain_right_index",
]


@pytest.mark.parametrize("value", LEAKS)
def test_an_absolute_path_is_found(value: str) -> None:
    assert find_absolute_paths(value), f"{value!r} should be reported as a leak"


@pytest.mark.parametrize("value", CLEAN)
def test_something_that_is_not_a_path_is_left_alone(value: str) -> None:
    assert not find_absolute_paths(value), f"{value!r} is not an absolute path"
    assert redact_absolute_paths(value) == value


@pytest.mark.parametrize("value", LEAKS)
def test_redaction_removes_what_the_finder_reports(value: str) -> None:
    assert not find_absolute_paths(redact_absolute_paths(value))


def test_redaction_keeps_the_part_that_is_evidence() -> None:
    """Which artifact and which file survive; whose machine it was does not."""
    redacted = redact_absolute_paths(
        "C:\\Users\\sirak\\.cache\\fpbench\\third_party\\verifinger-2025-2"
        "\\installation\\Bin\\Win64_x64\\NCore.dll"
    )
    assert redacted == (
        f"{ARTIFACT_STORE_PLACEHOLDER}/verifinger-2025-2/installation/"
        "Bin/Win64_x64/NCore.dll"
    )


def test_redaction_walks_a_whole_document() -> None:
    """A caller hands over the document, not a list of path-shaped fields.

    The Stage 11A leak was inside ``loaded_runtime_modules[*].file_name``, a
    field nobody had classified as holding a path.
    """
    document = {
        "loaded_runtime_modules": [
            {"name": "NCore", "file_name": "C:\\Users\\a\\.cache\\fpbench"
                                           "\\third_party\\v\\NCore.dll"},
        ],
        "count": 1,
        "declared_version": "2025.2.0.0",
    }
    redacted = redact_absolute_paths(document)
    assert not find_absolute_paths(redacted)
    assert redacted["count"] == 1
    assert redacted["declared_version"] == "2025.2.0.0"
    assert redacted["loaded_runtime_modules"][0]["name"] == "NCore"


def test_an_extra_root_is_replaced_before_the_built_in_ones() -> None:
    redacted = redact_absolute_paths(
        "C:\\fingerprint-benchmark\\workspace\\results\\run_a\\raw\\j.parquet",
        extra_roots={"C:\\fingerprint-benchmark\\workspace": "<workspace>"},
    )
    assert redacted == "<workspace>/results/run_a/raw/j.parquet"
