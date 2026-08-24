"""The primitive itself: what it does, in what order, on every outcome.

The store-level guarantee is checked over all eight stores in
``tests/contract/test_every_set_publishes_the_set_it_verified.py``. These are the
mechanics underneath it, with the stores' formats replaced by counters, because
what went wrong three times was never a format — it was an order, and a branch.

The previous version of this file tested a ``SetClaim`` whose ``write_body``
flag left the verification to each caller. It passed, thoroughly, while three
callers were getting that branch wrong. So these assert the two properties the
flag made unassertable: that verification happens on **every** path out of
:func:`publish_set`, and that nothing is created before everything present has
been checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.errors import StorageError
from fpbench.storage.set_publication import SetBody, publish_set


class _Recorder:
    """A body that records what was asked of it, and can be told to disagree."""

    def __init__(self, path: Path, *, agrees: bool = True) -> None:
        self.path = Path(path)
        self.agrees = agrees
        self.verified = 0
        self.created = 0
        self.log: list[str] = []

    def body(self) -> SetBody:
        return SetBody(
            path=self.path,
            verify_existing=self._verify,
            publish_missing=self._create,
        )

    def _verify(self) -> None:
        self.verified += 1
        self.log.append("verify")
        if not self.path.is_file():
            raise StorageError(f"missing: {self.path}")
        if not self.agrees:
            raise StorageError(f"{self.path} is not the expected body")

    def _create(self) -> None:
        self.created += 1
        self.log.append("create")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("body", encoding="utf-8")


def _publish(
    tmp_path: Path,
    recorders: tuple[_Recorder, ...],
    *,
    fingerprint: str = "a" * 64,
    whole_set: list[str] | None = None,
):
    manifest_path = tmp_path / "manifest.json"
    recorded = whole_set if whole_set is not None else []

    def stored_fingerprint() -> str:
        return json.loads(manifest_path.read_text(encoding="utf-8"))["fingerprint"]

    return publish_set(
        manifest_path=manifest_path,
        manifest={"fingerprint": fingerprint},
        fingerprint=fingerprint,
        stored_fingerprint=stored_fingerprint,
        bodies=tuple(recorder.body() for recorder in recorders),
        verify_whole_set=lambda: recorded.append("whole"),
        conflict=lambda stored: StorageError(f"conflict with {stored}"),
    )


def test_a_fresh_publication_creates_then_verifies(tmp_path: Path) -> None:
    one = _Recorder(tmp_path / "one")
    whole: list[str] = []

    result = _publish(tmp_path, (one,), whole_set=whole)

    assert result.created and not result.already_published
    assert one.log == ["create", "verify"], (
        "a body must be read back after it is written, not assumed"
    )
    assert whole == ["whole"]


def test_a_retry_over_a_finished_set_verifies_and_creates_nothing(
    tmp_path: Path,
) -> None:
    """The case that was silently skipped: everything present, so nothing read."""
    one = _Recorder(tmp_path / "one")
    _publish(tmp_path, (one,))

    again = _Recorder(tmp_path / "one")
    whole: list[str] = []
    result = _publish(tmp_path, (again,), whole_set=whole)

    assert not result.created and result.already_published
    assert again.created == 0, "a finished set was written again"
    assert again.verified >= 1, "a finished set was returned without being read"
    assert whole == ["whole"]


def test_everything_present_is_verified_before_anything_is_created(
    tmp_path: Path,
) -> None:
    """One body missing and another disagreeing is a conflict, not a repair."""
    first = _Recorder(tmp_path / "one")
    second = _Recorder(tmp_path / "two")
    _publish(tmp_path, (first, second))

    (tmp_path / "one").unlink()
    disagreeing = _Recorder(tmp_path / "two", agrees=False)
    missing = _Recorder(tmp_path / "one")

    with pytest.raises(StorageError):
        _publish(tmp_path, (missing, disagreeing))

    assert missing.created == 0, (
        "the missing body was created even though another body disagreed"
    )
    assert not (tmp_path / "one").is_file()


def test_a_different_fingerprint_is_refused_before_a_body_is_touched(
    tmp_path: Path,
) -> None:
    one = _Recorder(tmp_path / "one")
    _publish(tmp_path, (one,))

    intruder = _Recorder(tmp_path / "one")
    with pytest.raises(StorageError, match="conflict with"):
        _publish(tmp_path, (intruder,), fingerprint="b" * 64)

    assert intruder.log == [], "a conflicting set read or wrote a body"


def test_orphaned_bodies_are_decided_before_the_claim(tmp_path: Path) -> None:
    """Bodies under a name nothing claims: verified, or the claim is refused."""
    (tmp_path / "one").write_text("body", encoding="utf-8")

    agreeing = _Recorder(tmp_path / "one")
    _publish(tmp_path, (agreeing,))
    assert (tmp_path / "manifest.json").is_file()
    assert agreeing.created == 0

    other = tmp_path / "other"
    other.mkdir()
    (other / "one").write_text("body", encoding="utf-8")
    disagreeing = _Recorder(other / "one", agrees=False)
    with pytest.raises(StorageError):
        _publish(other, (disagreeing,))
    assert not (other / "manifest.json").is_file(), (
        "a set was claimed over bodies that disagree with it"
    )


def test_an_unreadable_manifest_is_the_callers_error_and_touches_nothing(
    tmp_path: Path,
) -> None:
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")
    one = _Recorder(tmp_path / "one")

    with pytest.raises(json.JSONDecodeError):
        _publish(tmp_path, (one,))

    assert one.log == []


def test_the_whole_set_check_runs_on_every_outcome(tmp_path: Path) -> None:
    """Fresh, resumed and already-finished all end at the same gate."""
    calls: list[str] = []

    one = _Recorder(tmp_path / "one")
    two = _Recorder(tmp_path / "two")
    _publish(tmp_path, (one, two), whole_set=calls)
    assert calls == ["whole"]

    (tmp_path / "two").unlink()
    _publish(tmp_path, (_Recorder(tmp_path / "one"), _Recorder(tmp_path / "two")),
             whole_set=calls)
    assert calls == ["whole", "whole"]

    _publish(tmp_path, (_Recorder(tmp_path / "one"), _Recorder(tmp_path / "two")),
             whole_set=calls)
    assert calls == ["whole", "whole", "whole"]


def test_only_the_missing_body_is_created(tmp_path: Path) -> None:
    first = _Recorder(tmp_path / "one")
    second = _Recorder(tmp_path / "two")
    _publish(tmp_path, (first, second))

    (tmp_path / "two").unlink()
    present = _Recorder(tmp_path / "one")
    absent = _Recorder(tmp_path / "two")
    result = _publish(tmp_path, (present, absent))

    assert present.created == 0
    assert absent.created == 1
    assert result.completed == (tmp_path / "two",)
