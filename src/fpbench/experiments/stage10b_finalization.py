"""The Stage 10B marker, the publisher, and the audit that proves the stage stayed inside itself.

The marker has two legal outcomes and validates differently under each.
``ALGORITHM4_CANDIDATE_SELECTED`` names the candidate, requires it to have
passed all ten hard gates, requires every score fact to be established, and
opens Stage 10C. ``ID3_FINGER_SDK_PREFLIGHT_FAIL`` names none, requires at least
one blocker, requires every unestablished fact to be published as unestablished
rather than as a default, opens nothing, and opens a candidate search instead.

Neither is a failure of the stage. A preflight that could only publish a
selection would be a preflight under pressure to find one, and that pressure is
what turns "the quota is probably enough" into a benchmark that stops at
comparison four thousand (docs/adr/0094, docs/adr/0096).

What the marker denies is checked rather than written as prose: no SD300 image
byte, score or pair manifest was read, no production adapter exists, no
threshold or decision profile was produced, no vendor byte entered Git, no
credential entered Git or CI, no licence was activated in CI, and not one byte
of Stage 8E's, Stage 9A's or Stage 10A's evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 10B began
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

from fpbench.core.id3_preflight_errors import (
    SensitiveEvidenceError,
    Stage10BFinalizationError,
)
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage10b_id3_identity import (
    ALGORITHM_SLOT,
    CANDIDATE_FAIL_VERDICT,
    CANDIDATE_ID,
    CANDIDATE_PASS_VERDICT,
    CANDIDATE_VERDICTS,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    GATE_COUNT,
    README_NAME,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_10A_FINALIZATION_FINGERPRINT,
    STAGE_10B_BLOCKED_OUTCOME,
    STAGE_10B_FINALIZATION_NAME,
    STAGE_10B_OUTCOMES,
    STAGE_10B_SCHEMA_VERSION,
    STAGE_10B_SELECTED_OUTCOME,
    STAGE_10B_SOURCE_FILES,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_10B_BASELINE_COMMIT",
    "Stage10BFinalization",
    "stage_10b_finalization_fingerprint",
    "stage10b_source_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "require_no_sensitive_published_data",
    "verify_stage10b_workspace_boundaries",
    "write_evidence_json",
    "write_stage10b_evidence",
    "main",
]

#: Stage 10B began here: the commit that re-closed Stage 10A over its two
#: corrective fixes.
STAGE_10B_BASELINE_COMMIT = "fc14a1d58fa5f25831a5d8e8f77e803c661e572f"

#: Commits inside Stage 10B's span that are **not** Stage 10B's work. Empty
#: today and kept because it will not be: every stage so far has had at least
#: one repair to an earlier stage land in the middle of its span, and widening
#: the allowed path set to absorb one would be false (docs/adr/0067).
_NON_STAGE_10B_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 10B is allowed to touch, each named rather than covered by
#: a prefix. Stage 10B adds one ``core`` module of its own rather than extending
#: an existing one, and adds no package: it is a qualification, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage10b-id3-finger-sdk-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0094-stage-10b-preflights-id3-before-algorithm-4-selection.md",
        "docs/adr/0095-proprietary-access-and-research-use-are-separate-gates.md",
        (
            "docs/adr/0096-evaluation-license-capacity-must-cover-the-frozen-"
            "workload.md"
        ),
        (
            "docs/adr/0097-id3-extractor-and-matcher-defaults-are-part-of-"
            "algorithm-identity.md"
        ),
        (
            "docs/adr/0098-id3-secrets-and-license-material-never-enter-public-"
            "evidence.md"
        ),
        "docs/experiments/stage10b-id3-finger-sdk-preflight.md",
        "docs/algorithms/algorithm4-candidates/id3-finger-sdk.md",
        *STAGE_10B_SOURCE_FILES,
    }
)
_ALLOWED_CHANGE_PREFIXES = ("evidence/stage10b-id3-finger-sdk-preflight/",)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage10b_")
    or path
    in {
        "src/fpbench/core/id3_preflight_errors.py",
        "docs/experiments/stage10b-id3-finger-sdk-preflight.md",
        "docs/algorithms/algorithm4-candidates/id3-finger-sdk.md",
        ".github/workflows/stage10b-id3-finger-sdk-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 10B may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason Stage 8C, 8D, 8E,
#: 9A and 10A assemble theirs: this module is audited for source that names a
#: prior stage's published evidence, and a literal here would make the audit
#: refuse the file that performs it.
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
        ("evidence", "stage10a-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "f" + "lare_errors.py"),
        ("src", "fpbench", "core", "algorithm4_errors.py"),
        ("src", "fpbench", "experiments", "stage9a_"),
        ("src", "fpbench", "experiments", "stage10a_"),
        ("docs", "algorithms", "algorithm4-candidates", "afrnet.md"),
        ("docs", "algorithms", "algorithm4-candidates", "jipnet.md"),
        ("configs", ""),
        ("integrations", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 10B module may import *at all*. A qualification layer that
#: reached into an algorithm, a runtime or a derivation would be a qualification
#: whose answers could depend on what had been run.
_FORBIDDEN_IMPORT_PREFIXES = tuple(
    name
    for name in (
        "source" + "afis",
        "nb" + "is",
        "f" + "lx",
        "id3finger",
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
        "fpbench.experiments.stage10a_" + "candidate_identity",
        "fpbench.experiments.stage10a_" + "candidate_evidence",
        "fpbench.experiments.stage10a_" + "preflight",
        "fpbench.experiments.stage10a_" + "finalization",
    )
)

#: What no Stage 10B module may import **at module level**, and may import
#: inside a function. Stage 10B executes nothing, and it must stay importable on
#: a machine with no scientific stack and no vendor SDK at all — which is the
#: machine its public CI runs on.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage paths Stage 10B source may name, and it may only read
#: them. Assembled from parts for the same reason the protected list is.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            ("evidence", "stage8e-research-only-policy", "stage-8e-finalization.json")
        ),
        "/".join(("evidence", "stage10a-" + "algorithm4-candidate-preflight")),
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
        raise Stage10BFinalizationError(
            f"cannot hash required Stage 10B file {path}: {exc}"
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
        raise Stage10BFinalizationError(
            f"cannot hash Stage 10B source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage10b_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this preflight."""
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in STAGE_10B_SOURCE_FILES
    }
    return stable_hash({"schema": "stage_10b_source_v1", "files": digests}, length=64)


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage10BFinalization:
    """Immutable authority for what Stage 10B established, and for what it did not.

    Two outcomes, validated differently. Under ``SELECTED`` the candidate is
    named, every gate passed, every score fact is established and Stage 10C
    opens. Under ``FAIL`` nothing is named, at least one blocker is carried,
    every unestablished fact is published as null rather than as a plausible
    default, and a candidate search opens instead. There is no third state and
    no way to write "selected pending a licence", which is the shape that would
    eventually be used.
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    predecessor_stage_10a_fingerprint: str
    stage8e_policy_fingerprint: str
    stage10b_source_fingerprint: str
    observations_fingerprint: str
    preflight_fingerprint: str

    candidate_verdict: str
    selected_candidate: str | None
    gate_count_defined: int
    gates_reached: int

    # What the qualification established, or did not.
    official_sdk_obtained: bool
    exact_sdk_identity_established: bool
    research_use_opens_execution: bool | None
    research_use_blocked: bool
    third_party_components_assessed: int
    license_activation_verified: bool
    license_workload_capacity_sufficient: bool | None
    required_models_identity_established: bool
    canonical500_input_route_resolved: bool
    single_finger_route_resolved: bool
    extraction_profile_resolved: bool
    matcher_profile_resolved: bool
    hidden_score_affecting_defaults: int
    raw_score_route_resolved: bool
    score_type: str | None
    score_range_min: int | None
    score_range_max: int | None
    score_direction: str | None
    threshold_in_raw_route: bool
    self_independent_extraction_required: bool
    pair_order_semantics_resolved: bool
    restart_determinism_verified: bool
    training_provenance_status: str
    sd300_training_overlap_found: bool

    # What the stage did not do.
    sd300_image_bytes_read: bool
    sd300_scores_read: bool
    sd300_pair_manifest_read: bool
    prior_algorithm_scores_read: bool
    production_adapter_created: bool
    benchmark_run_performed: bool
    threshold_produced: bool
    decision_profile_produced: bool
    calibration_performed: bool
    metrics_produced: bool
    third_party_bytes_added_to_git: bool
    secrets_added_to_git: bool
    license_activation_attempted_in_ci: bool
    credentials_stored_in_ci: bool
    license_bypass_attempted: bool
    stage8e_evidence_changed: bool
    stage9a_evidence_changed: bool
    stage10a_evidence_changed: bool

    # What it opens.
    opens_stage_10c: bool
    opens_candidate_search: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_10b_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "sd300_image_bytes_read",
        "sd300_scores_read",
        "sd300_pair_manifest_read",
        "prior_algorithm_scores_read",
        "production_adapter_created",
        "benchmark_run_performed",
        "threshold_produced",
        "decision_profile_produced",
        "calibration_performed",
        "metrics_produced",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "license_activation_attempted_in_ci",
        "credentials_stored_in_ci",
        "license_bypass_attempted",
        "stage8e_evidence_changed",
        "stage9a_evidence_changed",
        "stage10a_evidence_changed",
        "research_use_blocked",
        "sd300_training_overlap_found",
        "threshold_in_raw_route",
    )

    #: Every claim a ``SELECTED`` marker must establish. Listed rather than
    #: checked one by one, so that a claim added to the class is either on this
    #: list or visibly absent from it (spec, "successful outcome").
    ESTABLISHED_UNDER_SELECTION = (
        "official_sdk_obtained",
        "exact_sdk_identity_established",
        "license_activation_verified",
        "required_models_identity_established",
        "canonical500_input_route_resolved",
        "single_finger_route_resolved",
        "extraction_profile_resolved",
        "matcher_profile_resolved",
        "raw_score_route_resolved",
        "pair_order_semantics_resolved",
        "restart_determinism_verified",
        "self_independent_extraction_required",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_10B_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 10B finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome not in STAGE_10B_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(STAGE_10B_OUTCOMES)}; there is no "
                "third state and no 'selected pending a licence'"
            )
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.predecessor_stage_10a_fingerprint != (
            STAGE_10A_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 10A marker this stage "
                "follows; Stage 10A is immutable here (docs/adr/0094)"
            )
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )

        for name in (
            "predecessor_stage_10a_fingerprint",
            "stage8e_policy_fingerprint",
            "stage10b_source_fingerprint",
            "observations_fingerprint",
            "preflight_fingerprint",
            "stage_10b_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        if self.candidate_verdict not in CANDIDATE_VERDICTS:
            raise ValueError(
                f"candidate_verdict must be one of {list(CANDIDATE_VERDICTS)}"
            )

        gates = int(self.gate_count_defined)
        if gates != GATE_COUNT:
            raise ValueError(
                f"{GATE_COUNT} hard gates are defined for this candidate; a "
                "preflight with fewer would be a preflight that dropped one. "
                "This counts the gates the stage defined, not the gates the "
                "candidate reached"
            )
        object.__setattr__(self, "gate_count_defined", gates)

        reached = int(self.gates_reached)
        if not 0 <= reached <= gates:
            raise ValueError(
                f"gates_reached is {reached} and the stage defines {gates}"
            )
        object.__setattr__(self, "gates_reached", reached)

        hidden = int(self.hidden_score_affecting_defaults)
        if hidden < 0:
            raise ValueError("hidden_score_affecting_defaults is a count")
        object.__setattr__(self, "hidden_score_affecting_defaults", hidden)

        assessed = int(self.third_party_components_assessed)
        if assessed < 0:
            raise ValueError("third_party_components_assessed is a count")
        object.__setattr__(self, "third_party_components_assessed", assessed)

        for name in Stage10BFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 10B asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )

        blockers = tuple(dict(item) for item in self.blockers)
        for blocker in blockers:
            missing = sorted(
                {
                    "gate",
                    "blocker_code",
                    "affected_component",
                    "evidence",
                    "why_this_blocks_algorithm_4",
                    "how_this_would_be_lifted",
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

        if self.outcome == STAGE_10B_SELECTED_OUTCOME:
            self._validate_selected()
        else:
            self._validate_blocked()

        if self.source_tree_clean is not True:
            raise ValueError("Stage 10B evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 10B finalization requires a clean verifier tree")

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

        expected = stage_10b_finalization_fingerprint(self)
        if self.stage_10b_finalization_fingerprint != expected:
            raise ValueError(
                "stage_10b_finalization_fingerprint does not cover the marker's "
                "claims"
            )

    def _validate_selected(self) -> None:
        if self.candidate_verdict != CANDIDATE_PASS_VERDICT:
            raise ValueError(
                "a SELECTED marker carries the candidate's pass verdict"
            )
        selected = str(self.selected_candidate or "")
        if selected != CANDIDATE_ID:
            raise ValueError(
                f"a SELECTED marker names {CANDIDATE_ID!r} as the candidate it "
                "selected"
            )
        if self.gates_reached != self.gate_count_defined:
            raise ValueError(
                "a SELECTED marker reached every gate; a gate that was never "
                "reached is not a gate that passed"
            )
        for name in Stage10BFinalization.ESTABLISHED_UNDER_SELECTION:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"a SELECTED Stage 10B establishes {name}; a selection with "
                    "one of these open is the selection this stage exists to "
                    "prevent"
                )
        if self.research_use_opens_execution is not True:
            raise ValueError(
                "a SELECTED Stage 10B has a Stage 8E decision that opens "
                "execution for every component it obtained"
            )
        if self.license_workload_capacity_sufficient is not True:
            raise ValueError(
                "a SELECTED Stage 10B has a licence capacity that covers the "
                "frozen workload (docs/adr/0096)"
            )
        if self.hidden_score_affecting_defaults != 0:
            raise ValueError(
                "a SELECTED Stage 10B leaves no score-affecting default "
                "unresolved; a value nobody recorded still decides the score "
                "(docs/adr/0097)"
            )
        if (
            self.score_type != "integer"
            or self.score_range_min != 0
            or self.score_range_max != 65535
            or self.score_direction != "HIGHER_IS_MORE_SIMILAR"
        ):
            raise ValueError(
                "a SELECTED Stage 10B publishes the exact raw-score contract: "
                "one integer in 0..65535, higher meaning more similar"
            )
        if self.blockers:
            raise ValueError(
                "a SELECTED marker carries no blockers; a blocker is not a "
                "reservation to be weighed"
            )
        if self.opens_stage_10c is not True:
            raise ValueError("a SELECTED Stage 10B opens Stage 10C")
        if self.opens_candidate_search is not False:
            raise ValueError(
                "a SELECTED Stage 10B does not also open a search for another "
                "candidate"
            )

    def _validate_blocked(self) -> None:
        if self.candidate_verdict != CANDIDATE_FAIL_VERDICT:
            raise ValueError("a blocked marker carries the candidate's fail verdict")
        if self.selected_candidate is not None:
            raise ValueError(
                "a blocked marker selects nothing; the point of the outcome is "
                "that the slot stays empty"
            )
        if not self.blockers:
            raise ValueError(
                "a blocked marker names which blockers apply. A block nobody "
                "can point at is a block nobody can lift"
            )
        for name in Stage10BFinalization.ESTABLISHED_UNDER_SELECTION:
            if name == "self_independent_extraction_required":
                continue
            if getattr(self, name) is not False:
                raise ValueError(
                    f"{name} is established and the candidate is blocked; a "
                    "blocked marker publishes what was not established as not "
                    "established"
                )
        if self.self_independent_extraction_required is not True:
            raise ValueError(
                "the SELF rule is a frozen requirement rather than a finding, "
                "and it holds under either outcome (docs/adr/0070)"
            )
        if self.research_use_opens_execution is not None:
            raise ValueError(
                "no component was obtained, so Stage 8E assessed none and there "
                "is no decision to publish. A false here would read as a "
                "research-use refusal that nobody made (docs/adr/0095)"
            )
        if self.license_workload_capacity_sufficient is not None:
            raise ValueError(
                "an unresolved capacity is published as unresolved. A false "
                "would claim the quota was measured and found short"
            )
        for name in ("score_type", "score_range_min", "score_range_max", "score_direction"):
            if getattr(self, name) is not None:
                raise ValueError(
                    f"{name} is published only where the raw-score gate settled "
                    "it; what a vendor page says is an observation and lives in "
                    "the score contract document"
                )
        if self.opens_stage_10c is not False:
            raise ValueError(
                "a blocked Stage 10B opens no artifact integration; there is no "
                "artifact to integrate"
            )
        if self.opens_candidate_search is not True:
            raise ValueError(
                "a blocked Stage 10B opens a search for another candidate. "
                "Cracking, resetting a trial or working around a licence is not "
                "among the responses (docs/adr/0095)"
            )


def stage_10b_finalization_fingerprint(
    marker: Stage10BFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_10b_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_10b_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence tree holds, as POSIX paths below it, sorted.

    Recursive, although this stage's evidence is flat: a directory that appeared
    would be walked rather than ignored. Anything that is neither a directory nor
    a regular file, and anything reached through a link, is a refusal.
    """
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage10BFinalizationError(
            f"no published Stage 10B evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []

    def walk(current: Path, prefix: str) -> None:
        for path in sorted(current.iterdir()):
            relative = f"{prefix}{path.name}"
            if path.is_symlink():
                raise Stage10BFinalizationError(
                    f"published evidence may not be a link: {relative}"
                )
            if path.is_dir():
                walk(path, f"{relative}/")
                continue
            if not path.is_file():
                raise Stage10BFinalizationError(
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
        raise Stage10BFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage10BFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No upstream byte, tensor, image, score or machine path reached the evidence.

    Every published JSON document is walked as *data* — keys, not text — so a
    token inside a prose sentence does not trip it and a key buried six levels
    down does.
    """
    from fpbench.core.serialization import read_json

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise Stage10BFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage10BFinalizationError(
                f"published evidence {path.name} carries forbidden data: {found}"
            )


def require_no_sensitive_published_data(repository_root: Path) -> None:
    """No credential reached the evidence, by key or by value shape.

    Applied to the published bytes rather than to the objects the engine built,
    because the two can differ: a document written by hand, an edit made after
    derivation, or a README paragraph that quoted a key would all pass an
    in-memory check and fail here (docs/adr/0098).

    Raises:
        SensitiveEvidenceError: something shaped like licence material is
            present.
    """
    from fpbench.experiments.stage10b_preflight import find_sensitive_material

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Stage10BFinalizationError(
                    f"published evidence {path.name} is not readable JSON: {exc}"
                ) from exc
            findings = find_sensitive_material(payload)
        else:
            try:
                findings = find_sensitive_material(path.read_text(encoding="utf-8"))
            except OSError as exc:  # pragma: no cover - unreadable published file
                raise Stage10BFinalizationError(
                    f"cannot read published evidence {path.name}: {exc}"
                ) from exc
        if findings:
            raise SensitiveEvidenceError(
                f"published evidence {path.name} carries licence material: "
                f"{list(findings)}"
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
        raise Stage10BFinalizationError(
            f"cannot audit Stage 10B workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage10BFinalizationError(
            "cannot audit Stage 10B workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage10b_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return path.startswith("tests/") and path.endswith(".py") and "stage10b" in name


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage10b_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage10b_test(path)


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
    """Stage 10B's modules import no algorithm, no runtime and no closed stage."""
    for relative in STAGE_10B_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage10BFinalizationError(
                f"cannot audit Stage 10B source boundary {relative}: {exc}"
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
            raise Stage10BFinalizationError(
                f"{relative}: Stage 10B imports an algorithm, a vendor runtime, "
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
            raise Stage10BFinalizationError(
                f"{relative}: Stage 10B imports {eager} at module level. This "
                "stage executes nothing, and it has to stay importable on a "
                "machine with no scientific stack and no vendor SDK"
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
            raise Stage10BFinalizationError(
                f"{relative}: Stage 10B source names published evidence it is "
                f"not entitled to read: {literal!r}"
            )


def _stage_10b_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 10B's own commits changed, across its span.

    Commit by commit rather than endpoint to endpoint, so that a repair to an
    earlier stage that happened to land in the middle of this span is attributed
    to whoever made it (docs/adr/0067).
    """
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_10B_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_10B_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage10BFinalizationError(
            f"Stage 10B's span contains merge commits, which it cannot "
            f"attribute: {merges}"
        )
    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_10B_COMMITS_IN_SPAN:
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


def verify_stage10b_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 10B changed only its own surface, over its own span.

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
        raise Stage10BFinalizationError(
            f"cannot resolve Stage 10B repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage10BFinalizationError(
            "the Stage 10B boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_10B_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_10b_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage10BFinalizationError(
            f"Stage 10B changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage10BFinalizationError(
            f"paths outside Stage 10B changed during Stage 10B: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage10BFinalizationError(
            f"Stage 10B material exists outside its publication: {unpublished}"
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


def write_stage10b_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The thirteen derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, including the hand-written
    README, so it has to come after them. That is the same two-commit shape
    Stage 8D, Stage 8E, Stage 9A and Stage 10A published under: the documents in
    one commit, the marker in the next, against a clean tree.

    Raises:
        Stage10BFinalizationError: the marker was asked for and the tree is not
            clean apart from the marker being written.
    """
    from fpbench.experiments import stage10b_id3_observations as observed
    from fpbench.experiments import stage10b_preflight as engine

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)
    predecessor = engine.require_stage10a_is_the_closed_predecessor(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    preflight = engine.run_preflight()

    written: list[Path] = []
    for name in REQUIRED_EVIDENCE_FILES:
        if name in (README_NAME, STAGE_10B_FINALIZATION_NAME):
            continue
        written.append(
            write_evidence_json(
                directory / name, engine.evidence_document(preflight, name)
            )
        )
    if not include_marker:
        return tuple(written)

    require_expected_evidence_files(
        tuple(
            name
            for name in published_evidence_names(repository_root)
            if name != STAGE_10B_FINALIZATION_NAME
        )
        + (STAGE_10B_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)
    require_no_sensitive_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_10B_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage10BFinalizationError(
            "the Stage 10B marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage10b_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = engine.require_no_id3_bytes_in_git(repository_root)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_10B_FINALIZATION_NAME
    )
    passed = preflight.passed
    hidden_defaults = sum(
        1
        for item in (
            *observed.PUBLISHED_MATCHER_OPTIONS,
            *observed.PUBLISHED_EXTRACTOR_OPTIONS,
        )
        if item.is_score_affecting and item.documented_default is None
    )
    claims: dict[str, Any] = {
        "schema_version": STAGE_10B_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": preflight.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "predecessor_stage_10a_fingerprint": predecessor,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage10b_source_fingerprint": stage10b_source_fingerprint(repository_root),
        "observations_fingerprint": observed.observations_fingerprint(),
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "candidate_verdict": preflight.verdict,
        "selected_candidate": preflight.selected_candidate,
        "gate_count_defined": GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "official_sdk_obtained": passed,
        "exact_sdk_identity_established": passed,
        "research_use_opens_execution": True if passed else None,
        "research_use_blocked": False,
        "third_party_components_assessed": 0,
        "license_activation_verified": passed,
        "license_workload_capacity_sufficient": True if passed else None,
        "required_models_identity_established": passed,
        "canonical500_input_route_resolved": passed,
        "single_finger_route_resolved": passed,
        "extraction_profile_resolved": passed,
        "matcher_profile_resolved": passed,
        "hidden_score_affecting_defaults": 0 if passed else hidden_defaults,
        "raw_score_route_resolved": passed,
        "score_type": "integer" if passed else None,
        "score_range_min": 0 if passed else None,
        "score_range_max": 65535 if passed else None,
        "score_direction": "HIGHER_IS_MORE_SIMILAR" if passed else None,
        "threshold_in_raw_route": False,
        "self_independent_extraction_required": True,
        "pair_order_semantics_resolved": passed,
        "restart_determinism_verified": passed,
        "training_provenance_status": (
            "PROPRIETARY_UNDISCLOSED" if passed else "NOT_REACHED"
        ),
        "sd300_training_overlap_found": False,
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "sd300_pair_manifest_read": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "benchmark_run_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "third_party_bytes_added_to_git": bool(byte_audit.findings),
        "secrets_added_to_git": False,
        "license_activation_attempted_in_ci": False,
        "credentials_stored_in_ci": False,
        "license_bypass_attempted": False,
        "stage8e_evidence_changed": False,
        "stage9a_evidence_changed": False,
        "stage10a_evidence_changed": False,
        "opens_stage_10c": passed,
        "opens_candidate_search": not passed,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "evidence_content_hashes": {
            name: file_sha256(directory / PurePosixPath(name)) for name in hashed
        },
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }
    marker = Stage10BFinalization(
        **claims,
        stage_10b_finalization_fingerprint=stage_10b_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(write_evidence_json(directory / STAGE_10B_FINALIZATION_NAME, marker))
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage10b_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the
    marker too and refuses a dirty tree. ``status`` derives everything and prints
    the outcome, the gate list and the blockers without writing anything, which
    is what a reviewer runs before deciding whether to commit.
    """
    from fpbench.experiments import stage10b_id3_identity as ids
    from fpbench.experiments import stage10b_id3_observations as observed
    from fpbench.experiments import stage10b_preflight as engine

    parser = argparse.ArgumentParser(description="Stage 10B evidence")
    parser.add_argument(
        "action", choices=("status", "documents", "publish"), nargs="?", default="status"
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        preflight = engine.run_preflight()
        print(f"algorithm slot           {ALGORITHM_SLOT}")
        print(f"candidate                {CANDIDATE_ID}")
        print(f"outcome                  {preflight.outcome}")
        print(f"verdict                  {preflight.verdict}")
        print(f"selected candidate       {preflight.selected_candidate}")
        print(f"observations             {observed.observations_fingerprint()}")
        print(f"preflight                {preflight.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        for index, result in enumerate(preflight.results, start=1):
            print(f"{index:>2}  {result.gate.value:<{width}}  {result.status.value}")
        if preflight.blockers:
            print(f"blockers                 {len(preflight.blockers)}")
            for blocker in preflight.blockers:
                print(f"  {blocker.gate.value:<20s} {blocker.blocker_code.value}")
        return 0

    written = write_stage10b_evidence(root, include_marker=arguments.action == "publish")
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
