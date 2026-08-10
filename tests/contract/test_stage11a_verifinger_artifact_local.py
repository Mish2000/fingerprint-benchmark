"""The Stage 11A checks that need the real VeriFinger artifacts on this machine.

Marked ``verifinger_artifact`` and excluded from the public CI, which downloads
nothing (spec section 42). These are the tests that keep the published record
honest about the world rather than only about itself: the contract suite proves
the code agrees with its constants, and this file proves the constants agree with
four and a half gigabytes of somebody else's bytes.

Set ``FPBENCH_THIRD_PARTY_ROOT`` — or accept the default under the user's home —
and place the two acquired artifacts under this stage's prefix. Every test here
skips while they are absent, because absence is a legitimate state of any
checkout and not a finding about the stage.

Nothing in this file imports a vendor library, activates a licence, prints a
licence value or produces a score. The gates that would do those things are the
ones this stage published as unreached.
"""

from __future__ import annotations

import hashlib
import zipfile

import pytest

from fpbench.experiments import stage11a_artifacts as store
from fpbench.experiments import stage11a_verifinger_identity as frozen
from fpbench.experiments import stage11a_verifinger_observations as observed
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.verifinger_artifact


@pytest.fixture(scope="module")
def acquisition() -> store.AcquisitionState:
    state = store.acquisition_state(repository_root=REPOSITORY_ROOT)
    if not state.obtained:
        pytest.skip(
            "the VeriFinger 2025.2 artifacts are not in the local artifact "
            "store; acquire them from the locators in acquisition-manifest.json "
            f"into {frozen.ARTIFACT_STORE_PREFIX}/"
        )
    return state


@pytest.fixture(scope="module")
def archive(acquisition: store.AcquisitionState) -> zipfile.ZipFile:
    path = (
        store.artifact_store_prefix_path(repository_root=REPOSITORY_ROOT)
        / observed.SDK_ARCHIVE.filename
    )
    with zipfile.ZipFile(path) as handle:
        yield handle


def test_both_artifacts_verify_by_size_and_digest(
    acquisition: store.AcquisitionState,
) -> None:
    assert acquisition.unverified == ()
    for state in acquisition.states:
        assert state.presence is store.ArtifactPresence.VERIFIED


def test_the_standalone_manual_is_the_manual_inside_the_archive(
    archive: zipfile.ZipFile,
) -> None:
    """The claim that makes citing the documentation safe.

    A manual downloaded beside an archive could describe a different build. This
    one does not, and the check is a digest rather than a version string.
    """
    member = next(
        item
        for item in observed.CITED_ARCHIVE_MEMBERS
        if item.relative_path.endswith("Neurotechnology Biometric SDK.pdf")
    )
    digest = hashlib.sha256()
    with archive.open(member.relative_path) as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    assert digest.hexdigest() == member.sha256
    assert digest.hexdigest() == observed.DOCUMENTATION_PDF.sha256


def test_every_cited_member_is_in_the_archive_at_the_recorded_size_and_digest(
    archive: zipfile.ZipFile,
) -> None:
    """Every digest this stage published, checked against the bytes it names."""
    for member in (
        *observed.CITED_ARCHIVE_MEMBERS,
        *observed.FINGER_DATA_FILES,
        *observed.JAVA_BINDING_JARS,
    ):
        info = archive.getinfo(member.relative_path)
        assert info.file_size == member.size_bytes, member.relative_path
        digest = hashlib.sha256()
        with archive.open(info) as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        assert digest.hexdigest() == member.sha256, member.relative_path


def test_every_cited_native_library_matches(archive: zipfile.ZipFile) -> None:
    for library in observed.WINDOWS_X64_NATIVE_LIBRARIES:
        info = archive.getinfo(library.relative_path)
        assert info.file_size == library.size_bytes, library.relative_path
        digest = hashlib.sha256()
        with archive.open(info) as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
        assert digest.hexdigest() == library.sha256, library.relative_path


def test_the_archive_holds_the_member_count_and_size_that_were_published(
    archive: zipfile.ZipFile,
) -> None:
    members = [item for item in archive.infolist() if not item.is_dir()]
    assert len(members) == observed.ARCHIVE_MEMBER_COUNT
    assert sum(item.file_size for item in members) == (
        observed.ARCHIVE_UNCOMPRESSED_BYTES
    )


def test_the_main_archive_really_ships_no_python_binding(
    archive: zipfile.ZipFile,
) -> None:
    """A negative claim, checked rather than asserted."""
    names = [name.lower() for name in archive.namelist()]
    root = "neurotec_biometric_2025_2_sdk/bin/"
    python_dirs = {
        name[len(root) :].split("/")[0]
        for name in names
        if name.startswith(root) and "python" in name[len(root) :].split("/")[0]
    }
    assert not python_dirs
    assert observed.PYTHON_BINDING_IN_MAIN_SDK is False


def test_the_fingerprint_data_files_are_the_only_finger_models_needed(
    archive: zipfile.ZipFile,
) -> None:
    """The closure claim: the fingerprint models are inside the pinned bytes."""
    data = [
        name
        for name in archive.namelist()
        if "/Bin/Data/" in name and name.endswith(".ndf")
    ]
    finger = {name for name in data if "Finger" in name.split("/")[-1]}
    assert finger == {item.relative_path for item in observed.FINGER_DATA_FILES}


def test_nothing_here_activated_a_licence() -> None:
    """Never skips.

    The trial flag ships enabled and activation is a separate, deliberate act. If
    a licence has been activated on this machine, the published evidence is
    describing a different machine and the stage should be re-derived rather than
    read off disk.
    """
    state = store.qualification_run_state(repository_root=REPOSITORY_ROOT)
    if state.answers_execution_gates:
        pytest.fail(
            "a qualification record is present, so the execution gates are now "
            "answerable; re-run `make stage11a-documents` and "
            "`make stage11a-publish` rather than trusting the committed marker"
        )


def test_no_vendor_material_is_reachable_from_the_working_tree() -> None:
    """Never skips.

    An archive extracted into the checkout is the ordinary way vendor bytes end
    up tracked. This looks for the shapes anywhere under the working tree,
    tracked or not.
    """
    stray = sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for pattern in ("*.ndf", "*.lic", "Neurotec_Biometric_*")
        for path in REPOSITORY_ROOT.rglob(pattern)
        if path.is_file()
    )
    assert stray == [], (
        "Neurotechnology material is inside the working tree; it belongs in the "
        "artifact store, outside the repository (docs/adr/0083)"
    )
