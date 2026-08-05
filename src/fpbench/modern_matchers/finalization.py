"""Build the last-written Stage 8A authority over the exact evidence bytes."""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from fpbench.core.errors import Stage8AFinalizationError
from fpbench.core.modern_matcher_models import (
    STAGE8A_SCHEMA_VERSION,
    CandidateQualificationReport,
    ModernMatcherCandidateRegistry,
    ModernMatcherSelectionDecision,
    SelectionPolicy,
    Stage8AFinalization,
    Stage8AOutcome,
)
from fpbench.core.serialization import to_plain
from fpbench.storage.modern_matcher_store import Stage8AEvidenceStore

__all__ = [
    "STAGE8A_BASELINE_COMMIT",
    "STAGE8A_PUBLICATION_COMMIT",
    "file_sha256",
    "verify_stage8a_workspace_boundaries",
    "build_stage8a_finalization",
]

#: Stage 8A began here — the commit that closed Stage 7D.
STAGE8A_BASELINE_COMMIT = "f85e360439ea0d1eb66e2294fe570992fb868b9f"

#: ...and ended here, when its evidence was last published.  The boundary
#: audit asks what *Stage 8A* changed, so it must compare two fixed commits.
#: Comparing against ``HEAD`` instead answered a different question — "has
#: anything outside Stage 8A's allowlist changed since Stage 7D, ever" — which
#: no later stage can satisfy and which Stage 8A was never entitled to assert.
#: The claim that Stage 8A's own code has not moved is unaffected: it is
#: enforced separately, and more strictly, by the verifier's authority-path
#: comparison against ``verifier_source_commit`` (docs/adr/0067).
STAGE8A_PUBLICATION_COMMIT = "f075dcb33eec2c44e597ad0506dbe8dd6def7bc6"

_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage8a-modern-matcher-selection.yml",
        ".github/workflows/tests.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0061-stage-8a-qualifies-artifacts-not-papers.md",
        "docs/adr/0062-modern-matcher-selection-does-not-read-sd300.md",
        "docs/adr/0063-code-and-model-weights-have-separate-identities-and-licenses.md",
        "docs/adr/0064-preprocessing-is-part-of-the-algorithm.md",
        "docs/adr/0065-raw-score-readiness-does-not-imply-decision-readiness.md",
        "docs/adr/0066-no-paper-reimplementation-is-accepted-as-an-upstream-algorithm.md",
        "src/fpbench/core/errors.py",
        "src/fpbench/core/modern_matcher_models.py",
        "src/fpbench/experiments/stage8a_modern_matcher_selection.py",
        "src/fpbench/storage/__init__.py",
        "src/fpbench/storage/modern_matcher_store.py",
        "tests/stage8aworld.py",
    }
)
_ALLOWED_CHANGE_PREFIXES = (
    "configs/modern-matchers/",
    "evidence/stage8a-modern-matcher-selection/",
    "integrations/modern-matchers/",
    "src/fpbench/modern_matchers/",
)
#: Paths Stage 8A owns outright, as opposed to the shared files above that it
#: was merely allowed to touch.  Only these are scanned for uncommitted work:
#: an untracked file here would be Stage 8A material outside its publication,
#: while an untracked file anywhere else belongs to whoever is working now.
_STAGE8A_OWNED_PREFIXES = (
    "configs/modern-matchers/",
    "evidence/stage8a-modern-matcher-selection/",
    "integrations/modern-matchers/",
    "src/fpbench/modern_matchers/",
)
_STAGE8A_OWNED_EXACT = frozenset(
    {
        "src/fpbench/core/modern_matcher_models.py",
        "src/fpbench/experiments/stage8a_modern_matcher_selection.py",
        "src/fpbench/storage/modern_matcher_store.py",
        "tests/stage8aworld.py",
    }
)
_FORBIDDEN_IMPORT_PREFIXES = (
    "fpbench.adapters",
    "fpbench.cross_algorithm",
    "fpbench.datasets",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.execution",
    "fpbench.experiments",
    "fpbench.imaging",
    "fpbench.metrics",
    "fpbench.paired",
    "fpbench.protocols",
    "fpbench.provenance",
)
_FORBIDDEN_INPUT_REFERENCES = (
    "/".join(("workspace", "prepared")),
    "/".join(("workspace", "results")),
    "/".join(("workspace", "derivations")),
    "/".join(("evidence", "sourceafis-")),
    "/".join(("evidence", "nbis-")),
)


