"""Every file a stage fingerprints must be pinned to LF, and must be LF here.

A stage's source fingerprint is hashed over the checkout's bytes. On a Windows
checkout with ``core.autocrlf=true`` those bytes carry ``\\r\\n``; on Linux they
carry ``\\n``. The same commit therefore has two fingerprints, and the gate that
was green on the machine that published the marker goes red everywhere else —
which is exactly what happened to Stage 18A before ``.gitattributes`` grew the
block this test guards.

Two assertions, because either one alone can be satisfied while the property
fails: the path must be *declared* ``text eol=lf``, and the file in *this*
worktree must actually be LF. The first is what makes future checkouts correct;
the second catches a file that was committed with CRLF before the rule existed
and never renormalised.
"""

from __future__ import annotations

import fnmatch
import importlib
from pathlib import Path, PurePosixPath

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Where each stage keeps the tuple of files its fingerprint covers. A stage
#: added later belongs here; the test below fails loudly if the module exists
#: and the attribute does not, rather than skipping quietly.
_STAGE_SOURCE_LISTS = (
    ("fpbench.experiments.stage15a_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage16a_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage17a_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage18a_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage19a_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage19b_finalization", "_SOURCE_FILES"),
    ("fpbench.experiments.stage20a_mcc_sdk", "SOURCE_FILES"),
    ("fpbench.experiments.stage20b_finalization", "SOURCE_FILES"),
)


def _fingerprinted_paths() -> tuple[str, ...]:
    paths: set[str] = set()
    for module_name, attribute in _STAGE_SOURCE_LISTS:
        module = importlib.import_module(module_name)
        paths.update(getattr(module, attribute))
    return tuple(sorted(paths))


def _lf_patterns() -> tuple[str, ...]:
    """Every ``.gitattributes`` pattern that carries ``eol=lf``."""
    patterns: list[str] = []
    text = (REPOSITORY_ROOT / ".gitattributes").read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "eol=lf" not in stripped:
            continue
        patterns.append(stripped.split()[0])
    return tuple(patterns)


def _matches(pattern: str, path: str) -> bool:
    """Git's pathname matching, for the shapes this file uses.

    ``*`` matches within one path segment and ``**`` matches any number of
    segments — the distinction ``fnmatch`` does not make, and the reason this is
    written out rather than delegated. A pattern with no slash matches by
    basename anywhere in the tree, which is how Git reads it.
    """
    if "/" not in pattern.rstrip("/"):
        return fnmatch.fnmatchcase(PurePosixPath(path).name, pattern)

    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.split("/")

    def walk(p: int, q: int) -> bool:
        if p == len(pattern_parts):
            return q == len(path_parts)
        if pattern_parts[p] == "**":
            return any(walk(p + 1, rest) for rest in range(q, len(path_parts) + 1))
        if q == len(path_parts):
            return False
        if not fnmatch.fnmatchcase(path_parts[q], pattern_parts[p]):
            return False
        return walk(p + 1, q + 1)

    return walk(0, 0)


def _is_pinned(path: str, patterns: tuple[str, ...]) -> bool:
    return any(_matches(pattern, path) for pattern in patterns)


@pytest.mark.parametrize("relative", _fingerprinted_paths())
def test_a_fingerprinted_source_is_pinned_to_lf(relative: str) -> None:
    assert _is_pinned(relative, _lf_patterns()), (
        f"{relative} is inside a stage's source fingerprint but .gitattributes "
        "does not pin it to eol=lf, so its hash depends on which platform "
        "checked it out"
    )


@pytest.mark.parametrize("relative", _fingerprinted_paths())
def test_a_fingerprinted_source_is_lf_in_this_worktree(relative: str) -> None:
    path = REPOSITORY_ROOT / relative
    assert path.is_file(), f"{relative} is fingerprinted but not present"
    assert b"\r\n" not in path.read_bytes(), (
        f"{relative} still holds CRLF in this worktree. Pinning it in "
        "`.gitattributes` only affects future checkouts; the committed bytes "
        "need `git add --renormalize` as well"
    )
