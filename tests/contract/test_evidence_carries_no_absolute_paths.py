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

For a time this test carried that one document as an expected failure, because
redacting it moved Stage 11A's finalization fingerprint, and that value reaches
``algorithm_fingerprint`` and is stored in every one of Stage 11B's 6,000 raw
results — so the redaction invalidated a licensed-SDK run rather than re-issuing
a marker. The redaction now happens at the producer, which is what removed the
exemption and what forced that run to be executed again. There is deliberately
no allowlist left to add to: a historical exemption is indistinguishable from a
new leak once it is a set literal, and the next one should stop a publication
rather than join a list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fpbench.core.evidence_sanitisation import find_absolute_paths

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPOSITORY_ROOT / "evidence"


def _json_documents() -> list[Path]:
    return sorted(EVIDENCE.rglob("*.json"))


def _text_documents() -> list[Path]:
    return sorted(EVIDENCE.rglob("*.md"))


@pytest.mark.parametrize(
    "document", _json_documents(), ids=lambda p: p.relative_to(EVIDENCE).as_posix()
)
def test_a_published_json_document_names_no_absolute_path(document: Path) -> None:
    payload = json.loads(document.read_text(encoding="utf-8"))
    leaks = find_absolute_paths(payload, path=document.name)
    assert not leaks, (
        f"{document.relative_to(REPOSITORY_ROOT).as_posix()} publishes an "
        f"absolute path: {leaks[0][0]} = {leaks[0][1]!r}. Redact it at the "
        "producer with fpbench.core.evidence_sanitisation.redact_absolute_paths, "
        "then re-issue the marker's content hash"
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
