"""The Stage 13A checks that need the delivered FingerCell archive on this machine.

Marked ``fingercell_artifact`` and excluded from the public CI, which fetches
nothing, activates nothing and holds no credential. Every test here skips while
the store is empty, and an empty store is a legitimate state: the acquisition
gate then reports ``ACTION_REQUIRED`` and says exactly what has not been done.

Set ``FPBENCH_THIRD_PARTY_ROOT`` and place the official trial archive under this
stage's prefix, together with the declaration that says what it is and where it
came from.

Nothing in this file loads a vendor module, activates a licence, prints a licence
value or produces a score. Reading a delivered header, a delivered sample and a
delivered text file is all these tests do — which is the same footing the
evidence stands on.
"""

from __future__ import annotations

import pytest

from fpbench.experiments import stage13a_acquisition as store
from fpbench.experiments import stage13a_fingercell_identity as frozen
from fpbench.experiments import stage13a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.fingercell_artifact


@pytest.fixture(scope="module")
def state() -> store.AcquisitionState:
    found = store.acquisition_state(repository_root=REPOSITORY_ROOT)
    if found.presence is store.ArtifactPresence.ABSENT:
        pytest.skip(
            "no FingerCell material is in the local artifact store; set "
            "FPBENCH_THIRD_PARTY_ROOT and place the official trial archive under "
            f"{frozen.ARTIFACT_STORE_PREFIX}/ together with "
            f"{store.ARCHIVE_DECLARATION_NAME}"
        )
    return found


@pytest.fixture(scope="module")
def unpacked():
    root = store.unpacked_root(repository_root=REPOSITORY_ROOT)
    if not root.is_dir():
        pytest.skip("the trial archive has not been unpacked in the store")
    return root


def test_bytes_with_no_declaration_are_never_treated_as_a_delivery(
    state: store.AcquisitionState,
) -> None:
    """An archive nobody recorded the provenance of cannot be pinned to a vendor."""
    if state.presence is store.ArtifactPresence.UNDECLARED:
        assert state.obtained is False
        assert engine.run_preflight().status(
            frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION
        ) is frozen.GateStatus.ACTION_REQUIRED


def test_the_declared_archive_verifies_by_size_and_then_by_digest(
    state: store.AcquisitionState,
) -> None:
    if state.presence is not store.ArtifactPresence.VERIFIED:
        pytest.skip(f"the store is {state.presence.value}")
    declaration = state.declaration
    assert declaration is not None
    assert declaration.size_bytes > 0
    assert len(declaration.sha256) == 64
    assert declaration.sha256 != declaration.vendor_revision_hash


def test_the_delivered_archive_is_the_expected_product(
    state: store.AcquisitionState,
) -> None:
    if state.declaration is None:
        pytest.skip("nothing is declared")
    assert state.declaration.is_the_expected_product
    assert state.declaration.product == frozen.PRODUCT_FAMILY
    assert state.declaration.product_version == frozen.DECLARED_PRODUCT_VERSION


def test_the_delivered_revision_stamp_agrees_with_the_public_release_notes(
    state: store.AcquisitionState, unpacked
) -> None:
    """The archive settles the revision; the release notes only indicated it."""
    if state.declaration is None:
        pytest.skip("nothing is declared")
    stamp = unpacked / "FingerCell_3_3_SDK" / "Revision.txt"
    if not stamp.is_file():
        pytest.skip("the delivered revision stamp is not in the unpacked tree")
    text = stamp.read_text(encoding="utf-8", errors="replace")
    assert frozen.VENDOR_PRODUCT_REVISION_INDICATION in text
    assert frozen.VENDOR_REVISION_HASH_INDICATION in text
    assert state.declaration.revision_agrees_with_release_notes


def test_the_delivered_header_defines_reference_and_candidate(unpacked) -> None:
    """The words the frozen pair binding uses come from the API under test."""
    header = unpacked / "FingerCell_3_3_SDK" / "Include" / "FingerCell.h"
    if not header.is_file():
        pytest.skip("the delivered C header is not in the unpacked tree")
    text = header.read_text(encoding="utf-8", errors="replace")
    assert "FingerCellMatch" in text
    assert "hReference" in text
    assert "hCandidate" in text
    assert "FingerCellExtract" in text
    roles = {right for _, right in frozen.PAIR_ROLE_BINDING}
    assert roles == {"reference", "candidate"}


def test_the_delivered_binding_documents_the_score_direction(unpacked) -> None:
    header = unpacked / "FingerCell_3_3_SDK" / "Include" / "FingerCell.hpp"
    if not header.is_file():
        pytest.skip("the delivered C++ header is not in the unpacked tree")
    text = header.read_text(encoding="utf-8", errors="replace").lower()
    assert "the bigger the score is" in text
    assert frozen.SCORE_DIRECTION == "HIGHER_IS_MORE_SIMILAR"


def test_the_delivered_template_format_enumeration_defaults_to_proprietary(
    unpacked,
) -> None:
    header = unpacked / "FingerCell_3_3_SDK" / "Include" / "FingerCell.h"
    if not header.is_file():
        pytest.skip("the delivered C header is not in the unpacked tree")
    text = header.read_text(encoding="utf-8", errors="replace")
    assert "fctfProprietary = 0" in text
    assert frozen.REQUIRED_TEMPLATE_FORMAT is frozen.TemplateFormat.PROPRIETARY


