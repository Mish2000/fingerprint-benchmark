"""Bind the exact Stage 8B evidence bytes, and prove the stage stayed inside itself.

The boundary audit follows docs/adr/0067 from the start: it compares two fixed
commits, the one Stage 8B began at and the one it published at, rather than
comparing against a moving ``HEAD``.  The span's end is not a constant in this
file — it is read from the published marker's ``verifier_source_commit``, so
Stage 8C can exist without anyone editing Stage 8B.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path, PurePosixPath
from typing import Mapping

from fpbench.core.flx_errors import Stage8BFinalizationError
from fpbench.core.flx_models import (
    STAGE8B_SCHEMA_VERSION,
    FlxArtifactBinding,
    FlxOutcome,
    FlxQualificationReport,
    FlxRuntimeManifest,
    FlxRuntimePolicy,
    FlxRuntimeProbe,
    Stage8BFinalization,
)
from fpbench.flx import identity
from fpbench.storage.flx_store import Stage8BEvidenceStore

__all__ = [
    "STAGE8B_BASELINE_COMMIT",
    "file_sha256",
    "verify_stage8b_workspace_boundaries",
    "build_stage8b_finalization",
    "publish_stage8b_finalization",
]

#: Stage 8B began here: the commit that closed the Stage 8A boundary repair.
STAGE8B_BASELINE_COMMIT = "e065fad7162c3f584ded6ddcedd73aa0c84d9f54"

_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".github/workflows/stage8b-flx-runtime-qualification.yml",
        ".github/workflows/tests.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0068-local-execution-permission-is-not-a-licence-finding.md",
        "docs/adr/0069-the-executed-algorithm-is-one-implementation-of-one-variant.md",
        "docs/adr/0070-one-extraction-is-a-duplicated-pair.md",
        "docs/adr/0071-the-stage-8b-transform-is-declared-not-inherited.md",
        "docs/adr/0072-the-flx-runtime-is-a-bundle-pinned-by-bytes.md",
        "docs/adr/0073-a-raw-score-is-a-decimal-and-is-never-clamped.md",
        "src/fpbench/core/flx_errors.py",
        "src/fpbench/core/flx_models.py",
        "src/fpbench/experiments/stage8b_flx_runtime_qualification.py",
        "src/fpbench/storage/flx_store.py",
        "tests/flxworld.py",
    }
)
_ALLOWED_CHANGE_PREFIXES = (
    "configs/flx/",
    "evidence/stage8b-flx-runtime-qualification/",
    "integrations/flx/",
    "src/fpbench/flx/",
)
#: Paths Stage 8B owns outright, scanned for work that was written but never
#: published.  An untracked file anywhere else belongs to whoever is working now.
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES
_OWNED_EXACT = frozenset(
    {
        "src/fpbench/core/flx_errors.py",
        "src/fpbench/core/flx_models.py",
        "src/fpbench/experiments/stage8b_flx_runtime_qualification.py",
        "src/fpbench/storage/flx_store.py",
        "tests/flxworld.py",
    }
)
_FORBIDDEN_IMPORT_PREFIXES = (
    "fpbench.cross_algorithm",
    "fpbench.datasets",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.metrics",
    "fpbench.paired",
    "fpbench.protocols",
)
_FORBIDDEN_INPUT_REFERENCES = (
    "/".join(("workspace", "prepared")),
    "/".join(("workspace", "results")),
    "/".join(("workspace", "derivations")),
    "/".join(("evidence", "sourceafis-")),
    "/".join(("evidence", "nbis-")),
)
#: torch belongs in the worker, which is not importable from the research
#: engine and is deliberately not on this list of audited sources.
_STAGE8B_SOURCE_ROOTS = (
    "src/fpbench/flx",
    "src/fpbench/core/flx_models.py",
    "src/fpbench/core/flx_errors.py",
    "src/fpbench/storage/flx_store.py",
    "src/fpbench/experiments/stage8b_flx_runtime_qualification.py",
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage8BFinalizationError(
            f"cannot hash required Stage 8B evidence {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def _git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage8BFinalizationError(
            f"cannot audit Stage 8B workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage8BFinalizationError(
            "cannot audit Stage 8B workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage8b_test(path: str) -> bool:
    return (
        path.startswith("tests/")
        and "stage8b" in PurePosixPath(path).name.lower()
        and path.endswith(".py")
    )


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage8b_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage8b_test(path)


def _stage8b_sources(repository_root: Path) -> tuple[Path, ...]:
    sources: list[Path] = []
    for relative in _STAGE8B_SOURCE_ROOTS:
        candidate = repository_root / PurePosixPath(relative)
        if candidate.is_dir():
            sources.extend(sorted(candidate.rglob("*.py")))
        elif candidate.is_file():
            sources.append(candidate)
    return tuple(sources)


def _audit_source_boundaries(repository_root: Path) -> None:
    for path in _stage8b_sources(repository_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage8BFinalizationError(
                f"cannot audit Stage 8B source boundary {path}: {exc}"
            ) from exc
        imported: list[str] = []
        literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)
        blocked = sorted(
            name
            for name in imported
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _FORBIDDEN_IMPORT_PREFIXES
            )
        )
        if blocked:
            raise Stage8BFinalizationError(
                f"{path}: Stage 8B imports forbidden benchmark modules {blocked}"
            )
        machine_learning = sorted(
            name for name in imported if name.split(".")[0] in {"torch", "torchvision"}
        )
        if machine_learning:
            raise Stage8BFinalizationError(
                f"{path}: torch belongs in the isolated worker, not in the "
                f"research engine ({machine_learning})"
            )
        for literal in literals:
            normalized = literal.replace("\\", "/").lower()
            if any(reference in normalized for reference in _FORBIDDEN_INPUT_REFERENCES):
                raise Stage8BFinalizationError(
                    f"{path}: Stage 8B source names a forbidden prior-stage input"
                )


def verify_stage8b_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 8B changed only its own surface, over its own span.

    ``span_end_commit`` is the commit the publication names as its verifier.
    Reading the span's end from the evidence rather than from a constant is
    what lets Stage 8C exist without editing this file (docs/adr/0067).
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage8BFinalizationError(
            f"cannot resolve Stage 8B repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage8BFinalizationError(
            "the Stage 8B boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root, "merge-base", "--is-ancestor", STAGE8B_BASELINE_COMMIT, span_end_commit
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _git_output(
        repository_root,
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        STAGE8B_BASELINE_COMMIT,
        span_end_commit,
        "--",
    )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage8BFinalizationError(
            f"paths outside Stage 8B changed during Stage 8B: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage8BFinalizationError(
            f"Stage 8B material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


def build_stage8b_finalization(
    *,
    store: Stage8BEvidenceStore,
    binding: FlxArtifactBinding,
    manifest: FlxRuntimeManifest,
    probe: FlxRuntimeProbe,
    report: FlxQualificationReport,
    policy: FlxRuntimePolicy,
    profile_fingerprints: Mapping[str, str],
    stage8a_finalization_fingerprint: str,
    verifier_source_commit: str,
    verifier_source_tree_clean: bool,
    created_utc: str,
    require_git_provenance: bool = True,
) -> Stage8BFinalization:
    if require_git_provenance:
        verify_stage8b_workspace_boundaries(
            store.repository_root, span_end_commit=verifier_source_commit
        )
    missing = [name for name in store.PREREQUISITE_NAMES if not store.path(name).is_file()]
    if missing:
        raise Stage8BFinalizationError(
            f"finalization is last; missing evidence files {missing}"
        )
    if probe.artifact_binding_fingerprint != binding.fingerprint:
        raise Stage8BFinalizationError("the probe names another artifact binding")
    if probe.runtime_manifest_fingerprint != manifest.fingerprint:
        raise Stage8BFinalizationError("the probe names another runtime manifest")
    if report.probe_fingerprint != probe.fingerprint:
        raise Stage8BFinalizationError("the qualification report names another probe")
    if manifest.dependency_lock_sha256 == "":
        raise Stage8BFinalizationError("the runtime manifest names no dependency lock")

    return Stage8BFinalization.create(
        schema_version=STAGE8B_SCHEMA_VERSION,
        kind="stage_8b_finalization",
        outcome=report.outcome,
        stage8a_finalization_fingerprint=stage8a_finalization_fingerprint,
        source_archive_sha256=identity.SOURCE_ARCHIVE_SHA256,
        checkpoint_sha256=identity.CHECKPOINT_SHA256,
        artifact_binding_fingerprint=binding.fingerprint,
        runtime_manifest_fingerprint=manifest.fingerprint,
        preprocessing_profile_fingerprint=profile_fingerprints["preprocessing"],
        representation_profile_fingerprint=profile_fingerprints["representation"],
        score_profile_fingerprint=profile_fingerprints["score"],
        adapter_profile_fingerprint=profile_fingerprints["adapter"],
        runtime_probe_fingerprint=probe.fingerprint,
        qualification_report_fingerprint=report.fingerprint,
        runtime_policy_fingerprint=policy.fingerprint,
        evidence_content_hashes={
            name: file_sha256(store.path(name)) for name in store.PREREQUISITE_NAMES
        },
        verifier_source_commit=verifier_source_commit,
        verifier_source_tree_clean=verifier_source_tree_clean,
        biometric_inputs_read=False,
        prior_stages_unchanged=True,
        created_utc=created_utc,
    )


def publish_stage8b_finalization(
    *,
    repository_root: Path,
    lock_config: Path,
    policy_config: Path,
    verifier_source_commit: str,
    created_utc: str,
) -> Stage8BFinalization:
    """Read the nine published documents back, then write the tenth."""
    from fpbench.flx.loading import load_published_evidence

    store = Stage8BEvidenceStore(repository_root)
    published = load_published_evidence(store, policy_config=policy_config)
    marker = build_stage8b_finalization(
        store=store,
        binding=published.binding,
        manifest=published.manifest,
        probe=published.probe,
        report=published.report,
        policy=published.policy,
        profile_fingerprints=published.profile_fingerprints,
        stage8a_finalization_fingerprint=published.stage8a_finalization_fingerprint,
        verifier_source_commit=verifier_source_commit,
        verifier_source_tree_clean=True,
        created_utc=created_utc,
    )
    store.ensure_finalization(marker)
    return marker


def outcome_opens_stage_8c(outcome: FlxOutcome) -> bool:
    return outcome is FlxOutcome.RAW_SCORE_EXECUTION_READY
