"""The build manifest, the source lock, and what each of them refuses.

A build manifest is the document that turns "we ran NBIS 5.0.0" into something
checkable. Everything below is a way it could be wrong while still looking
plausible: a fingerprint that does not cover its own content, a digest that does
not match the file beside it, a target nobody certified, a test summary that
passed nothing, a libpng the machine supplied.

The source lock's own rule is the one about sealing. An unsealed lock cannot
verify anything, and a sealed one is never re-sealed by re-running a command: a
change in the bytes NIST published is a review, not a retry (spec section 4).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.adapters.nbis.build_manifest import (
    BUILD_MANIFEST_FILENAME,
    EXPECTED_PNG_PPI_POLICY,
    LOCK_FILENAME,
    SUPPORTED_TARGETS,
    NbisBuildManifestError,
    build_script_fingerprint,
    patchset_fingerprint,
    read_build_manifest,
    read_source_lock,
    verify_against_repository,
    verify_against_source_lock,
    verify_build_manifest,
)
from fpbench.core.serialization import write_json
from nbisworld import NBIS_INTEGRATION_DIRECTORY, build_stand_in, certify_host

pytestmark = pytest.mark.nbis_contract


@pytest.fixture(autouse=True)
def certified_host(monkeypatch):
    """Let this machine past the certified-target gate for these tests.

    The gate itself is asserted below and again in ``test_nbis_adapter.py``;
    without this every check in the file would fail for the same unrelated reason
    on any machine that is not Linux x86_64.
    """
    certify_host(monkeypatch)


def rewrite(build, **changes) -> Path:
    """Re-write the stored manifest with fields changed, breaking its signature."""
    payload = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    payload.update(changes)
    write_json(build.manifest_path, payload)
    return build.manifest_path


def resign(build, **changes) -> Path:
    """Re-write the manifest with fields changed *and* a fresh signature.

    For the checks that are not about the fingerprint: a tampered manifest would
    otherwise fail on the signature before reaching the rule under test.
    """
    from fpbench.adapters.nbis.build_manifest import (
        NbisBuildManifest,
        NbisOfficialTestSummary,
    )

    payload = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    payload.update(changes)
    payload.pop("manifest_fingerprint")
    payload["official_test_summary"] = NbisOfficialTestSummary.from_plain(
        payload["official_test_summary"]
    )
    payload["dynamic_dependencies"] = {
        tool: tuple(items) for tool, items in payload["dynamic_dependencies"].items()
    }
    write_json(build.manifest_path, NbisBuildManifest.create(**payload).as_plain())
    return build.manifest_path


# --------------------------------------------------------------- the model


def test_a_freshly_built_manifest_verifies(tmp_path):
    build = build_stand_in(tmp_path / "build")
    verify_build_manifest(
        build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
    )


def test_the_fingerprint_covers_the_content(tmp_path):
    build = build_stand_in(tmp_path / "build")
    manifest = build.manifest()
    assert manifest.manifest_fingerprint == manifest.computed_fingerprint()


def test_the_fingerprint_excludes_the_timestamp_and_itself(tmp_path):
    """Two builds of identical inputs must fingerprint identically."""
    build = build_stand_in(tmp_path / "build")
    content = build.manifest().fingerprinted_content()
    assert "created_utc" not in content
    assert "manifest_fingerprint" not in content


def test_a_tampered_field_breaks_the_fingerprint(tmp_path):
    build = build_stand_in(tmp_path / "build")
    rewrite(build, compiler_version="something else")
    with pytest.raises(NbisBuildManifestError, match="fingerprint"):
        verify_build_manifest(
            read_build_manifest(build.manifest_path),
            mindtct=build.mindtct,
            bozorth3=build.bozorth3,
        )


def test_an_unknown_key_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build")
    rewrite(build, surprise="value")
    with pytest.raises(NbisBuildManifestError, match="unknown keys"):
        read_build_manifest(build.manifest_path)


def test_a_missing_key_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build")
    payload = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    del payload["png_ppi_policy"]
    write_json(build.manifest_path, payload)
    with pytest.raises(NbisBuildManifestError, match="missing"):
        read_build_manifest(build.manifest_path)


@pytest.mark.parametrize(
    "value",
    ["/home/someone/build", "C:\\Users\\someone\\build", "/tmp/nbis"],
)
def test_a_local_path_in_a_field_is_refused(tmp_path, value):
    """Section 10: a manifest records what was built, never where."""
    build = build_stand_in(tmp_path / "build")
    rewrite(build, cflags=f"-O2 -I{value}")
    with pytest.raises(NbisBuildManifestError, match="local path"):
        read_build_manifest(build.manifest_path)


# ------------------------------------------------------- against the files


def test_a_replaced_executable_is_caught(tmp_path):
    build = build_stand_in(tmp_path / "build")
    build.mindtct.write_bytes(build.mindtct.read_bytes() + b"\n")
    with pytest.raises(NbisBuildManifestError, match="mindtct"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_a_missing_executable_is_caught(tmp_path):
    build = build_stand_in(tmp_path / "build")
    build.bozorth3.unlink()
    with pytest.raises(NbisBuildManifestError, match="bozorth3"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


# ------------------------------------------------------ acceptance clauses


def test_an_uncertified_target_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build", target=("darwin", "arm64"))
    with pytest.raises(NbisBuildManifestError, match="certified"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_the_certified_target_is_linux_x86_64():
    assert SUPPORTED_TARGETS == frozenset({("linux", "x86_64")})


def test_a_build_without_png_support_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build", png_support_compiled=False)
    with pytest.raises(NbisBuildManifestError, match="PNG support"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_an_unverified_gray8_path_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build", direct_gray8_png_verified=False)
    with pytest.raises(NbisBuildManifestError, match="greyscale PNG"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_a_different_ppi_policy_is_refused(tmp_path):
    """Section 22: the policy is measured, and only one measurement is usable."""
    build = build_stand_in(tmp_path / "build", png_ppi_policy="metadata_changes_extraction")
    with pytest.raises(NbisBuildManifestError, match="png_ppi_policy"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )
    assert EXPECTED_PNG_PPI_POLICY == "metadata_ignored_default_500"


@pytest.mark.parametrize("tolerated", ["rgb8", "corrupt"])
def test_a_build_that_accepts_a_pixel_changing_png_is_refused(tmp_path, tolerated):
    """Section 41: truecolour flattened, or unreadable turned into a template.

    16-bit and indexed are deliberately not here — the certified build accepts
    both, because libpng converts them, and the adapter is what refuses them
    (docs/adr/0048).
    """
    remaining = ",".join(sorted({"corrupt", "rgb8"} - {tolerated}))
    build = build_stand_in(
        tmp_path / "build", png_formats_refused_by_build=remaining
    )
    with pytest.raises(NbisBuildManifestError, match="the build accepts"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_the_measured_tolerances_are_recorded_rather_than_refused(tmp_path):
    """A build that tolerates 16-bit and indexed is still certifiable."""
    build = build_stand_in(
        tmp_path / "build", png_formats_refused_by_build="corrupt,rgb8"
    )
    verify_build_manifest(
        build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
    )
    assert build.manifest().png_formats_refused_by_build == "corrupt,rgb8"


def test_a_failing_official_test_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build", failed_tests=1)
    with pytest.raises(NbisBuildManifestError, match="official NIST tests"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_a_partly_executed_suite_is_refused(tmp_path):
    """Section 40: executed must equal discovered, or half a suite passed."""
    build = build_stand_in(tmp_path / "build", discovered_tests=12, executed_tests=6)
    with pytest.raises(NbisBuildManifestError, match="official NIST tests"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_an_empty_suite_is_not_a_pass(tmp_path):
    build = build_stand_in(tmp_path / "build", discovered_tests=0, executed_tests=0)
    with pytest.raises(NbisBuildManifestError, match="official NIST tests"):
        verify_build_manifest(
            build.manifest(), mindtct=build.mindtct, bozorth3=build.bozorth3
        )


def test_a_summary_whose_counts_do_not_add_up_is_refused(tmp_path):
    build = build_stand_in(tmp_path / "build")
    payload = json.loads(build.manifest_path.read_text(encoding="utf-8"))
    payload["official_test_summary"]["passed_tests"] = 3
    write_json(build.manifest_path, payload)
    with pytest.raises(NbisBuildManifestError, match=r"passed \+ failed"):
        read_build_manifest(build.manifest_path)


@pytest.mark.parametrize(
    "library", ["libpng16.so.16", "libz.so.1", "libfing.so"]
)
def test_a_forbidden_dynamic_dependency_is_refused(tmp_path, library):
    """Section 9: the bundle must own the code that produced the score."""
    build = build_stand_in(tmp_path / "build")
    resign(
        build,
        dynamic_dependencies={"mindtct": ["libc.so.6", library], "bozorth3": []},
    )
    with pytest.raises(NbisBuildManifestError, match="dynamically"):
        verify_build_manifest(
            read_build_manifest(build.manifest_path),
            mindtct=build.mindtct,
            bozorth3=build.bozorth3,
        )


def test_platform_base_libraries_are_allowed(tmp_path):
    """libc, libm, the loader and the compiler runtime may stay dynamic."""
    build = build_stand_in(tmp_path / "build")
    resign(
        build,
        dynamic_dependencies={
            "mindtct": [
                "libc.so.6",
                "libm.so.6",
                "ld-linux-x86-64.so.2",
                "libgcc_s.so.1",
            ],
            "bozorth3": ["libc.so.6"],
        },
    )
    verify_build_manifest(
        read_build_manifest(build.manifest_path),
        mindtct=build.mindtct,
        bozorth3=build.bozorth3,
    )


# ---------------------------------------------------------------- the lock


def test_the_committed_lock_reads_and_is_for_5_0_0():
    lock = read_source_lock(NBIS_INTEGRATION_DIRECTORY / LOCK_FILENAME)
    assert lock.release.version == "5.0.0"
    assert lock.tests.version == "5.0.0"
    assert lock.release.source == "official_nist_nigos"
    assert lock.tests.source == "official_nist_nigos"


def test_an_unsealed_lock_verifies_nothing(tmp_path):
    """It is a promise to check, not a check (spec section 4)."""
    path = tmp_path / LOCK_FILENAME
    entry = {
        "version": "5.0.0",
        "source": "official_nist_nigos",
        "url": None,
        "sha256": None,
        "size_bytes": 0,
    }
    write_json(
        path,
        {"schema_version": "1", "release": dict(entry), "tests": dict(entry)},
    )
    build = build_stand_in(tmp_path / "build")
    with pytest.raises(NbisBuildManifestError, match="never been sealed"):
        verify_against_source_lock(build.manifest(), read_source_lock(path))


def test_the_committed_lock_is_sealed_to_the_official_archives():
    """Section 59: both archives' digests and sizes are pinned."""
    lock = read_source_lock(NBIS_INTEGRATION_DIRECTORY / LOCK_FILENAME)
    assert lock.is_sealed
    for entry in (lock.release, lock.tests):
        assert entry.url.startswith("https://nigos.nist.gov/nist/nbis/")
        assert entry.size_bytes > 0


