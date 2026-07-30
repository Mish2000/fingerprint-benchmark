"""The exact ordered collection of scores an analysis is entitled to cite.

``completion.json`` says a run was audited and found sound. That is not enough
for the stage after this one. A decision layer has to be able to say *which*
6,000 raw results it applied a threshold to, and prove later that they have not
moved — and a completion manifest identifies the run, not the results
(docs/adr/0019).

So the result set gets an identity of its own: every stored result hashed, in
execution-plan order, folded into one fingerprint. Change one score and the
fingerprint changes. Change one failure code and the fingerprint changes.
Rewrite the same results tomorrow and it does not, because no timestamp is in
it.

The manifest is small and the entries are many, which is why they are stored
apart — ``manifest.json`` beside ``results.parquet`` — but they are one record
and neither is valid without the other.

Both dataclasses live in ``core`` because :mod:`fpbench.storage.result_set_store`
persists them and ``storage`` may only import ``core``. Deriving a result set
from a plan and a result store is :mod:`fpbench.execution.result_set`'s job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash

__all__ = [
    "ResultSetEntry",
    "ResultSetManifest",
    "ordered_results_hash",
    "result_set_fingerprint",
    "result_set_id",
    "RESULT_SET_SCHEMA_VERSION",
    "RESULT_SET_ID_LENGTH",
]

#: Bumped when the meaning of a result set changes. Inside the fingerprint, so
#: a bump separates new sets from old rather than silently reusing their ids.
RESULT_SET_SCHEMA_VERSION = "1"

#: Twelve hex characters, matching ``run_id`` and ``plan_id``.
RESULT_SET_ID_LENGTH = 12

_HEX = frozenset("0123456789abcdef")


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def _require_non_negative(value: int, field_name: str) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"{field_name} must not be negative")
    return number


@dataclass(frozen=True, slots=True)
class ResultSetEntry:
    """One stored result, at its place in the execution order.

    ``result_hash`` is the digest of the whole record — the same one the result
    file carries in its own parquet header — so verifying an entry means
    reading the file and re-deriving it, never trusting a second copy of a
    number.
    """

    ordinal: int
    job_id: str
    result_hash: str

    def __post_init__(self) -> None:
        validate_id(self.job_id)
        if int(self.ordinal) < 0:
            raise ValueError("ordinal is 0-based and must not be negative")
        object.__setattr__(self, "ordinal", int(self.ordinal))
        object.__setattr__(
            self, "result_hash", _require_digest(self.result_hash, "result_hash")
        )


def ordered_results_hash(entries: Iterable[ResultSetEntry]) -> str:
    """A digest of the results *in plan order*.

    Order is part of the identity. Two runs holding the same 6,000 results in a
    different order are not interchangeable — the ordinal is how a partially
    executed run is described precisely — so shuffling them changes this hash.
    """
    return stable_hash(
        {
            "schema": "result_set_ordered_results_v1",
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "job_id": entry.job_id,
                    "result_hash": entry.result_hash,
                }
                for entry in entries
            ],
        },
        length=64,
    )


def result_set_fingerprint(
    *,
    run_fingerprint: str,
    plan_fingerprint: str,
    runtime_bundle_fingerprint: str,
    entries: Iterable[ResultSetEntry],
    success_count: int,
    failure_count: int,
) -> str:
    """The digest behind ``result_set_id``.

    Includes the runtime bundle: the same pairs scored by two different builds
    of the same matcher are two different bodies of evidence, and the point of
    this record is that a later analysis cannot confuse them.
    """
    ordered = list(entries)
    return stable_hash(
        {
            "schema": "result_set_fingerprint_v1",
            "result_set_schema_version": RESULT_SET_SCHEMA_VERSION,
            "run_fingerprint": run_fingerprint,
            "plan_fingerprint": plan_fingerprint,
            "runtime_bundle_fingerprint": runtime_bundle_fingerprint,
            "entries": [
                {
                    "ordinal": entry.ordinal,
                    "job_id": entry.job_id,
                    "result_hash": entry.result_hash,
                }
                for entry in ordered
            ],
            "total_results": len(ordered),
            "success_count": int(success_count),
            "failure_count": int(failure_count),
        },
        length=64,
    )


def result_set_id(fingerprint: str) -> str:
    """``resultset_<12 chars of the result-set fingerprint>``."""
    digest = _require_digest(fingerprint, "result_set_fingerprint")
    return f"resultset_{digest[:RESULT_SET_ID_LENGTH]}"


@dataclass(frozen=True, slots=True)
class ResultSetManifest:
    """The identity of one immutable collection of raw results."""

    result_set_id: str
    result_set_fingerprint: str

    run_id: str
    run_fingerprint: str

    plan_id: str
    plan_fingerprint: str

    runtime_bundle_id: str
    runtime_bundle_fingerprint: str

    total_results: int
    success_count: int
    failure_count: int

    ordered_results_hash: str
    created_utc: str

    def __post_init__(self) -> None:
        for name in ("result_set_id", "run_id", "plan_id", "runtime_bundle_id"):
            validate_id(getattr(self, name))
        for name in (
            "result_set_fingerprint",
            "run_fingerprint",
            "plan_fingerprint",
            "runtime_bundle_fingerprint",
            "ordered_results_hash",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))
        for name in ("total_results", "success_count", "failure_count"):
            object.__setattr__(
                self, name, _require_non_negative(getattr(self, name), name)
            )
        if self.total_results <= 0:
            raise ValueError("a result set with no results is not a result set")
        if self.success_count + self.failure_count != self.total_results:
            raise ValueError(
                "a result set accounts for every result it holds: "
                f"{self.success_count} + {self.failure_count} != {self.total_results}"
            )
        created_utc = str(self.created_utc).strip()
        if not created_utc:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created_utc)

        expected_id = result_set_id(self.result_set_fingerprint)
        if self.result_set_id != expected_id:
            raise ValueError(
                f"result_set_id must be derived from the fingerprint: expected "
                f"{expected_id}, got {self.result_set_id!r}"
            )

    def counts(self) -> Mapping[str, int]:
        return {
            "total_results": self.total_results,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
        }
