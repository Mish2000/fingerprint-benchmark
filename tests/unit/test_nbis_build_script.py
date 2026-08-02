"""The rules the NBIS build script exists to enforce (spec sections 3 to 7).

Three of them, and each has a way of failing quietly if nobody checks:

**No silent download.** ``build`` has no code path that opens a socket, ``fetch``
will not run against an unsealed lock, and neither will accept a byte that
disagrees with it. There is no mirror and no fallback host.

**No unsafe extraction.** A single unacceptable entry — an absolute path, a
``..``, a symlink, a hard link, a device node — refuses the whole archive, before
anything is written.

**No behavioural patch.** The series is empty, and the script refuses to apply
one on anybody's behalf.

The script is imported by path because it lives under ``integrations/`` and is
not part of the ``fpbench`` package: it is a tool a person runs, and it stays
runnable without the package being installed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import struct
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from fpbench.core.serialization import write_json
from nbisworld import NBIS_INTEGRATION_DIRECTORY, REPOSITORY_ROOT

pytestmark = pytest.mark.nbis_contract


@pytest.fixture(scope="module")
def build_module():
    spec = importlib.util.spec_from_file_location(
        "fpbench_nbis_build_under_test", NBIS_INTEGRATION_DIRECTORY / "build.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before execution because the script's dataclasses use
    # ``from __future__ import annotations``, and resolving those needs the
    # module to be findable by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------- archive kinds


def clean_zip(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr("nbis/setup.sh", "#!/bin/sh\n")
        bundle.writestr("nbis/README", "hello\n")
    return path


def test_a_zip_a_tar_and_a_gzipped_tar_are_recognised(build_module, tmp_path):
    zipped = clean_zip(tmp_path / "a.zip")
    assert build_module.sniff_archive(zipped) == "zip"

    tarred = tmp_path / "b.tar"
    with tarfile.open(tarred, "w") as bundle:
        bundle.addfile(tarfile.TarInfo("nbis/setup.sh"), io.BytesIO(b""))
    assert build_module.sniff_archive(tarred) == "tar"

    gzipped = tmp_path / "c.tar.gz"
    with tarfile.open(gzipped, "w:gz") as bundle:
        bundle.addfile(tarfile.TarInfo("nbis/setup.sh"), io.BytesIO(b""))
    assert build_module.sniff_archive(gzipped) == "tar.gz"


def test_something_that_is_not_an_archive_is_refused(build_module, tmp_path):
    path = tmp_path / "not-an-archive"
    path.write_bytes(b"this is an HTML error page, not the NIST distribution")
    with pytest.raises(build_module.BuildError, match="not the NIST distribution"):
        build_module.sniff_archive(path)


# ---------------------------------------------------------- safe extraction


def test_a_clean_archive_extracts(build_module, tmp_path):
    archive = clean_zip(tmp_path / "clean.zip")
    root = build_module.safe_extract(archive, tmp_path / "out")
    assert (root / "nbis" / "setup.sh").is_file()


def test_extraction_refuses_a_directory_that_already_exists(build_module, tmp_path):
    archive = clean_zip(tmp_path / "clean.zip")
    (tmp_path / "out").mkdir()
    with pytest.raises(build_module.BuildError, match="already exists"):
        build_module.safe_extract(archive, tmp_path / "out")


@pytest.mark.parametrize(
    "name",
    ["/etc/passwd", "../escape.txt", "nbis/../../escape.txt", "C:\\Windows\\x"],
    ids=["absolute", "parent", "nested-parent", "drive-letter"],
)
def test_a_zip_entry_that_escapes_is_refused(build_module, tmp_path, name):
    archive = tmp_path / "hostile.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nbis/setup.sh", "#!/bin/sh\n")
        bundle.writestr(name, "payload")
    with pytest.raises(build_module.BuildError):
        build_module.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "out" / "nbis").exists() or not (tmp_path / "escape.txt").exists()


def test_a_zip_entry_that_is_a_symlink_is_refused(build_module, tmp_path):
    archive = tmp_path / "linky.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nbis/setup.sh", "#!/bin/sh\n")
        info = zipfile.ZipInfo("nbis/evil")
        info.external_attr = (0o120777 << 16) | 0o20
        bundle.writestr(info, "/etc/passwd")
    with pytest.raises(build_module.BuildError, match="symlink"):
        build_module.safe_extract(archive, tmp_path / "out")


@pytest.mark.parametrize(
    "kind,label",
    [
        (tarfile.SYMTYPE, "link"),
        (tarfile.LNKTYPE, "link"),
        (tarfile.CHRTYPE, "device node"),
        (tarfile.BLKTYPE, "device node"),
        (tarfile.FIFOTYPE, "device node"),
    ],
)
def test_a_tar_entry_that_is_not_a_plain_file_is_refused(
    build_module, tmp_path, kind, label
):
    archive = tmp_path / "hostile.tar"
    with tarfile.open(archive, "w") as bundle:
        ordinary = tarfile.TarInfo("nbis/setup.sh")
        bundle.addfile(ordinary, io.BytesIO(b""))
        member = tarfile.TarInfo("nbis/evil")
        member.type = kind
        member.linkname = "/etc/passwd"
        bundle.addfile(member)
    with pytest.raises(build_module.BuildError, match=label):
        build_module.safe_extract(archive, tmp_path / "out")


def test_a_tar_entry_that_escapes_is_refused(build_module, tmp_path):
    archive = tmp_path / "escape.tar"
    with tarfile.open(archive, "w") as bundle:
        member = tarfile.TarInfo("../escape.txt")
        payload = b"payload"
        member.size = len(payload)
        bundle.addfile(member, io.BytesIO(payload))
    with pytest.raises(build_module.BuildError, match="escapes"):
        build_module.safe_extract(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()


def test_nothing_is_extracted_into_the_repository(build_module, tmp_path):
    """Section 6: never into src/, never into integrations/, never the tree."""
    with pytest.raises(build_module.BuildError, match="inside the repository"):
        build_module._require_outside_repository(REPOSITORY_ROOT / "src")
    with pytest.raises(build_module.BuildError, match="inside the repository"):
        build_module._require_outside_repository(REPOSITORY_ROOT / "integrations")
    build_module._require_outside_repository(tmp_path)


# ---------------------------------------------------------------- the lock


def temporary_lock(build_module, monkeypatch, tmp_path, payload) -> Path:
    path = tmp_path / "nbis-5.0.0.lock.json"
    write_json(path, payload)
    monkeypatch.setattr(build_module, "LOCK_PATH", path)
    return path


def unsealed() -> dict:
    return json.loads(
        (NBIS_INTEGRATION_DIRECTORY / "nbis-5.0.0.lock.json").read_text("utf-8")
    )


def test_the_committed_lock_is_unsealed_until_somebody_records_the_archives():
    payload = unsealed()
    for name in ("release", "tests"):
        assert payload[name]["version"] == "5.0.0"
        assert payload[name]["source"] == "official_nist_nigos"
    assert (payload["release"]["sha256"] is None) == (
        payload["tests"]["sha256"] is None
    )


def test_fetch_refuses_an_unsealed_lock(build_module, monkeypatch, tmp_path, capsys):
    if unsealed()["release"]["sha256"] is not None:  # pragma: no cover
        pytest.skip("the lock has been sealed in this checkout")
    temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    assert build_module.main(["--cache", str(tmp_path / "cache"), "fetch"]) == 2
    assert "never been sealed" in capsys.readouterr().err


def test_build_refuses_an_unsealed_lock(build_module, monkeypatch, tmp_path, capsys):
    if unsealed()["release"]["sha256"] is not None:  # pragma: no cover
        pytest.skip("the lock has been sealed in this checkout")
    temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    assert build_module.main(["--cache", str(tmp_path / "cache"), "build"]) == 2
    assert "never been sealed" in capsys.readouterr().err


def test_sealing_records_the_digest_of_the_bytes_on_disk(
    build_module, monkeypatch, tmp_path, capsys
):
    """Section 4: computed here, never copied from a page or a mirror."""
    lock = temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    release = clean_zip(tmp_path / "release.zip")
    tests = clean_zip(tmp_path / "tests.zip")
    assert (
        build_module.main(
            [
                "seal",
                "--release",
                str(release),
                "--release-url",
                "https://example.invalid/release.zip",
                "--tests",
                str(tests),
                "--tests-url",
                "https://example.invalid/tests.zip",
            ]
        )
        == 0
    )
    payload = json.loads(lock.read_text("utf-8"))
    from fpbench.adapters.nbis.build_manifest import file_digest

    assert payload["release"]["sha256"] == file_digest(release)[0]
    assert payload["release"]["size_bytes"] == release.stat().st_size
    assert payload["tests"]["sha256"] == file_digest(tests)[0]
    capsys.readouterr()


def test_a_sealed_archive_is_never_re_sealed(build_module, monkeypatch, tmp_path, capsys):
    """A change in the bytes NIST published is a review, not a re-run."""
    temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    release = clean_zip(tmp_path / "release.zip")
    build_module.main(
        ["seal", "--release", str(release), "--release-url", "https://a.invalid/x.zip"]
    )
    replacement = tmp_path / "replacement.zip"
    with zipfile.ZipFile(replacement, "w") as bundle:
        bundle.writestr("nbis/setup.sh", "#!/bin/sh\n# different\n")
    assert (
        build_module.main(
            [
                "seal",
                "--release",
                str(replacement),
                "--release-url",
                "https://b.invalid/x.zip",
            ]
        )
        == 2
    )
    assert "already sealed" in capsys.readouterr().err


def test_sealing_without_a_url_is_refused(build_module, monkeypatch, tmp_path, capsys):
    temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    release = clean_zip(tmp_path / "release.zip")
    assert build_module.main(["seal", "--release", str(release)]) == 2
    assert "url is required" in capsys.readouterr().err


def test_sealing_something_that_is_not_an_archive_is_refused(
    build_module, monkeypatch, tmp_path, capsys
):
    temporary_lock(build_module, monkeypatch, tmp_path, unsealed())
    decoy = tmp_path / "decoy.zip"
    decoy.write_bytes(b"<html>404</html>")
    assert (
        build_module.main(
            ["seal", "--release", str(decoy), "--release-url", "https://a.invalid/x"]
        )
        == 2
    )
    capsys.readouterr()


# ------------------------------------------------------------------ policy


def test_the_build_flags_contain_nothing_machine_specific(build_module):
    """Section 9: no -march=native, no -ffast-math, no LTO, no PGO."""
    flags = " ".join(
        [build_module.CFLAGS, build_module.CPPFLAGS, build_module.LDFLAGS]
    )
    for fragment in build_module.FORBIDDEN_FLAG_FRAGMENTS:
        assert fragment not in flags


def test_a_forbidden_flag_in_the_environment_stops_the_build(
    build_module, monkeypatch
):
    monkeypatch.setenv("CFLAGS", "-O3 -march=native")
    with pytest.raises(build_module.BuildError, match="march=native"):
        build_module._require_acceptable_flags()


def test_a_non_empty_patch_series_stops_the_build(build_module, monkeypatch, tmp_path):
    """Section 7: this script never applies a patch on anybody's behalf."""
    series = tmp_path / "series.json"
    write_json(series, {"schema_version": "1", "patches": [{"file": "x.patch"}]})
    monkeypatch.setattr(build_module, "SERIES_PATH", series)
    with pytest.raises(build_module.BuildError, match="not empty"):
        build_module._require_no_patches_touch_behaviour()


