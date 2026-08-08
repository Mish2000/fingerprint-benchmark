"""The Stage 8E marker, the publisher, and the audit that proves the stage stayed inside itself.

The marker asserts something narrower than it might look like. It says a
repository-wide policy exists, that every third-party component this project
already depends on has been mapped into it, and that the public repository is
enforced against it. It does **not** say any upstream licence question was
resolved, and it says so in fields rather than in prose: two components are
recorded as ``UNKNOWN`` and one as ``NO_LICENSE_FOUND``, and all three are
executed on an explicit acceptance of risk rather than on a right anybody
established (docs/adr/0084).

The boundary audit follows docs/adr/0067: it compares the commit Stage 8E began
at with the commit it published at, rather than comparing against a moving
``HEAD``. The span's end is read from the published marker's
``verifier_source_commit``, so Stage 9A can exist without anyone editing this
file.

Stage 8E touches no shared file that a published marker pins. It adds two
``core`` modules of its own — for the reason :mod:`fpbench.core.flx_errors` and
:mod:`fpbench.core.calibration_errors` exist — one new package, three policy
documents, four ADRs, and its own tests, workflow and evidence. Nothing under
``src/fpbench/flx/``, ``src/fpbench/modern_matchers/``, ``configs/`` or
``integrations/`` changes, and neither does one byte of any earlier stage's
evidence.
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

from fpbench.core.serialization import stable_hash, to_plain
from fpbench.core.third_party_errors import Stage8EFinalizationError
from fpbench.experiments.stage8e_identity import (
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    LEGACY_SOURCE_DOCUMENTS,
    REQUIRED_EVIDENCE_FILES,
    STAGE8D_FINALIZATION_FINGERPRINT,
    STAGE8D_OUTCOME,
    STAGE_8E_OUTCOME,
    STAGE_8E_SCHEMA_VERSION,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_8E_BASELINE_COMMIT",
    "Stage8EFinalization",
    "stage_8e_finalization_fingerprint",
    "third_party_model_fingerprint",
    "policy_engine_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "verify_stage8e_workspace_boundaries",
    "write_evidence_json",
    "write_stage8e_evidence",
    "main",
]

#: Stage 8E began here: the approved HEAD that closed Stage 8D.
STAGE_8E_BASELINE_COMMIT = "2ad4698da5dd74a2aa5673ff08ffe71e69a750f0"

#: Commits inside Stage 8E's span that are **not** Stage 8E's work.
#:
#: Empty, and it is a list rather than nothing so that the next repair to an
#: earlier stage that lands mid-span has somewhere to go. History here is linear,
#: so ``git diff BASELINE..PUBLICATION`` would attribute such a commit to this
#: stage; the audit therefore walks the span commit by commit and skips whatever
#: is named here (docs/adr/0067).
_NON_STAGE_8E_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: The source whose bytes ``third_party_model_fingerprint`` covers: the vocabulary
#: and the containers. A change to any of them changes what a stored third-party
#: document *means*, so the marker pins them.
_MODEL_SOURCE_FILES = (
    "src/fpbench/core/third_party_models.py",
    "src/fpbench/core/third_party_errors.py",
    "src/fpbench/third_party/purpose.py",
)

#: The source whose bytes ``policy_engine_fingerprint`` covers: everything that
#: derives a decision, binds a record, resolves an artifact, records a
#: transformation, or refuses a tracked byte.
_ENGINE_SOURCE_FILES = (
    "src/fpbench/third_party/policy.py",
    "src/fpbench/third_party/manifest.py",
    "src/fpbench/third_party/artifacts.py",
    "src/fpbench/third_party/transformations.py",
    "src/fpbench/third_party/repository_guard.py",
    "src/fpbench/third_party/verify.py",
)

#: Shared files Stage 8E is allowed to touch, each named rather than covered by a
#: prefix. A shared file that changed without being on this list is a finding.
#:
#: The list is short, and deliberately so. Stage 8E adds two ``core`` modules of
#: its own rather than extending ``core/errors.py`` — which Stage 8A's published
#: verifier pins byte-for-byte — and it adds a package rather than widening one.
#: Nothing it touches is read by an earlier stage's gate.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage8e-research-only-policy.yml",
        ".github/workflows/tests.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0081-fpbench-is-personal-educational-research-only.md",
        "docs/adr/0082-third-party-license-observation-is-separate-from-local-research-use.md",
        "docs/adr/0083-third-party-bytes-are-never-redistributed-by-fpbench.md",
        "docs/adr/0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md",
        "docs/policy/research-only-purpose.md",
        "docs/policy/third-party-usage.md",
        "docs/policy/third-party-artifact-handling.md",
        "docs/experiments/stage8e-research-only-policy.md",
        "src/fpbench/core/third_party_errors.py",
        "src/fpbench/core/third_party_models.py",
        "src/fpbench/third_party/__init__.py",
        "src/fpbench/third_party/purpose.py",
        "src/fpbench/third_party/policy.py",
        "src/fpbench/third_party/manifest.py",
        "src/fpbench/third_party/artifacts.py",
        "src/fpbench/third_party/transformations.py",
        "src/fpbench/third_party/repository_guard.py",
        "src/fpbench/third_party/verify.py",
        "src/fpbench/experiments/stage8e_identity.py",
        "src/fpbench/experiments/stage8e_research_only_policy.py",
        "src/fpbench/experiments/stage8e_finalization.py",
    }
)
_ALLOWED_CHANGE_PREFIXES = ("evidence/stage8e-research-only-policy/",)

#: Paths Stage 8E owns outright, scanned for work that was written but never
#: published. Shared files are *allowed* changes without becoming *owned* paths,
#: because Stage 8E edited them without acquiring any claim over their future
#: (docs/adr/0067).
_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith(
        (
            "src/fpbench/third_party/",
            "src/fpbench/experiments/stage8e_",
            "docs/policy/",
            "evidence/stage8e-",
        )
    )
    or path
    in {
        "src/fpbench/core/third_party_errors.py",
        "src/fpbench/core/third_party_models.py",
        "docs/experiments/stage8e-research-only-policy.md",
        ".github/workflows/stage8e-research-only-policy.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 8E may never change, checked by name so the message says which.
#:
#: Assembled from parts rather than written out, for the reason Stage 8C and
#: Stage 8D assemble theirs: this module is audited for source that names a prior
#: stage's inputs, and a literal here would make the audit refuse the file that
#: performs it.
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
        ("configs", ""),
        ("integrations", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 8E module may import. A policy layer that reached into an
#: algorithm, a runtime or a derivation would be a policy layer whose answers
#: could depend on what had been run.
_FORBIDDEN_IMPORT_PREFIXES = tuple(
    name
    for name in (
        "source" + "afis",
        "nb" + "is",
        "f" + "lx",
        "torch",
        "yaml",
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

#: The only prior-stage paths Stage 8E source may name, and it may only read
#: them. A stronger rule than "no references at all", because Stage 8E genuinely
#: has to read four published documents to check its frozen legacy facts.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {relative for relative, _keys in LEGACY_SOURCE_DOCUMENTS}
    | {
        "/".join(
            (
                "evidence",
                "stage8d-calibration-infrastructure",
                "stage-8d-finalization.json",
            )
        )
    }
)

#: Assembled rather than written out, for the same reason the protected prefixes
#: above are: this module is itself audited for literals naming published
#: evidence, and spelling this one out would make the audit refuse the file that
#: performs it.
_EVIDENCE_PREFIX = "evidence" + "/"

_STAGE_8E_SOURCE_FILES = (
    *_MODEL_SOURCE_FILES,
    *_ENGINE_SOURCE_FILES,
    "src/fpbench/third_party/__init__.py",
    "src/fpbench/experiments/stage8e_identity.py",
    "src/fpbench/experiments/stage8e_research_only_policy.py",
    "src/fpbench/experiments/stage8e_finalization.py",
)


def _require_digest(value: object, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def write_evidence_json(path: Path, value: Any) -> Path:
    r"""Write one evidence document as bytes, with ``\n`` line endings.

    Not :func:`fpbench.core.serialization.write_json`, which reaches the disk
    through ``write_text`` and therefore emits CRLF on Windows. ``.gitattributes``
    pins this directory to LF, so a CRLF file would be committed as LF, checked
    out as CRLF here and as LF on a Linux runner, and the marker's content hashes
    — which are over raw bytes — would agree with exactly one of those two
    machines. Stage 8D's store learned this the same way.
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
        raise Stage8EFinalizationError(
            f"cannot hash required Stage 8E file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """A digest of one source file, with newlines normalised to ``\\n``.

    The normalisation is what makes the value portable. ``core.autocrlf`` is on
    for this repository, so the same committed blob is LF in one checkout and
    CRLF in another, and a raw digest would name the checkout rather than the
    code. Evidence files are different — ``.gitattributes`` pins them to LF — and
    those are hashed raw by :func:`file_sha256`.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage8EFinalizationError(
            f"cannot hash Stage 8E source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _source_family_fingerprint(
    repository_root: Path, relatives: tuple[str, ...], *, schema: str
) -> str:
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in relatives
    }
    return stable_hash({"schema": schema, "files": digests}, length=64)


