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
import shutil
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


def test_a_forbidden_flag_is_refused_wherever_it_comes_from(build_module):
    """Section 9: no -march=native, no -ffast-math, no LTO, no PGO."""
    for fragment in build_module.FORBIDDEN_FLAG_FRAGMENTS:
        with pytest.raises(build_module.BuildError, match="depend on"):
            build_module.require_acceptable_flags(**{"the build's CFLAGS": f"-O2 {fragment}"})


def test_a_forbidden_flag_in_the_environment_stops_the_build(
    build_module, monkeypatch
):
    monkeypatch.setenv("CFLAGS", "-O3 -march=native")
    with pytest.raises(build_module.BuildError, match="march=native"):
        build_module._require_acceptable_environment_flags()


def test_acceptable_flags_pass(build_module):
    build_module.require_acceptable_flags(
        **{"the build's CFLAGS": "-O2 -w -ansi -D_POSIX_SOURCE -D__NBIS_PNG__ -m64"}
    )


# ------------------------------------------------------- compiler provenance
#
# The compiler that is probed, the compiler that is invoked and the compiler that
# is recorded have to be one compiler. NBIS makes that harder than it sounds:
# ``setup.sh`` compiles its endianness probe with a literal ``gcc``, and
# ``rules.mak`` assigns ``CC := $(shell which gcc)``. Overriding ``CC`` on the
# make command line alone leaves both of those free to pick something else.


def stand_in_compiler(directory: Path, name: str, log: Path) -> Path:
    """A fake compiler that says who it is and records every invocation."""
    directory.mkdir(parents=True, exist_ok=True)
    tool = directory / f"{name}.py"
    tool.write_text(
        "import sys, pathlib\n"
        f"log = pathlib.Path(r'{log}')\n"
        "log.parent.mkdir(parents=True, exist_ok=True)\n"
        f"log.open('a').write('{name} ' + ' '.join(sys.argv[1:]) + chr(10))\n"
        "argv = sys.argv[1:]\n"
        "if '--version' in argv:\n"
        f"    print('cc ({name}) 1.2.3')\n"
        "elif '-dumpmachine' in argv:\n"
        f"    print('{name}-unknown-linux-gnu')\n"
        "else:\n"
        "    out = argv[argv.index('-o') + 1] if '-o' in argv else 'a.out'\n"
        "    pathlib.Path(out).write_text('linked')\n"
        "sys.exit(0)\n",
        encoding="ascii",
    )
    if os.name == "nt":
        launcher = directory / f"{name}.bat"
        launcher.write_text(
            '@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, tool), encoding="ascii"
        )
        return launcher
    launcher = directory / name
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{tool}" "$@"\n', encoding="ascii"
    )
    launcher.chmod(0o755)
    return launcher


def test_the_compiler_probed_is_the_one_cc_names(build_module, tmp_path, monkeypatch):
    alpha_log, beta_log = tmp_path / "alpha.log", tmp_path / "beta.log"
    stand_in_compiler(tmp_path / "bin", "alpha", alpha_log)
    beta = stand_in_compiler(tmp_path / "bin", "beta", beta_log)

    monkeypatch.setenv("CC", str(beta))
    compiler = build_module.resolve_compiler()

    assert compiler.executable == beta.resolve()
    assert compiler.version == "cc (beta) 1.2.3"
    assert compiler.target == "beta-unknown-linux-gnu"
    assert compiler.identity == "gcc"
    assert beta_log.is_file()
    assert not alpha_log.exists(), "the compiler that was not chosen was invoked"


def test_a_bare_cc_name_is_resolved_on_path(build_module, tmp_path, monkeypatch):
    log = tmp_path / "beta.log"
    beta = stand_in_compiler(tmp_path / "bin", "beta", log)
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CC", beta.stem if os.name == "nt" else "beta")
    compiler = build_module.resolve_compiler()
    assert compiler.executable == beta.resolve()


