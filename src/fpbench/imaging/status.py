"""How far along a preparation is, derived from files rather than remembered.

The same shape as :mod:`fpbench.derivations.status` one layer up, and for the
same reason. Nothing writes a status; a status is read off what exists on disk
and re-verified every time it is asked for. A persisted ``MATERIALISING`` would
be a lie the moment the machine rebooted.

The ordering is a ladder, and each rung is a different question:

``PROFILE_READY``   the transformation is pinned and the image list is promised
``PARTIAL``         some of the promised images exist
``IMAGES_COMPLETE`` all of them do, but nothing has checked them as a whole
``VERIFIED``        the manifest is on disk and the set re-verifies
``PREPARATION_READY`` the receipt and the finalization marker hold too

``INVALID`` is not the bottom of that ladder — it is off it. It means two
artefacts contradict each other, which is never fixed by materialising more.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from fpbench.core.enums import PreparationStatus
from fpbench.core.errors import StorageError
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import PreparationDefinition
from fpbench.core.models import ImageRecord
from fpbench.imaging.verify import (
    PreparedSetVerification,
    verify_prepared_artifacts,
    verify_prepared_image_set,
)
from fpbench.storage.prepared_image_set_store import PreparedImageSetStore

__all__ = ["PreparationState", "inspect_preparation"]


@dataclass(frozen=True, slots=True)
class PreparationState:
    """Where a preparation stands, and why it does not stand higher."""

    definition_id: str | None
    preparation_set_id: str | None

    status: PreparationStatus

    expected_images: int
    materialised_images: int
    missing_images: int

    manifest_valid: bool
    receipt_valid: bool
    finalization_valid: bool

    issues: tuple[str, ...]
    inspected_utc: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "issues", tuple(self.issues))

    @property
    def is_preparation_ready(self) -> bool:
        return self.status is PreparationStatus.PREPARATION_READY


def inspect_preparation(
    *,
    store: PreparedImageSetStore,
    definition: PreparationDefinition | None,
    preparation_set_id_value: str | None = None,
    images: Mapping[ImageId, ImageRecord] | None = None,
    dataset_root: Path | None = None,
    recompute_pixels: bool = False,
) -> PreparationState:
    """Report a preparation's state. Never writes anything.

    Args:
        definition: The promise, when one exists. Without it there is nothing to
            be partial *of*, and the state can only be ``NOT_PREPARED`` or, if a
            finished set was named directly, whatever that set verifies as.
        images: The image manifest, when the caller has it. Supplying it turns
            on source verification; omitting it checks only what is reachable
            from the workspace.
    """
    inspected_utc = _utc_now()

    if definition is None and preparation_set_id_value is None:
        return PreparationState(
            definition_id=None,
            preparation_set_id=None,
            status=PreparationStatus.NOT_PREPARED,
            expected_images=0,
            materialised_images=0,
            missing_images=0,
            manifest_valid=False,
            receipt_valid=False,
            finalization_valid=False,
            issues=("no preparation definition and no prepared set were named",),
            inspected_utc=inspected_utc,
        )

    expected = definition.expected_total_images if definition else 0
    materialised = 0
    issues: list[str] = []

    if definition is not None:
        if not store.has_definition(definition.definition_id):
            return PreparationState(
                definition_id=definition.definition_id,
                preparation_set_id=preparation_set_id_value,
                status=PreparationStatus.NOT_PREPARED,
                expected_images=expected,
                materialised_images=0,
                missing_images=expected,
                manifest_valid=False,
                receipt_valid=False,
                finalization_valid=False,
                issues=("the preparation definition has not been written",),
                inspected_utc=inspected_utc,
            )
        materialised = sum(
            1
            for image_id in definition.ordered_image_ids
            if store.has_entry(definition.definition_id, str(image_id))
        )

    # A finished set is what makes the pending directory irrelevant, so it is
    # looked for first.
    resolved_set = preparation_set_id_value
    if resolved_set is None and definition is not None:
        resolved_set = _find_finished_set(store, definition)

    if resolved_set is None or not store.has_manifest(resolved_set):
        status = (
            PreparationStatus.IMAGES_COMPLETE
            if definition is not None and materialised == expected and expected
            else PreparationStatus.PARTIAL
            if materialised
            else PreparationStatus.PROFILE_READY
        )
        return PreparationState(
            definition_id=definition.definition_id if definition else None,
            preparation_set_id=None,
            status=status,
            expected_images=expected,
            materialised_images=materialised,
            missing_images=max(expected - materialised, 0),
            manifest_valid=False,
            receipt_valid=False,
            finalization_valid=False,
            issues=tuple(issues),
            inspected_utc=inspected_utc,
        )

    try:
        verification = _verify(
            store=store,
            preparation_set_id_value=resolved_set,
            images=images,
            dataset_root=dataset_root,
            recompute_pixels=recompute_pixels,
        )
    except StorageError as exc:
        return PreparationState(
            definition_id=definition.definition_id if definition else None,
            preparation_set_id=resolved_set,
            status=PreparationStatus.INVALID,
            expected_images=expected,
            materialised_images=materialised,
            missing_images=max(expected - materialised, 0),
            manifest_valid=False,
            receipt_valid=False,
            finalization_valid=False,
            issues=(str(exc),),
            inspected_utc=inspected_utc,
        )

    has_receipt = store.has_receipt(resolved_set)
    has_marker = store.has_finalization(resolved_set)
    issues.extend(verification.issues)

    if issues:
        status = PreparationStatus.INVALID
    elif has_receipt and has_marker:
        status = PreparationStatus.PREPARATION_READY
    else:
        status = PreparationStatus.VERIFIED
        if not has_receipt:
            issues.append("no preparation receipt has been written")
        if not has_marker:
            issues.append("no finalization marker has been written")

    return PreparationState(
        definition_id=definition.definition_id if definition else None,
        preparation_set_id=resolved_set,
        status=status,
        expected_images=expected or verification.total_entries,
        materialised_images=verification.total_entries,
        missing_images=max((expected or verification.total_entries)
                          - verification.total_entries, 0),
        manifest_valid=verification.is_valid,
        receipt_valid=has_receipt and verification.is_valid,
        finalization_valid=has_marker and verification.is_valid,
        issues=tuple(issues),
        inspected_utc=inspected_utc,
    )


# ----------------------------------------------------------------- internals


def _verify(
    *,
    store: PreparedImageSetStore,
    preparation_set_id_value: str,
    images: Mapping[ImageId, ImageRecord] | None,
    dataset_root: Path | None,
    recompute_pixels: bool,
) -> PreparedSetVerification:
    if images is not None and dataset_root is not None:
        return verify_prepared_image_set(
            store=store,
            preparation_set_id_value=preparation_set_id_value,
            images=images,
            dataset_root=dataset_root,
            recompute_pixels=recompute_pixels,
            require_receipt=False,
            require_finalization=False,
        )
    return verify_prepared_artifacts(
        store=store,
        preparation_set_id_value=preparation_set_id_value,
        require_receipt=False,
        require_finalization=False,
    )


def _find_finished_set(
    store: PreparedImageSetStore, definition: PreparationDefinition
) -> str | None:
    """Which finished set, if any, this definition produced.

    Matched on the definition fingerprint stored inside the set, never on a
    pointer file: a pointer is a bookmark and this question decides whether a
    preparation is finished.
    """
    for candidate in store.preparation_set_ids():
        try:
            stored = store.read_definition(store.set_dir(candidate))
        except StorageError:
            continue
        if stored.definition_fingerprint == definition.definition_fingerprint:
            return candidate
    return None


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