def test_the_committed_patch_series_passes_the_same_check(build_module):
    build_module._require_no_patches_touch_behaviour()


# ------------------------------------------------------------- no network


def test_nothing_reaches_the_network_at_import_time():
    """A download during import would happen during pytest collection."""
    import ast

    source = (NBIS_INTEGRATION_DIRECTORY / "build.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            module = getattr(node, "module", "") or ""
            assert "urllib" not in module, module
            assert not any("urllib" in name for name in names), names


def test_the_only_download_is_inside_fetch():
    """``build`` cannot reach the network: the import is local to ``fetch``."""
    import ast

    source = (NBIS_INTEGRATION_DIRECTORY / "build.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    holders = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(inner, (ast.Import, ast.ImportFrom))
            and "urllib" in (getattr(inner, "module", "") or "")
            for inner in ast.walk(node)
        )
    }
    assert holders == {"command_fetch"}, holders


def test_the_probe_images_share_their_pixels(build_module, tmp_path):
    """Section 22: only the pHYs chunk differs between the three PPI probes."""
    images = build_module.probe_pngs(tmp_path)
    rasters = {}
    for name in ("gray8_500ppi", "gray8_1000ppi", "gray8_no_phys"):
        payload = images[name].read_bytes()
        idat = payload.find(b"IDAT")
        rasters[name] = payload[idat:]
    assert len(set(rasters.values())) == 1


def test_the_probe_set_covers_every_rejected_format(build_module, tmp_path):
    images = build_module.probe_pngs(tmp_path)
    assert set(images) == {
        "gray8_500ppi",
        "gray8_1000ppi",
        "gray8_no_phys",
        "gray16",
        "rgb8",
        "indexed8",
        "corrupt",
    }
    header = images["gray8_500ppi"].read_bytes()[16:33]
    width, height, depth, colour = struct.unpack(">IIBB", header[:10])
    assert (depth, colour) == (8, 0)
    assert width == height == 250