def test_a_cc_that_does_not_exist_is_refused(build_module, tmp_path, monkeypatch):
    monkeypatch.setenv("CC", str(tmp_path / "no-such-compiler"))
    with pytest.raises(build_module.BuildError, match="not an executable"):
        build_module.resolve_compiler()


def test_a_cc_that_is_not_on_path_is_refused(build_module, monkeypatch):
    monkeypatch.setenv("CC", "definitely-not-a-compiler-fpbench")
    with pytest.raises(build_module.BuildError, match="not on PATH"):
        build_module.resolve_compiler()


def test_make_is_told_the_compiler_and_never_the_flags(build_module, tmp_path):
    """Section 10: ``CFLAGS=`` on the command line would replace NBIS's own line.

    ``rules.mak`` builds ``CFLAGS`` out of feature macros including
    ``-D__NBIS_PNG__``. Overriding it would build an NBIS without the one thing
    this route cannot do without, and nothing would say so.
    """
    compiler = build_module.Compiler(
        executable=Path("/usr/bin/gcc-9").resolve() if os.name != "nt" else Path("C:/gcc"),
        identity="gcc",
        version="gcc 9.5.0",
        target="x86_64-linux-gnu",
        extra_flags=("-fcommon",),
    )
    argv = build_module.make_command("it", compiler)
    assert argv[:2] == ["make", "it"]
    assert argv[2] == f"CC={compiler.command}"
    assert "-fcommon" in argv[2]
    joined = " ".join(argv)
    assert "CFLAGS=" not in joined
    assert "LDFLAGS=" not in joined
    assert "CPPFLAGS=" not in joined


@pytest.mark.skipif(
    os.name == "nt", reason="the compiler shim is a POSIX shell stub"
)
def test_the_shim_makes_a_bare_gcc_the_chosen_compiler(
    build_module, tmp_path, monkeypatch
):
    """``setup.sh`` and ``rules.mak`` both resolve a bare name; the shim settles it."""
    alpha_log, beta_log = tmp_path / "alpha.log", tmp_path / "beta.log"
    alpha = stand_in_compiler(tmp_path / "bin", "alpha", alpha_log)
    beta = stand_in_compiler(tmp_path / "bin", "beta", beta_log)
    # alpha is what a bare name would otherwise find.
    (tmp_path / "bin" / "gcc").symlink_to(alpha)
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CC", str(beta))

    compiler = build_module.resolve_compiler()
    alpha_log.unlink(missing_ok=True)
    beta_log.unlink(missing_ok=True)

    shim = build_module.compiler_shim(tmp_path / "shim", compiler)
    for name in ("gcc", "cc"):
        build_module.run([name, "--version"], cwd=tmp_path, extra_path=shim)
    assert beta_log.is_file()
    assert not alpha_log.exists(), "a bare name still reached the wrong compiler"


