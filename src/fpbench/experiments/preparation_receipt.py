"""The one file from a preparation that is meant to leave the workspace.

A prepared-image set lives in a workspace; its receipt goes into version
control. That single difference decides everything here.

SD300 is redistribution-restricted — the delivery's own README says users "shall
adhere to all terms agreed to upon obtaining SD 300" — and a list of 3,000 image
ids, or 3,000 per-image digests, is an inventory of it. A receipt carrying either
would be a quiet republication. So the receipt carries counts and fingerprints
and nothing that identifies a single image, and :func:`require_sanitised_receipt`
checks that rather than trusting the builder to have remembered.

The counts are re-derived here from the entries rather than accepted from a
caller. A receipt that repeated numbers somebody passed in would be a summary of
a summary, and the whole point of the artefact is that a reader who has only
this file can check it against a workspace they were handed later.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Iterable, Mapping

from fpbench.core.errors import (
    ImagingError,
    PreparationFinalizationError,
    ResultConflictError,
)
from fpbench.core.identifiers import ImageId
from fpbench.core.imaging_models import (
    NO_RESOLUTION_CONCLUSION_STATEMENT,
    PREPARATION_FINALIZATION_SCHEMA_VERSION,
    PREPARATION_RECEIPT_SCHEMA_VERSION,
    PREPARATION_SET_ID_LENGTH,
    ImageTransformProfile,
    PreparationFinalizationMarker,
    PreparationReceipt,
    PreparationTransformAudit,
    PreparedImageEntry,
    PreparedImageSetManifest,
    TransformRuntimeManifest,
    preparation_finalization_fingerprint,
    preparation_receipt_content_hash,
    preparation_receipt_fingerprint,
    preparation_transform_audit_content_hash,
)
from fpbench.core.models import ImageRecord
from fpbench.core.serialization import to_plain

__all__ = [
    "EVIDENCE_DIRECTORY",
    "build_preparation_receipt",
    "build_preparation_finalization_marker",
    "require_sanitised_receipt",
    "verify_preparation_receipt",
    "write_preparation_evidence_copy",
    "FORBIDDEN_RECEIPT_KEYS",
]

#: Where a committed copy lives, relative to the repository root. One file per
#: preparation-set id, so two sets never overwrite each other.
EVIDENCE_DIRECTORY = Path("evidence") / "sd300-canonical500-images"

#: Field names a preparation receipt may never carry. Checked by name as well as
#: by shape, because the failure mode is somebody helpfully adding one.
FORBIDDEN_RECEIPT_KEYS: frozenset[str] = frozenset(
    {
        "image_id",
        "image_ids",
        "subject_id",
        "subject_ids",
        "finger_id",
        "finger_ids",
        "filename",
        "filenames",
        "relative_path",
        "relative_paths",
        "path",
        "paths",
        "entries",
        "entry_hash",
        "entry_hashes",
        "pixel_sha256",
        "encoded_sha256",
        "dimensions",
        "widths",
        "heights",
    }
)

#: Release names are not secret and appear as count keys. Anything that looks
#: like an SD300 image id, however, is an inventory row.
_ID_MARKERS = ("_plain_", "_roll_", "sd300a_", "sd300b_", "sd300c_")


def build_preparation_receipt(
    *,
    manifest: PreparedImageSetManifest,
    entries: Iterable[PreparedImageEntry],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    audit: PreparationTransformAudit,
    images: Mapping[ImageId, ImageRecord] | None = None,
    created_utc: str | None = None,
) -> PreparationReceipt:
    """Derive the sanitised receipt for a finished, verified preparation set.

    Args:
        images: The image manifest, when available. Used only to break the
            per-release counts out; without it the release breakdown falls back
            to the source resolutions, which are release-specific in SD300
            anyway. The receipt never records which image is in which release.
    """
    ordered = tuple(entries)
    if not ordered:
        raise ImagingError("a preparation receipt cannot be built over no entries")
    if not audit.is_clean:
        raise ImagingError("a preparation receipt requires a clean transform audit")
    if (
        audit.preparation_set_id != manifest.preparation_set_id
        or audit.preparation_set_fingerprint
        != manifest.preparation_set_fingerprint
    ):
        raise ImagingError("the transform audit describes a different prepared set")

    counts_by_release: dict[str, int] = {}
    counts_by_source_ppi: dict[str, int] = {}
    counts_by_action: dict[str, int] = {}
    total_source_bytes = 0
    total_output_bytes = 0

    for entry in ordered:
        key = str(entry.source_effective_ppi)
        counts_by_source_ppi[key] = counts_by_source_ppi.get(key, 0) + 1
        counts_by_action[entry.transform_action] = (
            counts_by_action.get(entry.transform_action, 0) + 1
        )
        total_source_bytes += entry.source_size_bytes
        total_output_bytes += entry.output_size_bytes

        release = _release_of(entry, images)
        counts_by_release[release] = counts_by_release.get(release, 0) + 1

    receipt = PreparationReceipt(
        schema_version=PREPARATION_RECEIPT_SCHEMA_VERSION,
        preparation_set_id=manifest.preparation_set_id,
        preparation_set_fingerprint=manifest.preparation_set_fingerprint,
        transform_profile_id=profile.profile_id,
        transform_profile_fingerprint=profile.profile_fingerprint,
        transform_runtime_id=runtime.runtime_id,
        transform_runtime_fingerprint=runtime.runtime_fingerprint,
        dataset_id=manifest.dataset_id,
        image_manifest_hash=manifest.image_manifest_hash,
        protocol_id=manifest.protocol_id,
        cohort_id=manifest.cohort_id,
        cohort_fingerprint=manifest.cohort_fingerprint,
        pair_manifest_hash=manifest.pair_manifest_hash,
        source_commit=runtime.source_revision,
        source_tree_clean=runtime.source_tree_clean,
        transform_audit_fingerprint=audit.audit_fingerprint,
        total_images=manifest.total_images,
        counts_by_release=counts_by_release,
        counts_by_source_ppi=counts_by_source_ppi,
        counts_by_transform_action=counts_by_action,
        total_source_bytes=total_source_bytes,
        total_output_bytes=total_output_bytes,
        statement=NO_RESOLUTION_CONCLUSION_STATEMENT,
        created_utc=created_utc or _utc_now(),
    )
    require_sanitised_receipt(receipt)
    return receipt


def require_sanitised_receipt(receipt: PreparationReceipt) -> None:
    """Refuse a receipt that would publish a dataset inventory.

    Checked rather than intended. The failure mode is not malice — it is
    somebody adding a helpful ``image_ids`` field to make debugging easier and
    committing it (spec section 49).

    Raises:
        ImagingError: the receipt names an image, a subject, a finger, a file or
            a per-image hash.
    """
    payload = to_plain(receipt)
    problems: list[str] = []

    for key in _walk_keys(payload):
        if key.lower() in FORBIDDEN_RECEIPT_KEYS:
            problems.append(f"carries a {key!r} field")

    rendered = json.dumps(payload, ensure_ascii=False).lower()
    for marker in _ID_MARKERS:
        if marker in rendered:
            problems.append(
                f"contains {marker!r}, which is part of an SD300 image id"
            )

    if problems:
        raise ImagingError(
            "a preparation receipt may not publish a dataset inventory: "
            + "; ".join(sorted(set(problems)))
        )


def verify_preparation_receipt(
    *,
    receipt: PreparationReceipt,
    manifest: PreparedImageSetManifest,
    entries: Iterable[PreparedImageEntry],
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    audit: PreparationTransformAudit,
    images: Mapping[ImageId, ImageRecord] | None = None,
) -> None:
    """Re-derive every load-bearing claim from current evidence.

    The receipt is never its own proof. A forged receipt can be internally
    self-consistent while contradicting the set it purports to summarise, so
    every field is re-derived and compared rather than the fingerprint being
    trusted.

    Raises:
        PreparationFinalizationError: any claim disagrees.
    """
    expected = build_preparation_receipt(
        manifest=manifest,
        entries=entries,
        profile=profile,
        runtime=runtime,
        audit=audit,
        images=images,
        created_utc=receipt.created_utc,
    )
    if preparation_receipt_fingerprint(receipt) != preparation_receipt_fingerprint(
        expected
    ):
        differences = [
            name
            for name in to_plain(expected)
            if name != "created_utc"
            and to_plain(getattr(receipt, name)) != to_plain(getattr(expected, name))
        ]
        raise PreparationFinalizationError(
            "the preparation receipt does not match the set it claims to "
            f"summarise; disagreeing field(s): {differences[:5]}"
        )
    require_sanitised_receipt(receipt)


def build_preparation_finalization_marker(
    *,
    manifest: PreparedImageSetManifest,
    profile: ImageTransformProfile,
    runtime: TransformRuntimeManifest,
    receipt: PreparationReceipt,
    audit: PreparationTransformAudit,
    entries_table_content_hash: str,
    summary_content_hash: str,
    created_utc: str | None = None,
) -> PreparationFinalizationMarker:
    """Build the last-written authority over an already verified chain."""
    if not runtime.source_tree_clean:
        raise PreparationFinalizationError(
            "finalising a preparation requires a committed, clean source tree; "
            "code that was never committed cannot be recovered from a receipt "
            "written later (docs/adr/0017)"
        )
    if not audit.is_clean:
        raise PreparationFinalizationError(
            "finalising a preparation requires a clean full transform audit"
        )
    if receipt.transform_audit_fingerprint != audit.audit_fingerprint:
        raise PreparationFinalizationError(
            "the preparation receipt does not cite the transform audit being finalised"
        )
    claims = {
        "schema_version": PREPARATION_FINALIZATION_SCHEMA_VERSION,
        "preparation_set_id": manifest.preparation_set_id,
        "preparation_set_fingerprint": manifest.preparation_set_fingerprint,
        "transform_profile_fingerprint": profile.profile_fingerprint,
        "transform_runtime_fingerprint": runtime.runtime_fingerprint,
        "entries_table_content_hash": entries_table_content_hash,
        "summary_content_hash": summary_content_hash,
        "receipt_fingerprint": preparation_receipt_fingerprint(receipt),
        "receipt_content_hash": preparation_receipt_content_hash(receipt),
        "transform_audit_fingerprint": audit.audit_fingerprint,
        "transform_audit_content_hash": preparation_transform_audit_content_hash(
            audit
        ),
        "source_commit": runtime.source_revision,
        "source_tree_clean": runtime.source_tree_clean,
    }
    fingerprint = preparation_finalization_fingerprint(claims)
    return PreparationFinalizationMarker(
        **claims,
        finalization_id=f"prepfinal_{fingerprint[:PREPARATION_SET_ID_LENGTH]}",
        finalization_fingerprint=fingerprint,
        created_utc=created_utc or _utc_now(),
    )


def write_preparation_evidence_copy(
    receipt: PreparationReceipt,
    *,
    repository_root: Path,
    directory: Path = EVIDENCE_DIRECTORY,
) -> Path:
    """Write the committable copy under ``evidence/``.

    Writing it makes the working tree dirty, which is why it is the *last* step
    of finalisation: every provenance check has already passed by the time this
    runs, and the next materialisation will require the receipt to be committed
    before it can start (docs/adr/0017).
    """
    require_sanitised_receipt(receipt)
    path = Path(repository_root) / directory / f"{receipt.preparation_set_id}.json"
    rendered = (
        json.dumps(to_plain(receipt), indent=2, ensure_ascii=False, sort_keys=False)
        + "\n"
    )
    # Match ``write_json`` on the current platform, so byte identity does not
    # mistake a line-ending convention for different evidence.
    payload = rendered.replace("\n", os.linesep).encode("utf-8")
    if path.is_file():
        if path.read_bytes() != payload:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                existing = {}
            current = dict(to_plain(receipt))
            shared_claims_match = all(
                key in current and value == current[key]
                for key, value in existing.items()
                if key not in {"schema_version", "created_utc"}
            )
            if (
                str(existing.get("schema_version")) == "1"
                and receipt.schema_version == "2"
                and shared_claims_match
            ):
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_bytes(payload)
                tmp.replace(path)
                return path
            raise ResultConflictError(
                f"{path} already contains a different evidence receipt; refusing to "
                "overwrite committed evidence"
            )
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError:  # pragma: no cover - lost a race with another process
        if path.read_bytes() != payload:
            raise ResultConflictError(
                f"{path} appeared with different content; refusing to overwrite it"
            )
    return path


# ----------------------------------------------------------------- internals


def _release_of(
    entry: PreparedImageEntry, images: Mapping[ImageId, ImageRecord] | None
) -> str:
    if images is not None:
        record = images.get(entry.image_id)
        if record is not None:
            return record.release
    return f"source_{entry.source_effective_ppi}ppi"


def _walk_keys(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_keys(item)


def _utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()
