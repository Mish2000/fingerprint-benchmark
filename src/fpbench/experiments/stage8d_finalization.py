"""The Stage 8D marker, and the audit that proves the stage stayed inside itself.

The marker's job is unusual for this project, and worth stating plainly: most
stage markers assert that something was measured. This one asserts that nothing
was. ``CALIBRATION_INFRASTRUCTURE_READY`` says the machinery exists and was
qualified on synthetic fixtures, and the same document says — in fields, not in
prose — that no development dataset was selected, no calibration was performed,
no production threshold exists, and no evaluation score row was read
(docs/adr/0078).

The boundary audit follows docs/adr/0067: it compares the commit Stage 8D began
at with the commit it published at, rather than comparing against a moving
``HEAD``. The span's end is read from the published marker's
``verifier_source_commit``, so Stage 9A can exist without anyone editing this
file.

Stage 8D touches more shared infrastructure than the stages before it — the
decision-profile schema, the shared enums, the storage layout — because a
calibration layer is not an algorithm route. Each of those is allowed only under
the three conditions docs/adr/0067's successor rule states: algorithm-neutral,
backward compatible, and fingerprint preserving. The last one is not taken on
trust: the two published schema mappings are pinned by literal digest in the
contract suite.
"""

from __future__ import annotations

import ast
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from fpbench.core.calibration_errors import Stage8DFinalizationError
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage8d_identity import (
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    PROTECTED_SOURCE_DOCUMENTS,
    REQUIRED_EVIDENCE_FILES,
    STAGE_8D_OUTCOME,
    STAGE_8D_SCHEMA_VERSION,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_8D_BASELINE_COMMIT",
    "Stage8DFinalization",
    "stage_8d_finalization_fingerprint",
    "calibration_model_fingerprint",
    "selection_engine_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "verify_stage8d_workspace_boundaries",
]

#: Stage 8D began here: the approved HEAD that closed Stage 8C.
STAGE_8D_BASELINE_COMMIT = "a27104b244489c02240c345ad4cee7e0d1a2cb3d"

#: Commits inside Stage 8D's span that are **not** Stage 8D's work.
#:
#: Two repairs to earlier stages' surfaces landed between the baseline and the
#: publication: a race in the external process runner, and two workspace guards
#: that crashed instead of skipping. Both were found *by* Stage 8D and fixed
#: *outside* it, on their own, because Stage 8D is not entitled to edit
#: `adapters/support/process.py` or Stage 7A's acceptance tests.
#:
#: Because history is linear, `git diff BASELINE..PUBLICATION` attributes their
#: changes to this stage. It should not: the audit's question is "which paths did
#: Stage 8D change?", and a span is only a proxy for that. So the audit walks the
#: span commit by commit and skips these two, which is the difference between
#: answering the question and answering a convenient approximation of it.
#:
#: The list is closed. The span ends at the published marker's commit, so no
#: future commit can enter it (docs/adr/0067).
_NON_STAGE_8D_COMMITS_IN_SPAN = frozenset(
    {
        # Fix Windows process and workspace regressions
        "29a1b041b1f9f44610d82169dda00472293743e7",
        # Avoid module-level workspace skips
        "9f571d53da56338c0df7d802712ccc095a4f054d",
    }
)

_HEX = frozenset("0123456789abcdef")

#: The source whose bytes ``calibration_model_fingerprint`` covers: the artifacts
#: and the rules for constructing one. A change to any of them changes what a
#: stored calibration document *means*, so the marker pins them.
_MODEL_SOURCE_FILES = (
    "src/fpbench/core/calibration_models.py",
    "src/fpbench/core/calibration_errors.py",
    "src/fpbench/calibration/models.py",
    "src/fpbench/calibration/protocol.py",
)

#: The source whose bytes ``selection_engine_fingerprint`` covers: everything
#: that decides *which* boundary is chosen, refuses an input, or turns the answer
#: into a decision profile.
_ENGINE_SOURCE_FILES = (
    "src/fpbench/calibration/selection.py",
    "src/fpbench/calibration/validation.py",
    "src/fpbench/calibration/verify.py",
    "src/fpbench/calibration/profiles.py",
)