@pytest.mark.skipif(
    os.name == "nt", reason="NBIS's build is driven by sh and make"
)
def test_probed_invoked_and_recorded_are_one_compiler(
    build_module, tmp_path, monkeypatch
):
    """The whole claim, over a source tree shaped like NBIS's.

    ``setup.sh`` compiles with a literal ``gcc`` exactly as NBIS's does, the
    makefile records ``$(CC)`` exactly as NBIS's rules do, and a second compiler
    sits on PATH ready to be picked by mistake. Only one of them may appear in the
    log, and it has to be the one the manifest will name.
    """
    if shutil.which("make") is None:
        pytest.skip("make is not installed")

    alpha_log, beta_log = tmp_path / "alpha.log", tmp_path / "beta.log"
    alpha = stand_in_compiler(tmp_path / "bin", "alpha", alpha_log)
    stand_in_compiler(tmp_path / "bin", "beta", beta_log)
    (tmp_path / "bin" / "gcc").symlink_to(alpha)
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("CC", str(tmp_path / "bin" / "beta"))

    source = tmp_path / "source"
    source.mkdir()
    # NBIS's own shape: setup.sh uses a literal gcc for its endianness probe and
    # writes rules.mak; rules.mak assigns CC from `which gcc`.
    (source / "setup.sh").write_text(
        "#!/bin/sh\n"
        "CC=gcc\n"
        "$CC am_big_endian.c -o am_big_endian\n"
        "printf 'CC := $(shell which gcc)\\n"
        "CFLAGS := -O2 -w -ansi -D_POSIX_SOURCE -D__NBIS_PNG__ -m64\\n"
        "CDEFS :=\\n"
        "LDFLAGS := -m64\\n' > rules.mak\n",
        encoding="ascii",
    )
    (source / "setup.sh").chmod(0o755)
    (source / "am_big_endian.c").write_text("int main(void){return 0;}\n")
    (source / "Makefile").write_text(
        "include rules.mak\n"
        "config it install:\n"
        "\t@$(CC) -c compiling-$@\n",
        encoding="ascii",
    )

    compiler = build_module.resolve_compiler()
    alpha_log.unlink(missing_ok=True)
    beta_log.unlink(missing_ok=True)

    flags = build_module.compile_nbis(
        source_root=source,
        install_root=tmp_path / "install",
        compiler=compiler,
        shim=build_module.compiler_shim(tmp_path / "shim", compiler),
    )

    assert not alpha_log.exists(), (
        f"the wrong compiler was invoked: {alpha_log.read_text()}"
    )
    invoked = beta_log.read_text(encoding="ascii")
    assert "am_big_endian.c" in invoked, "setup.sh used a different compiler"
    for target in ("config", "it", "install"):
        assert f"compiling-{target}" in invoked, f"make {target} used another compiler"

    # And what would be recorded is that same compiler, with NBIS's own flags.
    inputs = build_module.collect_build_inputs(_sealed_lock(build_module), compiler)
    assert inputs.compiler_version == compiler.version == "cc (beta) 1.2.3"
    assert inputs.compiler_target == "beta-unknown-linux-gnu"
    assert "-D__NBIS_PNG__" in flags["CFLAGS"], (
        "the feature macro NBIS's own rules.mak defines was lost"
    )


def _sealed_lock(build_module):
    from fpbench.adapters.nbis.build_manifest import NbisArchiveLock, NbisSourceLock

    archive = NbisArchiveLock(
        version="5.0.0",
        source="official_nist_nigos",
        url="https://example.invalid/x.zip",
        sha256="a" * 64,
        size_bytes=1,
    )
    return NbisSourceLock(schema_version="1", release=archive, tests=archive)


def test_the_build_id_covers_the_compiler(build_module):
    """A different compiler is a different build, in a different directory."""
    lock = _sealed_lock(build_module)
    first = build_module.collect_build_inputs(
        lock,
        build_module.Compiler(Path("/a"), "gcc", "gcc 9.5.0", "x86_64-linux-gnu"),
    )
    second = build_module.collect_build_inputs(
        lock,
        build_module.Compiler(Path("/a"), "gcc", "gcc 13.3.0", "x86_64-linux-gnu"),
    )
    third = build_module.collect_build_inputs(
        lock,
        build_module.Compiler(
            Path("/a"), "gcc", "gcc 9.5.0", "x86_64-linux-gnu", ("-fcommon",)
        ),
    )
    assert len({first.build_id, second.build_id, third.build_id}) == 3


def test_the_build_id_does_not_cover_the_compiler_path(build_module):
    """Where a machine keeps its compiler is not part of what a build is."""
    lock = _sealed_lock(build_module)
    here = build_module.collect_build_inputs(
        lock, build_module.Compiler(Path("/usr/bin/gcc"), "gcc", "v", "t")
    )
    there = build_module.collect_build_inputs(
        lock, build_module.Compiler(Path("/opt/tools/gcc"), "gcc", "v", "t")
    )
    assert here.build_id == there.build_id
    assert "/usr/bin" not in json.dumps(here.as_plain())


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