def _git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage8AFinalizationError(
            f"cannot audit Stage 8A workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage8AFinalizationError(
            "cannot audit Stage 8A workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _is_allowed_stage8a_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _is_stage8a_named_test(path)


def _is_stage8a_named_test(path: str) -> bool:
    return (
        path.startswith("tests/")
        and "stage8a" in PurePosixPath(path).name.lower()
        and path.endswith(".py")
    )


def _is_stage8a_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _STAGE8A_OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _STAGE8A_OWNED_PREFIXES):
        return True
    return _is_stage8a_named_test(path)


def _stage8a_python_sources(repository_root: Path) -> tuple[Path, ...]:
    source_root = repository_root / "src" / "fpbench" / "modern_matchers"
    sources = tuple(sorted(source_root.rglob("*.py")))
    entrypoint = (
        repository_root
        / "src"
        / "fpbench"
        / "experiments"
        / "stage8a_modern_matcher_selection.py"
    )
    if entrypoint.is_file():
        sources += (entrypoint,)
    store = (
        repository_root
        / "src"
        / "fpbench"
        / "storage"
        / "modern_matcher_store.py"
    )
    if store.is_file():
        sources += (store,)
    return sources


def _audit_stage8a_source_boundaries(repository_root: Path) -> None:
    for path in _stage8a_python_sources(repository_root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage8AFinalizationError(
                f"cannot audit Stage 8A source boundary {path}: {exc}"
            ) from exc
        imported: list[str] = []
        string_literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                string_literals.append(node.value)
        blocked_imports = sorted(
            name
            for name in imported
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _FORBIDDEN_IMPORT_PREFIXES
            )
        )
        if blocked_imports:
            raise Stage8AFinalizationError(
                f"{path}: Stage 8A imports forbidden prior-stage modules "
                f"{blocked_imports}"
            )
        for literal in string_literals:
            normalized = literal.replace("\\", "/").lower()
            if any(reference in normalized for reference in _FORBIDDEN_INPUT_REFERENCES):
                raise Stage8AFinalizationError(
                    f"{path}: Stage 8A source names a forbidden prior-stage input"
                )


