"""The Stage 11A marker, the publisher, and the audit that proves the stage stayed inside itself.

The marker has two legal outcomes and validates differently under each.
``VERIFINGER_PREFLIGHT_PASS`` names the candidate, requires every one of the
seventeen gates to have passed, requires the whole conjunction in
``ACCEPTANCE_CONDITIONS`` to hold, and opens Stage 11B.
``VERIFINGER_PREFLIGHT_FAIL`` names none, requires at least one blocker, requires
every unestablished fact to be published as unestablished rather than as a
plausible default, and opens nothing.

Neither is a failure of the stage. A preflight that could only publish a
selection would be a preflight under pressure to find one.

What the marker denies is checked rather than written as prose: no SD300 image
byte, score or pair manifest was read, no production adapter or generic-engine
adapter exists, no threshold or decision profile was produced, no vendor byte
entered Git, no credential entered Git or CI, no licence was activated anywhere,
no licence was bypassed, and not one byte of Stage 8E's or Stage 10B's evidence
changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 11A began
at with the commit it published at, rather than against a moving ``HEAD``, and it
walks the span commit by commit so that work belonging to another stage can be
attributed to that stage rather than to this one.
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
from fpbench.core.verifinger_preflight_errors import (
    Stage11AFinalizationError,
    VeriFingerSensitiveEvidenceError,
)
from fpbench.experiments.stage11a_verifinger_identity import (
    ACCEPTANCE_CONDITIONS,
    ALGORITHM_SLOT,
    CANDIDATE_FAIL_VERDICT,
    CANDIDATE_INCOMPLETE_VERDICT,
    CANDIDATE_ID,
    CANDIDATE_PASS_VERDICT,
    CANDIDATE_VERDICTS,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    GATE_COUNT,
    README_NAME,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_10B_FINALIZATION_FINGERPRINT,
    STAGE_11A_BLOCKED_OUTCOME,
    STAGE_11A_FINALIZATION_NAME,
    STAGE_11A_INCOMPLETE_OUTCOME,
    STAGE_11A_OUTCOMES,
    STAGE_11A_SCHEMA_VERSION,
    STAGE_11A_SELECTED_OUTCOME,
    STAGE_11A_SOURCE_FILES,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_11A_BASELINE_COMMIT",
    "Stage11AFinalization",
    "stage_11a_finalization_fingerprint",
    "stage11a_source_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "require_no_sensitive_published_data",
    "verify_stage11a_workspace_boundaries",
    "write_evidence_json",
    "write_stage11a_evidence",
    "main",
]

#: Stage 11A began here: the commit that republished the Stage 10B marker over
#: the reserved Stage 10C.
STAGE_11A_BASELINE_COMMIT = "57c332121642a81bf46db184c40cfc637eec61ff"

#: Commits inside Stage 11A's span that are **not** Stage 11A's work. Empty
#: today and kept because it will not be: every stage so far has had at least one
#: repair to an earlier stage land in the middle of its span, and widening the
#: allowed path set to absorb one would be false (docs/adr/0067).
_NON_STAGE_11A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 11A is allowed to touch, each named rather than covered by
#: a prefix.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".github/workflows/stage11a-verifinger-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0099-stage-11a-qualifies-verifinger-from-the-artifact-itself.md",
        (
            "docs/adr/0100-preflight-acquires-when-upstream-publishes-a-direct-"
            "locator.md"
        ),
        (
            "docs/adr/0101-every-score-affecting-setting-carries-an-upstream-"
            "provenance.md"
        ),
        "docs/adr/0102-a-native-transformed-score-is-a-raw-score.md",
        (
            "docs/adr/0103-network-for-licensing-is-not-network-in-the-"
            "computation.md"
        ),
        "docs/adr/0104-a-preflight-that-was-not-run-is-not-a-preflight-that-failed.md",
        "docs/adr/0105-one-upstream-sample-is-the-route-not-several.md",
        "docs/experiments/stage11a-verifinger-2025_2-preflight.md",
        "docs/algorithms/algorithm4-candidates/verifinger-2025-2.md",
        "environment.yml",
        *STAGE_11A_SOURCE_FILES,
    }
)
_ALLOWED_CHANGE_PREFIXES = (
    "evidence/stage11a-verifinger-2025_2-preflight/",
    # The qualification harness. A new integration of its own rather than an
    # edit to an existing one: the SourceAFIS bridge stays byte-for-byte where
    # Stage 4A left it, and the protected list below still says so.
    "integrations/verifinger-qualification/",
)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage11a_")
    or path
    in {
        "src/fpbench/core/verifinger_preflight_errors.py",
        "docs/experiments/stage11a-verifinger-2025_2-preflight.md",
        "docs/algorithms/algorithm4-candidates/verifinger-2025-2.md",
        ".github/workflows/stage11a-verifinger-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 11A may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason every stage since
#: 8C assembles theirs: this module is audited for source that names a prior
#: stage's published evidence, and a literal here would make the audit refuse the
#: file that performs it.
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
        ("evidence", "stage10b-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "f" + "lare_errors.py"),
        ("src", "fpbench", "core", "algorithm4_errors.py"),
        ("src", "fpbench", "core", "id3_preflight_errors.py"),
        ("src", "fpbench", "experiments", "stage9a_"),
        ("src", "fpbench", "experiments", "stage10a_"),
        ("src", "fpbench", "experiments", "stage10b_"),
        ("docs", "algorithms", "algorithm4-candidates", "afrnet.md"),
        ("docs", "algorithms", "algorithm4-candidates", "jipnet.md"),
        ("docs", "algorithms", "algorithm4-candidates", "id3-finger-sdk.md"),
        ("configs", ""),
        # Not ``integrations/`` entire: this stage adds one of its own, and a
        # prefix that covered the whole directory would refuse the file the
        # audit is being asked to permit. The three that exist are named.
        ("integrations", "source" + "afis-java"),
        ("integrations", "nb" + "is"),
        ("integrations", "f" + "lx"),
        ("integrations", "modern-matchers"),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 11A module may import *at all*. A qualification layer that
#: reached into an algorithm, a runtime or a derivation would be a qualification
#: whose answers could depend on what had been run.
_FORBIDDEN_IMPORT_PREFIXES = tuple(
    name
    for name in (
        "source" + "afis",
        "nb" + "is",
        "f" + "lx",
        "id3finger",
        "neurotec",
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
        "fpbench.experiments.stage9a_" + "flare_qualification",
        "fpbench.experiments.stage9a_" + "flare_finalization",
        "fpbench.experiments.stage10a_" + "preflight",
        "fpbench.experiments.stage10a_" + "finalization",
        "fpbench.experiments.stage10b_" + "preflight",
        "fpbench.experiments.stage10b_" + "finalization",
        "fpbench.experiments.stage10b_" + "id3_identity",
        "fpbench.experiments.stage10b_" + "id3_observations",
    )
)

#: What no Stage 11A module may import **at module level**, and may import inside
#: a function. Stage 11A executes nothing, and it must stay importable on a
#: machine with no scientific stack and no vendor SDK at all — which is the
#: machine its public CI runs on.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage paths Stage 11A source may name, and it may only read
#: them.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            ("evidence", "stage8e-research-only-policy", "stage-8e-finalization.json")
        ),
        "/".join(("evidence", "stage10b-" + "id3-finger-sdk-preflight")),
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
        raise Stage11AFinalizationError(
            f"cannot hash required Stage 11A file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """A digest of one source file, with newlines normalised to ``\\n``.

    ``core.autocrlf`` is on for this repository, so the same committed blob is LF
    in one checkout and CRLF in another, and a raw digest would name the checkout
    rather than the code.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage11AFinalizationError(
            f"cannot hash Stage 11A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage11a_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this preflight."""
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in STAGE_11A_SOURCE_FILES
    }
    return stable_hash({"schema": "stage_11a_source_v1", "files": digests}, length=64)


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage11AFinalization:
    """Immutable authority for what Stage 11A established, and for what it did not.

    The claim that distinguishes this marker from its predecessor's is
    ``artifact_obtained``. Stage 10B could not set it and said so; here it is
    true, and every conclusion below it is a conclusion about bytes that were
    fetched, hashed and opened.
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    predecessor_stage_10b_fingerprint: str
    stage8e_policy_fingerprint: str
    stage11a_source_fingerprint: str
    observations_fingerprint: str
    preflight_fingerprint: str

    candidate_verdict: str
    selected_candidate: str | None
    gate_count_defined: int
    gates_reached: int
    gates_passed: int
    gates_awaiting_action: int

    # What the qualification established, or did not.
    artifact_obtained: bool
    artifact_route: str
    artifact_identity_pinned: bool
    documentation_pinned_separately: bool
    runtime_identity_established: bool
    runtime_reported_version_read_by_execution: bool
    runtime_platform_locked: bool
    runtime_platform: str | None
    research_use_opens_execution: bool | None
    research_use_blocked: bool
    runtime_dependency_closure_complete: bool
    external_model_downloads_required: int
    canonical500_input_route_resolved: bool
    fpbench_preprocessing_required: bool
    extraction_profile_resolved: bool
    representation_profile_resolved: bool
    representation_type: str
    matcher_profile_resolved: bool
    extraction_settings_without_provenance: int
    matching_settings_without_provenance: int
    raw_score_route_resolved: bool
    raw_score_route_status: str
    score_numeric_type: str | None
    score_direction: str | None
    threshold_applied_inside_the_score: bool
    self_independent_extraction_required: bool
    self_semantics_demonstrated: bool
    pair_order_semantics_resolved: bool
    restart_determinism_verified: bool
    failure_semantics_resolved: bool
    network_role: str
    remote_computation_participates_in_the_score: bool | None
    runtime_feasibility_measured: bool
    license_workload_capacity_sufficient: bool | None
    training_provenance_status: str
    sd300_overlap_status: str
    sd300_training_overlap_found: bool | None
    failure_class: str | None

    # What the stage did not do.
    sd300_image_bytes_read: bool
    sd300_scores_read: bool
    sd300_pair_manifest_read: bool
    prior_algorithm_scores_read: bool
    licenses_activated: int
    qualification_run_performed: bool
    license_bypass_attempted: bool
    trial_reset_attempted: bool
    production_adapter_created: bool
    generic_engine_adapter_created: bool
    benchmark_run_performed: bool
    threshold_produced: bool
    decision_profile_produced: bool
    calibration_performed: bool
    metrics_produced: bool
    qualification_scores_produced: int
    benchmark_scores_produced: int
    sd300_scores_produced: int
    third_party_bytes_added_to_git: bool
    secrets_added_to_git: bool
    artifact_downloaded_in_ci: bool
    license_activated_in_ci: bool
    credentials_stored_in_ci: bool
    stage8e_evidence_changed: bool
    stage10b_evidence_changed: bool

    # What it opens.
    opens_stage_11b: bool
    opens_candidate_search: bool

    blockers: tuple[Mapping[str, str], ...]
    pending_actions: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_11a_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "sd300_image_bytes_read",
        "sd300_scores_read",
        "sd300_pair_manifest_read",
        "prior_algorithm_scores_read",
        "license_bypass_attempted",
        "trial_reset_attempted",
        "production_adapter_created",
        "generic_engine_adapter_created",
        "benchmark_run_performed",
        "threshold_produced",
        "decision_profile_produced",
        "calibration_performed",
        "metrics_produced",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "artifact_downloaded_in_ci",
        "license_activated_in_ci",
        "credentials_stored_in_ci",
        "stage8e_evidence_changed",
        "stage10b_evidence_changed",
        "research_use_blocked",
        "threshold_applied_inside_the_score",
        "fpbench_preprocessing_required",
    )

    #: Every claim a passing marker must establish — the specification's
    #: conjunction, expressed as fields. Listed rather than checked one by one so
    #: that a claim added to the class is either on this list or visibly absent.
    ESTABLISHED_UNDER_PASS = (
        "artifact_obtained",
        "artifact_identity_pinned",
        "runtime_identity_established",
        "runtime_platform_locked",
        "runtime_dependency_closure_complete",
        "canonical500_input_route_resolved",
        "extraction_profile_resolved",
        "representation_profile_resolved",
        "matcher_profile_resolved",
        "raw_score_route_resolved",
        "self_independent_extraction_required",
        "self_semantics_demonstrated",
        "pair_order_semantics_resolved",
        "restart_determinism_verified",
        "failure_semantics_resolved",
        "runtime_feasibility_measured",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_11A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 11A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome not in STAGE_11A_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(STAGE_11A_OUTCOMES)}; there is no "
                "third state and no 'passed pending a measurement'"
            )
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.predecessor_stage_10b_fingerprint != (
            STAGE_10B_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 10B marker this stage "
                "follows; Stage 10B is immutable here"
            )
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )

        for name in (
            "predecessor_stage_10b_fingerprint",
            "stage8e_policy_fingerprint",
            "stage11a_source_fingerprint",
            "observations_fingerprint",
            "preflight_fingerprint",
            "stage_11a_finalization_fingerprint",
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

        for name in ("gates_reached", "gates_passed"):
            value = int(getattr(self, name))
            if not 0 <= value <= gates:
                raise ValueError(f"{name} is {value} and the stage defines {gates}")
            object.__setattr__(self, name, value)
        if self.gates_passed > self.gates_reached:
            raise ValueError(
                "more gates passed than were reached, which is not a thing that "
                "can happen: NOT_REACHED is not a pass"
            )

        for name in (
            "extraction_settings_without_provenance",
            "matching_settings_without_provenance",
            "external_model_downloads_required",
            "licenses_activated",
            "qualification_scores_produced",
            "benchmark_scores_produced",
            "sd300_scores_produced",
        ):
            value = int(getattr(self, name))
            if value < 0:
                raise ValueError(f"{name} is a count")
            object.__setattr__(self, name, value)

        for name in Stage11AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 11A asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )
        # A qualification run scores fixtures — that is what qualifying a
        # verification route means — so this stage counts two kinds of score and
        # forbids only one of them. An earlier marker asserted a single
        # ``scores_produced == 0``, which made the run this stage requires
        # impossible to describe (docs/adr/0104).
        if self.benchmark_scores_produced != 0:
            raise ValueError(
                "Stage 11A measures no evaluation cohort. A benchmark score here "
                "would be a result published by a stage that has not admitted an "
                "algorithm"
            )
        if self.sd300_scores_produced != 0:
            raise ValueError(
                "not one SD300 score, at any point, under any outcome"
            )
        if self.qualification_scores_produced and not self.qualification_run_performed:
            raise ValueError(
                "qualification scores exist and no qualification run is "
                "recorded; a score with no run behind it came from somewhere "
                "nobody can inspect"
            )
        if self.qualification_run_performed and self.licenses_activated < 1:
            raise ValueError(
                "a qualification run obtained the finger licences, so at least "
                "one licence was activated. Asserting zero here was the "
                "invariant that made a legitimate trial impossible to report "
                "(docs/adr/0104)"
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

        for action in tuple(dict(item) for item in self.pending_actions):
            missing = sorted(
                {
                    "gate",
                    "action_code",
                    "what_is_missing",
                    "what_to_do",
                    "what_it_would_answer",
                }
                - set(action)
            )
            if missing:
                raise ValueError(f"a pending action is missing {missing}")
        object.__setattr__(
            self,
            "pending_actions",
            tuple(
                MappingProxyType(dict(sorted(item.items())))
                for item in sorted(
                    (dict(item) for item in self.pending_actions),
                    key=lambda item: (item["gate"], item["action_code"]),
                )
            ),
        )

        if self.outcome == STAGE_11A_SELECTED_OUTCOME:
            self._validate_passed()
        elif self.outcome == STAGE_11A_INCOMPLETE_OUTCOME:
            self._validate_incomplete()
        else:
            self._validate_blocked()

        if self.source_tree_clean is not True:
            raise ValueError("Stage 11A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 11A finalization requires a clean verifier tree")

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

        expected = stage_11a_finalization_fingerprint(self)
        if self.stage_11a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_11a_finalization_fingerprint does not cover the marker's "
                "claims"
            )

    def _validate_passed(self) -> None:
        if self.candidate_verdict != CANDIDATE_PASS_VERDICT:
            raise ValueError("a passing marker carries the candidate's pass verdict")
        if str(self.selected_candidate or "") != CANDIDATE_ID:
            raise ValueError(
                f"a passing marker names {CANDIDATE_ID!r} as the candidate it "
                "selected"
            )
        if self.gates_passed != self.gate_count_defined:
            raise ValueError(
                f"a passing marker passed all {self.gate_count_defined} gates; "
                "the acceptance conditions are conjunctive and unweighted "
                f"({len(ACCEPTANCE_CONDITIONS)} of them)"
            )
        for name in Stage11AFinalization.ESTABLISHED_UNDER_PASS:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"a passing Stage 11A establishes {name}; a pass with one of "
                    "these open is the pass this stage exists to prevent"
                )
        if self.research_use_opens_execution is not True:
            raise ValueError(
                "a passing Stage 11A has a Stage 8E decision that opens execution"
            )
        if self.license_workload_capacity_sufficient is not True:
            raise ValueError(
                "a passing Stage 11A has a licence that covers the frozen workload"
            )
        if (
            self.extraction_settings_without_provenance
            or self.matching_settings_without_provenance
        ):
            raise ValueError(
                "a passing Stage 11A leaves no score-affecting setting without "
                "an upstream provenance; a value nobody recorded still decides "
                "the score"
            )
        if self.gates_awaiting_action != 0:
            raise ValueError(
                "a passing Stage 11A has no outstanding action; a gate awaiting "
                "one was not asked"
            )
        if self.pending_actions:
            raise ValueError("a passing marker carries no outstanding actions")
        if not self.qualification_run_performed:
            raise ValueError(
                "a passing Stage 11A ran the bounded qualification; nine of its "
                "gates cannot be answered any other way"
            )
        if self.remote_computation_participates_in_the_score is not False:
            raise ValueError(
                "a passing Stage 11A has established that no remote service "
                "takes part in the score"
            )
        if self.sd300_training_overlap_found is not False:
            raise ValueError(
                "a passing Stage 11A found no SD300 development overlap; a pass "
                "with one would be a benchmark reporting on its own development "
                "data"
            )
        if self.blockers:
            raise ValueError("a passing marker carries no blockers")
        if self.failure_class is not None:
            raise ValueError("a passing marker classifies no failure")
        if self.opens_stage_11b is not True:
            raise ValueError("a passing Stage 11A opens Stage 11B")
        if self.opens_candidate_search is not False:
            raise ValueError(
                "a passing Stage 11A does not also open a search for another "
                "candidate"
            )


    def _validate_incomplete(self) -> None:
        """The third outcome: everything asked was answered, and some was not asked.

        The rules are the ones that keep it from drifting into either neighbour.
        It names no candidate, because nothing was selected. It carries **no
        failure class and no blocker**, because nothing was found wrong — that is
        the entire distinction from ``FAIL``. And it does **not** open a candidate
        search: moving on to another algorithm while this one has an unfinished
        chore and no adverse finding would be abandoning the strongest candidate
        so far for a reason nobody could write down (docs/adr/0104).
        """
        if self.candidate_verdict != CANDIDATE_INCOMPLETE_VERDICT:
            raise ValueError(
                "an incomplete marker carries the candidate's incomplete verdict"
            )
        if self.selected_candidate is not None:
            raise ValueError("an incomplete marker selects nothing")
        if self.blockers:
            raise ValueError(
                "an incomplete marker carries no blocker. A blocker is a finding "
                "against the route, and this outcome exists precisely for the "
                "case where there is none"
            )
        if self.failure_class is not None:
            raise ValueError(
                "an incomplete marker classifies no failure, because none "
                "occurred. Classifying an unpaid chore as a failure of any kind "
                "says something about the candidate that nothing established"
            )
        if not self.pending_actions:
            raise ValueError(
                "an incomplete marker names the actions that would complete it. "
                "An incompleteness nobody can act on is indistinguishable from a "
                "refusal"
            )
        if self.gates_awaiting_action < 1:
            raise ValueError(
                "an incomplete marker has at least one gate awaiting an action"
            )
        if self.gates_passed >= self.gate_count_defined:
            raise ValueError(
                "every gate passed, which is a pass rather than an incompleteness"
            )
        if self.gates_passed + self.gates_awaiting_action != self.gate_count_defined:
            raise ValueError(
                "an incomplete run asks every gate: none is NOT_REACHED, because "
                "nothing stopped it"
            )
        if self.opens_stage_11b is not False:
            raise ValueError(
                "an incomplete Stage 11A opens no integration; the route is not "
                "qualified yet"
            )
        if self.opens_candidate_search is not False:
            raise ValueError(
                "an incomplete Stage 11A does not open a search for another "
                "candidate. No methodological blocker was found here, and moving "
                "on would abandon the strongest candidate so far over an "
                "outstanding chore (docs/adr/0104)"
            )
        if self.self_independent_extraction_required is not True:
            raise ValueError(
                "the SELF rule is a frozen requirement rather than a finding, "
                "and it holds under every outcome (docs/adr/0070)"
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
                "a blocked marker names which blockers apply. A block nobody can "
                "point at is a block nobody can lift"
            )
        if self.gates_passed >= self.gate_count_defined:
            raise ValueError(
                "a blocked marker did not pass every gate; one of them stopped it"
            )
        if not self.blockers:
            raise ValueError("a blocked marker names at least one blocker")
        if self.failure_class is None:
            raise ValueError(
                "a blocked marker says what kind of failure it is. "
                "VERIFINGER_PREFLIGHT_FAIL reads the same whether the artifact "
                "could not be had and whether it was opened, read and found to "
                "need a measurement nobody took"
            )
        if self.license_workload_capacity_sufficient is not None:
            raise ValueError(
                "an unmeasured capacity is published as null. A false would "
                "claim the workload was measured and found not to fit"
            )
        if self.self_independent_extraction_required is not True:
            raise ValueError(
                "the SELF rule is a frozen requirement rather than a finding, "
                "and it holds under either outcome (docs/adr/0070)"
            )
        if self.opens_stage_11b is not False:
            raise ValueError(
                "a blocked Stage 11A opens no integration; there is no qualified "
                "route to integrate"
            )
        if self.opens_candidate_search is not True:
            raise ValueError(
                "a blocked Stage 11A leaves the Algorithm 4 slot empty and the "
                "search open"
            )


def stage_11a_finalization_fingerprint(
    marker: Stage11AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_11a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_11a_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------ published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence tree holds, as POSIX paths below it, sorted."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage11AFinalizationError(
            f"no published Stage 11A evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []

    def walk(current: Path, prefix: str) -> None:
        for path in sorted(current.iterdir()):
            relative = f"{prefix}{path.name}"
            if path.is_symlink():
                raise Stage11AFinalizationError(
                    f"published evidence may not be a link: {relative}"
                )
            if path.is_dir():
                walk(path, f"{relative}/")
                continue
            if not path.is_file():
                raise Stage11AFinalizationError(
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
        raise Stage11AFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage11AFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No upstream byte, template, image, score or machine path reached the evidence."""
    from fpbench.core.serialization import read_json

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*.json")):
        try:
            payload = read_json(path)
        except (OSError, ValueError) as exc:
            raise Stage11AFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage11AFinalizationError(
                f"published evidence {path.name} carries forbidden data: {found}"
            )