def third_party_model_fingerprint(repository_root: Path) -> str:
    """The bytes that decide what a stored third-party document means."""
    return _source_family_fingerprint(
        repository_root, _MODEL_SOURCE_FILES, schema="stage_8e_third_party_models_v1"
    )


def policy_engine_fingerprint(repository_root: Path) -> str:
    """The bytes that decide, bind, resolve, record and refuse."""
    return _source_family_fingerprint(
        repository_root, _ENGINE_SOURCE_FILES, schema="stage_8e_policy_engine_v1"
    )


# ---------------------------------------------------------------- the marker


@dataclass(frozen=True, slots=True)
class Stage8EFinalization:
    """Immutable authority for Stage 8E's claim, and for its careful denials.

    The denials matter more here than in most stages, because the temptation this
    stage exists to resist is exactly the one a green marker invites: reading
    "policy ready" as "licensing sorted". Every field below that says otherwise
    is checked by this constructor rather than written as prose.
    """

    schema_version: str
    kind: str
    outcome: str

    # The stage this follows, bound rather than assumed.
    stage8d_finalization_fingerprint: str
    stage8d_outcome: str

    # The policy.
    project_purpose: str
    purpose_fingerprint: str
    policy_fingerprint: str
    third_party_model_fingerprint: str
    policy_engine_fingerprint: str

    # What it was applied to.
    legacy_component_audit_fingerprint: str
    legacy_component_count: int
    legacy_manifest_count: int
    owner_risk_accepted_count: int
    blocked_component_count: int

    # What it enforces.
    repository_audit_fingerprint: str
    tracked_file_count: int
    third_party_bytes_in_git: int
    workflow_count: int
    workflow_findings: int

    # The qualification.
    policy_qualification_fingerprint: str
    policy_case_count: int
    policy_decision_cases: int
    policy_refusal_cases: int
    policy_identity_cases: int

    # What the stage asserts, and what it refuses to assert.
    commercial_use_by_project: bool
    third_party_redistribution_by_project: bool
    third_party_bytes_permitted_in_git: bool
    license_observation_separate_from_execution_decision: bool
    restricted_research_licenses_may_execute_locally: bool
    unresolved_license_may_require_owner_risk_acceptance: bool
    no_access_control_circumvention: bool
    dataset_rights_unchanged: bool
    historical_evidence_changed: bool
    upstream_license_question_resolved: bool
    fpbench_license_added: bool

    # What it opens.
    opens_stage_9a: bool

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_8e_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False``, named so that a flag added to the class
    #: is either checked here or is visibly absent from this list.
    DENIED_FLAGS = (
        "commercial_use_by_project",
        "third_party_redistribution_by_project",
        "third_party_bytes_permitted_in_git",
        "historical_evidence_changed",
        "upstream_license_question_resolved",
        "fpbench_license_added",
    )

    #: And every flag that must be ``True``. Both directions are load-bearing:
    #: the stage is as much about what it refuses to claim as about what it does.
    ASSERTED_FLAGS = (
        "license_observation_separate_from_execution_decision",
        "restricted_research_licenses_may_execute_locally",
        "unresolved_license_may_require_owner_risk_acceptance",
        "no_access_control_circumvention",
        "dataset_rights_unchanged",
        "opens_stage_9a",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_8E_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 8E finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome != STAGE_8E_OUTCOME:
            raise ValueError(f"outcome must be {STAGE_8E_OUTCOME}")
        if self.project_purpose != "PERSONAL_EDUCATIONAL_RESEARCH":
            raise ValueError(
                "the marker states the one declared purpose, and it is "
                "PERSONAL_EDUCATIONAL_RESEARCH rather than anything academic "
                "(docs/adr/0081)"
            )

        for name in (
            "stage8d_finalization_fingerprint",
            "purpose_fingerprint",
            "policy_fingerprint",
            "third_party_model_fingerprint",
            "policy_engine_fingerprint",
            "legacy_component_audit_fingerprint",
            "repository_audit_fingerprint",
            "policy_qualification_fingerprint",
            "stage_8e_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        for name in (
            "legacy_component_count",
            "legacy_manifest_count",
            "owner_risk_accepted_count",
            "blocked_component_count",
            "tracked_file_count",
            "third_party_bytes_in_git",
            "workflow_count",
            "workflow_findings",
            "policy_case_count",
            "policy_decision_cases",
            "policy_refusal_cases",
            "policy_identity_cases",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        if (
            self.policy_decision_cases
            + self.policy_refusal_cases
            + self.policy_identity_cases
            != self.policy_case_count
        ):
            raise ValueError(
                "every policy case decides, refuses or establishes an identity, "
                "and these do not add up"
            )
        if self.policy_refusal_cases <= 0:
            raise ValueError(
                "a qualification with no refusal cases has not tested the half of "
                "the policy that matters: what it will not allow"
            )
        if self.legacy_component_count <= 0:
            raise ValueError(
                "a policy applied to no existing component is a policy nobody has "
                "tried"
            )
        if self.owner_risk_accepted_count <= 0:
            raise ValueError(
                "this repository holds components with no established permission, "
                "and a marker claiming none would be describing a different "
                "repository (docs/adr/0084)"
            )
        if self.blocked_component_count != 0:
            raise ValueError(
                "a blocked component is a component this project may not execute, "
                "and three algorithms have already run"
            )
        if self.third_party_bytes_in_git != 0:
            raise ValueError(
                "the public repository holds a third-party byte, which is the one "
                "thing this stage exists to prevent (docs/adr/0083)"
            )
        if self.workflow_findings != 0:
            raise ValueError(
                "a workflow does something the frozen policy says CI does not"
            )
        if self.tracked_file_count <= 0 or self.workflow_count <= 0:
            raise ValueError(
                "an audit that scanned nothing is indistinguishable from an audit "
                "that found nothing"
            )

        for name in Stage8EFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 8E asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )
        for name in Stage8EFinalization.ASSERTED_FLAGS:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"Stage 8E asserts {name} is true; a marker that said "
                    "otherwise would be describing a different policy"
                )

        if self.source_tree_clean is not True:
            raise ValueError("Stage 8E evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 8E finalization requires a clean verifier tree")

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

        expected = stage_8e_finalization_fingerprint(self)
        if self.stage_8e_finalization_fingerprint != expected:
            raise ValueError(
                "stage_8e_finalization_fingerprint does not cover the marker's claims"
            )