def test_the_delivered_api_offers_merging_which_this_stage_refuses(
    unpacked,
) -> None:
    """Refusing merging is a protocol choice, not an absence in the SDK."""
    header = unpacked / "FingerCell_3_3_SDK" / "Include" / "FingerCell.h"
    if not header.is_file():
        pytest.skip("the delivered C header is not in the unpacked tree")
    text = header.read_text(encoding="utf-8", errors="replace")
    assert "FingerCellMergeTemplates" in text
    assert "MergeTemplates" in frozen.REFUSED_TEMPLATE_CONSTRUCTIONS


def test_the_official_tutorial_reads_the_score_with_no_threshold(unpacked) -> None:
    tutorial = (
        unpacked
        / "FingerCell_3_3_SDK"
        / "Tutorials"
        / "FingerCell"
        / "CPP"
        / "FCVerifyFingerCPP"
        / "FCVerifyFingerCPP.cpp"
    )
    if not tutorial.is_file():
        pytest.skip("the delivered verification tutorial is not in the unpacked tree")
    text = tutorial.read_text(encoding="utf-8", errors="replace")
    assert "Match(" in text
    assert "NInt score" in text
    assert "threshold" not in text.lower()


def test_the_official_route_obtains_a_fingercell_specific_entitlement(
    unpacked,
) -> None:
    """A running licensing service for the sibling product proves nothing here."""
    tutorial = (
        unpacked
        / "FingerCell_3_3_SDK"
        / "Tutorials"
        / "FingerCell"
        / "CPP"
        / "FCVerifyFingerCPP"
        / "FCVerifyFingerCPP.cpp"
    )
    if not tutorial.is_file():
        pytest.skip("the delivered verification tutorial is not in the unpacked tree")
    text = tutorial.read_text(encoding="utf-8", errors="replace")
    assert 'N_T("FingerCell")' in text
    assert "NLicense::Obtain" in text


def test_the_selected_binding_is_the_one_the_archive_actually_samples(
    unpacked,
) -> None:
    """Java was the preference; the archive decided (docs/adr/0116)."""
    samples = unpacked / "FingerCell_3_3_SDK" / "Samples" / "FingerCell"
    if not samples.is_dir():
        pytest.skip("the delivered samples are not in the unpacked tree")
    present = {item.name for item in samples.iterdir() if item.is_dir()}
    assert "CPP" in present
    assert "DotNET" not in present and "CSharp" not in present
    inspection = engine.package_inspection()
    if inspection is None:
        pytest.skip("no inspection record has been written yet")
    identity = inspection.get("package_identity", {})
    assert identity.get("selected_binding") == frozen.Binding.CPP.value


def test_the_runtime_closure_holds_the_algorithm_and_no_sibling_engine(
    unpacked,
) -> None:
    inspection = engine.package_inspection()
    if inspection is None:
        pytest.skip("no inspection record has been written yet")
    closure = inspection.get("runtime_closure", [])
    roles = {row["component_role"] for row in closure}
    assert frozen.ComponentRole.FINGERCELL_ALGORITHM.value in roles
    names = " ".join(row["relative_path"].lower() for row in closure)
    assert "nbiometrics" not in names, (
        "the general biometrics module carries the vendor's other fingerprint "
        "engine and must not be in this route (docs/adr/0114)"
    )
    for row in closure:
        assert len(row["sha256"]) == 64
        assert row["size_bytes"] > 0


def test_every_closure_component_still_hashes_to_what_was_recorded(
    unpacked,
) -> None:
    inspection = engine.package_inspection()
    if inspection is None:
        pytest.skip("no inspection record has been written yet")
    for row in inspection.get("runtime_closure", []):
        path = store.artifact_store_prefix_path(repository_root=REPOSITORY_ROOT)
        target = path / row["relative_path"]
        if not target.is_file():
            pytest.skip(f"{row['relative_path']} is not in the store")
        size, digest = store.hash_component(target)
        assert size == row["size_bytes"]
        assert digest == row["sha256"]


def test_the_delivered_licence_permits_testing_and_is_read_from_the_archive(
    unpacked,
) -> None:
    licence = (
        unpacked / "FingerCell_3_3_SDK" / "Documentation" / "SDK License.html"
    )
    if not licence.is_file():
        pytest.skip("the delivered licence agreement is not in the unpacked tree")
    text = licence.read_text(encoding="utf-8", errors="replace").lower()
    assert "testing" in text
    assert "non-exclusive" in text


def test_no_trial_is_activated_by_running_these_tests() -> None:
    """These read files. Nothing here loads a module or asks for a licence."""
    inspection = engine.package_inspection() or {}
    trial = inspection.get("trial")
    if trial is None:
        result = engine.run_preflight().status(
            frozen.PreflightGate.RESEARCH_USE_AND_TRIAL_OPERATION
        )
        assert result in (
            frozen.GateStatus.ACTION_REQUIRED,
            frozen.GateStatus.NOT_REACHED,
        )


def test_the_store_stays_outside_the_working_tree() -> None:
    prefix = store.artifact_store_prefix_path(repository_root=REPOSITORY_ROOT)
    assert REPOSITORY_ROOT not in prefix.parents
    assert prefix.is_absolute()