def test_a_sealed_lock_must_agree_with_the_manifest(tmp_path):
    sealed = tmp_path / LOCK_FILENAME
    write_json(
        sealed,
        {
            "schema_version": "1",
            "release": {
                "version": "5.0.0",
                "source": "official_nist_nigos",
                "url": "https://example.invalid/nbis.zip",
                "sha256": "a" * 64,
                "size_bytes": 1,
            },
            "tests": {
                "version": "5.0.0",
                "source": "official_nist_nigos",
                "url": "https://example.invalid/nbis-tests.zip",
                "sha256": "b" * 64,
                "size_bytes": 1,
            },
        },
    )
    build = build_stand_in(tmp_path / "build")
    with pytest.raises(NbisBuildManifestError, match="locked NBIS sources"):
        verify_against_source_lock(build.manifest(), read_source_lock(sealed))


def test_a_lock_for_another_version_is_refused(tmp_path):
    path = tmp_path / LOCK_FILENAME
    write_json(
        path,
        {
            "schema_version": "1",
            "release": {
                "version": "4.2.0",
                "source": "official_nist_nigos",
                "url": None,
                "sha256": None,
                "size_bytes": 0,
            },
            "tests": {
                "version": "5.0.0",
                "source": "official_nist_nigos",
                "url": None,
                "sha256": None,
                "size_bytes": 0,
            },
        },
    )
    with pytest.raises(NbisBuildManifestError, match="certifies"):
        read_source_lock(path)


