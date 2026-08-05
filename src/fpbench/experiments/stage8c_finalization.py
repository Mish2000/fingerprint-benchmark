"""The Stage 8C marker, and the audit that proves the stage stayed inside itself.

The general research finalization marker proves that a run, its result set and
its algorithm-specific validation form one verified chain.  Stage 8C makes three
further claims the general engine cannot know about:

* the run used the reference run's exact pairs and prepared pixels;
* it executed the route Stage 8B qualified, and no other;
* nothing downstream of a raw score derives from it.

This marker binds all three, the general chain, and the exact bytes of every
published file, into one last-written document.

The boundary audit follows docs/adr/0067 from the start: it compares two fixed
commits, the one Stage 8C began at and the one it published at, rather than
comparing against a moving ``HEAD``.  The span's end is not a constant in this
file — it is read from the published marker's ``verifier_source_commit``, so
Stage 8D can exist without anyone editing Stage 8C.  The untracked scan is
scoped the same way: it looks only at paths Stage 8C owns, because an
uncommitted file elsewhere belongs to whoever is working now.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.errors import ResearchPreflightError
from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage8c_identity import (
    EVIDENCE_DIRECTORY,
    REQUIRED_EVIDENCE_FILES,
    STAGE_8C_SCHEMA_VERSION,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_8C_FINALIZATION_SCHEMA_VERSION",
    "STAGE_8C_FINALIZATION_KIND",
    "STAGE_8C_BASELINE_COMMIT",
    "Stage8CFinalization",
    "alignment_report_content_hash",
    "operational_summary_content_hash",
    "stage_8c_finalization_fingerprint",
    "file_sha256",
    "verify_stage8c_workspace_boundaries",
    "published_evidence_names",
    "require_no_forbidden_published_data",
]

STAGE_8C_FINALIZATION_SCHEMA_VERSION = STAGE_8C_SCHEMA_VERSION
STAGE_8C_FINALIZATION_KIND = STAGE_FINALIZATION_KIND

#: Stage 8C began here: the approved HEAD that closed Stage 8B (spec section 31).
STAGE_8C_BASELINE_COMMIT = "755d13f929c280d4079b50374c6974e44468e174"

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 8C is allowed to touch, each named rather than covered by
#: a prefix. A shared file that changed without being on this list is a finding
#: (spec section 31).
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage8c-flx-canonical500-raw.yml",
        ".github/workflows/tests.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0074-stage-8c-reuses-the-canonical-pair-and-input-authority.md",
        "docs/adr/0075-logical-extractions-and-physical-forward-rows-are-different-counts.md",
        "docs/adr/0076-stage-8c-publishes-no-score-distribution-or-decision.md",
        "docs/adr/0077-stage-8c-finalization-binds-the-stage-8b-qualified-route.md",
        "docs/experiments/flx-canonical500-raw.md",
        # The one shared engine change, and it is algorithm-neutral: a narrower
        # sibling of require_execution_controls_equal, added beside it rather
        # than replacing it, so no NBIS or SourceAFIS fingerprint moves
        # (docs/adr/0074).
        "src/fpbench/experiments/canonical_run_alignment.py",
        "src/fpbench/experiments/flx_adapter.py",
        "src/fpbench/experiments/flx_canonical500_full.py",
        "src/fpbench/experiments/flx_failure_mapping.py",
        "src/fpbench/experiments/flx_research.py",
        "src/fpbench/experiments/flx_validation.py",
        "src/fpbench/experiments/stage8b_binding.py",
        "src/fpbench/experiments/stage8c_finalization.py",
        "src/fpbench/experiments/stage8c_verify.py",
        "src/fpbench/experiments/stage8c_identity.py",
        "tests/stage8cworld.py",
        "configs/algorithms/flx_deepprint_texminu_512_without_localization_v1.yaml",
        "configs/execution/flx_canonical500_sequential_no_retry_v1.yaml",
        "configs/experiments/flx_canonical500_full_v1.yaml",
    }
)
_ALLOWED_CHANGE_PREFIXES = ("evidence/flx-canonical500-raw/",)

#: Paths Stage 8C owns outright, scanned for work that was written but never
#: published. Deliberately the same list as the changes it is allowed to make.
_OWNED_EXACT = _ALLOWED_EXACT_CHANGES - {
    ".gitattributes",
    ".github/workflows/tests.yml",
    "Makefile",
    "README.md",
    "pyproject.toml",
    "docs/adr/README.md",
    "src/fpbench/experiments/canonical_run_alignment.py",
}
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 8C may never change, checked by name so the message says which
#: one (spec section 31).
_PROTECTED_PREFIXES = (
    "evidence/nbis-",
    "evidence/sourceafis-",
    "evidence/sd300-",
    "evidence/stage8a-",
    "evidence/stage8b-",
    "configs/flx/",
    "src/fpbench/flx/",
    "integrations/flx/",
)

#: What no Stage 8C module may import (spec section 18).
_FORBIDDEN_IMPORT_PREFIXES = (
    "fpbench.cross_algorithm",
    "fpbench.decisions",
    "fpbench.derivations",
    "fpbench.eligibility",
    "fpbench.evaluation",
    "fpbench.metrics",
    "fpbench.paired",
)
_FORBIDDEN_RUNTIME_IMPORTS = ("torch", "torchvision")
_FORBIDDEN_INPUT_REFERENCES = (
    "/".join(("evidence", "sourceafis-")),
    "/".join(("evidence", "nbis-")),
)

_STAGE8C_SOURCE_FILES = (
    "src/fpbench/experiments/flx_adapter.py",
    "src/fpbench/experiments/flx_canonical500_full.py",
    "src/fpbench/experiments/flx_failure_mapping.py",
    "src/fpbench/experiments/flx_research.py",
    "src/fpbench/experiments/flx_validation.py",
    "src/fpbench/experiments/stage8b_binding.py",
    "src/fpbench/experiments/stage8c_finalization.py",
    "src/fpbench/experiments/stage8c_verify.py",
    "src/fpbench/experiments/stage8c_identity.py",
)

#: Every token that would mean a score row, an embedding or a decision reached
#: the published evidence (spec section 28).
_FORBIDDEN_PUBLISHED_KEYS = (
    "raw_score",
    "raw_scores",
    "score_rows",
    "scores",
    "embedding",
    "embeddings",
    "representation_sha256",
    "representation_hashes",
    "texture_vector",
    "minutia_vector",
    "tensor",
    "threshold",
    "decision",
    "decisions",
    "eligibility",
    "score_statistics",
    "histogram",
    "percentile",
    "mean_score",
    "median_score",
    "min_score",
    "max_score",
)


def _require_digest(value: str, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


@dataclass(frozen=True, slots=True)
class Stage8CFinalization:
    """Immutable authority for Stage 8C's raw-run claim.

    Everything a reader needs in order to follow the chain from a published
    score count back to the qualified route and the canonical inputs, and
    nothing a reader could use to reconstruct a score.
    """

    schema_version: str
    kind: str
    outcome: str

    # The route.
    stage8b_finalization_fingerprint: str
    stage8b_outcome: str
    algorithm_id: str
    integration_id: str
    integration_fingerprint: str
    source_archive_sha256: str
    checkpoint_sha256: str
    runtime_bundle_id: str
    runtime_bundle_fingerprint: str
    runtime_manifest_fingerprint: str
    preprocessing_profile_fingerprint: str
    representation_profile_fingerprint: str
    score_profile_fingerprint: str
    adapter_profile_fingerprint: str

    # The run.
    run_id: str
    run_fingerprint: str
    plan_id: str
    plan_fingerprint: str
    result_set_id: str
    result_set_fingerprint: str
    completion_id: str
    completion_fingerprint: str
    run_source_commit: str
    run_source_tree_clean: bool

    # The inputs.
    reference_run_id: str
    reference_plan_id: str
    reference_result_set_id: str
    pair_manifest_hash: str
    preparation_set_id: str
    preparation_set_fingerprint: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    # The verification.
    audit_fingerprint: str
    algorithm_validation_fingerprint: str
    research_receipt_fingerprint: str
    research_receipt_content_hash: str
    research_finalization_fingerprint: str
    alignment_fingerprint: str
    alignment_report_content_hash: str
    operational_summary_fingerprint: str
    operational_summary_content_hash: str

    # The counts.
    planned_count: int
    stored_count: int
    success_count: int
    algorithmic_failure_count: int
    blocking_failure_count: int
    preprocess_call_count: int
    logical_extraction_call_count: int
    physical_forward_row_count: int
    comparison_call_count: int

    # The limits.
    permits_decisions: bool
    opens_stage_8d: bool
    prior_result_scores_read: bool
    score_statistics_published: bool

    evidence_content_hashes: Mapping[str, str]
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_8c_finalization_fingerprint: str
    created_utc: str

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_8C_FINALIZATION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 8C finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_8C_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_8C_FINALIZATION_KIND!r}")
        if self.outcome != "FLX_CANONICAL500_RAW_READY":
            raise ValueError("outcome must be FLX_CANONICAL500_RAW_READY")

        for name in (
            "run_id",
            "plan_id",
            "result_set_id",
            "completion_id",
            "reference_run_id",
            "reference_plan_id",
            "reference_result_set_id",
            "runtime_bundle_id",
            "preparation_set_id",
            "algorithm_id",
            "integration_id",
        ):
            validate_id(str(getattr(self, name)))
        for name in (
            "stage8b_finalization_fingerprint",
            "integration_fingerprint",
            "source_archive_sha256",
            "checkpoint_sha256",
            "runtime_bundle_fingerprint",
            "runtime_manifest_fingerprint",
            "preprocessing_profile_fingerprint",
            "representation_profile_fingerprint",
            "score_profile_fingerprint",
            "adapter_profile_fingerprint",
            "run_fingerprint",
            "plan_fingerprint",
            "result_set_fingerprint",
            "completion_fingerprint",
            "pair_manifest_hash",
            "preparation_set_fingerprint",
            "transform_profile_fingerprint",
            "transform_runtime_fingerprint",
            "audit_fingerprint",
            "algorithm_validation_fingerprint",
            "research_receipt_fingerprint",
            "research_receipt_content_hash",
            "research_finalization_fingerprint",
            "alignment_fingerprint",
            "alignment_report_content_hash",
            "operational_summary_fingerprint",
            "operational_summary_content_hash",
            "stage_8c_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        for name in (
            "planned_count",
            "stored_count",
            "success_count",
            "algorithmic_failure_count",
            "blocking_failure_count",
            "preprocess_call_count",
            "logical_extraction_call_count",
            "physical_forward_row_count",
            "comparison_call_count",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        # The three arithmetic facts a reader should not have to check by hand.
        if self.stored_count != self.planned_count:
            raise ValueError(
                f"{self.stored_count} stored outcomes for {self.planned_count} "
                "planned jobs; a complete run stores one result per planned job"
            )
        if self.success_count + self.algorithmic_failure_count != self.stored_count:
            raise ValueError(
                "every stored outcome is a raw score or a declared algorithmic "
                "failure, and these do not add up"
            )
        if self.blocking_failure_count:
            raise ValueError(
                "a Stage 8C finalization requires zero blocking failures "
                "(spec section 16.3)"
            )
        # docs/adr/0075: the two extraction counts are different numbers.
        if self.physical_forward_row_count != self.logical_extraction_call_count * 2:
            raise ValueError(
                "physical forward rows must be twice the logical extractions "
                "under duplicate_pair_take_first_row (docs/adr/0070)"
            )

        if self.permits_decisions is not False:
            raise ValueError("Stage 8C permits no decision (docs/adr/0076)")
        if self.opens_stage_8d is not True:
            raise ValueError("a complete Stage 8C opens Stage 8D")
        if self.prior_result_scores_read is not False:
            raise ValueError("Stage 8C reads no prior algorithm's scores")
        if self.score_statistics_published is not False:
            raise ValueError("Stage 8C publishes no score statistic")
        if self.run_source_tree_clean is not True:
            raise ValueError("a research run is created from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 8C finalization requires a clean verifier tree")

        for name in ("run_source_commit", "verifier_source_commit"):
            commit = str(getattr(self, name)).strip().lower()
            if len(commit) != 40 or not set(commit) <= _HEX:
                raise ValueError(f"{name} must be a full 40-character commit SHA")
            object.__setattr__(self, name, commit)

        hashes = {
            str(name): _require_digest(str(value), f"evidence_content_hashes[{name}]")
            for name, value in sorted(dict(self.evidence_content_hashes).items())
        }
        object.__setattr__(self, "evidence_content_hashes", MappingProxyType(hashes))

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = stage_8c_finalization_fingerprint(self)
        if self.stage_8c_finalization_fingerprint != expected:
            raise ValueError(
                "stage_8c_finalization_fingerprint does not cover the marker's claims"
            )


def alignment_report_content_hash(report: Mapping[str, Any] | Any) -> str:
    """Digest the complete stored report, including its inspection timestamp."""
    return stable_hash(
        {
            "schema": "stage_8c_alignment_report_content_v1",
            "alignment_report": to_plain(report),
        },
        length=64,
    )


def operational_summary_content_hash(summary: Mapping[str, Any] | Any) -> str:
    """Digest the complete published operational summary."""
    return stable_hash(
        {
            "schema": "stage_8c_operational_summary_content_v1",
            "operational_summary": to_plain(summary),
        },
        length=64,
    )


def stage_8c_finalization_fingerprint(
    marker: Stage8CFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_8c_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_8c_finalization_v1", "marker": plain}, length=64
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise ResearchPreflightError(
            f"cannot hash required Stage 8C evidence {path}: {exc}"
        ) from exc
    return digest.hexdigest()


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence directory holds, sorted.

    ``run_<run_id>.json`` cannot be named before the run exists, so the required
    set is matched by shape: exactly one file of that form, and nothing else
    outside the fixed list (spec section 28).
    """
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise ResearchPreflightError(
            f"no published Stage 8C evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise ResearchPreflightError(
                f"published evidence may not be a link: {path.name}"
            )
        if not path.is_file():
            raise ResearchPreflightError(
                f"published evidence holds a non-file entry: {path.name}"
            )
        names.append(path.name)
    return tuple(names)


