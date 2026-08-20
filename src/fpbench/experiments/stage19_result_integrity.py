"""The one count Stage 19A/19B may publish for a canonical raw run.

The resumable Stage 19 runners store one JSON object per comparison in
``pair-outcomes.jsonl``.  Diagnostics are derived from that file, but they are a
report rather than the store itself.  Finalization therefore reads both and
requires every independent description of the run's cardinality to agree.

In particular, no caller supplies ``stored`` or ``missing``.  A command-line
number is a claim about the result store, not evidence from it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "Stage19ResultIntegrityError",
    "OutcomeStoreIntegrity",
    "canonical_source_sha256",
    "verify_outcome_store_integrity",
]


class Stage19ResultIntegrityError(RuntimeError):
    """The outcome store and the diagnostic report do not describe one run."""


@dataclass(frozen=True, slots=True)
class OutcomeStoreIntegrity:
    """Counts derived from the outcome store, after equality was proved."""

    expected_outcomes: int
    stored_outcomes: int
    unique_pair_ids: int
    unique_ordinals: int
    diagnostic_comparisons: int
    missing: int
    outcome_store_sha256: str

    def describe(self) -> dict[str, int | str]:
        return {
            "expected_outcomes": self.expected_outcomes,
            "stored_outcomes": self.stored_outcomes,
            "unique_pair_ids": self.unique_pair_ids,
            "unique_ordinals": self.unique_ordinals,
            "diagnostic_comparisons": self.diagnostic_comparisons,
            "missing": self.missing,
            "outcome_store_sha256": self.outcome_store_sha256,
        }


def canonical_source_sha256(path: Path) -> str:
    """Hash a text source identically on LF and CRLF checkouts.

    Stage source fingerprints describe repository content, not the checkout's
    platform-specific newline materialization.  Outcome-store hashes remain
    byte-exact and deliberately do not use this helper.
    """
    payload = Path(path).read_bytes()
    canonical = payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(canonical).hexdigest()


def _exact_non_negative_int(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise Stage19ResultIntegrityError(
            f"{field} must be a non-negative JSON integer"
        )
    return value


def verify_outcome_store_integrity(
    outcomes_path: Path,
    diagnostics: Mapping[str, Any],
    *,
    expected_outcomes: int,
) -> OutcomeStoreIntegrity:
    """Read the JSONL store and prove all five canonical counts are equal.

    The stronger ordinal check matters even after the counts agree: 6,000
    distinct ordinals numbered 1..6,000 are not the canonical 0..5,999 run.
    """
    expected = _exact_non_negative_int(expected_outcomes, "expected_outcomes")
    path = Path(outcomes_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise Stage19ResultIntegrityError(
            f"cannot read the Stage 19 outcome store {path}: {exc}"
        ) from exc

    pair_ids: list[str] = []
    ordinals: list[int] = []
    status_counts: dict[str, int] = {}
    for line_number, raw_line in enumerate(payload.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Stage19ResultIntegrityError(
                f"{path}:{line_number}: unreadable JSON outcome ({exc})"
            ) from exc
        if not isinstance(row, dict):
            raise Stage19ResultIntegrityError(
                f"{path}:{line_number}: an outcome must be a JSON object"
            )

        pair_id = row.get("pair_id")
        if type(pair_id) is not str or not pair_id.strip():
            raise Stage19ResultIntegrityError(
                f"{path}:{line_number}: pair_id must be a non-empty string"
            )
        ordinal = _exact_non_negative_int(
            row.get("ordinal"), f"{path}:{line_number}: ordinal"
        )
        status = row.get("status")
        if type(status) is not str or not status.strip():
            raise Stage19ResultIntegrityError(
                f"{path}:{line_number}: status must be a non-empty string"
            )

        pair_ids.append(pair_id.strip())
        ordinals.append(ordinal)
        status_counts[status] = status_counts.get(status, 0) + 1

    stored = len(pair_ids)
    unique_pairs = len(set(pair_ids))
    unique_ordinals = len(set(ordinals))

    overall = diagnostics.get("overall")
    if not isinstance(overall, Mapping):
        raise Stage19ResultIntegrityError(
            "the diagnostic report has no overall comparison population"
        )
    diagnostic_comparisons = _exact_non_negative_int(
        overall.get("comparisons"), "diagnostics.overall.comparisons"
    )

    observed = {
        "unique pair_ids": unique_pairs,
        "unique ordinals": unique_ordinals,
        "diagnostic comparisons": diagnostic_comparisons,
        "stored outcomes": stored,
        "expected outcomes": expected,
    }
    if len(set(observed.values())) != 1:
        detail = ", ".join(f"{name}={value}" for name, value in observed.items())
        raise Stage19ResultIntegrityError(
            "Stage 19 finalization requires unique pair_ids == unique ordinals == "
            "diagnostic comparisons == stored outcomes == expected outcomes; "
            + detail
        )

    expected_ordinals = set(range(expected))
    if set(ordinals) != expected_ordinals:
        missing_ordinals = sorted(expected_ordinals - set(ordinals))
        unexpected_ordinals = sorted(set(ordinals) - expected_ordinals)
        raise Stage19ResultIntegrityError(
            "the outcome-store ordinals are not the canonical 0.."
            f"{expected - 1}: missing={missing_ordinals[:3]}, "
            f"unexpected={unexpected_ordinals[:3]}"
        )

    reported_counts = diagnostics.get("outcome_counts")
    if not isinstance(reported_counts, Mapping):
        raise Stage19ResultIntegrityError(
            "the diagnostic report has no outcome_counts mapping"
        )
    normalized_counts = {
        str(status): _exact_non_negative_int(
            count, f"diagnostics.outcome_counts[{status!r}]"
        )
        for status, count in reported_counts.items()
    }
    if normalized_counts != status_counts:
        raise Stage19ResultIntegrityError(
            "diagnostics.outcome_counts does not describe the outcome store: "
            f"diagnostics={normalized_counts}, store={status_counts}"
        )

    return OutcomeStoreIntegrity(
        expected_outcomes=expected,
        stored_outcomes=stored,
        unique_pair_ids=unique_pairs,
        unique_ordinals=unique_ordinals,
        diagnostic_comparisons=diagnostic_comparisons,
        missing=expected - stored,
        outcome_store_sha256=hashlib.sha256(payload).hexdigest(),
    )
