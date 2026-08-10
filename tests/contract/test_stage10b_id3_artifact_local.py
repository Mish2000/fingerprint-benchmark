"""The Stage 10B checks that need a delivered id3 SDK on this machine.

Marked ``id3_artifact`` and excluded from the public CI, which fetches nothing,
activates nothing and holds no credential (docs/adr/0098). Every test here skips
while the package is absent, and absence is the stage's published result: the
acquisition gate failed, so nothing was delivered and nothing was activated.

Set ``FPBENCH_THIRD_PARTY_ROOT`` and place a delivered package under this
stage's prefix. Then these say what the evidence would have to be corrected to
before any of it could be believed — because Stage 10B froze no package identity,
so material found here cannot be verified against anything, and the honest
response is to re-run the stage rather than to trust a file.

Nothing in this file imports the vendor binding, activates a licence, prints a
licence value or produces a score. The tenth gate would do all of that, and it
was never reached.
"""

from __future__ import annotations

import pytest

from fpbench.experiments import stage10b_id3_identity as frozen
from fpbench.experiments import stage10b_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.id3_artifact


@pytest.fixture(scope="module")
def state() -> engine.PackageAcquisition:
    found = engine.package_acquisition_state(repository_root=REPOSITORY_ROOT)
    if not found.store_holds_material:
        pytest.skip(
            "no id3 material is in the local artifact store; set "
            "FPBENCH_THIRD_PARTY_ROOT and place a delivered package under "
            f"{frozen.ARTIFACT_STORE_PREFIX}/"
        )
    return found


def test_material_in_the_store_is_reported_and_never_treated_as_the_sdk(
    state: engine.PackageAcquisition,
) -> None:
    """A copy nobody can verify is not a copy of anything in particular.

    Stage 10B froze no filename, digest, size or platform, because none was
    delivered. Material appearing under this prefix therefore has nothing to be
    checked against, and the acquisition state says so rather than upgrading
    itself to ``OBTAINED``.
    """
    assert state.frozen_identity_available is False
    assert state.status is frozen.AcquisitionStatus.NOT_ATTEMPTED_HERE
    assert state.obtained is False
    assert any("verify it against" in finding for finding in state.findings)


def test_a_delivered_package_means_this_stage_must_be_re_run(
    state: engine.PackageAcquisition,
) -> None:
    """The published outcome describes a machine with no package.

    If one is here, the marker on disk is describing a different machine from
    the one running these tests, and the correct response is `make
    stage10b-documents` and `make stage10b-publish` — not an edit to the
    evidence.
    """
    preflight = engine.run_preflight()
    assert preflight.stopped_at is frozen.PreflightGate.ACQUISITION_ACCESS, (
        "the acquisition gate now passes; re-derive and republish Stage 10B "
        "rather than reading the committed marker"
    )


def test_no_licence_material_sits_inside_the_repository() -> None:
    """Never skips. Vendor artifacts are refused by name as well as by digest."""
    audit = engine.require_no_id3_bytes_in_git(REPOSITORY_ROOT)
    assert audit.clean


def test_no_licence_file_is_reachable_from_the_repository_root() -> None:
    """Never skips.

    A licence activated in the wrong directory is the ordinary way one ends up
    tracked. This looks for the vendor's own licence-file shapes anywhere under
    the working tree, tracked or not.
    """
    stray = sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in REPOSITORY_ROOT.rglob("*.lic")
        if path.is_file()
    ) + sorted(
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in REPOSITORY_ROOT.rglob("*.id3nn")
        if path.is_file()
    )
    assert stray == [], (
        "vendor licence or model material is inside the working tree; it belongs "
        "in the artifact store, outside the repository (docs/adr/0083)"
    )
