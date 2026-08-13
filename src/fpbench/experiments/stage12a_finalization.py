"""The Stage 12A marker, the publisher, and the audit that keeps the stage inside itself.

The marker has two legal outcomes and validates differently under each.
``IDKIT_PREFLIGHT_PASS`` names the candidate, requires all ten gates to have
passed on a delivered package, requires every acceptance condition to hold, and
opens Stage 12B. ``IDKIT_PREFLIGHT_FAIL`` names none, requires at least one
blocker, requires every unestablished fact to be published as unestablished
rather than as a default, and opens nothing.

There is no third marker. ``IDKIT_PREFLIGHT_PENDING_ACCESS`` is a published
outcome of the *preflight* and never of a finalization: a marker is a
finalization, and there is nothing final about waiting for a vendor to reply. The
publisher refuses to write one while the run is pending, which is what stops
"pending" from quietly becoming the third state that gets used
(docs/adr/0107, docs/adr/0108).

What the marker denies is checked rather than written as prose: no SD300 image
byte, score or pair manifest was read, no prior algorithm's scores were consulted,
no production adapter exists, no threshold or metric was produced, no vendor byte
entered Git, no credential entered Git or CI, no licence was activated in CI, and
not one byte of Stage 8E's, Stage 11A's or Stage 11B's evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 12A began
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

from fpbench.core.idkit_preflight_errors import (
    IdkitSensitiveEvidenceError,
    Stage12AFinalizationError,
)
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage12a_idkit_identity import (
    ALGORITHM_SLOT,
    CANDIDATE_ID,
    DERIVABLE_EVIDENCE_FILES,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    FPBENCH_SCORE_TRANSFORMATION,
    GATE_COUNT,
    IMPLEMENTATION_ORIGIN,
    IMPLEMENTATION_VERSION_UNRESOLVED,
    PAIR_ROLE_BINDING,
    README_NAME,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_11B_FINALIZATION_FINGERPRINT,
    STAGE_12A_FAIL_OUTCOME,
    STAGE_12A_FINAL_OUTCOMES,
    STAGE_12A_FINALIZATION_NAME,
    STAGE_12A_PASS_OUTCOME,
    STAGE_12A_PENDING_OUTCOME,
    STAGE_12A_SCHEMA_VERSION,
    STAGE_12A_SOURCE_FILES,
    STAGE_FINALIZATION_KIND,
)

__all__ = [
    "STAGE_12A_BASELINE_COMMIT",
    "Stage12AFinalization",
    "stage_12a_finalization_fingerprint",
    "stage12a_source_fingerprint",
    "file_sha256",
    "source_file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "require_no_sensitive_published_data",
    "verify_stage12a_workspace_boundaries",
    "write_evidence_json",
    "write_stage12a_evidence",
    "main",
]

#: Stage 12A began here: the commit that re-closed Stage 11B over its corrected
#: evidence.
STAGE_12A_BASELINE_COMMIT = "170a303b55609ed1aa67d24531050e372c6b2592"

#: Commits inside Stage 12A's span that are **not** Stage 12A's work. Empty
#: today and kept because it will not be: every stage so far has had at least one
#: repair to an earlier stage land in the middle of its span, and widening the
#: allowed path set to absorb one would be false (docs/adr/0067).
_NON_STAGE_12A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 12A is allowed to touch, each named rather than covered by
#: a prefix. Stage 12A adds one ``core`` module of its own rather than extending
#: an existing one, and adds no package: it is a qualification, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".github/workflows/stage12a-idkit-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0107-stage-12a-preflights-idkit-before-algorithm-5-selection.md",
        "docs/adr/0108-a-pending-acquisition-is-not-a-failed-candidate.md",
        (
            "docs/adr/0109-an-asymmetric-matcher-is-bound-by-protocol-not-"
            "normalised.md"
        ),
        "docs/adr/0110-a-published-version-is-not-a-delivered-package.md",
        "docs/adr/0111-the-licence-clock-starts-after-the-harness-compiles.md",
        "docs/experiments/stage12a-idkit-preflight.md",
        "docs/algorithms/algorithm5-candidates/innovatrics-idkit.md",
        *STAGE_12A_SOURCE_FILES,
    }
)
#: Written out in full rather than assembled, unlike every other evidence path in
#: this module. The source audit permits a literal that names *this stage's own*
#: directory, and it identifies one by comparing the tail against the directory
#: name — so a split literal would leave a bare ``evidence/`` for it to refuse.
_ALLOWED_CHANGE_PREFIXES = ("evidence/stage12a-idkit-preflight/",)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage12a_")
    or path
    in {
        "src/fpbench/core/idkit_preflight_errors.py",
        "docs/experiments/stage12a-idkit-preflight.md",
        "docs/algorithms/algorithm5-candidates/innovatrics-idkit.md",
        ".github/workflows/stage12a-idkit-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 12A may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason every stage since
#: 8C assembles its own: this module is audited for source that names a prior
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
        ("evidence", "stage11a-"),
        ("evidence", "stage11b-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "verifinger_"),
        ("src", "fpbench", "core", "id3_preflight_errors.py"),
        ("src", "fpbench", "core", "algorithm4_errors.py"),
        ("src", "fpbench", "experiments", "stage10a_"),
        ("src", "fpbench", "experiments", "stage10b_"),
        ("src", "fpbench", "experiments", "stage11a_"),
        ("src", "fpbench", "experiments", "stage11b_"),
        ("src", "fpbench", "adapters", ""),
        ("configs", ""),
        ("integrations", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 12A module may import *at all*. A qualification layer that
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
        "fpbench.experiments.stage10a_" + "candidate_identity",
        "fpbench.experiments.stage10b_" + "id3_identity",
        "fpbench.experiments.stage10b_" + "preflight",
        "fpbench.experiments.stage11a_" + "verifinger_identity",
        "fpbench.experiments.stage11a_" + "preflight",
        "fpbench.experiments.stage11a_" + "qualification",
        "fpbench.experiments.stage11b_" + "identity",
        "fpbench.experiments.stage11b_" + "finalization",
    )
)

#: What no Stage 12A module may import **at module level**, and may import inside
#: a function. Stage 12A executes nothing without a package, and it must stay
#: importable on a machine with no scientific stack and no vendor SDK at all —
#: which is the machine its public CI runs on.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage paths Stage 12A source may name, and it may only read
#: them. Assembled from parts for the same reason the protected list is.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            ("evidence", "stage8e-research-only-policy", "stage-8e-finalization.json")
        ),
        "/".join(("evidence", "stage11b-" + "verifinger-canonical500-raw")),
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
        raise Stage12AFinalizationError(
            f"cannot hash required Stage 12A file {path}: {exc}"
        ) from exc
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """A digest of one source file, with newlines normalised to ``\\n``.

    ``core.autocrlf`` is on for this repository, so the same committed blob is LF
    in one checkout and CRLF in another, and a raw digest would name the checkout
    rather than the code. Evidence files are hashed raw, because
    ``.gitattributes`` pins them to LF.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage12AFinalizationError(
            f"cannot hash Stage 12A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage12a_source_fingerprint(repository_root: Path) -> str:
    """The bytes that decided this preflight."""
    digests = {
        relative: source_file_sha256(Path(repository_root) / PurePosixPath(relative))
        for relative in STAGE_12A_SOURCE_FILES
    }
    return stable_hash({"schema": "stage_12a_source_v1", "files": digests}, length=64)


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage12AFinalization:
    """Immutable authority for what Stage 12A established, and for what it did not.

    Two outcomes, validated differently, and no way to express the third. Under
    ``PASS`` the candidate is named, every gate passed, every route fact is
    established and Stage 12B opens. Under ``FAIL`` nothing is named, at least one
    blocker is carried, every unestablished fact is published as null rather than
    as a plausible default, and nothing opens.

    A marker under ``IDKIT_PREFLIGHT_PENDING_ACCESS`` is refused outright rather
    than validated leniently. It is the shape that would otherwise be used
    (docs/adr/0108).
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    candidate: str
    stage11b_outcome: str
    stage11b_finalization_fingerprint: str
    stage8e_policy_fingerprint: str
    stage12a_source_fingerprint: str
    observations_fingerprint: str
    preflight_fingerprint: str

    gate_count_defined: int
    gates_reached: int
    gates_passed: int

    # What the package turned out to be, or nothing.
    exact_product: str | None
    implementation_origin: str
    implementation_version: str | None
    package_sha256: str | None
    platform: str | None
    official_package_obtained: bool
    acquisition_status: str
    one_official_binding_selected: bool
    runtime_dependency_closure_known: bool

    # What the licence permitted, or nothing.
    research_use_opens_execution: bool | None
    research_use_blocked: bool
    license_activated: bool
    license_workload_sufficient: bool | None

    # What the route turned out to be, or nothing.
    canonical500_route: bool
    fpbench_preprocessing_required: bool
    dpi_500_before_extraction: bool
    single_finger_route: bool
    representation_type: str | None
    multi_finger_consolidation_used: bool
    extraction_settings_frozen: bool
    matcher_settings_frozen: bool
    hidden_score_affecting_defaults: int | None
    raw_score_route: bool
    score_numeric_type: str | None
    score_direction: str | None
    threshold_applied_inside_the_score: bool
    fpbench_score_transformation: str

    # What a run demonstrated, or nothing.
    pair_orientation: str
    self_independent_extraction: bool
    restart_determinism: bool
    failure_semantics_resolved: bool
    local_smoke_passed: bool
    runtime_feasibility_measured: bool

    training_provenance: str
    sd300_overlap_status: str
    sd300_used: bool
    failure_class: str | None

    # What the stage did not do.
    sd300_image_bytes_read: bool
    sd300_pair_manifest_read: bool
    sd300_scores_read: bool
    prior_algorithm_scores_read: bool
    production_adapter_created: bool
    canonical_experiment_config_created: bool
    benchmark_run_performed: bool
    result_set_produced: bool
    threshold_produced: bool
    calibration_performed: bool
    metrics_produced: bool
    production_algorithm_id_frozen: bool
    third_party_bytes_added_to_git: bool
    secrets_added_to_git: bool
    license_activation_attempted_in_ci: bool
    credentials_stored_in_ci: bool
    license_bypass_attempted: bool
    stage8e_evidence_changed: bool
    stage11a_evidence_changed: bool
    stage11b_evidence_changed: bool

    opens_stage_12b: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_12a_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "sd300_image_bytes_read",
        "sd300_pair_manifest_read",
        "sd300_scores_read",
        "sd300_used",
        "prior_algorithm_scores_read",
        "production_adapter_created",
        "canonical_experiment_config_created",
        "benchmark_run_performed",
        "result_set_produced",
        "threshold_produced",
        "calibration_performed",
        "metrics_produced",
        "production_algorithm_id_frozen",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "license_activation_attempted_in_ci",
        "credentials_stored_in_ci",
        "license_bypass_attempted",
        "stage8e_evidence_changed",
        "stage11a_evidence_changed",
        "stage11b_evidence_changed",
        "research_use_blocked",
        "fpbench_preprocessing_required",
        "multi_finger_consolidation_used",
        "threshold_applied_inside_the_score",
    )

    #: Every claim a ``PASS`` marker must establish. Listed rather than checked
    #: one by one, so that a claim added to the class is either on this list or
    #: visibly absent from it.
    ESTABLISHED_UNDER_PASS = (
        "official_package_obtained",
        "one_official_binding_selected",
        "runtime_dependency_closure_known",
        "license_activated",
        "canonical500_route",
        "dpi_500_before_extraction",
        "single_finger_route",
        "extraction_settings_frozen",
        "matcher_settings_frozen",
        "raw_score_route",
        "self_independent_extraction",
        "restart_determinism",
        "failure_semantics_resolved",
        "local_smoke_passed",
        "runtime_feasibility_measured",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_12A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 12A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome == STAGE_12A_PENDING_OUTCOME:
            raise ValueError(
                f"{STAGE_12A_PENDING_OUTCOME} is an outcome of the preflight and "
                "never of a finalization. A marker is a finalization, and nothing "
                "about waiting for a vendor is final (docs/adr/0108)"
            )
        if self.outcome not in STAGE_12A_FINAL_OUTCOMES:
            raise ValueError(
                f"outcome must be one of {list(STAGE_12A_FINAL_OUTCOMES)}"
            )
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.candidate != CANDIDATE_ID:
            raise ValueError(f"candidate must be {CANDIDATE_ID!r}")
        if self.implementation_origin != IMPLEMENTATION_ORIGIN:
            raise ValueError(
                f"implementation_origin must be {IMPLEMENTATION_ORIGIN!r}; a "
                "package from anywhere else is not this candidate"
            )
        if self.stage11b_finalization_fingerprint != (
            STAGE_11B_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 11B marker this stage "
                "follows; Stage 11B is immutable here"
            )
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )
        if self.fpbench_score_transformation != FPBENCH_SCORE_TRANSFORMATION:
            raise ValueError(
                "fpbench applies no score transformation, in either direction. A "
                "marker that recorded one would be describing a different "
                "benchmark"
            )
        expected_orientation = "_".join(
            f"{left.split('.')[-1]}_{right}" for left, right in PAIR_ROLE_BINDING
        )
        if self.pair_orientation != expected_orientation:
            raise ValueError(
                f"pair_orientation must be {expected_orientation!r}: the binding "
                "is frozen and is applied to every pair regardless of what the "
                "two orderings score (docs/adr/0109)"
            )

        for name in (
            "stage11b_finalization_fingerprint",
            "stage8e_policy_fingerprint",
            "stage12a_source_fingerprint",
            "observations_fingerprint",
            "preflight_fingerprint",
            "stage_12a_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        gates = int(self.gate_count_defined)
        if gates != GATE_COUNT:
            raise ValueError(
                f"{GATE_COUNT} hard gates are defined for this candidate; a "
                "preflight with fewer would be a preflight that dropped one. This "
                "counts the gates the stage defined, not the gates it reached"
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
                "can happen"
            )

        for name in Stage12AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 12A asserts {name} is false; a marker that said "
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
                    "why_this_blocks_algorithm_5",
                    "how_this_would_be_lifted",
                }
                - set(blocker)
            )
            if missing:
                raise ValueError(
                    f"a blocker is missing {missing}. A blocker nobody can act on "
                    "is a blocker nobody can lift"
                )
        object.__setattr__(
            self,
            "blockers",
            tuple(
                MappingProxyType(dict(sorted(item.items())))
                for item in sorted(blockers, key=lambda item: item["blocker_code"])
            ),
        )

        if self.outcome == STAGE_12A_PASS_OUTCOME:
            self._validate_pass()
        else:
            self._validate_fail()

        if self.source_tree_clean is not True:
            raise ValueError("Stage 12A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 12A finalization requires a clean verifier tree")

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

        expected = stage_12a_finalization_fingerprint(self)
        if self.stage_12a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_12a_finalization_fingerprint does not cover the marker's "
                "claims"
            )

    def _validate_pass(self) -> None:
        if self.gates_reached != self.gate_count_defined:
            raise ValueError(
                "a PASS marker reached every gate; a gate that was never reached "
                "is not a gate that passed"
            )
        if self.gates_passed != self.gate_count_defined:
            raise ValueError("a PASS marker passed every gate")
        for name in Stage12AFinalization.ESTABLISHED_UNDER_PASS:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"a PASS Stage 12A establishes {name}; a pass with one of "
                    "these open is the pass this stage exists to prevent"
                )
        for name in (
            "exact_product",
            "implementation_version",
            "package_sha256",
            "platform",
            "representation_type",
            "score_numeric_type",
            "score_direction",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"a PASS Stage 12A publishes {name} as observed from the "
                    "delivered package"
                )
        if self.implementation_version == IMPLEMENTATION_VERSION_UNRESOLVED:
            raise ValueError(
                "a PASS Stage 12A knows which version it qualified; the number on "
                "a course page is not one (docs/adr/0110)"
            )
        if self.research_use_opens_execution is not True:
            raise ValueError(
                "a PASS Stage 12A has a Stage 8E decision that opens execution"
            )
        if self.license_workload_sufficient is not True:
            raise ValueError(
                "a PASS Stage 12A has a licence capacity that covers the frozen "
                "workload (docs/adr/0096)"
            )
        if self.hidden_score_affecting_defaults != 0:
            raise ValueError(
                "a PASS Stage 12A leaves no score-affecting default unresolved; a "
                "value nobody recorded still decides the score"
            )
        if self.blockers:
            raise ValueError(
                "a PASS marker carries no blockers; a blocker is not a "
                "reservation to be weighed"
            )
        if self.failure_class is not None:
            raise ValueError("a PASS marker classifies no failure")
        if self.sd300_overlap_status != "NO_EVIDENCE_FOUND":
            raise ValueError(
                "a PASS Stage 12A reached the provenance gate and found no "
                "positive overlap evidence"
            )
        if self.opens_stage_12b is not True:
            raise ValueError("a PASS Stage 12A opens Stage 12B")

    def _validate_fail(self) -> None:
        if not self.blockers:
            raise ValueError(
                "a FAIL marker names which blockers apply. A block nobody can "
                "point at is a block nobody can lift"
            )
        if self.gates_passed == self.gate_count_defined:
            raise ValueError(
                "every gate passed and the outcome is FAIL, which is not a thing "
                "that can happen"
            )
        for name in (
            "exact_product",
            "implementation_version",
            "package_sha256",
            "platform",
            "representation_type",
            "score_numeric_type",
            "score_direction",
        ):
            value = getattr(self, name)
            if value is not None and not self.official_package_obtained:
                raise ValueError(
                    f"{name} is published and no package was obtained; what was "
                    "not established is published as unestablished, not as a "
                    "plausible default"
                )
        if not self.official_package_obtained:
            if self.research_use_opens_execution is not None:
                raise ValueError(
                    "no component was obtained, so Stage 8E assessed none and "
                    "there is no decision to publish. A false here would read as "
                    "a research-use refusal that nobody made (docs/adr/0095)"
                )
            if self.license_workload_sufficient is not None:
                raise ValueError(
                    "an unresolved capacity is published as unresolved. A false "
                    "would claim the quota was measured and found short"
                )
            if self.hidden_score_affecting_defaults is not None:
                raise ValueError(
                    "no settings inventory exists for a package nobody holds, and "
                    "a count of zero would read as a closed inventory"
                )
        if self.failure_class is None:
            raise ValueError(
                "a FAIL marker says what kind of failure it is. "
                "IDKIT_PREFLIGHT_FAIL reads the same whether the vendor refused "
                "the package or the delivered API had no per-pair score, and "
                "those are different results"
            )
        if self.opens_stage_12b is not False:
            raise ValueError(
                "a FAIL Stage 12A opens no production integration; there is no "
                "qualified route to integrate"
            )


def stage_12a_finalization_fingerprint(
    marker: Stage12AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_12a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_12a_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------- published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence tree holds, as POSIX paths below it, sorted.

    Recursive, although this stage's evidence is flat: a directory that appeared
    would be walked rather than ignored. Anything that is neither a directory nor
    a regular file, and anything reached through a link, is a refusal.
    """
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        raise Stage12AFinalizationError(
            f"no published Stage 12A evidence at {EVIDENCE_DIRECTORY.as_posix()}"
        )
    names: list[str] = []

    def walk(current: Path, prefix: str) -> None:
        for path in sorted(current.iterdir()):
            relative = f"{prefix}{path.name}"
            if path.is_symlink():
                raise Stage12AFinalizationError(
                    f"published evidence may not be a link: {relative}"
                )
            if path.is_dir():
                walk(path, f"{relative}/")
                continue
            if not path.is_file():
                raise Stage12AFinalizationError(
                    f"published evidence holds a non-file entry: {relative}"
                )
            names.append(relative)

    walk(directory, "")
    return tuple(names)


def require_expected_evidence_files(
    names: tuple[str, ...], *, marker_expected: bool = True
) -> None:
    """The fixed list, and nothing else.

    ``marker_expected`` is what makes a pending publication checkable. While the
    outcome is ``IDKIT_PREFLIGHT_PENDING_ACCESS`` the marker legitimately does
    not exist, and a check that demanded it would have to be switched off for
    exactly the stage it was written for.
    """
    present = set(names)
    expected = set(REQUIRED_EVIDENCE_FILES)
    if not marker_expected:
        expected.discard(STAGE_12A_FINALIZATION_NAME)
        if STAGE_12A_FINALIZATION_NAME in present:
            raise Stage12AFinalizationError(
                "a Stage 12A marker is published and the preflight is pending. "
                "One of the two is wrong, and it is not the preflight"
            )
    missing = sorted(expected - present)
    if missing:
        raise Stage12AFinalizationError(f"published evidence is missing {missing}")
    extra = sorted(present - expected)
    if extra:
        raise Stage12AFinalizationError(
            f"published evidence holds files nothing accounts for: {extra}"
        )


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No upstream byte, template, image, score or machine path reached the evidence.

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
            raise Stage12AFinalizationError(
                f"published evidence {path.name} is not readable JSON: {exc}"
            ) from exc
        found = sorted(_forbidden_keys(payload))
        if found:
            raise Stage12AFinalizationError(
                f"published evidence {path.name} carries forbidden data: {found}"
            )


def require_no_sensitive_published_data(repository_root: Path) -> None:
    """No credential and no machine path reached the evidence, by key or by shape.

    Applied to the published bytes rather than to the objects the engine built,
    because the two can differ: a document written by hand, an edit made after
    derivation, or a README paragraph that quoted a hardware ID would all pass an
    in-memory check and fail here.

    Raises:
        IdkitSensitiveEvidenceError: something shaped like licence material or a
            machine is present.
    """
    from fpbench.experiments.stage12a_preflight import find_sensitive_material

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Stage12AFinalizationError(
                    f"published evidence {path.name} is not readable JSON: {exc}"
                ) from exc
            findings = find_sensitive_material(payload)
        else:
            try:
                findings = find_sensitive_material(path.read_text(encoding="utf-8"))
            except OSError as exc:  # pragma: no cover - unreadable published file
                raise Stage12AFinalizationError(
                    f"cannot read published evidence {path.name}: {exc}"
                ) from exc
        if findings:
            raise IdkitSensitiveEvidenceError(
                f"published evidence {path.name} carries licence or machine "
                f"material: {list(findings)}"
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


# ---------------------------------------------------------------- the boundary


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
        raise Stage12AFinalizationError(
            f"cannot audit Stage 12A workspace boundaries with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise Stage12AFinalizationError(
            "cannot audit Stage 12A workspace boundaries with Git"
            + (f": {detail}" if detail else "")
        )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _named_stage12a_test(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return path.startswith("tests/") and path.endswith(".py") and "stage12a" in name


def _is_allowed_change(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _ALLOWED_EXACT_CHANGES:
        return True
    if any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES):
        return True
    return _named_stage12a_test(path)


def _is_owned_path(raw_path: str) -> bool:
    path = PurePosixPath(raw_path).as_posix()
    if path != raw_path or path.startswith("../") or path.startswith("/"):
        return False
    if path in _OWNED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _OWNED_PREFIXES):
        return True
    return _named_stage12a_test(path)


def _module_level_imports(tree: ast.Module) -> list[str]:
    """Imports at the top level of a module, and inside nothing else.

    Walks only the module body and the bodies of ``if``/``try`` blocks at that
    level, because a conditional import at module level still runs on import. An
    import inside a function does not, and that is the distinction the rule turns
    on.
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
    """Stage 12A's modules import no algorithm, no runtime and no closed stage."""
    for relative in STAGE_12A_SOURCE_FILES:
        path = Path(repository_root) / PurePosixPath(relative)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Stage12AFinalizationError(
                f"cannot audit Stage 12A source boundary {relative}: {exc}"
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
            raise Stage12AFinalizationError(
                f"{relative}: Stage 12A imports an algorithm, a vendor runtime, a "
                f"derivation layer or a closed stage {blocked}"
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
            raise Stage12AFinalizationError(
                f"{relative}: Stage 12A imports {eager} at module level. This "
                "stage has to stay importable on a machine with no scientific "
                "stack and no vendor SDK"
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
            raise Stage12AFinalizationError(
                f"{relative}: Stage 12A source names published evidence it is not "
                f"entitled to read: {literal!r}"
            )


def _stage_12a_changed_paths(
    repository_root: Path, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 12A's own commits changed, across its span.

    Commit by commit rather than endpoint to endpoint, so that a repair to an
    earlier stage that happened to land in the middle of this span is attributed
    to whoever made it (docs/adr/0067).
    """
    revisions = _git_output(
        repository_root,
        "rev-list",
        "--no-merges",
        f"{STAGE_12A_BASELINE_COMMIT}..{span_end_commit}",
    )
    all_revisions = _git_output(
        repository_root, "rev-list", f"{STAGE_12A_BASELINE_COMMIT}..{span_end_commit}"
    )
    merges = sorted(set(all_revisions) - set(revisions))
    if merges:
        raise Stage12AFinalizationError(
            f"Stage 12A's span contains merge commits, which it cannot attribute: "
            f"{merges}"
        )
    changed: set[str] = set()
    for revision in revisions:
        if revision in _NON_STAGE_12A_COMMITS_IN_SPAN:
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


def verify_stage12a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> None:
    """Prove Stage 12A changed only its own surface, over its own span.

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
        raise Stage12AFinalizationError(
            f"cannot resolve Stage 12A repository root: {exc}"
        ) from exc
    if actual_root != expected_root:
        raise Stage12AFinalizationError(
            "the Stage 12A boundary audit requires the Git worktree root"
        )
    _git_output(
        repository_root,
        "merge-base",
        "--is-ancestor",
        STAGE_12A_BASELINE_COMMIT,
        span_end_commit,
    )
    _git_output(repository_root, "merge-base", "--is-ancestor", span_end_commit, "HEAD")
    changed = _stage_12a_changed_paths(repository_root, span_end_commit)
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage12AFinalizationError(
            f"Stage 12A changed paths an earlier stage owns: {protected}"
        )
    forbidden = sorted(path for path in changed if not _is_allowed_change(path))
    if forbidden:
        raise Stage12AFinalizationError(
            f"paths outside Stage 12A changed during Stage 12A: {forbidden}"
        )
    unpublished = sorted(
        path
        for path in _git_output(
            repository_root, "ls-files", "--others", "--exclude-standard"
        )
        if _is_owned_path(path)
    )
    if unpublished:
        raise Stage12AFinalizationError(
            f"Stage 12A material exists outside its publication: {unpublished}"
        )
    _audit_source_boundaries(repository_root)


# --------------------------------------------------------------- the publisher


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


def write_stage12a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The eleven derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, including the hand-written
    README, so it has to come after them. That is the same two-commit shape every
    stage since 8D published under: the documents in one commit, the marker in
    the next, against a clean tree.

    Raises:
        Stage12AFinalizationError: a marker was asked for while the preflight is
            pending, or the tree is not clean apart from the marker being
            written.
    """
    from fpbench.experiments import stage12a_idkit_observations as observed
    from fpbench.experiments import stage12a_preflight as engine

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)
    predecessor = engine.require_stage11b_is_the_closed_predecessor(repository_root)

    directory = repository_root / EVIDENCE_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)

    preflight = engine.run_preflight()

    written: list[Path] = []
    for name in DERIVABLE_EVIDENCE_FILES:
        written.append(
            write_evidence_json(
                directory / name, engine.evidence_document(preflight, name)
            )
        )
    if not include_marker:
        return tuple(written)

    if preflight.outcome == STAGE_12A_PENDING_OUTCOME:
        raise Stage12AFinalizationError(
            "no Stage 12A marker is written while an official acquisition route "
            f"is outstanding: the preflight is {preflight.outcome} and paused at "
            f"{preflight.paused_at.value if preflight.paused_at else 'acquisition'}. "
            "The documents are published and describe exactly that. A marker here "
            "would finalise a stage that is waiting for a reply (docs/adr/0108)"
        )

    require_expected_evidence_files(
        tuple(
            name
            for name in published_evidence_names(repository_root)
            if name != STAGE_12A_FINALIZATION_NAME
        )
        + (STAGE_12A_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)
    require_no_sensitive_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_12A_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage12AFinalizationError(
            "the Stage 12A marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage12a_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = engine.require_no_idkit_bytes_in_git(repository_root)

    hashed = tuple(name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_12A_FINALIZATION_NAME)
    claims = _marker_claims(
        repository_root,
        preflight,
        predecessor=predecessor,
        observations_fingerprint=observed.observations_fingerprint(),
        evidence_content_hashes={
            name: file_sha256(directory / PurePosixPath(name)) for name in hashed
        },
        commit=commit,
        byte_findings=bool(byte_audit.findings),
    )
    marker = Stage12AFinalization(
        **claims,
        stage_12a_finalization_fingerprint=stage_12a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(write_evidence_json(directory / STAGE_12A_FINALIZATION_NAME, marker))
    return tuple(written)


def _marker_claims(
    repository_root: Path,
    preflight: Any,
    *,
    predecessor: str,
    observations_fingerprint: str,
    evidence_content_hashes: Mapping[str, str],
    commit: str,
    byte_findings: bool,
) -> dict[str, Any]:
    """Assemble the marker's claims from what the run actually established.

    Everything a package would have settled is read from the preflight's own
    documents rather than restated here, and everything unestablished is ``None``
    rather than a plausible default.
    """
    from fpbench.experiments import stage12a_idkit_identity as frozen
    from fpbench.experiments import stage12a_preflight as engine

    passed = preflight.passed
    acquisition = engine.acquisition_state()
    declaration = acquisition.declaration
    inspection = engine.package_inspection() or {}
    contract = inspection.get("score_contract") if isinstance(inspection, Mapping) else None
    contract = contract if isinstance(contract, Mapping) else {}
    representation = (
        inspection.get("representation") if isinstance(inspection, Mapping) else None
    )
    representation = representation if isinstance(representation, Mapping) else {}
    route = inspection.get("input_route") if isinstance(inspection, Mapping) else None
    route = route if isinstance(route, Mapping) else {}
    licence = inspection.get("license") if isinstance(inspection, Mapping) else None
    licence = licence if isinstance(licence, Mapping) else {}

    def gate_passed(gate: frozen.PreflightGate) -> bool:
        return preflight.status(gate) is frozen.GateStatus.PASS

    orientation = "_".join(
        f"{left.split('.')[-1]}_{right}" for left, right in PAIR_ROLE_BINDING
    )
    obtained = acquisition.obtained
    return {
        "schema_version": STAGE_12A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": preflight.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "candidate": CANDIDATE_ID,
        "stage11b_outcome": frozen.STAGE_11B_OUTCOME,
        "stage11b_finalization_fingerprint": predecessor,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage12a_source_fingerprint": stage12a_source_fingerprint(repository_root),
        "observations_fingerprint": observations_fingerprint,
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "gate_count_defined": GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "exact_product": declaration.exact_product_name if declaration else None,
        "implementation_origin": IMPLEMENTATION_ORIGIN,
        "implementation_version": (
            declaration.implementation_version if declaration else None
        ),
        "package_sha256": declaration.package_sha256 if declaration else None,
        "platform": (
            f"{declaration.operating_system}/{declaration.architecture}"
            if declaration
            else None
        ),
        "official_package_obtained": obtained,
        "acquisition_status": acquisition.status.value,
        "one_official_binding_selected": gate_passed(
            frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
        ),
        "runtime_dependency_closure_known": gate_passed(
            frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
        ),
        "research_use_opens_execution": True if passed else None,
        "research_use_blocked": False,
        "license_activated": bool(licence.get("activated")),
        "license_workload_sufficient": True if passed else None,
        "canonical500_route": gate_passed(
            frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
        ),
        "fpbench_preprocessing_required": False,
        "dpi_500_before_extraction": bool(route.get("dpi_set_before_extraction")),
        "single_finger_route": gate_passed(
            frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
        ),
        "representation_type": (
            str(representation.get("representation_type")) if representation else None
        ),
        "multi_finger_consolidation_used": False,
        "extraction_settings_frozen": gate_passed(
            frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
        ),
        "matcher_settings_frozen": gate_passed(
            frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
        ),
        # Counted, not assumed. Under a pass it is zero because the closure gate
        # said so; under a failure with a package in hand it is however many
        # settings the inspection actually left without an authority; and with no
        # package it is ``None``, because a count of zero over an inventory
        # nobody recorded would read as a closed inventory.
        "hidden_score_affecting_defaults": (
            len(engine.unresolved_score_affecting_settings()) if obtained else None
        ),
        "raw_score_route": gate_passed(
            frozen.PreflightGate.SINGLE_FINGER_MATCHER_RAW_SCORE
        ),
        "score_numeric_type": (
            str(contract.get("numeric_type")) if contract.get("numeric_type") else None
        ),
        "score_direction": (
            str(contract.get("direction")) if contract.get("direction") else None
        ),
        "threshold_applied_inside_the_score": False,
        "fpbench_score_transformation": FPBENCH_SCORE_TRANSFORMATION,
        "pair_orientation": orientation,
        "self_independent_extraction": gate_passed(
            frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "restart_determinism": gate_passed(
            frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "failure_semantics_resolved": gate_passed(
            frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "local_smoke_passed": gate_passed(
            frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES
        ),
        "runtime_feasibility_measured": gate_passed(
            frozen.PreflightGate.WORKLOAD_RUNTIME_FEASIBILITY
        ),
        "training_provenance": (
            frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
            if gate_passed(frozen.PreflightGate.TRAINING_PROVENANCE)
            else frozen.TrainingProvenanceStatus.NOT_REACHED.value
        ),
        "sd300_overlap_status": preflight.sd300_overlap_status.value,
        "sd300_used": False,
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
        "threshold_produced": False,
        "calibration_performed": False,
        "metrics_produced": False,
        "production_algorithm_id_frozen": False,
        "third_party_bytes_added_to_git": byte_findings,
        "secrets_added_to_git": False,
        "license_activation_attempted_in_ci": False,
        "credentials_stored_in_ci": False,
        "license_bypass_attempted": False,
        "stage8e_evidence_changed": False,
        "stage11a_evidence_changed": False,
        "stage11b_evidence_changed": False,
        "opens_stage_12b": preflight.opens_stage_12b,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "evidence_content_hashes": dict(evidence_content_hashes),
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage12a_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the marker
    too and refuses a dirty tree — and refuses outright while the preflight is
    pending. ``status`` derives everything and prints the outcome, the gate list
    and the blockers without writing anything, which is what a reviewer runs
    before deciding whether to commit.
    """
    from fpbench.experiments import stage12a_idkit_identity as ids
    from fpbench.experiments import stage12a_idkit_observations as observed
    from fpbench.experiments import stage12a_preflight as engine

    parser = argparse.ArgumentParser(description="Stage 12A evidence")
    parser.add_argument(
        "action", choices=("status", "documents", "publish"), nargs="?", default="status"
    )
    parser.add_argument("--repository-root", default=".")
    arguments = parser.parse_args(argv)
    root = Path(arguments.repository_root).resolve()

    if arguments.action == "status":
        preflight = engine.run_preflight()
        state = engine.acquisition_state()
        print(f"algorithm slot           {ALGORITHM_SLOT}")
        print(f"candidate                {CANDIDATE_ID}")
        print(f"implementation version   {IMPLEMENTATION_VERSION_UNRESOLVED}")
        print(f"outcome                  {preflight.outcome}")
        print(f"acquisition              {state.status.value}")
        print(f"package presence         {state.presence.value}")
        print(
            "failure class            "
            + (preflight.failure_class.value if preflight.failure_class else "none")
        )
        print(f"opens stage 12b          {preflight.opens_stage_12b}")
        print(f"observations             {observed.observations_fingerprint()}")
        print(f"preflight                {preflight.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        for index, result in enumerate(preflight.results, start=1):
            print(f"{index:>2}  {result.gate.value:<{width}}  {result.status.value}")
        if preflight.blockers:
            print(f"blockers                 {len(preflight.blockers)}")
            for blocker in preflight.blockers:
                print(f"  {blocker.gate.value:<34s} {blocker.blocker_code.value}")
        reason = preflight.pending_reason
        if reason is not None:
            print(f"pending                  {reason.acquisition_status.value}")
            for item in reason.what_is_outstanding:
                print(f"  - {item}")
        return 0

    written = write_stage12a_evidence(root, include_marker=arguments.action == "publish")
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
