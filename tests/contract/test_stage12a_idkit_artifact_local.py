"""The Stage 12A checks that need a delivered IDKit package on this machine.

Marked ``idkit_artifact`` and excluded from the public CI, which fetches nothing,
activates nothing and holds no credential. Every test here skips while the store
is empty, and an empty store is the stage's published result: the acquisition
gate is pending, so nothing was delivered and nothing was activated.

Set ``FPBENCH_THIRD_PARTY_ROOT`` and place a delivered package under this stage's
prefix, together with the declaration that says what it is and where it came
from. Then these say what has to hold before any gate below the first can be
believed — because Stage 12A froze no package identity in advance, so bytes found
here can be verified only against what the person who received them recorded.

Nothing in this file imports a vendor binding, activates a licence, prints a
licence value or produces a score.
"""

from __future__ import annotations

import pytest

from fpbench.experiments import stage12a_acquisition as store
from fpbench.experiments import stage12a_idkit_identity as frozen
from fpbench.experiments import stage12a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.idkit_artifact


@pytest.fixture(scope="module")
def state() -> store.AcquisitionState:
    found = store.acquisition_state(repository_root=REPOSITORY_ROOT)
    if found.presence is store.PackagePresence.ABSENT:
        pytest.skip(
            "no IDKit material is in the local artifact store; set "
            "FPBENCH_THIRD_PARTY_ROOT and place a delivered package under "
            f"{frozen.ARTIFACT_STORE_PREFIX}/ together with "
            f"{store.PACKAGE_DECLARATION_NAME}"
        )
    return found


def test_bytes_with_no_declaration_are_never_treated_as_a_delivery(
    state: store.AcquisitionState,
) -> None:
    """A copy nobody recorded the provenance of is not a delivery.

    The point is not that the file is wrong. It is that a package which cannot
    be tied to a vendor and a channel cannot be pinned by anything, and the gate
    below it would then be describing bytes of unknown origin.
    """
    if state.presence is store.PackagePresence.UNDECLARED:
        assert state.obtained is False
        assert state.status.is_pending
        assert "provenance" in state.detail


def test_a_declared_package_matches_the_bytes_beside_it(
    state: store.AcquisitionState,
) -> None:
    if state.declaration is None:
        pytest.skip("no package declaration is present")
    assert state.presence is store.PackagePresence.VERIFIED
    assert state.obtained is True
    assert state.declaration.product_family is frozen.ProductFamily.IDKIT_SDK, (
        "the delivered package resolves to a different Innovatrics product; "
        "IDKit and the ANSI&ISO SDK generate different templates"
    )
    assert (
        state.declaration.implementation_version
        != frozen.IMPLEMENTATION_VERSION_UNRESOLVED
    )


def test_the_delivery_channel_is_one_of_the_vendors_own(
    state: store.AcquisitionState,
) -> None:
    if state.declaration is None:
        pytest.skip("no package declaration is present")
    assert state.declaration.delivery_channel in frozen.DeliveryChannel


def test_the_store_declarations_carry_no_credential(
    state: store.AcquisitionState,
) -> None:
    """Guarded at the reader, so nothing travels from the store into a document."""
    store.read_declared_state(repository_root=REPOSITORY_ROOT)
    store.read_package_declaration(repository_root=REPOSITORY_ROOT)
    inspection = engine.package_inspection()
    if inspection is not None:
        assert engine.find_sensitive_material(inspection) == ()


def test_the_preflight_moves_past_acquisition_once_a_package_verifies(
    state: store.AcquisitionState,
) -> None:
    if not state.obtained:
        pytest.skip("no verified package is present")
    preflight = engine.run_preflight()
    assert preflight.status(frozen.PreflightGate.ACQUISITION_ACCESS) is (
        frozen.GateStatus.PASS
    )
    assert preflight.paused_at is None
    assert preflight.gates_reached >= 2


def test_a_qualification_record_here_names_the_engine_that_produced_it() -> None:
    """A fake record in the store answers nothing, on purpose."""
    from fpbench.experiments.stage12a_qualification import read_record, record_path

    try:
        payload = read_record(record_path(repository_root=REPOSITORY_ROOT))
    except Exception:  # pragma: no cover - an unusable store
        pytest.skip("no local artifact store is resolvable here")
    if payload is None:
        pytest.skip("no qualification record is present")
    assert payload.get("engine_kind") in ("DELIVERED_SDK", "FAKE_SDK")
    if payload.get("engine_kind") == "FAKE_SDK":
        assert engine.qualification_record() is None
    assert payload.get("scoring_comparisons", 0) <= (
        frozen.QUALIFICATION_MAX_SCORING_COMPARISONS
    )
    for value in (payload.get("passes") or {}).values():
        assert "score" not in value, "a score value reached the local record"
