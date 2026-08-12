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


def test_the_committed_evidence_describes_this_machine(
    acquisition: store.AcquisitionState,
) -> None:
    """Compare the marker with the local qualification store when it exists.

    Activation is a deliberate act, and after it the nine execution-dependent
    gates become answerable. If a verified qualification record is present here
    and the committed marker still says otherwise, the evidence is describing a
    different machine — and the response is to re-derive, never to edit.
    """
    import json

    state = store.qualification_run_state(repository_root=REPOSITORY_ROOT)
    marker_path = (
        REPOSITORY_ROOT
        / frozen.EVIDENCE_DIRECTORY
        / frozen.STAGE_11A_FINALIZATION_NAME
    )
    if not marker_path.is_file():
        pytest.skip("the Stage 11A marker has not been published yet")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["qualification_run_performed"] == state.performed, (
        "a qualification record has appeared or disappeared since the marker was "
        "published; run `make stage11a-documents` and `make stage11a-publish` "
        "rather than trusting the committed one"
    )


def test_a_present_record_verifies_or_is_reported_as_not_verifying() -> None:
    """Never skips. A record that does not verify must answer nothing."""
    state = store.qualification_run_state(repository_root=REPOSITORY_ROOT)
    if state.record_present and not state.performed:
        assert state.invalid_reason
        assert state.answers_execution_gates is False


def test_the_qualification_preconditions_are_reportable_here(
    acquisition: store.AcquisitionState,
) -> None:
    """The three named chores, checked against this machine rather than assumed."""
    from fpbench.experiments.stage11a_qualification import (
        PreconditionStatus,
        check_preconditions,
    )

    found = check_preconditions(repository_root=REPOSITORY_ROOT)
    assert found.status is not PreconditionStatus.ARTIFACTS_MISSING, (
        "this suite only runs with the artifacts present, so the precondition "
        "check must agree that they are"
    )


def test_the_harness_compiles_against_the_pinned_bindings_or_says_why(
    acquisition: store.AcquisitionState,
) -> None:
    """The one test that would catch a harness written against an API that moved.

    Skips where there is no Java toolchain, because that is a chore rather than a
    finding — the same distinction the stage itself now draws.
    """
    from fpbench.experiments.stage11a_qualification import (
        PreconditionStatus,
        check_preconditions,
        prepare_installation,
    )

    found = check_preconditions(repository_root=REPOSITORY_ROOT)
    if found.status is PreconditionStatus.JAVA_MISSING:
        pytest.skip(f"no Java toolchain here: {found.detail}")
    import subprocess

    from fpbench.experiments.stage11a_qualification import (
        HARNESS_SOURCE,
        _classpath,
        _clean_environment,
        _java_tool,
        verify_installation_digests,
    )

    install = prepare_installation(repository_root=REPOSITORY_ROOT)
    verified = verify_installation_digests(install)
    assert verified, "every pinned component is re-hashed before anything loads it"

    javac = _java_tool("javac")
    assert javac is not None
    classes = install.parent / "harness-classes"
    classes.mkdir(parents=True, exist_ok=True)
    compiled = subprocess.run(
        (
            javac,
            "-cp",
            _classpath(install),
            "-d",
            str(classes),
            str(REPOSITORY_ROOT / HARNESS_SOURCE),
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=600,
        env=_clean_environment(install),
    )
    assert compiled.returncode == 0, (
        "the harness does not compile against the pinned 2025.2 bindings, so "
        "every API name in it is a guess: "
        + (compiled.stderr or "").strip()[:1500]
    )
    assert (classes / "VeriFingerQualification.class").is_file()


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
