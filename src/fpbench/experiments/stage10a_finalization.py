"""The Stage 10A marker, the publisher, and the audit that proves the stage stayed inside itself.

The marker has two legal outcomes and validates differently under each.
``ALGORITHM4_CANDIDATE_SELECTED`` names exactly one candidate, requires that
candidate to have passed all seven hard gates, and opens the artifact
qualification that follows. ``ALGORITHM4_PREFLIGHT_NO_SURVIVOR`` names none,
requires at least one blocker, opens nothing, and opens a search for a third
candidate instead. Neither is a failure. A stage that could only publish a
selection would be a stage under pressure to find one, and that pressure is
precisely what turns a weak candidate into Algorithm 4 (docs/adr/0089).

What the marker denies is the same under both outcomes and is checked rather
than written as prose: no SD300 image byte and no SD300 score was read, no
candidate was chosen on reported performance, no score-affecting preprocessing
was invented, no production adapter exists, no calibration happened, no
third-party byte entered Git, and not one byte of Stage 8E's or Stage 9A's
evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 10A began
at with the commit it published at, rather than against a moving ``HEAD``, and
it walks the span commit by commit so that work belonging to another stage can
be attributed to that stage rather than to this one.
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

from fpbench.core.algorithm4_errors import Stage10AFinalizationError
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage10a_candidate_identity import (
    ALGORITHM_SLOT,
    CANDIDATES,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_10A_FINALIZATION_NAME,
    STAGE_10A_NO_SURVIVOR_OUTCOME,
    STAGE_10A_OUTCOMES,
    STAGE_10A_SCHEMA_VERSION,
    STAGE_10A_SELECTED_OUTCOME,
    STAGE_FINALIZATION_KIND,
    candidate,
    candidate_document_names,
)

__all__ = [
    "STAGE_10A_BASELINE_COMMIT",
    "Stage10AFinalization",
    "stage_10a_finalization_fingerprint",
    "stage10a_source_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "verify_stage10a_workspace_boundaries",
    "write_evidence_json",
    "write_stage10a_evidence",
    "main",
]

#: Stage 10A began here: the approved HEAD that closed Stage 9A.
STAGE_10A_BASELINE_COMMIT = "efeac1c83e4f9bef5f4567c323fd13e57970a178"

#: Commits inside Stage 10A's span that are **not** Stage 10A's work. Empty
#: today and kept because it will not be: every stage so far has had at least
#: one repair to an earlier stage land in the middle of its span, and widening
#: the allowed path set to absorb one would be false (docs/adr/0067).
_NON_STAGE_10A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: The source whose bytes the marker pins. A change to any of them changes what
#: this preflight concluded.
_STAGE_10A_SOURCE_FILES = (
    "src/fpbench/core/algorithm4_errors.py",
    "src/fpbench/experiments/stage10a_candidate_identity.py",
    "src/fpbench/experiments/stage10a_candidate_evidence.py",
    "src/fpbench/experiments/stage10a_preflight.py",
    "src/fpbench/experiments/stage10a_finalization.py",
)

#: Shared files Stage 10A is allowed to touch, each named rather than covered by
#: a prefix. Stage 10A adds one ``core`` module of its own rather than extending
#: an existing one, and adds no package: it is a selection, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage10a-algorithm4-candidate-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0089-algorithm-4-selection-requires-preflight-before-commitment.md",
        (
            "docs/adr/0090-adjusted-third-party-reimplementations-do-not-inherit-"
            "original-algorithm-identity.md"
        ),
        "docs/adr/0091-benchmark-input-domain-compatibility-is-a-hard-candidate-gate.md",
        (
            "docs/adr/0092-fpbench-does-not-invent-score-affecting-input-"
            "construction-to-admit-a-candidate.md"
        ),
        "docs/adr/0093-algorithm-4-is-selected-only-among-hard-gate-survivors.md",
        "docs/experiments/stage10a-algorithm4-candidate-preflight.md",
        *_STAGE_10A_SOURCE_FILES,
    }
)
_ALLOWED_CHANGE_PREFIXES = (
    "evidence/stage10a-algorithm4-candidate-preflight/",
    "docs/algorithms/algorithm4-candidates/",
)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage10a_")
    or path
    in {
        "src/fpbench/core/algorithm4_errors.py",
        "docs/experiments/stage10a-algorithm4-candidate-preflight.md",
        ".github/workflows/stage10a-algorithm4-candidate-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 10A may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason Stage 8C, 8D, 8E
#: and 9A assemble theirs: this module is audited for source that names a prior
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
        ("evidence", "stage9a-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "f" + "lare_errors.py"),
        ("src", "fpbench", "experiments", "stage9a_"),
        ("configs", ""),
        ("integrations", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 10A module may import *at all*. A selection layer that reached
#: into an algorithm, a runtime or a derivation would be a selection whose
#: answers could depend on what had been run.
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
        "fpbench.experiments.stage9a_" + "flare_identity",
        "fpbench.experiments.stage9a_" + "flare_artifacts",
        "fpbench.experiments.stage9a_" + "flare_route",
        "fpbench.experiments.stage9a_" + "flare_qualification",
        "fpbench.experiments.stage9a_" + "flare_finalization",
    )
)

#: What no Stage 10A module may import **at module level**, and may import
#: inside a function. Stage 10A executes nothing, and it must stay importable on
#: a machine with no scientific stack at all — which is the machine its public
#: CI runs on.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage path Stage 10A source may name, and it may only read it.
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
        raise Stage10AFinalizationError(
            f"cannot hash required Stage 10A file {path}: {exc}"
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
        raise Stage10AFinalizationError(
            f"cannot hash Stage 10A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage10a_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this preflight."""
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in _STAGE_10A_SOURCE_FILES
    }
    return stable_hash(
        {"schema": "stage_10a_source_v1", "files": digests}, length=64
    )


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage10AFinalization:
    """Immutable authority for what Stage 10A established, and for what it did not.

    Two outcomes, validated differently. Under ``SELECTED`` exactly one
    candidate is named, that candidate's verdict is ``PASS`` and the artifact
    qualification opens. Under ``NO_SURVIVOR`` no candidate is named, every
    verdict is ``FAIL``, at least one blocker is carried and a candidate search
    opens instead. There is no third state and no way to write "selected with
    reservations", which is the shape that would eventually be used.
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    stage8e_policy_fingerprint: str
    stage10a_source_fingerprint: str
    reconnaissance_fingerprint: str
    preflight_fingerprint: str
    third_party_usage_manifest_fingerprint: str

    selected_candidate: str | None
    afrnet_preflight: str
    jipnet_preflight: str
    candidate_count: int
    survivor_count: int
    gates_evaluated_per_candidate: int

    # What the stage did not do.
    selection_based_on_reported_performance: bool
    reported_performance_read: bool
    sd300_image_bytes_read: bool
    sd300_scores_read: bool
    prior_algorithm_scores_read: bool
    fpbench_score_affecting_preprocessing_invented: bool
    candidate_checkpoint_bytes_downloaded: int
    production_adapter_created: bool
    calibration_performed: bool
    threshold_produced: bool
    decision_profile_produced: bool
    benchmark_run_performed: bool
    third_party_bytes_added_to_git: bool
    stage8e_evidence_changed: bool
    stage9a_evidence_changed: bool
    upstream_behaviour_modified: bool

    # What it opens.
    opens_algorithm4_artifact_qualification: bool
    opens_candidate_search: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_10a_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "selection_based_on_reported_performance",
        "reported_performance_read",
        "sd300_image_bytes_read",
        "sd300_scores_read",
        "prior_algorithm_scores_read",
        "fpbench_score_affecting_preprocessing_invented",
        "production_adapter_created",
        "calibration_performed",
        "threshold_produced",
        "decision_profile_produced",
        "benchmark_run_performed",
        "third_party_bytes_added_to_git",
        "stage8e_evidence_changed",
        "stage9a_evidence_changed",
        "upstream_behaviour_modified",
    )

    _VERDICT_FIELDS = ("afrnet_preflight", "jipnet_preflight")

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_10A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 10A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome not in STAGE_10A_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(STAGE_10A_OUTCOMES)}; there is no "
                "third state and no 'selected with reservations'"
            )
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )

        for name in (
            "stage10a_source_fingerprint",
            "reconnaissance_fingerprint",
            "preflight_fingerprint",
            "third_party_usage_manifest_fingerprint",
            "stage_10a_finalization_fingerprint",
            "stage8e_policy_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        count = int(self.candidate_count)
        if count != len(CANDIDATES):
            raise ValueError(
                f"candidate_count is {count} and Stage 10A weighed "
                f"{len(CANDIDATES)}. A preflight over a different set is a "
                "different preflight"
            )
        object.__setattr__(self, "candidate_count", count)

        gates = int(self.gates_evaluated_per_candidate)
        if gates != 7:
            raise ValueError(
                "every candidate is measured against seven hard gates; a "
                "preflight with fewer would be a preflight that dropped one"
            )
        object.__setattr__(self, "gates_evaluated_per_candidate", gates)

        downloaded = int(self.candidate_checkpoint_bytes_downloaded)
        if downloaded != 0:
            raise ValueError(
                "no candidate reached the artifact gate, so no checkpoint byte "
                "was fetched. A non-zero count here would contradict the stage"
            )
        object.__setattr__(self, "candidate_checkpoint_bytes_downloaded", downloaded)

        verdicts: dict[str, str] = {}
        for item, name in zip(CANDIDATES, Stage10AFinalization._VERDICT_FIELDS):
            verdict = str(getattr(self, name))
            if verdict not in (item.pass_outcome, item.fail_outcome):
                raise ValueError(
                    f"{name} must be {item.pass_outcome!r} or "
                    f"{item.fail_outcome!r}, not {verdict!r}"
                )
            verdicts[item.candidate_id] = verdict

        survivors = int(self.survivor_count)
        expected_survivors = sum(
            1
            for item in CANDIDATES
            if verdicts[item.candidate_id] == item.pass_outcome
        )
        if survivors != expected_survivors:
            raise ValueError(
                f"survivor_count is {survivors} and the verdicts give "
                f"{expected_survivors}"
            )
        object.__setattr__(self, "survivor_count", survivors)

        for name in Stage10AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 10A asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )

        blockers = tuple(dict(item) for item in self.blockers)
        for blocker in blockers:
            missing = sorted(
                {
                    "candidate",
                    "gate",
                    "blocker_code",
                    "affected_component",
                    "evidence",
                    "why_this_blocks_algorithm_4",
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
                for item in sorted(
                    blockers,
                    key=lambda item: (item["candidate"], item["blocker_code"]),
                )
            ),
        )

        if self.outcome == STAGE_10A_SELECTED_OUTCOME:
            selected = self.selected_candidate
            if selected is None:
                raise ValueError("a SELECTED marker names the candidate it selected")
            chosen = candidate(str(selected).lower())
            if verdicts[chosen.candidate_id] != chosen.pass_outcome:
                raise ValueError(
                    f"{selected} was selected and its verdict is "
                    f"{verdicts[chosen.candidate_id]!r}"
                )
            object.__setattr__(self, "selected_candidate", chosen.marker_token)
            if self.opens_algorithm4_artifact_qualification is not True:
                raise ValueError(
                    "a SELECTED Stage 10A opens the Algorithm 4 artifact "
                    "qualification"
                )
            if self.opens_candidate_search is not False:
                raise ValueError(
                    "a SELECTED Stage 10A does not also open a search for "
                    "another candidate"
                )
        else:
            if self.selected_candidate is not None:
                raise ValueError(
                    "a NO_SURVIVOR marker selects nothing; the point of the "
                    "outcome is that the slot stays empty"
                )
            if survivors != 0:
                raise ValueError(
                    "a NO_SURVIVOR marker has no survivors, by definition"
                )
            if not self.blockers:
                raise ValueError(
                    "a NO_SURVIVOR marker names which blockers apply. A block "
                    "nobody can point at is a block nobody can lift"
                )
            if self.opens_algorithm4_artifact_qualification is not False:
                raise ValueError(
                    "a NO_SURVIVOR Stage 10A opens no artifact qualification; "
                    "there is no artifact to qualify"
                )
            if self.opens_candidate_search is not True:
                raise ValueError(
                    "a NO_SURVIVOR Stage 10A opens a search for a third "
                    "candidate. Weakening a gate to fill the slot is what this "
                    "stage exists to prevent (docs/adr/0089)"
                )

        if self.source_tree_clean is not True:
            raise ValueError("Stage 10A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 10A finalization requires a clean verifier tree")

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

        expected = stage_10a_finalization_fingerprint(self)
        if self.stage_10a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_10a_finalization_fingerprint does not cover the marker's "
                "claims"
            )


def stage_10a_finalization_fingerprint(
    marker: Stage10AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_10a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_10a_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence tree holds, as POSIX paths below it, sorted.

    Recursive, because this stage's evidence has one directory per candidate. A
    directory is walked; anything that is neither a directory nor a regular
    file, and anything reached through a link, is a refusal.
    """
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage10AFinalizationError(
            f"no published Stage 10A evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []

    def walk(current: Path, prefix: str) -> None:
        for path in sorted(current.iterdir()):
            relative = f"{prefix}{path.name}"
            if path.is_symlink():
                raise Stage10AFinalizationError(
                    f"published evidence may not be a link: {relative}"
                )
            if path.is_dir():
                walk(path, f"{relative}/")
                continue
            if not path.is_file():
                raise Stage10AFinalizationError(
                    f"published evidence holds a non-file entry: {relative}"
                )
            names.append(relative)

    walk(directory, "")
    return tuple(names)


def require_expected_evidence_files(names: tuple[str, ...]) -> None:
    """The fixed list, and nothing else."""
    present = set(names)
    expected = set(REQUIRED_EVIDENCE_FILES)
    missing = sorted(expected - present)
    if missing:
        raise Stage10AFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage10AFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No upstream byte, tensor, image, score or machine path reached the evidence.

    Every published JSON document is walked as *data* — keys, not text — so a
    token inside a prose sentence in the README does not trip it and a key
    buried six levels down does.
    """
    from fpbench.core.serialization import read_json

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise Stage10AFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage10AFinalizationError(
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
        raise Stage10AFinalizationError(
            f"cannot audit Stage 10A workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage10AFinalizationError(
            "cannot audit Stage 10A workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage10a_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return path.startswith("tests/") and path.endswith(".py") and "stage10a" in name


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage10a_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage10a_test(path)


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
    """Stage 10A's modules import no algorithm, no runtime and no closed stage."""
    for relative in _STAGE_10A_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage10AFinalizationError(
                f"cannot audit Stage 10A source boundary {relative}: {exc}"
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
            raise Stage10AFinalizationError(
                f"{relative}: Stage 10A imports an algorithm, a runtime bundle, "
                f"a derivation layer or a closed stage {blocked}"
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
            raise Stage10AFinalizationError(
                f"{relative}: Stage 10A imports {eager} at module level. This "
                "stage executes nothing, and it has to stay importable on a "
                "machine with no scientific stack"
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
            raise Stage10AFinalizationError(
                f"{relative}: Stage 10A source names published evidence it is "
                f"not entitled to read: {literal!r}"
            )


def _stage_10a_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 10A's own commits changed, across its span.

    Commit by commit rather than endpoint to endpoint, so that a repair to an
    earlier stage that happened to land in the middle of this span is attributed
    to whoever made it (docs/adr/0067).
    """
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_10A_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_10A_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage10AFinalizationError(
            f"Stage 10A's span contains merge commits, which it cannot "
            f"attribute: {merges}"
        )
    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_10A_COMMITS_IN_SPAN:
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


def verify_stage10a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 10A changed only its own surface, over its own span.

    ``span_end_commit`` is the commit the publication names as its verifier.
    Reading the span's end from the evidence rather than from a constant is what
    lets the next stage exist without editing this file (docs/adr/0067).
    """
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage10AFinalizationError(
            f"cannot resolve Stage 10A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage10AFinalizationError(
            "the Stage 10A boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_10A_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_10a_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage10AFinalizationError(
            f"Stage 10A changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage10AFinalizationError(
            f"paths outside Stage 10A changed during Stage 10A: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage10AFinalizationError(
            f"Stage 10A material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


# -------------------------------------------------------------- the publisher


def _head_commit(repository_root: Path) -> str:
    return _git_output(repository_root, "rev-parse", "HEAD")[0].strip().lower()


def _tree_is_clean(repository_root: Path, *, ignoring: tuple[str, ...] = ()) -> bool:
    """Whether the working tree is clean, ignoring the files being written."""
    entries = _git_output(
        repository_root, "status", "--porcelain", "--untracked-files=all"
    )
    for entry in entries:
        path = entry[3:].strip().strip('"')
        if path not in ignoring:
            return False
    return True


def write_stage10a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The twenty derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, so it has to come after them.
    That is the same two-commit shape Stage 8D, Stage 8E and Stage 9A published
    under: the documents in one commit, the marker in the next, against a clean
    tree.

    Raises:
        Stage10AFinalizationError: the marker was asked for and the tree is not
            clean apart from the marker being written.
    """
    from fpbench.experiments import stage10a_preflight as engine

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    outcome = engine.run_preflight()
    usage = engine.build_usage_audit()

    written: list[Path] = []
    written.append(
        write_evidence_json(
            directory / "candidate-set.json",
            {
                **engine.candidate_set_document(),
                "third_party_usage": engine.usage_manifest_document(usage),
            },
        )
    )
    for preflight in outcome.candidates:
        target = directory / preflight.candidate_id
        for name in candidate_document_names(preflight.identity):
            written.append(
                write_evidence_json(
                    target / name,
                    engine.candidate_document(
                        preflight, name, repository_root=repository_root
                    ),
                )
            )
    written.append(
        write_evidence_json(
            directory / "candidate-comparison.json",
            engine.candidate_comparison_document(outcome),
        )
    )
    if not include_marker:
        return tuple(written)

    require_expected_evidence_files(
        tuple(
            name
            for name in published_evidence_names(repository_root)
            if name != STAGE_10A_FINALIZATION_NAME
        )
        + (STAGE_10A_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_10A_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage10AFinalizationError(
            "the Stage 10A marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage10a_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = engine.require_no_candidate_bytes_in_git(repository_root)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_10A_FINALIZATION_NAME
    )
    verdicts = {item.candidate_id: item.verdict for item in outcome.candidates}
    claims: dict[str, Any] = {
        "schema_version": STAGE_10A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": outcome.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage10a_source_fingerprint": stage10a_source_fingerprint(repository_root),
        "reconnaissance_fingerprint": _reconnaissance_fingerprint(),
        "preflight_fingerprint": outcome.preflight_fingerprint,
        "third_party_usage_manifest_fingerprint": (
            usage.manifest.manifest_fingerprint
        ),
        "selected_candidate": (
            candidate(outcome.selected_candidate).marker_token
            if outcome.selected_candidate
            else None
        ),
        "afrnet_preflight": verdicts["afrnet"],
        "jipnet_preflight": verdicts["jipnet"],
        "candidate_count": len(CANDIDATES),
        "survivor_count": len(outcome.survivors),
        "gates_evaluated_per_candidate": 7,
        "selection_based_on_reported_performance": False,
        "reported_performance_read": False,
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "prior_algorithm_scores_read": False,
        "fpbench_score_affecting_preprocessing_invented": False,
        "candidate_checkpoint_bytes_downloaded": 0,
        "production_adapter_created": False,
        "calibration_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "benchmark_run_performed": False,
        "third_party_bytes_added_to_git": bool(byte_audit.findings),
        "stage8e_evidence_changed": False,
        "stage9a_evidence_changed": False,
        "upstream_behaviour_modified": False,
        "opens_algorithm4_artifact_qualification": (
            outcome.outcome == STAGE_10A_SELECTED_OUTCOME
        ),
        "opens_candidate_search": (
            outcome.outcome == STAGE_10A_NO_SURVIVOR_OUTCOME
        ),
        "blockers": engine.marker_blocker_rows(outcome.blockers),
        "evidence_content_hashes": {
            name: file_sha256(directory / PurePosixPath(name)) for name in hashed
        },
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }
    marker = Stage10AFinalization(
        **claims,
        stage_10a_finalization_fingerprint=stage_10a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(
        write_evidence_json(directory / STAGE_10A_FINALIZATION_NAME, marker)
    )
    return tuple(written)


def _reconnaissance_fingerprint() -> str:
    from fpbench.experiments.stage10a_candidate_evidence import (
        reconnaissance_fingerprint,
    )

    return reconnaissance_fingerprint()


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage10a_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the
    marker too and refuses a dirty tree. ``status`` derives everything and
    prints the outcome, the gate matrix and the blockers without writing
    anything, which is what a reviewer runs before deciding whether to commit.
    """
    from fpbench.experiments import stage10a_candidate_identity as ids
    from fpbench.experiments import stage10a_preflight as engine

    parser = argparse.ArgumentParser(description="Stage 10A evidence")
    parser.add_argument(
        "action",
        choices=("status", "documents", "publish"),
        nargs="?",
        default="status",
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        outcome = engine.run_preflight()
        print(f"algorithm slot           {ALGORITHM_SLOT}")
        print(f"outcome                  {outcome.outcome}")
        print(f"selected candidate       {outcome.selected_candidate}")
        print(f"preflight                {outcome.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        header = "".join(
            f"  {item.candidate_id:>12s}" for item in outcome.candidates
        )
        print(f"{'gate':<{width}}{header}")
        for gate in ids.GATE_ORDER:
            row = "".join(
                f"  {item.status(gate).value:>12s}" for item in outcome.candidates
            )
            print(f"{gate.value:<{width}}{row}")
        for item in outcome.candidates:
            print(f"{item.candidate_id:<{width}}  {item.verdict}")
        if outcome.blockers:
            print(f"blockers                 {len(outcome.blockers)}")
            for blocker in outcome.blockers:
                print(
                    f"  {blocker.candidate_id:<8s} {blocker.gate.value:<14s} "
                    f"{blocker.blocker_code.value}"
                )
        return 0

    written = write_stage10a_evidence(
        root, include_marker=arguments.action == "publish"
    )
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
