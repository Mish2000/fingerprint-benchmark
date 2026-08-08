"""The Stage 9A marker, the publisher, and the audit that proves the stage stayed inside itself.

The marker has two legal outcomes and validates differently under each, which is
unusual here and is the point. ``FLARE_FULL_ROUTE_ARTIFACTS_READY`` asserts that
every gate closed and carries no blockers; ``FLARE_FULL_ROUTE_BLOCKED`` carries
at least one blocker, each with the component it affects and a statement of why
score fidelity cannot be established, and it opens nothing. Neither is a
failure. A stage that could only publish success would be a stage under pressure
to find some (docs/adr/0085).

What the marker denies is the same under both outcomes and is checked rather
than written as prose: no SD300 image byte and no prior score was read, no
calibration happened, no threshold and no decision profile were produced, no
production adapter exists, no runtime was qualified, no benchmark ran, no
third-party byte entered Git, and not one byte of Stage 8E's evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 9A began
at with the commit it published at, rather than against a moving ``HEAD``. Its
import rule is one notch more precise than Stage 8E's, because this stage
legitimately opens a checkpoint when one is present: a runtime may be imported
*inside a function*, never at module level, so a module can offer an optional
inspection without becoming a module that needs torch to be imported at all.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.flare_errors import Stage9AFinalizationError
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage9a_flare_identity import (
    ALGORITHM_CANDIDATE_ID,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_9A_BLOCKED_OUTCOME,
    STAGE_9A_OUTCOMES,
    STAGE_9A_READY_OUTCOME,
    STAGE_9A_SCHEMA_VERSION,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_9A_BASELINE_COMMIT",
    "Stage9AFinalization",
    "stage_9a_finalization_fingerprint",
    "stage9a_source_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "verify_stage9a_workspace_boundaries",
    "write_evidence_json",
    "write_stage9a_evidence",
    "main",
]

#: Stage 9A began here: the approved HEAD that closed Stage 8E.
STAGE_9A_BASELINE_COMMIT = "c74b219f5125a4fd91fafcdec0d9ad6c660611cd"

#: Commits inside Stage 9A's span that are **not** Stage 9A's work. Empty, and a
#: set rather than nothing so that a repair to an earlier stage landing mid-span
#: has somewhere to go (docs/adr/0067).
_NON_STAGE_9A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: The source whose bytes the marker pins. A change to any of them changes what
#: this qualification concluded.
_STAGE_9A_SOURCE_FILES = (
    "src/fpbench/core/flare_errors.py",
    "src/fpbench/experiments/stage9a_flare_identity.py",
    "src/fpbench/experiments/stage9a_flare_artifacts.py",
    "src/fpbench/experiments/stage9a_flare_route.py",
    "src/fpbench/experiments/stage9a_flare_qualification.py",
    "src/fpbench/experiments/stage9a_flare_finalization.py",
)

#: Shared files Stage 9A is allowed to touch, each named rather than covered by
#: a prefix. Stage 9A adds one ``core`` module of its own rather than extending
#: an existing one, and adds no package: it is a qualification, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage9a-flare-artifact-qualification.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0085-stage-9-selects-the-full-flare-route.md",
        "docs/adr/0086-flare-identity-is-fdd-d6-dualpose-dualenh-maxcosine.md",
        "docs/adr/0087-flare-score-affecting-upstream-gaps-must-not-be-guessed.md",
        (
            "docs/adr/0088-flare-paper-route-and-public-code-must-resolve-to-"
            "one-transform-graph.md"
        ),
        "docs/experiments/stage9a-flare-artifact-qualification.md",
        *_STAGE_9A_SOURCE_FILES,
    }
)
_ALLOWED_CHANGE_PREFIXES = (
    "evidence/stage9a-flare-artifact-qualification/",
    "docs/algorithms/flare/",
)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage9a_")
    or path
    in {
        "src/fpbench/core/flare_errors.py",
        "docs/experiments/stage9a-flare-artifact-qualification.md",
        ".github/workflows/stage9a-flare-artifact-qualification.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 9A may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason Stage 8C, 8D and
#: 8E assemble theirs: this module is audited for source that names a prior
#: stage's published evidence, and a literal here would make the audit refuse
#: the file that performs it.
_PROTECTED_PREFIXES = tuple(
    "/".join(parts)
    for parts in (
        ("evidence", "sd300-"),
        ("evidence", "source" + "afis-"),
        ("evidence", "nb" + "is-"),
        ("evidence", "f" + "lx-"),
        ("evidence", "stage8a-"),
        ("evidence", "stage8b-"),
        ("evidence", "stage8d-"),
        ("evidence", "stage8e-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("configs", ""),
        ("integrations", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 9A module may import *at all*. A qualification layer that
#: reached into an algorithm, a runtime or a derivation would be a qualification
#: whose answers could depend on what had been run.
_FORBIDDEN_IMPORT_PREFIXES = tuple(
    name
    for name in (
        "source" + "afis",
        "nb" + "is",
        "f" + "lx",
        "pyarrow",
        "fpbench." + "f" + "lx",
        "fpbench.modern_matchers",
        "fpbench.calibration",
        "fpbench.adapters",
        "fpbench.cross_algorithm",
        "fpbench.datasets",
        "fpbench.decisions",
        "fpbench.derivations",
        "fpbench.eligibility",
        "fpbench.evaluation",
        "fpbench.execution",
        "fpbench.imaging",
        "fpbench.metrics",
        "fpbench.paired",
        "fpbench.protocols",
        "fpbench.storage",
    )
)

#: What no Stage 9A module may import **at module level**, and may import inside
#: a function. This is the one place Stage 9A's rule is looser than Stage 8E's,
#: and it is looser on purpose: the checkpoint inspection needs torch when a
#: checkpoint is present and must not need it otherwise, and the synthetic
#: fixture writer needs an image library only when somebody asks for images.
#: Importing them at module level would make every caller of this package need
#: a runtime it has no other use for.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage path Stage 9A source may name, and it may only read it.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            (
                "evidence",
                "stage8e-research-only-policy",
                "stage-8e-finalization.json",
            )
        )
    }
)

_EVIDENCE_PREFIX = "evidence" + "/"


def _require_digest(value: object, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def write_evidence_json(path: Path, value: Any) -> Path:
    r"""Write one evidence document as bytes, with ``\n`` line endings.

    Not :func:`fpbench.core.serialization.write_json`, which reaches the disk
    through ``write_text`` and therefore emits CRLF on Windows. ``.gitattributes``
    pins this directory to LF, and the marker's content hashes are over raw
    bytes, so a CRLF file would agree with exactly one of the two machines that
    checked it out.
    """
    payload = json.dumps(to_plain(value), indent=2, ensure_ascii=False, sort_keys=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes((payload + "\n").encode("utf-8"))
    temporary.replace(path)
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage9AFinalizationError(
            f"cannot hash required Stage 9A file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """A digest of one source file, with newlines normalised to ``\\n``.

    ``core.autocrlf`` is on for this repository, so the same committed blob is
    LF in one checkout and CRLF in another, and a raw digest would name the
    checkout rather than the code. Evidence files are hashed raw, because
    ``.gitattributes`` pins them to LF.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage9AFinalizationError(
            f"cannot hash Stage 9A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage9a_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this qualification."""
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in _STAGE_9A_SOURCE_FILES
    }
    return stable_hash(
        {"schema": "stage_9a_source_v1", "files": digests}, length=64
    )


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage9AFinalization:
    """Immutable authority for what Stage 9A established, and for what it did not.

    Two outcomes, validated differently. Under ``READY`` every gate below must
    be closed and ``blockers`` must be empty. Under ``BLOCKED`` at least one
    blocker must be named and ``opens_stage_9b`` must be false. There is no
    third state and no way to write "ready with reservations", which is the
    shape that would eventually be used (docs/adr/0085).
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_candidate: str
    stage8e_policy_fingerprint: str
    stage9a_source_fingerprint: str

    # The route's shape, which is what makes it this algorithm.
    required_source_repositories: int
    required_pose_estimators: int
    required_enhancers: int
    required_descriptor_branches: int
    binary_route_enabled: bool

    # The artifacts.
    upstream_source_manifest_fingerprint: str
    artifact_manifest_fingerprint: str
    third_party_usage_manifest_fingerprint: str
    required_artifact_count: int
    all_required_artifacts_identity_established: bool
    all_required_artifacts_locally_verified: bool
    all_required_research_use_decisions_open_execution: bool

    # The route.
    transform_graph_fingerprint: str
    public_code_route_audit_fingerprint: str
    checkpoint_compatibility_fingerprint: str
    route_model_qualification_fingerprint: str
    qualification_fingerprint: str
    paper_route_resolved: bool
    public_code_route_resolved: bool
    transform_graph_resolved: bool
    checkpoint_compatibility_resolved: bool
    material_parameter_provenance_complete: bool
    route_model_qualification_holds: bool

    # Training provenance.
    training_overlap_with_sd300_found: bool
    training_overlap_status: str

    # What the stage did not do.
    sd300_image_bytes_read: bool
    sd300_score_rows_read: bool
    prior_algorithm_scores_read: bool
    calibration_performed: bool
    threshold_produced: bool
    decision_profile_produced: bool
    production_adapter_created: bool
    runtime_qualified: bool
    benchmark_run_performed: bool
    third_party_bytes_added_to_git: bool
    stage8e_evidence_changed: bool
    upstream_behaviour_modified: bool

    # What it opens.
    opens_stage_9b: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_9a_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "binary_route_enabled",
        "training_overlap_with_sd300_found",
        "sd300_image_bytes_read",
        "sd300_score_rows_read",
        "prior_algorithm_scores_read",
        "calibration_performed",
        "threshold_produced",
        "decision_profile_produced",
        "production_adapter_created",
        "runtime_qualified",
        "benchmark_run_performed",
        "third_party_bytes_added_to_git",
        "stage8e_evidence_changed",
        "upstream_behaviour_modified",
    )

    #: Every gate READY requires. Under ``BLOCKED`` they are reported as found,
    #: which is what makes a blocked marker useful rather than merely negative.
    READY_GATES = (
        "all_required_artifacts_identity_established",
        "all_required_artifacts_locally_verified",
        "all_required_research_use_decisions_open_execution",
        "paper_route_resolved",
        "public_code_route_resolved",
        "transform_graph_resolved",
        "checkpoint_compatibility_resolved",
        "material_parameter_provenance_complete",
        "route_model_qualification_holds",
    )

    _TRAINING_OVERLAP_STATUSES = (
        "NO_EVIDENCE_FOUND",
        "PARTIALLY_RESOLVED",
        "RESOLVED_ABSENT",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_9A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 9A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome not in STAGE_9A_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(STAGE_9A_OUTCOMES)}; there is no "
                "third state and no 'ready with reservations'"
            )
        if self.algorithm_candidate != ALGORITHM_CANDIDATE_ID:
            raise ValueError(
                f"algorithm_candidate must be {ALGORITHM_CANDIDATE_ID!r} "
                "(docs/adr/0086)"
            )
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )

        for name in (
            "stage9a_source_fingerprint",
            "upstream_source_manifest_fingerprint",
            "artifact_manifest_fingerprint",
            "third_party_usage_manifest_fingerprint",
            "transform_graph_fingerprint",
            "public_code_route_audit_fingerprint",
            "checkpoint_compatibility_fingerprint",
            "route_model_qualification_fingerprint",
            "qualification_fingerprint",
            "stage_9a_finalization_fingerprint",
            "stage8e_policy_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        for name, expected in (
            ("required_source_repositories", 2),
            ("required_pose_estimators", 2),
            ("required_enhancers", 2),
            ("required_descriptor_branches", 4),
        ):
            value = int(getattr(self, name))
            if value != expected:
                raise ValueError(
                    f"{name} is {value} and this algorithm is defined by "
                    f"{expected}. A route with fewer is a different algorithm "
                    "(docs/adr/0085)"
                )
            object.__setattr__(self, name, value)

        count = int(self.required_artifact_count)
        if count <= 0:
            raise ValueError(
                "a qualification of no artifacts is a qualification of nothing"
            )
        object.__setattr__(self, "required_artifact_count", count)

        for name in Stage9AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 9A asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )

        if self.training_overlap_status not in (
            Stage9AFinalization._TRAINING_OVERLAP_STATUSES
        ):
            raise ValueError(
                "training_overlap_status must be one of "
                f"{list(Stage9AFinalization._TRAINING_OVERLAP_STATUSES)}. "
                "'PROVEN_ABSENT' is deliberately not among them: no mention in a "
                "paper is absence of evidence (spec section 18)"
            )

        blockers = tuple(dict(item) for item in self.blockers)
        for blocker in blockers:
            missing = sorted(
                {
                    "blocker_code",
                    "affected_component",
                    "evidence",
                    "why_score_fidelity_cannot_be_established",
                }
                - set(blocker)
            )
            if missing:
                raise ValueError(
                    f"a blocker is missing {missing}. A blocker nobody can act "
                    "on is a blocker nobody can lift"
                )
        object.__setattr__(
            self,
            "blockers",
            tuple(
                MappingProxyType(dict(sorted(item.items())))
                for item in sorted(blockers, key=lambda item: item["blocker_code"])
            ),
        )

        if self.outcome == STAGE_9A_READY_OUTCOME:
            unmet = [
                name
                for name in Stage9AFinalization.READY_GATES
                if getattr(self, name) is not True
            ]
            if unmet:
                raise ValueError(
                    f"a READY marker requires every gate, and these are unmet: "
                    f"{sorted(unmet)}"
                )
            if self.blockers:
                raise ValueError(
                    "a READY marker carries no blockers; a blocker is not a "
                    "reservation to be weighed"
                )
            if self.opens_stage_9b is not True:
                raise ValueError("a READY Stage 9A opens Stage 9B")
        else:
            if not self.blockers:
                raise ValueError(
                    "a BLOCKED marker names which blockers apply. A block "
                    "nobody can point at is a block nobody can lift"
                )
            if self.opens_stage_9b is not False:
                raise ValueError(
                    "a BLOCKED Stage 9A opens nothing; the point of stopping is "
                    "not to build FLARE according to this project's own "
                    "interpretation"
                )

        if self.source_tree_clean is not True:
            raise ValueError("Stage 9A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 9A finalization requires a clean verifier tree")

        for name in ("source_commit", "verifier_source_commit"):
            commit = str(getattr(self, name)).strip().lower()
            if len(commit) != 40 or not set(commit) <= _HEX:
                raise ValueError(f"{name} must be a full 40-character commit SHA")
            object.__setattr__(self, name, commit)

        hashes = {
            str(name): _require_digest(value, f"evidence_content_hashes[{name}]")
            for name, value in sorted(dict(self.evidence_content_hashes).items())
        }
        object.__setattr__(self, "evidence_content_hashes", MappingProxyType(hashes))

        created = str(self.created_utc).strip()
        if not created:
            raise ValueError("created_utc must not be empty")
        object.__setattr__(self, "created_utc", created)

        expected = stage_9a_finalization_fingerprint(self)
        if self.stage_9a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_9a_finalization_fingerprint does not cover the marker's claims"
            )


def stage_9a_finalization_fingerprint(
    marker: Stage9AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_9a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_9a_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence directory holds, sorted."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage9AFinalizationError(
            f"no published Stage 9A evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise Stage9AFinalizationError(
                f"published evidence may not be a link: {path.name}"
            )
        if not path.is_file():
            raise Stage9AFinalizationError(
                f"published evidence holds a non-file entry: {path.name}"
            )
        names.append(path.name)
    return tuple(names)


def require_expected_evidence_files(names: tuple[str, ...]) -> None:
    """The fixed list, and nothing else."""
    present = set(names)
    expected = set(REQUIRED_EVIDENCE_FILES)
    missing = sorted(expected - present)
    if missing:
        raise Stage9AFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage9AFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No upstream byte, tensor, image, score or machine path reached the evidence.

    Every published JSON document is walked as *data* — keys, not text — so a
    token inside a prose sentence in the README does not trip it and a key buried
    six levels down does.
    """
    from fpbench.core.serialization import read_json

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise Stage9AFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage9AFinalizationError(
                f"published evidence {path.name} carries forbidden data: {found}"
            )