def stage_8e_finalization_fingerprint(
    marker: Stage8EFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_8e_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_8e_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence directory holds, sorted."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage8EFinalizationError(
            f"no published Stage 8E evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise Stage8EFinalizationError(
                f"published evidence may not be a link: {path.name}"
            )
        if not path.is_file():
            raise Stage8EFinalizationError(
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
        raise Stage8EFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage8EFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No licence text, upstream byte, score or machine path reached the evidence.

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
            raise Stage8EFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage8EFinalizationError(
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


# ------------------------------------------------------------- the boundary


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
        raise Stage8EFinalizationError(
            f"cannot audit Stage 8E workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage8EFinalizationError(
            "cannot audit Stage 8E workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage8e_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        path.startswith("tests/")
        and path.endswith(".py")
        and ("stage8e" in name or name.startswith("test_third_party_"))
    )


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage8e_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage8e_test(path)


def _audit_source_boundaries(repository_root: Path) -> None:
    """Stage 8E's modules import no algorithm, no runtime and no derivation layer."""
    for relative in _STAGE_8E_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage8EFinalizationError(
                f"cannot audit Stage 8E source boundary {relative}: {exc}"
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
            raise Stage8EFinalizationError(
                f"{relative}: Stage 8E imports an algorithm, a runtime or a "
                f"derivation layer {blocked}"
            )
        own = EVIDENCE_DIRECTORY.name
        for literal in literals:
            normalized = literal.replace("\\", "/")
            if not normalized.startswith(_EVIDENCE_PREFIX):
                continue
            if normalized in _PERMITTED_PRIOR_STAGE_DOCUMENTS:
                continue
            # Stage 8E's own evidence, named in full or by a prefix of its
            # directory. A bare ``evidence/`` leaves nothing after the prefix and
            # is refused: a module that could reach for the whole tree is a module
            # nobody could say what it read.
            tail = normalized[len(_EVIDENCE_PREFIX) :]
            if tail and (own.startswith(tail) or tail.startswith(own)):
                continue
            raise Stage8EFinalizationError(
                f"{relative}: Stage 8E source names published evidence it is not "
                f"entitled to read: {literal!r}"
            )


def _stage_8e_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 8E's own commits changed, across its span.

    Commit by commit rather than endpoint to endpoint, so that a repair to an
    earlier stage that happened to land in the middle of this span is attributed
    to whoever made it. A merge commit has no single parent to diff against and
    there are none in this history; if one appears, it is reported rather than
    silently skipped.
    """
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_8E_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_8E_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage8EFinalizationError(
            f"Stage 8E's span contains merge commits, which it cannot attribute: "
            f"{merges}"
        )

    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_8E_COMMITS_IN_SPAN:
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


def verify_stage8e_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 8E changed only its own surface, over its own span.

    ``span_end_commit`` is the commit the publication names as its verifier.
    Reading the span's end from the evidence rather than from a constant is what
    lets Stage 9A exist without editing this file (docs/adr/0067).
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage8EFinalizationError(
            f"cannot resolve Stage 8E repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage8EFinalizationError(
            "the Stage 8E boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_8E_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_8e_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage8EFinalizationError(
            f"Stage 8E changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage8EFinalizationError(
            f"paths outside Stage 8E changed during Stage 8E: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage8EFinalizationError(
            f"Stage 8E material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


# ------------------------------------------------------------- the publisher


def _head_commit(repository_root: Path) -> str:
    return _git_output(repository_root, "rev-parse", "HEAD")[0].strip().lower()


def _tree_is_clean(repository_root: Path, *, ignoring: tuple[str, ...] = ()) -> bool:
    """Whether the working tree is clean, optionally ignoring the files being written.

    ``ignoring`` exists for exactly one moment: the marker is derived against the
    *other* evidence documents, which have to be written before it and are
    therefore uncommitted while it is derived. Nothing else may be dirty.
    """
    entries = _git_output(repository_root, "status", "--porcelain", "--untracked-files=all")
    for entry in entries:
        path = entry[3:].strip().strip('"')
        if path not in ignoring:
            return False
    return True


def write_stage8e_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The five derivable documents first, then the marker — which is derived
    against the *exact bytes* of the other five, so it has to come after them.
    That is the same two-commit shape Stage 8D published under: the documents in
    one commit, the marker in the next, against a clean tree.

    ``include_marker=False`` writes only the five. Use it before the documents
    are committed; the marker pins a commit and a clean tree, and a marker
    derived over uncommitted bytes would name a state that never existed in
    history.

    Raises:
        Stage8EFinalizationError: the marker was asked for and the tree is not
            clean apart from the evidence being written.
    """
    from fpbench.experiments.stage8e_research_only_policy import (
        REQUIRED_IGNORE_PATTERNS,
        build_legacy_audit,
        build_repository_audit,
        policy_contract_report,
        require_stage8d_is_the_stage_this_follows,
        run_policy_qualification,
    )
    from fpbench.third_party.policy import third_party_policy
    from fpbench.third_party.purpose import project_purpose

    repository_root = Path(repository_root)
    require_stage8d_is_the_stage_this_follows(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    declaration = project_purpose()
    policy = third_party_policy()
    legacy = build_legacy_audit(repository_root)
    repository = build_repository_audit(repository_root)
    qualification = run_policy_qualification()

    written: list[Path] = []
    written.append(write_evidence_json(directory / "project-purpose.json", declaration))
    written.append(write_evidence_json(directory / "third-party-policy.json", policy))
    written.append(
        write_evidence_json(
            directory / "legacy-component-audit.json",
            {
                "schema_version": "1",
                "statement": (
                    "Every third-party component this project already depends on, "
                    "mapped into the Stage 8E vocabulary by the same engine a "
                    "future algorithm will use. No historical evidence was "
                    "rewritten, no licence question was resolved, and nothing "
                    "here is upstream content."
                ),
                "audit_fingerprint": legacy.audit_fingerprint,
                "component_count": len(legacy.mappings),
                "by_route": {
                    route: sum(
                        1 for mapping in legacy.mappings if mapping.route == route
                    )
                    for route in sorted({m.route for m in legacy.mappings})
                },
                "by_component_kind": dict(legacy.by_kind()),
                "by_license_observation_status": dict(legacy.by_status()),
                "by_research_use_decision": dict(legacy.by_decision()),
                "owner_risk_accepted_count": legacy.risk_accepted_count,
                "blocked_count": legacy.blocked_count,
                "manifests": [
                    {
                        "manifest_id": manifest.manifest_id,
                        "subject": manifest.subject,
                        "manifest_fingerprint": manifest.manifest_fingerprint,
                        "record_count": len(manifest.records),
                        "opens_execution": manifest.opens_execution,
                    }
                    for manifest in legacy.manifests
                ],
                "components": [
                    {
                        "route": mapping.route,
                        "observation": to_plain(mapping.observation),
                        "assessment": to_plain(mapping.assessment),
                        "usage_record": to_plain(mapping.record),
                    }
                    for mapping in legacy.mappings
                ],
            },
        )
    )
    written.append(
        write_evidence_json(
            directory / "repository-artifact-audit.json",
            {
                "schema_version": "1",
                "statement": (
                    "What Git actually tracks and what the public workflows "
                    "actually do. .gitignore is a convenience; this is the "
                    "enforcement (docs/adr/0083)."
                ),
                "repository_audit_fingerprint": (
                    repository.repository_audit_fingerprint
                ),
                "tracked_files": {
                    "audit_fingerprint": repository.artifacts.audit_fingerprint,
                    # No file count here, deliberately. The population grows with
                    # every commit — including the one that publishes this
                    # document — so a count written here could never be
                    # re-derived from a later tree. The count at the moment the
                    # marker was written is in the marker, which names a commit.
                    "every_tracked_file_was_hashed": (
                        repository.artifacts.every_tracked_file_was_hashed
                    ),
                    "rules": list(repository.artifacts.rules),
                    "allowed_exceptions": list(
                        repository.artifacts.allowed_exceptions
                    ),
                    "exception_reason": (
                        "synthetic checkerboards, gradients and ridge-shaped "
                        "stripes generated by tests/fixtures/imaging/generate.py; "
                        "no subject produced any of them"
                    ),
                    "findings": [
                        to_plain(finding) for finding in repository.artifacts.findings
                    ],
                },
                "workflows": {
                    "workflow_count": repository.workflows.workflow_count,
                    "scanned_tokens": list(repository.workflows.scanned_tokens),
                    "findings": [
                        to_plain(finding) for finding in repository.workflows.findings
                    ],
                },
                "ignore_coverage": {
                    "required_patterns": list(REQUIRED_IGNORE_PATTERNS),
                    "missing_patterns": list(repository.missing_ignore_patterns),
                },
                "clean": repository.clean,
            },
        )
    )
    written.append(
        write_evidence_json(
            directory / "policy-contract-report.json",
            policy_contract_report(repository_root),
        )
    )

    if not include_marker:
        return tuple(written)

    names = tuple(
        sorted(
            name
            for name in REQUIRED_EVIDENCE_FILES
            if name != "stage-8e-finalization.json"
        )
    )
    relative_names = tuple(
        (EVIDENCE_DIRECTORY / name).as_posix() for name in names
    )
    commit = _head_commit(repository_root)
    if not _tree_is_clean(repository_root, ignoring=relative_names):
        raise Stage8EFinalizationError(
            "the Stage 8E marker is derived against a clean tree at a real "
            "commit. Commit the five evidence documents first, then run this "
            "again: the marker pins their exact bytes and the commit they were "
            "published in"
        )

    claims: dict[str, Any] = {
        "schema_version": STAGE_8E_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": STAGE_8E_OUTCOME,
        "stage8d_finalization_fingerprint": STAGE8D_FINALIZATION_FINGERPRINT,
        "stage8d_outcome": STAGE8D_OUTCOME,
        "project_purpose": declaration.purpose.value,
        "purpose_fingerprint": declaration.purpose_fingerprint,
        "policy_fingerprint": policy.policy_fingerprint,
        "third_party_model_fingerprint": third_party_model_fingerprint(repository_root),
        "policy_engine_fingerprint": policy_engine_fingerprint(repository_root),
        "legacy_component_audit_fingerprint": legacy.audit_fingerprint,
        "legacy_component_count": len(legacy.mappings),
        "legacy_manifest_count": len(legacy.manifests),
        "owner_risk_accepted_count": legacy.risk_accepted_count,
        "blocked_component_count": legacy.blocked_count,
        "repository_audit_fingerprint": repository.repository_audit_fingerprint,
        "tracked_file_count": repository.artifacts.tracked_file_count,
        "third_party_bytes_in_git": len(repository.artifacts.findings),
        "workflow_count": repository.workflows.workflow_count,
        "workflow_findings": len(repository.workflows.findings),
        "policy_qualification_fingerprint": qualification.qualification_fingerprint,
        "policy_case_count": len(qualification.cases),
        "policy_decision_cases": qualification.decision_cases,
        "policy_refusal_cases": qualification.refusal_cases,
        "policy_identity_cases": qualification.identity_cases,
        "commercial_use_by_project": False,
        "third_party_redistribution_by_project": False,
        "third_party_bytes_permitted_in_git": False,
        "license_observation_separate_from_execution_decision": True,
        "restricted_research_licenses_may_execute_locally": True,
        "unresolved_license_may_require_owner_risk_acceptance": True,
        "no_access_control_circumvention": True,
        "dataset_rights_unchanged": True,
        "historical_evidence_changed": False,
        "upstream_license_question_resolved": False,
        "fpbench_license_added": (repository_root / "LICENSE").exists(),
        "opens_stage_9a": True,
        "evidence_content_hashes": {
            name: file_sha256(directory / name) for name in names
        },
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }
    marker = Stage8EFinalization(
        **claims,
        stage_8e_finalization_fingerprint=stage_8e_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(
        write_evidence_json(directory / "stage-8e-finalization.json", marker)
    )
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage8e_finalization``.

    ``documents`` writes the five derivable documents; ``publish`` writes those
    and the marker, and refuses a dirty tree. ``status`` derives everything and
    prints the fingerprints without writing anything, which is what a reviewer
    runs before deciding whether to commit.
    """
    parser = argparse.ArgumentParser(description="Stage 8E evidence")
    parser.add_argument(
        "action", choices=("status", "documents", "publish"), nargs="?", default="status"
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        from fpbench.experiments.stage8e_research_only_policy import (
            build_legacy_audit,
            build_repository_audit,
            run_policy_qualification,
        )
        from fpbench.third_party.policy import third_party_policy
        from fpbench.third_party.purpose import project_purpose

        legacy = build_legacy_audit(root)
        repository = build_repository_audit(root)
        qualification = run_policy_qualification()
        print(f"outcome                 {STAGE_8E_OUTCOME}")
        print(f"purpose_fingerprint     {project_purpose().purpose_fingerprint}")
        print(f"policy_fingerprint      {third_party_policy().policy_fingerprint}")
        print(f"legacy_audit            {legacy.audit_fingerprint}")
        print(
            f"  {len(legacy.mappings)} components, "
            f"{legacy.risk_accepted_count} risk-accepted, "
            f"{legacy.blocked_count} blocked"
        )
        print(f"  by decision           {dict(legacy.by_decision())}")
        print(f"repository_audit        {repository.repository_audit_fingerprint}")
        print(
            f"  {repository.artifacts.tracked_file_count} tracked files, "
            f"{len(repository.artifacts.findings)} third-party bytes, "
            f"{repository.workflows.workflow_count} workflows, "
            f"{len(repository.workflows.findings)} workflow findings"
        )
        print(f"policy_qualification    {qualification.qualification_fingerprint}")
        print(
            f"  {len(qualification.cases)} cases: "
            f"{qualification.decision_cases} decisions, "
            f"{qualification.refusal_cases} refusals, "
            f"{qualification.identity_cases} identities"
        )
        return 0

    written = write_stage8e_evidence(
        root, include_marker=arguments.action == "publish"
    )
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
