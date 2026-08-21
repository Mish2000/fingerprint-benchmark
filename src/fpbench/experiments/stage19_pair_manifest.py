"""Reading the pair manifest a Stage 19 run must be bound to.

:mod:`fpbench.experiments.stage19_result_integrity` states the rules and stays
standard-library-only, so they can be read without knowing that a pair manifest
is a parquet file. This module is the part that knows.

**The hash is re-derived, never taken on trust.** The manifest artifact carries
``pair_manifest_hash`` in its schema metadata, written by
:class:`fpbench.storage.manifest_store.ManifestStore` as a digest over its own
provenance and rows. A publisher that read that value and published it would be
repeating a claim the file makes about itself. So the digest is recomputed here
from the rows as loaded, by the same rule, and the two must agree — after which
the caller compares the result to the stage's frozen reference constant.

That chain is what makes the constant a *check* rather than a source: the
finalization no longer writes ``pair_manifest_hash`` down beside the run, it
derives it from the artifact the run consumed and refuses if the artifact is not
the one the stage was defined over.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from fpbench.core.serialization import stable_hash
from fpbench.experiments.stage19_result_integrity import (
    CanonicalPair,
    Stage19ResultIntegrityError,
)

__all__ = [
    "CanonicalPairManifest",
    "load_canonical_pair_manifest",
    "pairs_path_for",
]

#: The metadata keys ``ManifestStore`` stamps beside a pair table, and which the
#: hash is computed over. Order is irrelevant — ``stable_hash`` sorts — but the
#: *set* is not: a key added there without being added here would make the
#: recomputation disagree with the artifact for a reason that is not a fault.
_PROVENANCE_KEYS = ("protocol_id", "cohort_id", "image_manifest_hash", "schema_version")


@dataclass(frozen=True, slots=True)
class CanonicalPairManifest:
    """The comparisons a canonical run is defined over, and their digest."""

    pairs: tuple[CanonicalPair, ...]
    pair_manifest_hash: str
    protocol_id: str
    cohort_id: str
    source_path: Path

    def __len__(self) -> int:
        return len(self.pairs)


def pairs_path_for(workspace: Path, protocol_id: str, cohort_id: str) -> Path:
    """Where the cohort published its pair manifest."""
    return (
        Path(workspace)
        / "manifests"
        / "protocols"
        / protocol_id
        / "cohorts"
        / cohort_id
        / "pairs.parquet"
    )


def _decoded_metadata(table: "pq.pa.Table") -> dict[str, str]:
    raw = table.schema.metadata or {}
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        try:
            decoded[key.decode("utf-8")] = value.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - parquet writes utf-8
            continue
    return decoded


def load_canonical_pair_manifest(
    pairs_path: Path,
    *,
    expected_pair_manifest_hash: str | None = None,
) -> CanonicalPairManifest:
    """Load the pair manifest and prove it is what it says it is.

    Raises:
        Stage19ResultIntegrityError: the artifact is missing, its metadata does
            not describe its own rows, or it is not the manifest the stage was
            defined over.
    """
    path = Path(pairs_path)
    if not path.is_file():
        raise Stage19ResultIntegrityError(
            f"no pair manifest at {path}. A Stage 19 store cannot be verified "
            "without the authority it was supposed to have run over"
        )

    try:
        table = pq.read_table(path)
    except Exception as exc:  # noqa: BLE001 - any parquet fault is one fault here
        raise Stage19ResultIntegrityError(
            f"cannot read the pair manifest {path}: {type(exc).__name__}: {exc}"
        ) from exc

    metadata = _decoded_metadata(table)
    missing = [key for key in (*_PROVENANCE_KEYS, "pair_manifest_hash") if key not in metadata]
    if missing:
        raise Stage19ResultIntegrityError(
            f"{path} carries no {missing}; it was not written by ManifestStore "
            "and cannot act as the pair authority"
        )

    rows = table.to_pylist()
    provenance = {key: metadata[key] for key in _PROVENANCE_KEYS}
    recomputed = stable_hash({"provenance": provenance, "pairs": rows}, length=64)
    declared = metadata["pair_manifest_hash"]
    if recomputed != declared:
        raise Stage19ResultIntegrityError(
            f"{path} declares pair_manifest_hash {declared[:12]}... and its own "
            f"rows hash to {recomputed[:12]}.... The artifact does not describe "
            "itself"
        )

    if expected_pair_manifest_hash is not None and recomputed != expected_pair_manifest_hash:
        raise Stage19ResultIntegrityError(
            f"{path} is pair manifest {recomputed[:12]}... and this stage is "
            f"defined over {expected_pair_manifest_hash[:12]}.... A run over a "
            "different set of comparisons is a different experiment"
        )

    pairs = tuple(
        CanonicalPair(
            ordinal=ordinal,
            pair_id=str(row["pair_id"]),
            release=str(row["release"]),
            protocol_stage=str(row["protocol_stage"]),
            ground_truth=str(row["ground_truth"]),
            left_image_id=str(row["left_image_id"]),
            right_image_id=str(row["right_image_id"]),
        )
        # The manifest's own row order is the protocol order, and it is what the
        # other algorithms' runs consumed. No sort.
        for ordinal, row in enumerate(rows)
    )

    return CanonicalPairManifest(
        pairs=pairs,
        pair_manifest_hash=recomputed,
        protocol_id=provenance["protocol_id"],
        cohort_id=provenance["cohort_id"],
        source_path=path,
    )
