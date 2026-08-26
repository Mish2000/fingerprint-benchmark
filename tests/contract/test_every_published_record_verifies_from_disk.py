"""Every published record, re-verified from the bytes on disk and nothing else.

This is the check the earlier scan should have been. That one asserted that
three binding *fields were present* in each published record — and it passed
while eleven of the twenty-three records could not be verified at all, because
Stage 9A and Stage 10A published a flattened summary instead of the three
documents. Presence of a field is not the ability to check it, and the gap
between those two is exactly where a receipt can pass for evidence.

So this file does the whole thing the hard way: it reads the published JSON,
rebuilds the observation, the assessment and the record through the strict
readers, and runs the real ``verify_usage_record`` over them. Nothing here
imports a builder or re-derives a value from live code — if the evidence cannot
answer for itself, this fails.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.third_party_models import (
    IdentityLinkBasis,
    read_license_observation,
    read_research_use_assessment,
    read_third_party_usage_record,
)
from fpbench.third_party.verify import verify_usage_record

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"

#: Every third-party component this repository has ever used, across the three
#: stages that publish one. A number rather than "however many we find": a scan
#: that silently found nine would report a clean repository.
EXPECTED_RECORD_COUNT = 23

#: How the twenty-three divide. Fixed here so that a component quietly changing
#: state — an assertion becoming a derivation, or an unresolved identity being
#: cleared — has to be a deliberate edit to this line.
EXPECTED_BY_BASIS = {
    IdentityLinkBasis.EVIDENCE_LOCATOR: 2,
    IdentityLinkBasis.UPSTREAM_COMMIT: 6,
    IdentityLinkBasis.PUBLISHER_ASSERTION: 9,
    IdentityLinkBasis.UNRESOLVED_DOCUMENTATION_ONLY: 6,
}


def _triplets() -> list[tuple[Path, dict]]:
    """Every published node carrying all three documents of one component."""
    found: list[tuple[Path, dict]] = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - evidence parses in CI
            continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if {"observation", "assessment", "usage_record"} <= set(node):
                    found.append((path, node))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)
    return found


def test_the_published_evidence_carries_every_component() -> None:
    """Exactly twenty-three, and each one only once."""
    triplets = _triplets()
    assert len(triplets) == EXPECTED_RECORD_COUNT, (
        f"{len(triplets)} components publish all three documents, and this "
        f"repository uses {EXPECTED_RECORD_COUNT}. A component that publishes a "
        "summary instead cannot be verified from the disk at all"
    )

    identifiers = [node["usage_record"]["record_id"] for _, node in triplets]
    duplicates = sorted({i for i in identifiers if identifiers.count(i) > 1})
    assert not duplicates, f"these record ids are published twice: {duplicates}"


@pytest.mark.parametrize("index", range(EXPECTED_RECORD_COUNT))
def test_each_published_record_re_verifies_from_its_own_documents(index: int) -> None:
    """Rebuild the three from JSON and run the real verifier over them.

    Parametrised one per record so a failure names the component rather than
    reporting that something, somewhere, did not verify.
    """
    triplets = _triplets()
    if index >= len(triplets):
        pytest.fail(
            f"only {len(triplets)} components publish all three documents; "
            f"{EXPECTED_RECORD_COUNT} were expected"
        )

    path, node = triplets[index]
    where = f"{path.relative_to(REPOSITORY_ROOT).as_posix()}"

    observation = read_license_observation(node["observation"])
    assessment = read_research_use_assessment(node["assessment"])
    record = read_third_party_usage_record(node["usage_record"])

    report = verify_usage_record(record, observation, assessment)
    assert report.verified, f"{where}: {record.record_id}: {report.findings}"
    assert report.upstream_binding_reproduced, (
        f"{where}: {record.record_id}: the upstream binding did not re-derive"
    )


def test_the_states_are_what_this_repository_declares() -> None:
    counted: dict[IdentityLinkBasis, int] = {}
    for _, node in _triplets():
        record = read_third_party_usage_record(node["usage_record"])
        counted[record.identity_link_basis] = (
            counted.get(record.identity_link_basis, 0) + 1
        )
    assert counted == EXPECTED_BY_BASIS, (
        f"the published components divide as {counted!r} and this repository "
        f"declares {EXPECTED_BY_BASIS!r}"
    )


def test_no_component_publishes_a_summary_instead_of_its_documents() -> None:
    """The failure this file exists for, stated from the other end.

    A node that names an upstream identity and a usage fingerprint is a
    published component. If it does not also carry the three documents, it is a
    receipt: a reader can compare digests they have no way to recompute.
    """
    summaries = []
    for path in sorted(EVIDENCE.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # pragma: no cover - evidence parses in CI
            continue

        def walk(node: object) -> None:
            if isinstance(node, dict):
                looks_like_a_record = (
                    "upstream_identity" in node and "usage_fingerprint" in node
                )
                # The record *inside* a triplet is not a summary; its two
                # companions sit beside it.
                nested_in_triplet = "observation" in node and "assessment" in node
                if looks_like_a_record and not nested_in_triplet:
                    parent_has_them = False
                    summaries.append(
                        (
                            path.relative_to(REPOSITORY_ROOT).as_posix(),
                            node.get("record_id", "?"),
                            parent_has_them,
                        )
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(payload)

    # A record nested under a triplet reaches here as its own dict, so keep only
    # the ones whose id no triplet publishes.
    published = {
        node["usage_record"]["record_id"] for _, node in _triplets()
    }
    orphans = sorted(
        {(where, record_id) for where, record_id, _ in summaries if record_id not in published}
    )
    assert not orphans, (
        "these components publish a summary and no documents, so nothing on "
        f"disk can verify them: {orphans}"
    )
