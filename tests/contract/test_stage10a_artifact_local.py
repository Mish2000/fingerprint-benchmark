"""The Stage 10A checks that need an artifact on this machine.

Marked ``algorithm4_preflight_artifact`` and excluded from the public CI, which
fetches nothing. There is exactly one artifact to check, and that is the point
of the stage: neither candidate reached the gate that would have downloaded a
checkpoint, so the only third-party bytes Stage 10A ever obtained are the pinned
source archive its identity gate rests on.

Set ``FPBENCH_THIRD_PARTY_ROOT`` and place the archive at the location the
placement names. Absent, these skip; present and wrong, they fail.
"""

from __future__ import annotations

import pytest

from fpbench.experiments import stage10a_candidate_evidence as observed
from fpbench.experiments import stage10a_preflight as engine
from fpbench.experiments.algorithm_research import REPOSITORY_ROOT

pytestmark = pytest.mark.algorithm4_preflight_artifact


@pytest.fixture(scope="module")
def status() -> engine.SourceArchiveStatus:
    found = engine.source_archive_status(repository_root=REPOSITORY_ROOT)
    if not found.present:
        pytest.skip(
            "the pinned candidate source archive is not in the local artifact "
            "store; set FPBENCH_THIRD_PARTY_ROOT and place it at "
            f"{engine.placement_for_source_archive().relative_location}"
        )
    return found


def test_the_archive_on_this_machine_is_the_archive_the_manifest_expects(
    status: engine.SourceArchiveStatus,
) -> None:
    assert status.identity_frozen is True
    assert status.verified is True, status.findings
    assert status.findings == ()


def test_the_resolved_path_stays_inside_the_store(
    status: engine.SourceArchiveStatus,
) -> None:
    from fpbench.third_party import resolve_third_party_root

    root = resolve_third_party_root(repository_root=REPOSITORY_ROOT)
    path = engine.store_path_for_source_archive(root=root)
    assert path.is_file()
    assert root in path.parents


def test_the_archive_is_the_commit_the_identity_gate_rests_on(
    status: engine.SourceArchiveStatus,
) -> None:
    """The gate cites files by digest; this checks they came from this archive."""
    import tarfile

    from fpbench.third_party import resolve_third_party_root

    root = resolve_third_party_root(repository_root=REPOSITORY_ROOT)
    path = engine.store_path_for_source_archive(root=root)
    expected = {item.relative_path: item for item in observed.JIPNET_PINNED_FILES}
    seen: dict[str, tuple[str, int]] = {}
    prefix = f"JIPNet-{observed.JIPNET_REPOSITORY.commit}/"
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith(prefix):
                continue
            relative = member.name[len(prefix) :]
            if relative not in expected:
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            import hashlib

            digest = hashlib.sha256(stream.read()).hexdigest()
            seen[relative] = (digest, member.size)
    assert set(seen) == set(expected), sorted(set(expected) - set(seen))
    for relative, (digest, size) in sorted(seen.items()):
        assert digest == expected[relative].sha256, relative
        assert size == expected[relative].size_bytes, relative


def test_no_candidate_checkpoint_is_in_the_store() -> None:
    """Never skips. The stage's result is that nothing was worth downloading."""
    from fpbench.third_party import resolve_third_party_root

    try:
        root = resolve_third_party_root(repository_root=REPOSITORY_ROOT)
    except Exception:
        pytest.skip("no local artifact store is resolvable here")
    prefix = root / "algorithm4-preflight"
    if not prefix.is_dir():
        return
    checkpoints = sorted(
        path.name
        for path in prefix.rglob("*")
        if path.is_file() and path.suffix in (".pth", ".ckpt", ".tar", ".pt")
        and not path.name.endswith(".tar.gz")
    )
    assert checkpoints == [], (
        "a candidate checkpoint is in the store, and neither candidate reached "
        f"the gate that would have fetched one: {checkpoints}"
    )