def verify_stage8a_workspace_boundaries(repository_root: Path) -> None:
    """Prove that Stage 8A changed only its allowlisted surface and is isolated.

    The audited span is fixed: ``STAGE8A_BASELINE_COMMIT`` to
    ``STAGE8A_PUBLICATION_COMMIT``.  Work committed after the publication is
    some other stage's, and is neither Stage 8A's to permit nor Stage 8A's to
    forbid.  Both commits are still required to be in the current history, so
    a rewritten or abandoned Stage 8A is caught rather than skipped.
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage8AFinalizationError(
            f"cannot resolve Stage 8A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage8AFinalizationError(
            "Stage 8A workspace boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE8A_BASELINE_COMMIT,
        STAGE8A_PUBLICATION_COMMIT,
    )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE8A_PUBLICATION_COMMIT,
        "HEAD",
    )
    changed = set(
        _git_output(
            repository_root,
            "diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            STAGE8A_BASELINE_COMMIT,
            STAGE8A_PUBLICATION_COMMIT,
            "--",
        )
    )
    forbidden_changes = sorted(
        path for path in changed if not _is_allowed_stage8a_change(path)
    )
    if forbidden_changes:
        raise Stage8AFinalizationError(
            "prior-stage paths changed during Stage 8A: "
            f"{forbidden_changes}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root,
            "ls-files",
            "--others",
            "--exclude-standard",
        )
        if _is_stage8a_owned_path(path)
    )
    if unpublished:
        raise Stage8AFinalizationError(
            "Stage 8A material exists outside its publication: "
            f"{unpublished}"
        )
    _audit_stage8a_source_boundaries(repository_root)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage8AFinalizationError(f"cannot hash required Stage 8A evidence {path}: {exc}") from exc
    return digest.hexdigest()


def build_stage8a_finalization(
    *,
    store: Stage8AEvidenceStore,
    registry: ModernMatcherCandidateRegistry,
    reports: Sequence[CandidateQualificationReport],
    decision: ModernMatcherSelectionDecision,
    policy: SelectionPolicy,
    verifier_source_commit: str,
    verifier_source_tree_clean: bool,
    created_utc: str,
    require_git_provenance: bool = True,
) -> Stage8AFinalization:
    if type(require_git_provenance) is not bool:
        raise Stage8AFinalizationError(
            "require_git_provenance must be a boolean"
        )
    if require_git_provenance:
        verify_stage8a_workspace_boundaries(store.repository_root)
    reports_by_id = {report.candidate_id: report for report in reports}
    if len(reports_by_id) != len(tuple(reports)):
        raise Stage8AFinalizationError(
            "finalization requires exactly one report per candidate"
        )
    candidate_ids = tuple(candidate.candidate_id for candidate in registry.candidates)
    if set(reports_by_id) != set(candidate_ids):
        raise Stage8AFinalizationError("finalization requires one report for every frozen candidate")
    if decision.registry_fingerprint != registry.fingerprint:
        raise Stage8AFinalizationError("selection decision names another registry")
    if decision.selection_policy_fingerprint != policy.fingerprint:
        raise Stage8AFinalizationError("selection decision names another selection policy")
    expected_report_fingerprints = {
        candidate_id: reports_by_id[candidate_id].fingerprint
        for candidate_id in sorted(reports_by_id)
    }
    if dict(decision.candidate_qualification_fingerprints) != expected_report_fingerprints:
        raise Stage8AFinalizationError("selection decision does not bind every qualification report")
    prerequisites = [store.registry_path, store.selection_path, store.readme_path]
    prerequisites.extend(store.qualification_path(candidate_id) for candidate_id in candidate_ids)
    missing = [path.name for path in prerequisites if not path.is_file()]
    if missing:
        raise Stage8AFinalizationError(f"finalization is last; missing evidence files {missing}")
    stored_registry = store.read_document(store.registry_path, "candidate registry")
    if stored_registry != to_plain(registry):
        raise Stage8AFinalizationError(
            "the registry on disk differs from the registry passed to finalization"
        )
    stored_decision = store.read_document(store.selection_path, "selection decision")
    if stored_decision != to_plain(decision):
        raise Stage8AFinalizationError(
            "the selection on disk differs from the decision passed to finalization"
        )
    for candidate_id, report in reports_by_id.items():
        stored_report = store.read_document(
            store.qualification_path(candidate_id),
            f"qualification for {candidate_id}",
        )
        if stored_report != to_plain(report):
            raise Stage8AFinalizationError(
                f"{candidate_id}: report on disk differs from the report passed to finalization"
            )

    required_artifacts: dict[str, str] = {}
    required_candidate_id = decision.selected_candidate_id or decision.raw_score_candidate_id
    if required_candidate_id is not None:
        required_artifacts[required_candidate_id] = reports_by_id[
            required_candidate_id
        ].artifact_manifest.fingerprint

    return Stage8AFinalization.create(
        schema_version=STAGE8A_SCHEMA_VERSION,
        kind="stage_8a_finalization",
        outcome=decision.outcome,
        registry_fingerprint=registry.fingerprint,
        registry_content_hash=file_sha256(store.registry_path),
        qualification_fingerprints=expected_report_fingerprints,
        qualification_content_hashes={
            candidate_id: file_sha256(store.qualification_path(candidate_id))
            for candidate_id in sorted(reports_by_id)
        },
        selection_decision_fingerprint=decision.fingerprint,
        selection_decision_content_hash=file_sha256(store.selection_path),
        readme_content_hash=file_sha256(store.readme_path),
        selection_policy_fingerprint=policy.fingerprint,
        required_local_artifact_fingerprints=required_artifacts,
        forbidden_inputs_read=False,
        prior_stages_unchanged=True,
        verifier_source_commit=verifier_source_commit,
        verifier_source_tree_clean=verifier_source_tree_clean,
        created_utc=created_utc,
    )