#: Shared files Stage 8D is allowed to touch, each named rather than covered by a
#: prefix. A shared file that changed without being on this list is a finding.
#:
#: The four ``core`` and ``storage`` entries are the ones that need justifying,
#: and each satisfies the three conditions:
#:
#: * ``enums.py`` — a new algorithm-neutral vocabulary section, plus ``EVALUATION``
#:   as an *alias* of ``TEST`` whose serialized value is unchanged;
#: * ``decision_models.py`` — schema 3 under a fingerprint mapping of its own,
#:   with schemas 1 and 2 pinned by literal digest in the contract suite;
#: * ``decision_set_store.py`` — three ``get`` reads for keys no older document
#:   has, so a stored schema-1 or schema-2 profile reconstructs identically;
#: * ``layout.py`` — a new directory family that nothing else writes into.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage8d-calibration-infrastructure.yml",
        ".github/workflows/tests.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0078-stage-8d-builds-calibration-infrastructure-without-calibrating.md",
        "docs/adr/0079-calibration-data-must-be-development-not-evaluation.md",
        "docs/adr/0080-calibration-selects-native-score-boundaries-without-score-normalization.md",
        "docs/calibration/architecture.md",
        "docs/calibration/operating-point-selection.md",
        "docs/experiments/stage8d-calibration-infrastructure.md",
        "src/fpbench/core/calibration_errors.py",
        "src/fpbench/core/calibration_models.py",
        "src/fpbench/core/decision_models.py",
        "src/fpbench/core/enums.py",
        "src/fpbench/calibration/__init__.py",
        "src/fpbench/calibration/models.py",
        "src/fpbench/calibration/protocol.py",
        "src/fpbench/calibration/selection.py",
        "src/fpbench/calibration/validation.py",
        "src/fpbench/calibration/verify.py",
        "src/fpbench/calibration/profiles.py",
        "src/fpbench/storage/calibration_store.py",
        "src/fpbench/storage/decision_set_store.py",
        "src/fpbench/storage/layout.py",
        "src/fpbench/experiments/stage8d_identity.py",
        "src/fpbench/experiments/stage8d_calibration_infrastructure.py",
        "src/fpbench/experiments/stage8d_finalization.py",
        "tests/unit/test_calibration_models.py",
        "tests/unit/test_calibration_selection.py",
        "tests/unit/test_calibration_store.py",
        # Stage 7D asserted that the schema catalogue held exactly two versions.
        # It holds three now, and the test still pins that the first two are the
        # ones stage 7D published (spec section 22).
        "tests/unit/test_strict_threshold_comparators.py",
        # The "no earlier receipt moved" guard was phrased as "every directory
        # except these exemptions", so Stage 8A, 8B and 8C had each come back to
        # add themselves. Stage 8D would have been the fourth — its protected
        # registry names all three executed algorithms because that is what the
        # artifact is for. It is now stated positively over the eight directories
        # that predate NBIS, which is a closed list nothing can join
        # (docs/adr/0067).
        "tests/regression/test_sourceafis_unmoved_after_nbis.py",
        # "storage may import only core" was a stated rule that nothing checked.
        # Stage 8D's store was first written with a deferred import of its own
        # parser from `fpbench.calibration`, which inverts the layering the whole
        # model/factory split rests on. Now enforced over the syntax tree.
        "tests/unit/test_import_boundaries.py",
    }
)
_ALLOWED_CHANGE_PREFIXES = ("evidence/stage8d-calibration-infrastructure/",)

#: Paths Stage 8D owns outright, scanned for work that was written but never
#: published. Shared files are *allowed* changes without becoming *owned* paths,
#: because Stage 8D edited them without acquiring any claim over their future
#: (docs/adr/0067).
_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith(
        (
            "src/fpbench/calibration/",
            "src/fpbench/experiments/stage8d_",
            "docs/calibration/",
            "evidence/stage8d-",
        )
    )
    or path
    in {
        "src/fpbench/core/calibration_errors.py",
        "src/fpbench/core/calibration_models.py",
        "src/fpbench/storage/calibration_store.py",
        "docs/experiments/stage8d-calibration-infrastructure.md",
        ".github/workflows/stage8d-calibration-infrastructure.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 8D may never change, checked by name so the message says which.
#:
#: Assembled from parts rather than written out, for the same reason Stage 8C
#: assembles its own list: this module is audited for source that names a prior
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
        ("configs", "decisions", ""),
        ("configs", "algorithms", ""),
        ("configs", "f" + "lx", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("integrations", ""),
    )
)

#: What no Stage 8D module may import (spec section 30).
_FORBIDDEN_IMPORT_PREFIXES = tuple(
    name
    for name in (
        "source" + "afis",
        "nb" + "is",
        "f" + "lx",
        "torch",
        "fpbench." + "f" + "lx",
        "fpbench.cross_algorithm",
        "fpbench.experiments.algorithm_decisions",
        "fpbench.experiments.algorithm_evaluation",
        "fpbench.eligibility",
        "fpbench.metrics",
        "fpbench.paired",
    )
)

#: The only prior-stage paths Stage 8D source may name, and it may only read
#: them. Every other reference to an earlier stage's evidence is a finding — a
#: stronger rule than "no references at all", because Stage 8D genuinely has to
#: read four published documents to build its protected registry (spec section 24).
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    relative for relative, _keys in PROTECTED_SOURCE_DOCUMENTS
)

