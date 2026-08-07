"""Determinism across processes, and the import boundary as a running check.

Two things the rest of the suite cannot establish from inside one interpreter.

**Restart determinism.** Shuffling rows and round-tripping JSON both happen in
the process that made the selection. A *second* process, with a different hash
seed, is what rules out an answer that depended on set or dict iteration order —
the one source of nondeterminism that is invisible until the day it is not
(spec section 29).

**The import boundary, executed.** ``_audit_source_boundaries`` is the check the
finalization runs, and a check that only ever runs at publication time is a check
that fails when it is most expensive to fix. It needs no Git and no evidence, so
it runs here on every test invocation (spec section 30).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import fpbench
from fpbench.experiments.stage8d_finalization import (
    _audit_source_boundaries,
    _is_allowed_change,
    _is_owned_path,
)

pytestmark = pytest.mark.stage8d_contract

REPOSITORY_ROOT = Path(fpbench.__file__).resolve().parents[2]


# ------------------------------------------------------- restart determinism


#: Re-derives the whole synthetic qualification and prints its identity. Run in a
#: fresh interpreter, twice, under two different hash seeds.
_PROBE = textwrap.dedent(
    """
    from fpbench.experiments.stage8d_calibration_infrastructure import (
        run_synthetic_qualification,
    )

    qualification = run_synthetic_qualification()
    print(qualification.qualification_fingerprint)
    for case in qualification.cases:
        print(case.case_id, case.outcome)
    """
)


def _run_probe(seed: str) -> str:
    import os

    environment = dict(os.environ)
    environment["PYTHONHASHSEED"] = seed
    completed = subprocess.run(
        (sys.executable, "-c", _PROBE),
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPOSITORY_ROOT),
        env=environment,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def test_a_fresh_process_under_a_different_hash_seed_agrees_exactly() -> None:
    """Spec section 29: same threshold, comparator, counts and fingerprint.

    Two interpreters, two hash seeds. Every case's outcome is compared, not only
    the qualification fingerprint, so a single case that drifted would be named
    rather than hidden inside one digest.
    """
    first = _run_probe("0")
    second = _run_probe("12345")
    assert first == second
    assert first.strip(), "the probe printed nothing"


def test_the_qualification_agrees_with_the_one_this_process_derives() -> None:
    from fpbench.experiments.stage8d_calibration_infrastructure import (
        run_synthetic_qualification,
    )

    in_process = run_synthetic_qualification()
    assert _run_probe("0").splitlines()[0] == in_process.qualification_fingerprint


# --------------------------------------------------------- the import boundary


def test_no_stage_8d_module_imports_an_algorithm_or_a_derivation_layer() -> None:
    """Spec section 30, run rather than merely defined.

    Covers every Stage 8D source file, including the experiment modules — which
    the ``fpbench.calibration`` boundary test cannot, because they legitimately
    live outside the package.
    """
    _audit_source_boundaries(REPOSITORY_ROOT)


def test_stage_8d_source_names_only_the_evidence_it_may_read() -> None:
    """The four published documents the protected registry is built from.

    Asserted by the same audit as above; this test exists to state the claim
    separately, because "names no prior evidence at all" would be the wrong rule
    and is the one a reader would assume (spec section 24).
    """
    from fpbench.experiments.stage8d_finalization import (
        _PERMITTED_PRIOR_STAGE_DOCUMENTS,
    )

    assert len(_PERMITTED_PRIOR_STAGE_DOCUMENTS) == 4
    for relative in _PERMITTED_PRIOR_STAGE_DOCUMENTS:
        assert (REPOSITORY_ROOT / relative).is_file(), relative
    _audit_source_boundaries(REPOSITORY_ROOT)


# ------------------------------------------------------------- the allowlists


@pytest.mark.parametrize(
    "path",
    [
        "evidence/flx-canonical500-raw/stage-8c-finalization.json",
        "evidence/sourceafis-canonical500-full/run_4c59fa02a6ab.json",
        "evidence/nbis-canonical500-raw/stage-7c-finalization.json",
        "configs/decisions/sourceafis_java_3_18_1_documented_40_v1.yaml",
        "src/fpbench/flx/identity.py",
        "src/fpbench/modern_matchers/verify.py",
        "src/fpbench/decisions/apply.py",
        "src/fpbench/metrics/__init__.py",
    ],
)
def test_a_prior_stages_path_is_not_an_allowed_stage_8d_change(path) -> None:
    assert _is_allowed_change(path) is False
    assert _is_owned_path(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "src/fpbench/calibration/selection.py",
        "src/fpbench/core/calibration_models.py",
        "src/fpbench/experiments/stage8d_identity.py",
        "evidence/stage8d-calibration-infrastructure/stage-8d-finalization.json",
        "tests/contract/test_stage8d_methodology.py",
        "tests/unit/test_calibration_selection.py",
    ],
)
def test_stage_8d_owns_its_own_surface(path) -> None:
    assert _is_allowed_change(path) is True
    assert _is_owned_path(path) is True


def test_a_shared_file_is_allowed_without_becoming_owned() -> None:
    """docs/adr/0067: Stage 8D edited them without a claim over their future."""
    for path in (
        "pyproject.toml",
        "Makefile",
        "README.md",
        "src/fpbench/core/enums.py",
        "src/fpbench/core/decision_models.py",
        "src/fpbench/storage/layout.py",
        "src/fpbench/storage/decision_set_store.py",
    ):
        assert _is_allowed_change(path) is True, path
        assert _is_owned_path(path) is False, path


def test_the_audit_attributes_a_change_to_the_commit_that_made_it() -> None:
    """Two repairs to earlier stages landed inside Stage 8D's span.

    Both were found by Stage 8D and fixed outside it, because Stage 8D may not
    edit `adapters/support/process.py` or Stage 7A's acceptance tests. History is
    linear, so an endpoint-to-endpoint diff blames this stage for them. The audit
    walks the span commit by commit and skips exactly those two, which is the
    difference between answering "which paths did Stage 8D change?" and answering
    a convenient approximation of it (docs/adr/0067).
    """
    import subprocess

    from fpbench.experiments.stage8d_finalization import (
        _NON_STAGE_8D_COMMITS_IN_SPAN,
        _stage_8d_changed_paths,
    )

    head = subprocess.run(
        ("git", "-C", str(REPOSITORY_ROOT), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    attributed = set(_stage_8d_changed_paths(REPOSITORY_ROOT, head))
    assert attributed, "the audit attributed nothing to Stage 8D"
    assert all(_is_allowed_change(path) for path in attributed), sorted(
        path for path in attributed if not _is_allowed_change(path)
    )

    # The excluded commits are real, are ancestors of HEAD, and did touch paths
    # Stage 8D is not entitled to — otherwise excluding them would be pointless.
    for revision in _NON_STAGE_8D_COMMITS_IN_SPAN:
        touched = subprocess.run(
            (
                "git", "-C", str(REPOSITORY_ROOT), "diff-tree",
                "--no-commit-id", "--name-only", "-r", revision,
            ),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split()
        assert touched, revision
        forbidden = {path for path in touched if not _is_allowed_change(path)}
        assert forbidden, f"{revision} touched nothing Stage 8D was barred from"
        # And excluding it actually removed those: they are absent from what the
        # audit attributes, so the exclusion is doing work rather than decorating.
        assert not (forbidden & attributed), revision


def test_a_path_escaping_the_repository_is_refused() -> None:
    for path in ("../elsewhere/thing.py", "/etc/passwd", "src\\fpbench\\calibration\\x.py"):
        assert _is_allowed_change(path) is False
        assert _is_owned_path(path) is False
