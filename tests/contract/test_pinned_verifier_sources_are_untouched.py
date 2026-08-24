"""Files a published verifier pins byte-for-byte must still match their commit.

Stage 8A, Stage 8B and Stage 8C each publish a verifier that requires a named
set of paths to be byte-identical to its own ``verifier_source_commit``, and
clean including untracked files. Editing one turns a committed evidence gate red.

The gate is also the last thing to notice. It needs a workspace, and it reports
several minutes into an integration run with a message about "the active Stage
8C authority source" that names no file. This reproduces the same `git diff` in
a tenth of a second and says which path and which stage.

It is not hypothetical. A repository-wide change to how JSON documents are
written moved the import in two of these files, and nothing said so until a
full run.

The established response to needing a change inside one of these sets is a
*sibling module*, not a widened allowlist: Stage 8B added
``core/flx_errors.py``, Stage 8D ``core/calibration_errors.py``, Stage 8E
``core/third_party_errors.py``, and the atomic-write work added
``core/json_io.py`` rather than editing the ``core/serialization.py`` that
Stage 8A pins (ADR 0139).
"""

from __future__ import annotations

import importlib
import json
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Stage, the module holding its pinned paths, and the marker naming the commit
#: those paths are pinned to.
_PINNED_SETS = (
    (
        "8A",
        "fpbench.modern_matchers.verify",
        "evidence/stage8a-modern-matcher-selection/stage-8a-finalization.json",
    ),
    (
        "8B",
        "fpbench.flx.verify",
        "evidence/stage8b-flx-runtime-qualification/stage-8b-finalization.json",
    ),
    (
        "8C",
        "fpbench.experiments.stage8c_verify",
        "evidence/flx-canonical500-raw/stage-8c-finalization.json",
    ),
)


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(REPOSITORY_ROOT), *arguments),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.fixture(scope="module", autouse=True)
def _needs_a_worktree() -> None:
    if not (REPOSITORY_ROOT / ".git").exists():
        pytest.skip("not a Git worktree; the pinning gate does not apply here")


@pytest.mark.parametrize(
    ("stage", "module_name", "marker"), _PINNED_SETS, ids=lambda v: str(v)
)
def test_the_pinned_source_still_matches_the_verifier_commit(
    stage: str, module_name: str, marker: str
) -> None:
    paths = importlib.import_module(module_name)._VERIFIER_AUTHORITY_PATHS
    document = json.loads((REPOSITORY_ROOT / marker).read_text(encoding="utf-8"))
    commit = document["verifier_source_commit"]

    if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        pytest.skip(f"Stage {stage}'s verifier commit is not in this clone")

    diff = _git("diff", "--name-only", commit, "--", *paths)
    drifted = sorted(diff.stdout.split())
    assert not drifted, (
        f"Stage {stage} pins these paths byte-for-byte to {commit[:12]} and they "
        f"differ here: {drifted}. Add a sibling module instead of editing them "
        "(ADR 0139), or re-publish the stage deliberately"
    )


@pytest.mark.parametrize(
    ("stage", "module_name", "marker"), _PINNED_SETS, ids=lambda v: str(v)
)
def test_the_pinned_source_tree_carries_nothing_untracked(
    stage: str, module_name: str, marker: str
) -> None:
    """The verifiers require clean *including untracked files*."""
    paths = importlib.import_module(module_name)._VERIFIER_AUTHORITY_PATHS
    status = _git("status", "--porcelain", "--untracked-files=all", "--", *paths)
    dirty = sorted(line[3:] for line in status.stdout.splitlines() if line.strip())
    assert not dirty, (
        f"Stage {stage}'s pinned source tree is not clean: {dirty}"
    )


def test_every_pinned_path_still_exists() -> None:
    """A verifier that pins a path Git no longer has can never go green."""
    missing = []
    for stage, module_name, _ in _PINNED_SETS:
        for path in importlib.import_module(module_name)._VERIFIER_AUTHORITY_PATHS:
            if not (REPOSITORY_ROOT / path).exists():
                missing.append(f"{path} (Stage {stage})")
    assert not missing, f"published verifiers pin paths that are gone: {missing}"


# ------------------------------------------------- what is still on the old writer


#: Files that still write JSON through the fixed-``.tmp`` writer in
#: ``core/serialization.py``, and what closing that would cost.
#:
#: This used to name ``storage/modern_matcher_store.py`` and
#: ``storage/flx_store.py``, with a note that the two were exempt because fixing
#: them re-issues four stages of published evidence: Stage 8A's
#: ``verifier_source_commit`` moves, which moves Stage 8A's fingerprint, which
#: Stage 8B binds, whose fingerprint ``stage8c_identity`` freezes, whose
#: fingerprint ``stage8d_identity`` freezes — and Stage 8C's own verifier pins
#: the module holding its predecessor constant, so it takes several commits.
#:
#: That was a decision to take deliberately rather than as a side effect of a
#: refactor. It was taken, the four markers were re-issued over unchanged runs,
#: and the storage layer has no check-then-write publication left.
#:
#: What remains is one *experiment* module, and it is a different case. It writes
#: evidence markers, which ADR 0139 leaves on ``replace_*`` on purpose: a marker
#: is regenerated by design, so create-if-absent would be the wrong semantic. The
#: entry stays because a fixed ``.tmp`` is still a shared scratch name, and
#: because moving it would re-issue Stage 8C for no gain in the meantime.
_ON_THE_FIXED_TEMP_WRITER = {
    "src/fpbench/experiments/flx_canonical500_full.py": "8C",
}


def test_the_fixed_temp_writer_has_exactly_the_known_callers() -> None:
    """A *new* caller of the unsafe writer is a regression, not an exemption."""
    callers = set()
    for path in sorted((REPOSITORY_ROOT / "src").rglob("*.py")):
        relative = path.relative_to(REPOSITORY_ROOT).as_posix()
        if relative == "src/fpbench/core/serialization.py":
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("from fpbench.core.serialization import") and (
                "write_json" in line
            ):
                callers.add(relative)

    unexpected = sorted(callers - set(_ON_THE_FIXED_TEMP_WRITER) - _ALSO_PINNED)
    assert not unexpected, (
        f"{unexpected} import the fixed-temp write_json from core.serialization. "
        "New code uses fpbench.core.json_io, which writes through the shared "
        "atomic publisher (ADR 0139)"
    )


#: Other modules that import the same writer. They are in the same position, and
#: pinned by a stage's ``_SOURCE_FILES`` rather than by a verifier's authority
#: paths — which is why they are listed apart: the check below can only ask about
#: the paths a *verifier* pins.
_ALSO_PINNED = frozenset(
    {
        "src/fpbench/experiments/stage11b_finalization.py",
        "src/fpbench/experiments/verifinger_canonical500_full.py",
    }
)


def test_the_known_callers_are_still_pinned() -> None:
    """If one stops being pinned, it can and should be fixed."""
    pinned: set[str] = set()
    for _stage, module_name, _marker in _PINNED_SETS:
        pinned.update(importlib.import_module(module_name)._VERIFIER_AUTHORITY_PATHS)

    freed = sorted(
        relative
        for relative in _ON_THE_FIXED_TEMP_WRITER
        if not any(
            relative == entry or relative.startswith(entry.rstrip("/") + "/")
            for entry in pinned
        )
    )
    assert not freed, (
        f"{freed} are no longer pinned by a published verifier, so nothing "
        "stops them moving to fpbench.core.json_io. Move them and delete this "
        "entry"
    )