#: Assembled rather than written out, for the same reason the protected prefixes
#: above are: this module is itself audited for literals naming published
#: evidence, and spelling this one out would make the audit refuse the file that
#: performs it.
_EVIDENCE_PREFIX = "evidence" + "/"

_STAGE_8D_SOURCE_FILES = (
    *_MODEL_SOURCE_FILES,
    *_ENGINE_SOURCE_FILES,
    "src/fpbench/calibration/__init__.py",
    "src/fpbench/storage/calibration_store.py",
    "src/fpbench/experiments/stage8d_identity.py",
    "src/fpbench/experiments/stage8d_calibration_infrastructure.py",
    "src/fpbench/experiments/stage8d_finalization.py",
)


def _require_digest(value: object, field_name: str) -> str:
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1 << 20), b""):
                digest.update(block)
    except OSError as exc:
        raise Stage8DFinalizationError(
            f"cannot hash required Stage 8D file {path}: {exc}"
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
        raise Stage8DFinalizationError(
            f"cannot hash Stage 8D source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _source_family_fingerprint(
    repository_root: Path, relatives: tuple[str, ...], *, schema: str
) -> str:
    """A digest over a named family of source files.

    Each file is hashed by :func:`source_file_sha256`, so a checkout that
    converted line endings does not change the identity of the code. What it does
    change — a character of logic — changes it immediately.
    """
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in relatives
    }
    return stable_hash({"schema": schema, "files": digests}, length=64)


def calibration_model_fingerprint(repository_root: Path) -> str:
    """The bytes that decide what a stored calibration document means."""
    return _source_family_fingerprint(
        repository_root, _MODEL_SOURCE_FILES, schema="stage_8d_calibration_models_v1"
    )


def selection_engine_fingerprint(repository_root: Path) -> str:
    """The bytes that decide which boundary is chosen, and what is refused."""
    return _source_family_fingerprint(
        repository_root, _ENGINE_SOURCE_FILES, schema="stage_8d_selection_engine_v1"
    )


# ---------------------------------------------------------------- the marker


@dataclass(frozen=True, slots=True)
class Stage8DFinalization:
    """Immutable authority for Stage 8D's claim, and for its many denials.

    Every ``False`` and every ``0`` below is load-bearing. A marker that merely
    omitted them would be a marker a reader had to interpret, and the whole point
    of the stage is that what it did *not* do is as precisely stated as what it
    did (docs/adr/0078).
    """

    schema_version: str
    kind: str
    outcome: str

    # The stage this follows, bound rather than assumed.
    stage8c_finalization_fingerprint: str
    stage8c_outcome: str

    # The machinery.
    calibration_model_fingerprint: str
    selection_engine_fingerprint: str
    protected_evaluation_registry_fingerprint: str
    synthetic_qualification_fingerprint: str

    # The shape of the qualification.
    synthetic_case_count: int
    synthetic_selection_cases: int
    synthetic_refusal_cases: int
    synthetic_identity_cases: int
    protected_identity_count: int

    # What was *not* done.
    real_development_dataset_selected: bool
    real_calibration_performed: bool
    production_threshold_count: int
    production_decision_profile_count: int
    evaluation_score_rows_read: bool
    sd300_score_statistics_read: bool
    historical_decision_profiles_changed: bool
    stage8c_evidence_changed: bool

    # What it opens.
    opens_algorithm_expansion: bool

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_8d_finalization_fingerprint: str
    created_utc: str

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_8D_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 8D finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome != STAGE_8D_OUTCOME:
            raise ValueError(f"outcome must be {STAGE_8D_OUTCOME}")

        for name in (
            "stage8c_finalization_fingerprint",
            "calibration_model_fingerprint",
            "selection_engine_fingerprint",
            "protected_evaluation_registry_fingerprint",
            "synthetic_qualification_fingerprint",
            "stage_8d_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        for name in (
            "synthetic_case_count",
            "synthetic_selection_cases",
            "synthetic_refusal_cases",
            "synthetic_identity_cases",
            "protected_identity_count",
            "production_threshold_count",
            "production_decision_profile_count",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, value)

        if (
            self.synthetic_selection_cases
            + self.synthetic_refusal_cases
            + self.synthetic_identity_cases
            != self.synthetic_case_count
        ):
            raise ValueError(
                "every synthetic case selects, refuses or establishes an identity, "
                "and these do not add up"
            )
        if self.synthetic_case_count <= 0:
            raise ValueError(
                "a qualification with no cases has qualified nothing"
            )
        if self.synthetic_refusal_cases <= 0:
            raise ValueError(
                "a qualification with no refusal cases has not tested the half of "
                "the engine that matters (docs/adr/0079)"
            )
        if self.protected_identity_count <= 0:
            raise ValueError(
                "a protected-evaluation registry that protects nothing looks like a "
                "check and is not one"
            )

        # The denials, each checked rather than merely stored.
        for name in (
            "real_development_dataset_selected",
            "real_calibration_performed",
            "evaluation_score_rows_read",
            "sd300_score_statistics_read",
            "historical_decision_profiles_changed",
            "stage8c_evidence_changed",
        ):
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 8D asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage "
                    "(docs/adr/0078)"
                )
        if self.production_threshold_count != 0:
            raise ValueError("Stage 8D produces no production threshold")
        if self.production_decision_profile_count != 0:
            raise ValueError("Stage 8D produces no production decision profile")
        if self.opens_algorithm_expansion is not True:
            raise ValueError(
                "a complete Stage 8D opens algorithm expansion, not a calibration "
                "stage; opening one would be the decision docs/adr/0078 defers"
            )
        if self.source_tree_clean is not True:
            raise ValueError("Stage 8D evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 8D finalization requires a clean verifier tree")

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

        expected = stage_8d_finalization_fingerprint(self)
        if self.stage_8d_finalization_fingerprint != expected:
            raise ValueError(
                "stage_8d_finalization_fingerprint does not cover the marker's claims"
            )