# ------------------------------------------------------------ the patchset


def test_the_committed_patch_series_is_empty():
    """Section 7: no patches, and the fingerprint of that is in every manifest."""
    payload = json.loads(
        (NBIS_INTEGRATION_DIRECTORY / "patches" / "series.json").read_text("utf-8")
    )
    assert payload == {"schema_version": "1", "patches": []}


def test_the_patchset_fingerprint_is_stable():
    series = NBIS_INTEGRATION_DIRECTORY / "patches" / "series.json"
    assert patchset_fingerprint(series) == patchset_fingerprint(series)


def test_a_patch_series_naming_a_missing_file_is_refused(tmp_path):
    series = tmp_path / "series.json"
    write_json(series, {"schema_version": "1", "patches": [{"file": "absent.patch"}]})
    with pytest.raises(NbisBuildManifestError, match="does not exist"):
        patchset_fingerprint(series)


def test_a_patch_series_escaping_its_directory_is_refused(tmp_path):
    series = tmp_path / "series.json"
    write_json(
        series, {"schema_version": "1", "patches": [{"file": "../../etc/passwd"}]}
    )
    with pytest.raises(NbisBuildManifestError, match="plain file"):
        patchset_fingerprint(series)


def test_the_build_script_fingerprint_covers_both_scripts(tmp_path):
    first = build_script_fingerprint(NBIS_INTEGRATION_DIRECTORY)
    copy = tmp_path / "integration"
    copy.mkdir()
    for name in ("build.py", "verify_build.py"):
        (copy / name).write_bytes((NBIS_INTEGRATION_DIRECTORY / name).read_bytes())
    assert build_script_fingerprint(copy) == first
    (copy / "verify_build.py").write_text("# changed\n", encoding="utf-8")
    assert build_script_fingerprint(copy) != first


def test_the_repository_check_covers_lock_patches_and_scripts(tmp_path):
    build = build_stand_in(tmp_path / "build")
    with pytest.raises(NbisBuildManifestError):
        verify_against_repository(
            build.manifest(), integration_directory=NBIS_INTEGRATION_DIRECTORY
        )


def test_the_manifest_filename_is_the_one_the_layout_names():
    assert BUILD_MANIFEST_FILENAME == "nbis-build-manifest.json"
