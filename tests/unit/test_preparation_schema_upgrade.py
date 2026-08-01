"""Only known preparation-publication schema upgrades may replace evidence."""

from __future__ import annotations

import pytest

from canonicalworld import build_canonical_world, publish_receipt_and_marker
from fpbench.core.errors import ResultConflictError
from fpbench.core.serialization import to_plain, write_json
from fpbench.experiments.preparation_receipt import write_preparation_evidence_copy
from fpbench.imaging.verify import verify_prepared_image_set

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def _v1_receipt(receipt):
    payload = dict(to_plain(receipt))
    payload["schema_version"] = "1"
    payload.pop("transform_audit_fingerprint")
    payload.pop("verifier_source_commit")
    payload.pop("verifier_source_tree_clean")
    payload.pop("verifier_transform_runtime_fingerprint")
    return payload


def _v1_marker(marker):
    payload = dict(to_plain(marker))
    payload["schema_version"] = "1"
    payload.pop("transform_audit_fingerprint")
    payload.pop("transform_audit_content_hash")
    payload.pop("verifier_source_commit")
    payload.pop("verifier_source_tree_clean")
    payload.pop("verifier_transform_runtime_fingerprint")
    return payload


def _v2_receipt(receipt):
    payload = dict(to_plain(receipt))
    payload["schema_version"] = "2"
    payload.pop("verifier_source_commit")
    payload.pop("verifier_source_tree_clean")
    payload.pop("verifier_transform_runtime_fingerprint")
    return payload


def _v2_marker(marker):
    payload = dict(to_plain(marker))
    payload["schema_version"] = "2"
    payload.pop("verifier_source_commit")
    payload.pop("verifier_source_tree_clean")
    payload.pop("verifier_transform_runtime_fingerprint")
    return payload


@pytest.mark.parametrize("legacy_version", ["1", "2"])
def test_workspace_publication_can_upgrade_only_after_a_fresh_full_audit(
    tmp_path, legacy_version
):
    world = build_canonical_world(tmp_path)
    publish_receipt_and_marker(world)
    store = world.store
    set_id = world.preparation_set_id
    receipt = store.read_receipt(set_id)
    marker = store.read_finalization(set_id)

    if legacy_version == "1":
        write_json(store.receipt_path(set_id), _v1_receipt(receipt))
        write_json(store.finalization_path(set_id), _v1_marker(marker))
        store.transform_audit_path(set_id).unlink()
    else:
        write_json(store.receipt_path(set_id), _v2_receipt(receipt))
        write_json(store.finalization_path(set_id), _v2_marker(marker))

    verification = verify_prepared_image_set(
        store=store,
        preparation_set_id_value=set_id,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
        require_receipt=False,
        require_finalization=False,
        check_existing_publication=False,
    )
    assert verification.is_valid
    assert verification.transform_audit is not None
    assert verification.transform_audit.is_clean

    store.ensure_transform_audit(
        preparation_set_id=set_id, audit=verification.transform_audit
    )
    store.ensure_receipt(preparation_set_id=set_id, receipt=receipt)
    store.ensure_finalization(preparation_set_id=set_id, marker=marker)

    assert store.read_receipt(set_id) == receipt
    assert store.read_finalization(set_id) == marker
    assert len(tuple((store.set_dir(set_id) / "publication-history").glob("*.json"))) == 2


def test_evidence_upgrade_refuses_a_changed_shared_claim(tmp_path):
    world = build_canonical_world(tmp_path / "world")
    publish_receipt_and_marker(world)
    receipt = world.store.read_receipt(world.preparation_set_id)
    repository = tmp_path / "repository"
    path = (
        repository
        / "evidence"
        / "sd300-canonical500-images"
        / f"{receipt.preparation_set_id}.json"
    )
    payload = _v1_receipt(receipt)
    payload["total_images"] = receipt.total_images + 1
    write_json(path, payload)

    with pytest.raises(ResultConflictError, match="refusing to overwrite"):
        write_preparation_evidence_copy(receipt, repository_root=repository)

    assert path.read_text(encoding="utf-8").find(
        f'"total_images": {receipt.total_images + 1}'
    ) >= 0