def require_expected_evidence_files(names: tuple[str, ...]) -> str:
    """The fixed list plus exactly one ``run_<run_id>.json``. No extras.

    Returns:
        The run file's name.

    Raises:
        ResearchPreflightError: a required file is missing, an unexpected one is
            present, or the run file is absent or duplicated.
    """
    present = set(names)
    run_files = sorted(
        name
        for name in present
        if name.startswith("run_") and name.endswith(".json")
    )
    if len(run_files) != 1:
        raise ResearchPreflightError(
            f"expected exactly one run_<run_id>.json, found {run_files}"
        )
    expected = set(REQUIRED_EVIDENCE_FILES) | {run_files[0]}
    missing = sorted(expected - present)
    if missing:
        raise ResearchPreflightError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise ResearchPreflightError(
            f"published evidence holds files nothing accounts for: {extra} "
            "(spec section 28)"
        )
    return run_files[0]


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No score row, embedding, threshold or decision reached the evidence.

    Every published JSON document is walked as data — keys and string values —
    rather than grepped, so a token inside a prose sentence in the README does
    not trip it and a key buried six levels down does (spec section 28).
    """
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.glob("*.json")):
        from fpbench.core.serialization import read_json

        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise ResearchPreflightError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise ResearchPreflightError(
                f"published evidence {path.name} carries forbidden data: {found} "
                "(docs/adr/0076, spec section 28)"
            )


def _forbidden_keys(node: Any, trail: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            bare = name.rsplit(".", 1)[-1].lower()
            if bare in _FORBIDDEN_PUBLISHED_KEYS:
                found.add(where)
            found |= _forbidden_keys(value, where)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found |= _forbidden_keys(item, f"{trail}[{index}]")
    return found


# ------------------------------------------------------------ the boundary


def _git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ResearchPreflightError(
            f"cannot audit Stage 8C workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ResearchPreflightError(
            "cannot audit Stage 8C workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage8c_test(path: str) -> bool:
    return (
        path.startswith("tests/")
        and "stage8c" in PurePosixPath(path).name.lower()
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
    return _named_stage8c_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage8c_test(path)


def _audit_source_boundaries(repository_root: Path) -> None:
    """Stage 8C's modules import no derivation layer and no torch."""
    for relative in _STAGE8C_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise ResearchPreflightError(
                f"cannot audit Stage 8C source boundary {relative}: {exc}"
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
            raise ResearchPreflightError(
                f"{relative}: Stage 8C imports forbidden derivation modules {blocked}"
            )
        machine_learning = sorted(
            name
            for name in imported
            if name.split(".")[0] in _FORBIDDEN_RUNTIME_IMPORTS
        )
        if machine_learning:
            raise ResearchPreflightError(
                f"{relative}: torch belongs in the isolated worker, not in the "
                f"research engine ({machine_learning})"
            )
        for literal in literals:
            normalized = literal.replace("\\", "/").lower()
            if any(
                reference in normalized for reference in _FORBIDDEN_INPUT_REFERENCES
            ):
                raise ResearchPreflightError(
                    f"{relative}: Stage 8C source names a forbidden prior-stage input"
                )


def verify_stage8c_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 8C changed only its own surface, over its own span.

    ``span_end_commit`` is the commit the publication names as its verifier.
    Reading the span's end from the evidence rather than from a constant is what
    lets Stage 8D exist without editing this file (docs/adr/0067).
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise ResearchPreflightError(
            f"cannot resolve Stage 8C repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise ResearchPreflightError(
            "the Stage 8C boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_8C_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _git_output(
        repository_root,
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        STAGE_8C_BASELINE_COMMIT,
        span_end_commit,
        "--",
    )
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise ResearchPreflightError(
            f"Stage 8C changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise ResearchPreflightError(
            f"paths outside Stage 8C changed during Stage 8C: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise ResearchPreflightError(
            f"Stage 8C material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)
