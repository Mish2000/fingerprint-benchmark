"""Definitions are filed by id, and stage 5A's flat file still reads.

Stage 5A wrote one ``definition.json`` per experiment and run. That was correct
while an experiment could pin only one thing, and it stopped being correct the
moment a second metric policy over the same decisions became a legitimate second
evaluation. The store namespaces new definitions and reads the old file where it
is — because that file is cited by a committed receipt and a finalization
marker, and moving it would invalidate a verified chain to achieve nothing
(spec section 35).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from fpbench.core.json_io import write_json
from fpbench.storage.definition_store import DefinitionStore

pytestmark = pytest.mark.metrics

RUN = "run_example"
EXPERIMENT = "example_experiment_v1"


@dataclass(frozen=True)
class _Definition:
    """The two fields the filing system needs, and a payload to round-trip.

    A dataclass because the store serialises through ``to_plain``, which is how
    every real definition reaches disk.
    """

    definition_id: str
    definition_fingerprint: str
    note: str = ""


def _store(root: Path) -> DefinitionStore:
    return DefinitionStore(
        root,
        experiment_id=EXPERIMENT,
        loader=lambda payload: _Definition(
            payload["definition_id"],
            payload["definition_fingerprint"],
            payload.get("note", ""),
        ),
        pointer_name="current-thing.json",
    )


def _definition(suffix: str = "a") -> _Definition:
    fingerprint = suffix * 64
    return _Definition(f"example_{fingerprint[:12]}", fingerprint, note=suffix)


def test_a_definition_is_written_under_its_own_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    definition = _definition()
    path = store.write(RUN, definition)

    assert path.parent.name == definition.definition_id
    assert path.parent.parent.name == "definitions"
    assert store.read(RUN, definition.definition_id) == definition


def test_two_definitions_coexist(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first, second = _definition("a"), _definition("b")
    store.write(RUN, first)
    store.write(RUN, second)

    assert set(store.definition_ids(RUN)) == {
        first.definition_id,
        second.definition_id,
    }
    assert store.read(RUN, first.definition_id).note == "a"
    assert store.read(RUN, second.definition_id).note == "b"


def test_writing_the_same_definition_twice_is_a_no_op(tmp_path: Path) -> None:
    store = _store(tmp_path)
    definition = _definition()
    path = store.write(RUN, definition)
    stamp = path.stat().st_mtime_ns
    assert store.write(RUN, definition) == path
    assert path.stat().st_mtime_ns == stamp


def test_a_different_definition_under_the_same_id_is_a_conflict(
    tmp_path: Path,
) -> None:
    from fpbench.core.errors import StorageError

    store = _store(tmp_path)
    definition = _definition()
    store.write(RUN, definition)

    forged = _Definition(definition.definition_id, "c" * 64, note="forged")
    with pytest.raises(StorageError, match="refusing to"):
        store.write(RUN, forged)


def test_the_legacy_flat_file_is_still_readable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    definition = _definition()
    write_json(
        store.legacy_definition_path(RUN),
        {
            "definition_id": definition.definition_id,
            "definition_fingerprint": definition.definition_fingerprint,
            "note": definition.note,
        },
    )

    assert store.read(RUN, definition.definition_id) == definition
    assert store.read_active(RUN) == definition


def test_writing_a_definition_the_legacy_file_already_pins_is_a_no_op(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    definition = _definition()
    legacy = store.legacy_definition_path(RUN)
    write_json(
        legacy,
        {
            "definition_id": definition.definition_id,
            "definition_fingerprint": definition.definition_fingerprint,
            "note": definition.note,
        },
    )

    # Rewriting it in the new layout would leave two files claiming one
    # identity, which is worse than the flat filename it replaced.
    assert store.write(RUN, definition) == legacy
    assert store.definition_ids(RUN) == ()


def test_the_namespaced_definition_wins_when_both_exist(tmp_path: Path) -> None:
    store = _store(tmp_path)
    legacy_definition = _definition("a")
    write_json(
        store.legacy_definition_path(RUN),
        {
            "definition_id": legacy_definition.definition_id,
            "definition_fingerprint": legacy_definition.definition_fingerprint,
            "note": "legacy",
        },
    )
    current = _definition("b")
    store.write(RUN, current)
    store.write_pointer(RUN, definition_id=current.definition_id)

    assert store.read_active(RUN) == current


def test_the_pointer_carries_extra_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    definition = _definition()
    store.write(RUN, definition)
    store.write_pointer(
        RUN, definition_id=definition.definition_id, metric_set_id="metricset_abc123"
    )

    assert store.read_pointer(RUN) == definition.definition_id
    assert store.read_pointer_value(RUN, "metric_set_id") == "metricset_abc123"
    assert store.read_pointer_value(RUN, "absent") is None


def test_a_missing_definition_reports_the_namespaced_path(tmp_path: Path) -> None:
    from fpbench.core.errors import StorageError

    store = _store(tmp_path)
    with pytest.raises(StorageError, match="definition not found"):
        store.read(RUN, "example_000000000000")


def test_reading_nothing_at_all_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).read_active(RUN) is None