def stage_8d_finalization_fingerprint(
    marker: Stage8DFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_8d_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_8d_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence directory holds, sorted."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage8DFinalizationError(
            f"no published Stage 8D evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink():
            raise Stage8DFinalizationError(
                f"published evidence may not be a link: {path.name}"
            )
        if not path.is_file():
            raise Stage8DFinalizationError(
                f"published evidence holds a non-file entry: {path.name}"
            )
        names.append(path.name)
    return tuple(names)


def require_expected_evidence_files(names: tuple[str, ...]) -> None:
    """The fixed list, and nothing else.

    Unlike Stage 8C, every Stage 8D filename is known in advance: there is no run
    to name a file after, because there was no run.
    """
    present = set(names)
    expected = set(REQUIRED_EVIDENCE_FILES)
    missing = sorted(expected - present)
    if missing:
        raise Stage8DFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage8DFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No score, threshold, distribution or subject identifier reached the evidence.

    Every published JSON document is walked as *data* — keys, not text — so a
    token inside a prose sentence in the README does not trip it and a key buried
    six levels down does (spec section 36).
    """
    from fpbench.core.serialization import read_json

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.glob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise Stage8DFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage8DFinalizationError(
                f"published evidence {path.name} carries forbidden data: {found} "
                "(spec section 36)"
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
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage8DFinalizationError(
            f"cannot audit Stage 8D workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage8DFinalizationError(
            "cannot audit Stage 8D workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage8d_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        path.startswith("tests/")
        and path.endswith(".py")
        and ("stage8d" in name or name.startswith("test_calibration_"))
    )


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage8d_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage8d_test(path)


def _audit_source_boundaries(repository_root: Path) -> None:
    """Stage 8D's modules import no algorithm and no derivation layer."""
    for relative in _STAGE_8D_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage8DFinalizationError(
                f"cannot audit Stage 8D source boundary {relative}: {exc}"
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
            raise Stage8DFinalizationError(
                f"{relative}: Stage 8D imports an algorithm or a derivation layer "
                f"{blocked} (spec section 30)"
            )
        own = EVIDENCE_DIRECTORY.name
        for literal in literals:
            normalized = literal.replace("\\", "/")
            if not normalized.startswith(_EVIDENCE_PREFIX):
                continue
            if normalized in _PERMITTED_PRIOR_STAGE_DOCUMENTS:
                continue
            # Stage 8D's own evidence, named in full or by a prefix of its
            # directory. A bare ``evidence/`` leaves nothing after the prefix and
            # is refused: a module that could reach for the whole tree is a module
            # nobody could say what it read.
            tail = normalized[len(_EVIDENCE_PREFIX) :]
            if tail and (own.startswith(tail) or tail.startswith(own)):
                continue
            raise Stage8DFinalizationError(
                f"{relative}: Stage 8D source names published evidence it is not "
                f"entitled to read: {literal!r} (spec section 24)"
            )


def _stage_8d_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 8D's own commits changed, across its span.

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
        f"{STAGE_8D_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_8D_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage8DFinalizationError(
            f"Stage 8D's span contains merge commits, which it cannot attribute: "
            f"{merges}"
        )

    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_8D_COMMITS_IN_SPAN:
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


def verify_stage8d_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 8D changed only its own surface, over its own span.

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
        raise Stage8DFinalizationError(
            f"cannot resolve Stage 8D repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage8DFinalizationError(
            "the Stage 8D boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_8D_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_8d_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage8DFinalizationError(
            f"Stage 8D changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage8DFinalizationError(
            f"paths outside Stage 8D changed during Stage 8D: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage8DFinalizationError(
            f"Stage 8D material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)
