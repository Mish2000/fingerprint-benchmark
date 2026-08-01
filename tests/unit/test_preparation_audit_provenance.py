"""A full transform audit is attributable without becoming verifier-locked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from canonicalworld import (
    build_canonical_world,
    make_runtime,
    publish_receipt_and_marker,
)
from fpbench.core.enums import PreparationStatus
from fpbench.core.errors import PreparationFinalizationError
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.experiments import sd300_canonical500_images as experiment
from fpbench.experiments.preparation_receipt import build_preparation_receipt
from fpbench.imaging.verify import verify_prepared_image_set
from fpbench.imaging.status import inspect_preparation

pytestmark = [pytest.mark.imaging, pytest.mark.canonical500]


def _software(commit: str, *, clean: bool = True) -> SoftwareProvenance:
    return SoftwareProvenance(
        provenance_kind="git",
        source_revision=commit,
        source_tree_clean=clean,
        package_version="0.1.0",
        python_version="3.12.13",
        python_implementation="CPython",
        dependency_versions={"pyarrow": "15.0.0", "pyyaml": "6.0"},
    )


def _prepared(world, software):
    return SimpleNamespace(
        software=software,
        store=world.store,
        inputs=SimpleNamespace(
            images=world.images,
            dataset_root=world.dataset_root,
        ),
    )


def _patch_source_bundle(monkeypatch, world):
    monkeypatch.setattr(
        experiment, "preparation_source_bundle", lambda _inputs: world.source_bundle
    )


def _status(world):
    return inspect_preparation(
        store=world.store,
        definition=world.definition,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
    )


def test_verifier_runtime_drift_issues_no_marker(tmp_path, monkeypatch):
    world = build_canonical_world(tmp_path)
    software = _software("c" * 40)
    before = make_runtime(software=software)
    after = make_runtime(software=software, pillow_version="99.0.0")
    runtimes = iter((before, after))
    monkeypatch.setattr(experiment, "_capture_provenance", lambda *_a, **_k: software)
    monkeypatch.setattr(
        experiment, "capture_transform_runtime", lambda **_k: next(runtimes)
    )
    _patch_source_bundle(monkeypatch, world)

    with pytest.raises(PreparationFinalizationError, match="runtime changed"):
        experiment._run_transform_audit_with_provenance(
            prepared=_prepared(world, software),
            manifest=world.manifest,
            repository_root=tmp_path,
            require_clean=True,
        )

    assert not world.store.has_finalization(world.preparation_set_id)
    assert not world.store.has_receipt(world.preparation_set_id)
    assert _status(world).status is not PreparationStatus.PREPARATION_READY


def test_dirty_verifier_tree_issues_no_publication(tmp_path, monkeypatch):
    world = build_canonical_world(tmp_path)
    dirty = _software("d" * 40, clean=False)
    monkeypatch.setattr(experiment, "_capture_provenance", lambda *_a, **_k: dirty)
    _patch_source_bundle(monkeypatch, world)

    with pytest.raises(PreparationFinalizationError, match="committed, clean"):
        experiment._run_transform_audit_with_provenance(
            prepared=_prepared(world, dirty),
            manifest=world.manifest,
            repository_root=tmp_path,
            require_clean=True,
        )

    assert not world.store.has_finalization(world.preparation_set_id)
    assert not world.store.has_receipt(world.preparation_set_id)
    assert _status(world).status is not PreparationStatus.PREPARATION_READY


def test_new_code_can_verify_an_audit_issued_by_an_older_verifier(tmp_path):
    world = build_canonical_world(tmp_path)
    historical_software = _software("d" * 40)
    historical_runtime = make_runtime(software=historical_software)
    publish_receipt_and_marker(world, verifier_runtime=historical_runtime)

    verification = verify_prepared_image_set(
        store=world.store,
        preparation_set_id_value=world.preparation_set_id,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
    )

    assert verification.is_valid
    receipt = world.store.read_receipt(world.preparation_set_id)
    assert receipt.source_commit == world.runtime.source_revision
    assert receipt.verifier_source_commit == "d" * 40
    assert (
        receipt.verifier_transform_runtime_fingerprint
        == historical_runtime.runtime_fingerprint
    )


def test_retry_preserves_semantic_audit_and_records_the_new_verifier(
    tmp_path, monkeypatch
):
    world = build_canonical_world(tmp_path)
    old_software = _software("c" * 40)
    old_before = make_runtime(software=old_software)
    old_after = make_runtime(software=old_software, zlib_version="changed")
    first_runtimes = iter((old_before, old_after))
    monkeypatch.setattr(
        experiment, "_capture_provenance", lambda *_a, **_k: old_software
    )
    monkeypatch.setattr(
        experiment, "capture_transform_runtime", lambda **_k: next(first_runtimes)
    )
    _patch_source_bundle(monkeypatch, world)

    with pytest.raises(PreparationFinalizationError, match="runtime changed"):
        experiment._run_transform_audit_with_provenance(
            prepared=_prepared(world, old_software),
            manifest=world.manifest,
            repository_root=tmp_path,
            require_clean=True,
        )

    new_software = _software("e" * 40)
    new_runtime = make_runtime(software=new_software)
    retry_runtimes = iter((new_runtime, new_runtime))
    monkeypatch.setattr(
        experiment, "_capture_provenance", lambda *_a, **_k: new_software
    )
    monkeypatch.setattr(
        experiment, "capture_transform_runtime", lambda **_k: next(retry_runtimes)
    )

    audit, recorded_runtime = experiment._run_transform_audit_with_provenance(
        prepared=_prepared(world, new_software),
        manifest=world.manifest,
        repository_root=tmp_path,
        require_clean=True,
    )
    independently_derived = verify_prepared_image_set(
        store=world.store,
        preparation_set_id_value=world.preparation_set_id,
        images=world.images,
        dataset_root=world.dataset_root,
        source_bundle=world.source_bundle,
        require_receipt=False,
        require_finalization=False,
        check_existing_publication=False,
    ).transform_audit

    assert independently_derived is not None
    assert audit.audit_fingerprint == independently_derived.audit_fingerprint
    assert recorded_runtime.runtime_fingerprint == new_runtime.runtime_fingerprint
    receipt = build_preparation_receipt(
        manifest=world.manifest,
        entries=world.entries,
        profile=world.profile,
        runtime=world.runtime,
        audit=audit,
        verifier_runtime=recorded_runtime,
        images=world.images,
    )
    assert receipt.verifier_source_commit == "e" * 40
    assert (
        receipt.verifier_transform_runtime_fingerprint
        == new_runtime.runtime_fingerprint
    )