def _forbidden_keys(node: Any, trail: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.rsplit(".", 1)[-1].lower() in FORBIDDEN_PUBLISHED_KEYS:
                found.add(where)
            found |= _forbidden_keys(value, where)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found |= _forbidden_keys(item, f"{trail}[{index}]")
    return found


# --------------------------------------------------------------- the boundary


def _git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage9AFinalizationError(
            f"cannot audit Stage 9A workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage9AFinalizationError(
            "cannot audit Stage 9A workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage9a_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return path.startswith("tests/") and path.endswith(".py") and "stage9a" in name


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage9a_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage9a_test(path)


def _module_level_imports(tree: ast.Module) -> list[str]:
    """Imports at the top level of a module, and inside nothing else.

    Walks only the module body and the bodies of ``if``/``try`` blocks at that
    level, because a conditional import at module level still runs on import.
    An import inside a function does not, and that is the distinction the rule
    turns on.
    """
    names: list[str] = []
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, (ast.If, ast.Try)):
            pending.extend(node.body)
            pending.extend(getattr(node, "orelse", []))
            pending.extend(getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                pending.extend(handler.body)
    return names


def _audit_source_boundaries(repository_root: Path) -> None:
    """Stage 9A's modules import no algorithm, and no runtime at module level."""
    for relative in _STAGE_9A_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage9AFinalizationError(
                f"cannot audit Stage 9A source boundary {relative}: {exc}"
            ) from exc

        every_import: list[str] = []
        literals: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                every_import.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                every_import.append(node.module)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)

        blocked = sorted(
            name
            for name in every_import
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _FORBIDDEN_IMPORT_PREFIXES
            )
        )
        if blocked:
            raise Stage9AFinalizationError(
                f"{relative}: Stage 9A imports an algorithm, a runtime bundle or "
                f"a derivation layer {blocked}"
            )

        eager = sorted(
            name
            for name in _module_level_imports(tree)
            if any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in _DEFERRED_ONLY_IMPORT_PREFIXES
            )
        )
        if eager:
            raise Stage9AFinalizationError(
                f"{relative}: Stage 9A imports {eager} at module level. A "
                "runtime is imported inside the function that needs it, so that "
                "importing this package never needs one"
            )

        own = EVIDENCE_DIRECTORY.name
        for literal in literals:
            normalized = literal.replace("\\", "/")
            if not normalized.startswith(_EVIDENCE_PREFIX):
                continue
            if normalized in _PERMITTED_PRIOR_STAGE_DOCUMENTS:
                continue
            tail = normalized[len(_EVIDENCE_PREFIX) :]
            if tail and (own.startswith(tail) or tail.startswith(own)):
                continue
            raise Stage9AFinalizationError(
                f"{relative}: Stage 9A source names published evidence it is not "
                f"entitled to read: {literal!r}"
            )


