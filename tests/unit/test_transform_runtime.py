"""What a transform runtime fingerprint covers, and what it deliberately does not.

The profile pins ``Lanczos3``, which is a mathematical kernel. This fingerprint
pins the code that evaluates it, because two wheels can carry the same version
string and different compiled extensions — a different libjpeg, a different
zlib, a local patch — and a benchmark whose inputs differ in the last bit is a
benchmark nobody can reproduce.

The tests come in pairs on purpose: for every term that must move the
fingerprint there is one that must not. A fingerprint that changed when nothing
meaningful changed would make every resumed materialisation fail; one that
stayed put when Pillow changed would let a set be half produced by one resampler
and half by another.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from fpbench.core.errors import ImagingError, ResearchPreflightError
from fpbench.core.imaging_models import (
    TransformRuntimeManifest,
    transform_runtime_fingerprint,
    transform_runtime_id,
)
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.imaging.runtime import (
    DEPENDENCY_LOCK_PATH,
    capture_transform_runtime,
    dependency_lock_sha256,
    pillow_distribution_fingerprint,
    pillow_zlib_version,
)
from canonicalworld import make_runtime

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def _rebuild(runtime: TransformRuntimeManifest, **changes) -> TransformRuntimeManifest:
    """A runtime with one term changed and its identity re-derived."""
    fields = {
        name: getattr(runtime, name)
        for name in (
            "software_fingerprint",
            "dependency_lock_sha256",
            "pillow_version",
            "pillow_distribution_fingerprint",
            "pillow_file_count",
            "python_version",
            "python_implementation",
            "platform_system",
            "platform_machine",
            "zlib_runtime_version",
            "source_revision",
            "source_tree_clean",
        )
    }
    fields.update(changes)
    fingerprint = transform_runtime_fingerprint(_Draft(**fields))
    return TransformRuntimeManifest(
        runtime_id=transform_runtime_id(fingerprint),
        runtime_fingerprint=fingerprint,
        created_utc=runtime.created_utc,
        **fields,
    )


class _Draft:
    __slots__ = (
        "software_fingerprint",
        "dependency_lock_sha256",
        "pillow_version",
        "pillow_distribution_fingerprint",
        "pillow_file_count",
        "python_version",
        "python_implementation",
        "platform_system",
        "platform_machine",
        "zlib_runtime_version",
        "source_revision",
        "source_tree_clean",
    )

    def __init__(self, **fields):
        for name in self.__slots__:
            setattr(self, name, fields[name])


# ------------------------------------------------------ what it must record


def test_capturing_the_real_environment_records_pillow_and_its_bytes():
    software = SoftwareProvenance(
        provenance_kind="git",
        source_revision="d" * 40,
        source_tree_clean=True,
        package_version="0.1.0",
        python_version="3.12.13",
        python_implementation="CPython",
        dependency_versions={"pyarrow": "15.0.0", "pyyaml": "6.0"},
    )
    runtime = capture_transform_runtime(software=software)

    installed_version, installed_fingerprint, file_count = (
        pillow_distribution_fingerprint()
    )
    assert runtime.pillow_version == installed_version
    assert runtime.pillow_distribution_fingerprint == installed_fingerprint
    assert runtime.pillow_file_count == file_count
    assert runtime.zlib_runtime_version == pillow_zlib_version()
    assert runtime.dependency_lock_sha256 == dependency_lock_sha256()
    assert runtime.source_revision == "d" * 40
    assert runtime.runtime_id.startswith("imgruntime_")


def test_the_lock_file_exists_and_pins_an_exact_pillow():
    text = DEPENDENCY_LOCK_PATH.read_text("utf-8")
    assert "Pillow==" in text
    pinned = next(
        line.split("==", 1)[1].strip()
        for line in text.splitlines()
        if line.strip().startswith("Pillow==")
    )
    installed, _, _ = pillow_distribution_fingerprint()
    assert pinned == installed, (
        "the installed Pillow is not the one requirements-imaging.lock pins; a "
        "canonical set produced now could not be reproduced from this repository"
    )


def test_a_missing_lock_is_a_research_preflight_failure(tmp_path):
    with pytest.raises(ResearchPreflightError, match="dependency lock"):
        dependency_lock_sha256(tmp_path / "absent.lock")


def test_the_distribution_fingerprint_is_stable_across_calls():
    first = pillow_distribution_fingerprint()
    second = pillow_distribution_fingerprint()
    assert first == second


def test_the_distribution_fingerprint_does_not_depend_on_where_pillow_is_installed():
    """No absolute path enters the digest.

    Two machines with identical bytes in ``/opt/conda`` and in
    ``C:\\Users\\...`` are the same runtime, and a fingerprint that disagreed
    would make a prepared-image set unshareable for no reason (spec section 24).
    """
    _, fingerprint, _ = pillow_distribution_fingerprint()
    import PIL

    install_root = str(Path(PIL.__file__).resolve().parent)
    assert install_root not in fingerprint
    # A digest is 64 hex characters and can contain no path by construction; the
    # meaningful check is that the recipe never sees one, so re-run it under a
    # changed working directory and compare.
    import os

    previous = os.getcwd()
    os.chdir(Path(previous).anchor or previous)
    try:
        _, again, _ = pillow_distribution_fingerprint()
    finally:
        os.chdir(previous)
    assert again == fingerprint


# ------------------------------------------------- what must move it, and not


def test_the_timestamp_is_outside_the_fingerprint():
    runtime = make_runtime()
    later = dataclasses.replace(runtime, created_utc="2099-01-01T00:00:00+00:00")
    assert later.runtime_fingerprint == runtime.runtime_fingerprint
    assert later.runtime_id == runtime.runtime_id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pillow_version", "12.4.0"),
        ("pillow_distribution_fingerprint", "e" * 64),
        ("pillow_file_count", 124),
        ("dependency_lock_sha256", "f" * 64),
        ("source_revision", "9" * 40),
        ("zlib_runtime_version", "1.3.1"),
        ("python_version", "3.13.0"),
        ("platform_machine", "arm64"),
    ],
)
def test_changing_any_pinned_term_changes_the_fingerprint(field, value):
    runtime = make_runtime()
    changed = _rebuild(runtime, **{field: value})
    assert changed.runtime_fingerprint != runtime.runtime_fingerprint
    assert changed.runtime_id != runtime.runtime_id


def test_a_manifest_must_fingerprint_to_its_own_identity():
    runtime = make_runtime()
    with pytest.raises(ValueError, match="runtime_fingerprint does not cover"):
        dataclasses.replace(runtime, pillow_version="99.0.0")


def test_a_manifest_stored_under_a_foreign_id_is_rejected():
    runtime = make_runtime()
    with pytest.raises(ValueError, match="runtime_id must be derived"):
        dataclasses.replace(runtime, runtime_id="imgruntime_000000000000")


def test_a_dirty_tree_is_recorded_and_refused_at_finalisation():
    """Development may capture a dirty runtime; finalisation may not use one.

    Capturing has to work in a test run from a source tree with edits in it.
    Publishing a preparation from one must not: code that was never committed
    cannot be recovered from a receipt written later (docs/adr/0017).
    """
    from fpbench.core.errors import PreparationFinalizationError
    from fpbench.experiments.preparation_receipt import (
        build_preparation_finalization_marker,
    )

    dirty = SoftwareProvenance(
        provenance_kind="unavailable",
        source_revision="unavailable",
        source_tree_clean=False,
        package_version="0.1.0",
        python_version="3.12.13",
        python_implementation="CPython",
        dependency_versions={"pyarrow": "15.0.0", "pyyaml": "6.0"},
    )
    runtime = capture_transform_runtime(software=dirty)
    assert runtime.source_tree_clean is False

    with pytest.raises(PreparationFinalizationError, match="clean source tree"):
        build_preparation_finalization_marker(
            manifest=None,  # never reached
            profile=None,
            runtime=runtime,
            receipt=None,
            audit=None,
            verifier_runtime=runtime,
            entries_table_content_hash="0" * 64,
            summary_content_hash="0" * 64,
        )


def test_pillow_must_be_installed_for_a_runtime_to_exist(monkeypatch):
    from importlib.metadata import PackageNotFoundError

    def absent(_name):
        raise PackageNotFoundError("Pillow")

    monkeypatch.setattr("importlib.metadata.distribution", absent)
    with pytest.raises(ImagingError, match="not installed"):
        pillow_distribution_fingerprint()