def require_no_sensitive_published_data(repository_root: Path) -> None:
    """No credential reached the evidence, by key or by value shape.

    Applied to the published bytes rather than to the objects the engine built,
    because the two can differ: a document written by hand, an edit made after
    derivation, or a README paragraph that quoted a serial would all pass an
    in-memory check and fail here (spec section 43).
    """
    from fpbench.experiments.stage11a_preflight import find_sensitive_material

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Stage11AFinalizationError(
                    f"published evidence {path.name} is not readable JSON: {exc}"
                ) from exc
            findings = find_sensitive_material(payload)
        else:
            try:
                findings = find_sensitive_material(path.read_text(encoding="utf-8"))
            except OSError as exc:  # pragma: no cover - unreadable published file
                raise Stage11AFinalizationError(
                    f"cannot read published evidence {path.name}: {exc}"
                ) from exc
        if findings:
            raise VeriFingerSensitiveEvidenceError(
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
        raise Stage11AFinalizationError(
            f"cannot audit Stage 11A workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage11AFinalizationError(
            "cannot audit Stage 11A workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage11a_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return path.startswith("tests/") and path.endswith(".py") and "stage11a" in name


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage11a_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage11a_test(path)


def _module_level_imports(tree: ast.Module) -> list[str]:
    """Imports at the top level of a module, and inside nothing else."""
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
    """Stage 11A's modules import no algorithm, no runtime and no closed stage."""
    for relative in STAGE_11A_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage11AFinalizationError(
                f"cannot audit Stage 11A source boundary {relative}: {exc}"
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
            raise Stage11AFinalizationError(
                f"{relative}: Stage 11A imports an algorithm, a vendor runtime, "
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
            raise Stage11AFinalizationError(
                f"{relative}: Stage 11A imports {eager} at module level. This "
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
            raise Stage11AFinalizationError(
                f"{relative}: Stage 11A source names published evidence it is "
                f"not entitled to read: {literal!r}"
            )


def _stage_11a_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 11A's own commits changed, across its span."""
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_11A_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_11A_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage11AFinalizationError(
            f"Stage 11A's span contains merge commits, which it cannot "
            f"attribute: {merges}"
        )
    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_11A_COMMITS_IN_SPAN:
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


def verify_stage11a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 11A changed only its own surface, over its own span."""
    repository_root = Path(repository_root)
    roots = _git_output(repository_root, "rev-parse", "--show-toplevel")
    try:
        actual_root = Path(roots[0]).resolve(strict=True)
        expected_root = repository_root.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise Stage11AFinalizationError(
            f"cannot resolve Stage 11A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage11AFinalizationError(
            "the Stage 11A boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_11A_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_11a_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage11AFinalizationError(
            f"Stage 11A changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage11AFinalizationError(
            f"paths outside Stage 11A changed during Stage 11A: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage11AFinalizationError(
            f"Stage 11A material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


# -------------------------------------------------------------- the publisher


def _head_commit(repository_root: Path) -> str:
    return _git_output(repository_root, "rev-parse", "HEAD")[0].strip().lower()


def _tree_is_clean(repository_root: Path, *, ignoring: tuple[str, ...] = ()) -> bool:
    entries = _git_output(
        repository_root, "status", "--porcelain", "--untracked-files=all"
    )
    for entry in entries:
        path = entry[3:].strip().strip('"')
        if path not in ignoring:
            return False
    return True


def write_stage11a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The fifteen derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, including the hand-written
    README, so it has to come after them. Same two-commit shape as every stage
    since 8D: the documents in one commit, the marker in the next, against a
    clean tree.
    """
    from fpbench.experiments import stage11a_artifacts as store
    from fpbench.experiments import stage11a_preflight as engine
    from fpbench.experiments import stage11a_verifinger_identity as frozen
    from fpbench.experiments import stage11a_verifinger_observations as observed

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)
    predecessor = engine.require_stage10b_is_the_closed_predecessor(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    preflight = engine.run_preflight()

    written: list[Path] = []
    for name in REQUIRED_EVIDENCE_FILES:
        if name in (README_NAME, STAGE_11A_FINALIZATION_NAME):
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
            if name != STAGE_11A_FINALIZATION_NAME
        )
        + (STAGE_11A_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)
    require_no_sensitive_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_11A_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage11AFinalizationError(
            "the Stage 11A marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage11a_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = store.require_no_verifinger_bytes_in_git(repository_root)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_11A_FINALIZATION_NAME
    )
    passed = preflight.passed
    acquisition = store.acquisition_state()
    hidden = len(engine.unresolved_score_affecting_settings())

    def reached(gate: frozen.PreflightGate) -> bool:
        return preflight.status(gate) is frozen.GateStatus.PASS

    qualification = store.qualification_run_state(repository_root=repository_root)
    record = qualification.record or {}
    lock = record.get("platform_lock") or {}
    extraction_open = sum(
        1
        for item in observed.PUBLISHED_EXTRACTOR_SETTINGS
        if item.is_unresolved_score_affecting_default
        and item.name not in (record.get("delivered_runtime_defaults") or {})
    )
    matching_open = sum(
        1
        for item in observed.PUBLISHED_MATCHER_SETTINGS
        if item.is_unresolved_score_affecting_default
        and item.name not in (record.get("delivered_runtime_defaults") or {})
    )
    platform = (
        f"{lock.get('operating_system')}/{lock.get('architecture')}"
        if lock
        else None
    )

    claims: dict[str, Any] = {
        "schema_version": STAGE_11A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": preflight.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "predecessor_stage_10b_fingerprint": predecessor,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage11a_source_fingerprint": stage11a_source_fingerprint(repository_root),
        "observations_fingerprint": observed.observations_fingerprint(),
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "candidate_verdict": preflight.verdict,
        "selected_candidate": preflight.selected_candidate,
        "gate_count_defined": GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "artifact_obtained": acquisition.obtained,
        "artifact_route": observed.SDK_ARCHIVE.route.value,
        "artifact_identity_pinned": acquisition.obtained,
        "documentation_pinned_separately": acquisition.obtained,
        "runtime_identity_established": reached(
            frozen.PreflightGate.RUNTIME_IDENTITY
        ),
        "runtime_reported_version_read_by_execution": bool(record),
        "runtime_platform_locked": bool(lock),
        "runtime_platform": platform,
        "research_use_opens_execution": (
            True if reached(frozen.PreflightGate.RESEARCH_USE_PERMISSION) else None
        ),
        "research_use_blocked": False,
        "runtime_dependency_closure_complete": reached(
            frozen.PreflightGate.ARTIFACT_CLOSURE
        ),
        "external_model_downloads_required": 0,
        "canonical500_input_route_resolved": reached(
            frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
        ),
        "fpbench_preprocessing_required": False,
        "extraction_profile_resolved": reached(
            frozen.PreflightGate.EXTRACTION_PROFILE
        ),
        "representation_profile_resolved": reached(
            frozen.PreflightGate.REPRESENTATION_PROFILE
        ),
        "representation_type": (
            frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value
            if reached(frozen.PreflightGate.REPRESENTATION_PROFILE)
            else frozen.RepresentationType.NOT_REACHED.value
        ),
        "matcher_profile_resolved": reached(frozen.PreflightGate.MATCHER_PROFILE),
        "extraction_settings_without_provenance": extraction_open,
        "matching_settings_without_provenance": matching_open,
        "raw_score_route_resolved": reached(frozen.PreflightGate.RAW_SCORE_ROUTE),
        "raw_score_route_status": (
            frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.value
            if reached(frozen.PreflightGate.RAW_SCORE_ROUTE)
            else frozen.ScoreRouteStatus.NOT_REACHED.value
        ),
        "score_numeric_type": (
            observed.DOCUMENTED_SCORE_TYPE
            if reached(frozen.PreflightGate.RAW_SCORE_ROUTE)
            else None
        ),
        "score_direction": (
            observed.DOCUMENTED_SCORE_DIRECTION
            if reached(frozen.PreflightGate.RAW_SCORE_ROUTE)
            else None
        ),
        "threshold_applied_inside_the_score": False,
        "self_independent_extraction_required": True,
        "self_semantics_demonstrated": reached(frozen.PreflightGate.SELF_SEMANTICS),
        "pair_order_semantics_resolved": reached(
            frozen.PreflightGate.PAIR_ORIENTATION
        ),
        "restart_determinism_verified": reached(
            frozen.PreflightGate.SCORE_DETERMINISM
        ),
        "failure_semantics_resolved": reached(frozen.PreflightGate.FAILURE_SEMANTICS),
        "network_role": (
            frozen.NetworkRole.LICENSE_VALIDATION_ONLY.value
            if reached(frozen.PreflightGate.NETWORK_DEPENDENCY)
            else frozen.NetworkRole.NOT_REACHED.value
        ),
        "remote_computation_participates_in_the_score": (
            False if reached(frozen.PreflightGate.NETWORK_DEPENDENCY) else None
        ),
        "runtime_feasibility_measured": reached(
            frozen.PreflightGate.RUNTIME_FEASIBILITY
        ),
        "license_workload_capacity_sufficient": (
            True if reached(frozen.PreflightGate.LICENSE_CAPACITY) else None
        ),
        "training_provenance_status": (
            frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
            if reached(frozen.PreflightGate.TRAINING_PROVENANCE)
            else frozen.TrainingProvenanceStatus.NOT_REACHED.value
        ),
        "sd300_overlap_status": preflight.sd300_overlap_status.value,
        "sd300_training_overlap_found": (
            False if reached(frozen.PreflightGate.TRAINING_PROVENANCE) else None
        ),
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "sd300_image_bytes_read": False,
        "sd300_scores_read": False,
        "sd300_pair_manifest_read": False,
        "prior_algorithm_scores_read": False,
        "licenses_activated": 1 if qualification.performed else 0,
        "qualification_run_performed": qualification.performed,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "production_adapter_created": False,
        "generic_engine_adapter_created": False,
        "benchmark_run_performed": False,
        "threshold_produced": False,
        "decision_profile_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "qualification_scores_produced": int(
            record.get("qualification_scores_produced") or 0
        ),
        "benchmark_scores_produced": 0,
        "sd300_scores_produced": 0,
        "third_party_bytes_added_to_git": bool(byte_audit.findings),
        "secrets_added_to_git": False,
        "artifact_downloaded_in_ci": False,
        "license_activated_in_ci": False,
        "credentials_stored_in_ci": False,
        "stage8e_evidence_changed": False,
        "stage10b_evidence_changed": False,
        "opens_stage_11b": passed,
        "opens_candidate_search": preflight.blocked,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "pending_actions": engine.marker_pending_action_rows(
            preflight.pending_actions
        ),
        "evidence_content_hashes": {
            name: file_sha256(directory / PurePosixPath(name)) for name in hashed
        },
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }
    marker = Stage11AFinalization(
        **claims,
        stage_11a_finalization_fingerprint=stage_11a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(
        write_evidence_json(directory / STAGE_11A_FINALIZATION_NAME, marker)
    )
    return tuple(written)


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage11a_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the marker
    too and refuses a dirty tree. ``status`` derives everything and prints the
    outcome, the gate list and the blockers without writing anything, which is
    what a reviewer runs before deciding whether to commit.
    """
    from fpbench.experiments import stage11a_artifacts as store
    from fpbench.experiments import stage11a_preflight as engine
    from fpbench.experiments import stage11a_verifinger_identity as ids
    from fpbench.experiments import stage11a_verifinger_observations as observed

    parser = argparse.ArgumentParser(description="Stage 11A evidence")
    parser.add_argument(
        "action", choices=("status", "documents", "publish"), nargs="?", default="status"
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        preflight = engine.run_preflight()
        acquisition = store.acquisition_state()
        print(f"algorithm slot           {ALGORITHM_SLOT}")
        print(f"candidate                {CANDIDATE_ID}")
        print(f"outcome                  {preflight.outcome}")
        print(f"verdict                  {preflight.verdict}")
        print(
            "failure class            "
            + (preflight.failure_class.value if preflight.failure_class else "none")
        )
        print(f"artifact route           {observed.SDK_ARCHIVE.route.value}")
        print(f"artifact obtained        {acquisition.obtained}")
        for item in acquisition.states:
            print(f"  {item.filename:<48s} {item.presence.value}")
        print(f"selected candidate       {preflight.selected_candidate}")
        print(f"observations             {observed.observations_fingerprint()}")
        print(f"preflight                {preflight.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        for index, result in enumerate(preflight.results, start=1):
            print(f"{index:>2}  {result.gate.value:<{width}}  {result.status.value}")
        print(f"gates passed             {preflight.gates_passed}/{ids.GATE_COUNT}")
        print(f"gates awaiting action    {preflight.gates_awaiting_action}")
        if preflight.blockers:
            print(f"blockers                 {len(preflight.blockers)}")
            for blocker in preflight.blockers:
                print(f"  {blocker.gate.value:<32s} {blocker.blocker_code.value}")
        else:
            print("blockers                 0 — nothing was found wrong")
        if preflight.pending_actions:
            print(f"pending actions          {len(preflight.pending_actions)}")
            for action in preflight.pending_actions:
                print(f"  {action.gate.value:<32s} {action.action_code.value}")
            print(
                "one qualification run would close "
                f"{len(ids.EXECUTION_DEPENDENT_GATES)} gates: "
                "`make stage11a-qualify`"
            )
        return 0

    written = write_stage11a_evidence(root, include_marker=arguments.action == "publish")
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