def _stage_9a_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 9A's own commits changed, across its span.

    Commit by commit rather than endpoint to endpoint, so that a repair to an
    earlier stage that happened to land in the middle of this span is attributed
    to whoever made it (docs/adr/0067).
    """
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_9A_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_9A_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage9AFinalizationError(
            f"Stage 9A's span contains merge commits, which it cannot attribute: "
            f"{merges}"
        )
    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_9A_COMMITS_IN_SPAN:
            continue
        changed.update(
            _git_output(
                repository_root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "-r",
                "--diff-filter=ACDMRTUXB",
                revision,
            )
        )
    return tuple(sorted(changed))


def verify_stage9a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 9A changed only its own surface, over its own span.

    ``span_end_commit`` is the commit the publication names as its verifier.
    Reading the span's end from the evidence rather than from a constant is what
    lets Stage 9B exist without editing this file (docs/adr/0067).
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage9AFinalizationError(
            f"cannot resolve Stage 9A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage9AFinalizationError(
            "the Stage 9A boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_9A_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_9a_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage9AFinalizationError(
            f"Stage 9A changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage9AFinalizationError(
            f"paths outside Stage 9A changed during Stage 9A: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage9AFinalizationError(
            f"Stage 9A material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


# -------------------------------------------------------------- the publisher


def _head_commit(repository_root: Path) -> str:
    return _git_output(repository_root, "rev-parse", "HEAD")[0].strip().lower()


def _tree_is_clean(repository_root: Path, *, ignoring: tuple[str, ...] = ()) -> bool:
    """Whether the working tree is clean, optionally ignoring the files being written."""
    entries = _git_output(
        repository_root, "status", "--porcelain", "--untracked-files=all"
    )
    for entry in entries:
        path = entry[3:].strip().strip('"')
        if path not in ignoring:
            return False
    return True


def write_stage9a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The nine derivable documents first, then the marker — which is derived
    against the *exact bytes* of the other nine, so it has to come after them.
    That is the same two-commit shape Stage 8D and Stage 8E published under: the
    documents in one commit, the marker in the next, against a clean tree.

    Raises:
        Stage9AFinalizationError: the marker was asked for and the tree is not
            clean apart from the evidence being written.
    """
    from fpbench.experiments import stage9a_flare_artifacts as artifacts
    from fpbench.experiments import stage9a_flare_qualification as qualification
    from fpbench.experiments import stage9a_flare_route as route

    repository_root = Path(repository_root)
    artifacts.require_stage8e_is_the_policy_this_reuses(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    inventory = artifacts.build_artifact_inventory(repository_root=repository_root)
    usage = artifacts.build_flare_usage_audit()
    compatibility = qualification.build_compatibility_report(
        repository_root=repository_root
    )
    graph = route.resolve_transform_graph()
    audit = route.public_code_route_audit()
    model = qualification.run_route_model_qualification()
    byte_audit = qualification.audit_tracked_bytes_against_flare_artifacts(
        repository_root
    )
    outcome = qualification.build_qualification_report(
        repository_root=repository_root
    )

    written: list[Path] = []
    written.append(
        write_evidence_json(
            directory / "upstream-source-manifest.json",
            artifacts.upstream_source_manifest(),
        )
    )
    written.append(
        write_evidence_json(
            directory / "artifact-manifest.json",
            artifacts.artifact_manifest(inventory),
        )
    )
    written.append(
        write_evidence_json(
            directory / "third-party-usage-manifest.json",
            artifacts.third_party_usage_manifest_document(usage),
        )
    )
    written.append(
        write_evidence_json(
            directory / "training-provenance.json", route.training_provenance()
        )
    )
    written.append(
        write_evidence_json(
            directory / "checkpoint-compatibility.json",
            qualification.checkpoint_compatibility_document(compatibility),
        )
    )
    written.append(
        write_evidence_json(
            directory / "paper-route-contract.json", route.paper_route_contract()
        )
    )
    written.append(
        write_evidence_json(
            directory / "public-code-route-audit.json",
            _route_audit_document(audit),
        )
    )
    written.append(
        write_evidence_json(
            directory / "transform-graph-resolution.json",
            _transform_graph_document(graph),
        )
    )
    written.append(
        write_evidence_json(
            directory / "qualification-report.json",
            {
                **qualification.qualification_report_document(
                    outcome, graph=graph, audit=audit, model=model,
                    byte_audit=byte_audit,
                ),
                "score_contract": route.score_contract(),
            },
        )
    )
    if not include_marker:
        return tuple(written)

    names = published_evidence_names(repository_root)
    require_expected_evidence_files(
        tuple(name for name in names if name != "stage-9a-finalization.json")
        + ("stage-9a-finalization.json",)
    )
    require_no_forbidden_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / "stage-9a-finalization.json").as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage9AFinalizationError(
            "the Stage 9A marker is derived against a clean tree and the exact "
            "committed bytes of the other nine documents; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage9a_workspace_boundaries(repository_root, span_end_commit=commit)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != "stage-9a-finalization.json"
    )
    provenance = route.training_provenance()
    claims: dict[str, Any] = {
        "schema_version": STAGE_9A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": outcome.outcome,
        "algorithm_candidate": ALGORITHM_CANDIDATE_ID,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage9a_source_fingerprint": stage9a_source_fingerprint(repository_root),
        "required_source_repositories": 2,
        "required_pose_estimators": 2,
        "required_enhancers": 2,
        "required_descriptor_branches": 4,
        "binary_route_enabled": False,
        "upstream_source_manifest_fingerprint": file_sha256(
            directory / "upstream-source-manifest.json"
        ),
        "artifact_manifest_fingerprint": file_sha256(
            directory / "artifact-manifest.json"
        ),
        "third_party_usage_manifest_fingerprint": (
            usage.manifest.manifest_fingerprint
        ),
        "required_artifact_count": inventory.required_count,
        "all_required_artifacts_identity_established": (
            outcome.all_identities_established
        ),
        "all_required_artifacts_locally_verified": outcome.all_locally_verified,
        "all_required_research_use_decisions_open_execution": (
            outcome.research_use_opens_execution
        ),
        "transform_graph_fingerprint": graph.graph_fingerprint,
        "public_code_route_audit_fingerprint": audit.audit_fingerprint,
        "checkpoint_compatibility_fingerprint": compatibility.report_fingerprint,
        "route_model_qualification_fingerprint": model.qualification_fingerprint,
        "qualification_fingerprint": outcome.qualification_fingerprint,
        "paper_route_resolved": outcome.paper_route_resolved,
        "public_code_route_resolved": outcome.public_code_route_resolved,
        "transform_graph_resolved": outcome.transform_graph_resolved,
        "checkpoint_compatibility_resolved": (
            outcome.checkpoint_compatibility_established
        ),
        "material_parameter_provenance_complete": (
            outcome.parameter_provenance_complete
        ),
        "route_model_qualification_holds": outcome.route_model_holds,
        "training_overlap_with_sd300_found": outcome.training_overlap_found,
        "training_overlap_status": str(provenance["sd300_training_overlap_status"]),
        "sd300_image_bytes_read": False,
        "sd300_score_rows_read": False,
        "prior_algorithm_scores_read": False,
        "calibration_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "production_adapter_created": False,
        "runtime_qualified": False,
        "benchmark_run_performed": False,
        "third_party_bytes_added_to_git": bool(outcome.flare_bytes_in_git),
        "stage8e_evidence_changed": False,
        "upstream_behaviour_modified": False,
        "opens_stage_9b": outcome.outcome == STAGE_9A_READY_OUTCOME,
        "blockers": tuple(
            {
                "blocker_code": item.blocker_code,
                "affected_component": item.affected_component,
                "evidence": item.evidence,
                "why_score_fidelity_cannot_be_established": (
                    item.why_score_fidelity_cannot_be_established
                ),
            }
            for item in outcome.blockers
        ),
        "evidence_content_hashes": {
            name: file_sha256(directory / name) for name in hashed
        },
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }
    marker = Stage9AFinalization(
        **claims,
        stage_9a_finalization_fingerprint=stage_9a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(
        write_evidence_json(directory / "stage-9a-finalization.json", marker)
    )
    return tuple(written)


def _transform_graph_document(graph: Any) -> Mapping[str, Any]:
    from fpbench.experiments.stage9a_flare_route import (
        PARAMETER_PROVENANCE,
        TRANSFORM_OPERATIONS,
    )

    return {
        "schema": "stage_9a_transform_graph_resolution_v1",
        "graph_fingerprint": graph.graph_fingerprint,
        "operation_count": graph.operation_count,
        "score_affecting_count": graph.score_affecting_count,
        "authoritative_count": graph.authoritative_count,
        "resolved": graph.resolved,
        "unresolved_operations": list(graph.unresolved_operations),
        "unresolved_parameters": list(graph.unresolved_parameters),
        "operations": [
            {
                "operation_id": item.operation_id,
                "stage": item.stage,
                "description": item.description,
                "authority": item.authority.value,
                "authority_locator": item.authority_locator,
                "score_affecting": item.score_affecting,
                "input_dtype": item.input_dtype,
                "output_dtype": item.output_dtype,
                "geometry": item.geometry,
                "interpolation": item.interpolation,
                "padding_mode": item.padding_mode,
                "padding_value": item.padding_value,
                "normalization": item.normalization,
                "coordinate_convention": item.coordinate_convention,
                "rotation_direction": item.rotation_direction,
                "angle_units": item.angle_units,
                "rounding_behaviour": item.rounding_behaviour,
                "branches": list(item.branches),
                "blocks": item.blocks,
                "notes": list(item.notes),
            }
            for item in TRANSFORM_OPERATIONS
        ],
        "parameter_provenance": [
            {
                "parameter": item.parameter,
                "value": item.value,
                "source_type": item.source_type,
                "source_locator": item.source_locator,
                "authority": item.authority.value,
                "blocks": item.blocks,
            }
            for item in PARAMETER_PROVENANCE
        ],
    }


def _route_audit_document(audit: Any) -> Mapping[str, Any]:
    from fpbench.experiments.stage9a_flare_route import ROUTE_AUDIT_ROWS

    return {
        "schema": "stage_9a_public_code_route_audit_v1",
        "audit_fingerprint": audit.audit_fingerprint,
        "row_count": audit.row_count,
        "resolved": audit.resolved,
        "score_affecting_ambiguous": list(audit.score_affecting_ambiguous),
        "score_affecting_contradictory": list(audit.score_affecting_contradictory),
        "glue_required_operations": list(audit.glue_required_operations),
        "rows": [
            {
                "operation": row.operation,
                "paper_statement": row.paper_statement,
                "paper_source": row.paper_source,
                "official_code_location": row.official_code_location,
                "artifact_dependencies": list(row.artifact_dependencies),
                "parameter_sources": list(row.parameter_sources),
                "resolution": row.resolution.value,
                "score_affecting": row.score_affecting,
                "fpbench_glue_required": row.fpbench_glue_required,
                "detail": row.detail,
            }
            for row in ROUTE_AUDIT_ROWS
        ],
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage9a_flare_finalization``.

    ``documents`` writes the nine derivable documents; ``publish`` writes those
    and the marker, and refuses a dirty tree. ``status`` derives everything and
    prints the outcome and its blockers without writing anything, which is what
    a reviewer runs before deciding whether to commit.
    """
    from fpbench.experiments import stage9a_flare_qualification as qualification
    from fpbench.experiments import stage9a_flare_route as route

    parser = argparse.ArgumentParser(description="Stage 9A evidence")
    parser.add_argument(
        "action", choices=("status", "documents", "publish"), nargs="?", default="status"
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        graph = route.resolve_transform_graph()
        audit = route.public_code_route_audit()
        model = qualification.run_route_model_qualification()
        outcome = qualification.build_qualification_report(repository_root=root)
        print(f"algorithm_candidate      {ALGORITHM_CANDIDATE_ID}")
        print(f"outcome                  {outcome.outcome}")
        print(f"qualification            {outcome.qualification_fingerprint}")
        print(
            f"transform graph          {graph.authoritative_count}/"
            f"{graph.operation_count} operations authoritative"
        )
        if graph.unresolved_operations:
            print(f"  unresolved operations  {list(graph.unresolved_operations)}")
        if graph.unresolved_parameters:
            print(f"  unresolved parameters  {list(graph.unresolved_parameters)}")
        print(f"route audit              {audit.row_count} rows")
        if audit.score_affecting_ambiguous:
            print(f"  ambiguous              {list(audit.score_affecting_ambiguous)}")
        if audit.score_affecting_contradictory:
            print(
                f"  contradictory          "
                f"{list(audit.score_affecting_contradictory)}"
            )
        print(
            f"route model              {len(model.cases)} cases, "
            f"all hold: {model.all_hold}"
        )
        if outcome.blockers:
            print(f"blockers                 {len(outcome.blockers)}")
            for item in outcome.blockers:
                print(f"  {item.blocker_code}")
                print(f"      {item.affected_component}")
        return 0 if outcome.outcome == STAGE_9A_BLOCKED_OUTCOME or outcome.ready else 1

    written = write_stage9a_evidence(
        root, include_marker=arguments.action == "publish"
    )
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
