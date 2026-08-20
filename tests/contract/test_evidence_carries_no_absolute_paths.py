"""``evidence/`` must not name anybody's machine.

``evidence/README.md`` promises it, several stage markers assert it about
themselves as ``"absolute_paths_in_evidence": false``, and until this test
existed nothing checked either claim. Stage 11A's ``runtime-identity.json``
published seven module paths under the author's home directory, in a directory
whose README said there were none.

The check runs over the published *bytes* rather than over the model that
produced them, for the same reason
:func:`fpbench.core.research_models.require_sanitised` does: the leak was in a
string value of a field nobody thought of as holding a path, and a per-field
allowlist would have missed it exactly as the reviewers did.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.evidence_sanitisation import find_absolute_paths

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"

#: The one document that still publishes absolute paths, and cannot be fixed
#: without re-running a 500-comparison licensed-SDK run.
#:
#: ``stage11a-.../runtime-identity.json`` records seven module paths under the
#: author's home directory. Redacting them changes the file's digest, which is
#: in Stage 11A's ``evidence_content_hashes``, which is inside
#: ``stage_11a_finalization_fingerprint`` — and that value is frozen into
#: ``verifinger_java.identity.PIPELINE_METADATA``, so it reaches
#: ``algorithm_fingerprint`` and is stored in every one of Stage 11B's 500 raw
#: results. Changing it does not re-issue a marker; it invalidates a run, and
#: re-executing that run needs the VeriFinger trial re-activated and a JVM.
#:
#: So it is named here rather than quietly excluded. Removing this entry is the
#: last step of that re-run, not a tidy-up.
_BLOCKED_ON_A_RERUN = frozenset(
    {"stage11a-verifinger-2025_2-preflight/runtime-identity.json"}
)


def _json_documents() -> list[Path]:
    return sorted(EVIDENCE.rglob("*.json"))


def _text_documents() -> list[Path]:
    return sorted(EVIDENCE.rglob("*.md"))


@pytest.mark.parametrize(
    "document", _json_documents(), ids=lambda p: p.relative_to(EVIDENCE).as_posix()
)
def test_a_published_json_document_names_no_absolute_path(document: Path) -> None:
    relative = document.relative_to(EVIDENCE).as_posix()
    if relative in _BLOCKED_ON_A_RERUN:
        pytest.xfail(
            "publishes absolute paths; redacting them invalidates Stage 11B's "
            "500-comparison run (see _BLOCKED_ON_A_RERUN)"
        )
    payload = json.loads(document.read_text(encoding="utf-8"))
    leaks = find_absolute_paths(payload, path=document.name)
    assert not leaks, (
        f"{document.relative_to(REPOSITORY_ROOT).as_posix()} publishes an "
        f"absolute path: {leaks[0][0]} = {leaks[0][1]!r}. Redact it at the "
        "producer with fpbench.core.evidence_sanitisation.redact_absolute_paths, "
        "then re-issue the marker's content hash"
    )


def test_the_blocked_list_still_names_a_real_leak() -> None:
    """An exemption that stopped being needed must be deleted, not carried.

    If the Stage 11B run is ever re-executed and this document redacted, this
    test fails and points at the entry to remove.
    """
    for relative in _BLOCKED_ON_A_RERUN:
        document = EVIDENCE / relative
        assert document.is_file(), f"{relative} is exempted and does not exist"
        payload = json.loads(document.read_text(encoding="utf-8"))
        assert find_absolute_paths(payload, path=document.name), (
            f"{relative} no longer publishes an absolute path — remove it from "
            "_BLOCKED_ON_A_RERUN"
        )


@pytest.mark.parametrize(
    "document", _text_documents(), ids=lambda p: p.relative_to(EVIDENCE).as_posix()
)
def test_a_published_readme_names_no_absolute_path(document: Path) -> None:
    leaks = find_absolute_paths(
        document.read_text(encoding="utf-8"), path=document.name
    )
    assert not leaks, (
        f"{document.relative_to(REPOSITORY_ROOT).as_posix()} publishes an "
        f"absolute path: {leaks[0][1]!r}"
    )
