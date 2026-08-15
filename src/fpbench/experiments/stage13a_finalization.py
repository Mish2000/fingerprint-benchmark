"""The Stage 13A marker, the publisher, and the audit that keeps the stage inside itself.

The marker has two legal outcomes and validates differently under each.
``FINGERCELL_PREFLIGHT_PASS`` names the candidate, requires all ten gates to have
passed against the delivered trial, requires every acceptance condition to hold,
and opens Stage 13B. ``FINGERCELL_PREFLIGHT_FAIL`` requires at least one blocker,
requires every unestablished fact to be published as unestablished rather than as
a plausible default, and opens nothing.

There is no third marker. ``FINGERCELL_PREFLIGHT_INCOMPLETE`` is a published
outcome of the *preflight* and never of a finalization: a marker is a
finalization, and there is nothing final about a step somebody has not taken yet.
The publisher refuses to write one while any gate is ``ACTION_REQUIRED``, which
is what stops "incomplete" from quietly becoming the third state that gets used
(docs/adr/0112).

What the marker denies is checked rather than written as prose: no SD300 image
byte, score or pair manifest was read, no prior algorithm's scores were consulted,
no production adapter exists, no threshold, decision or metric was produced, no
vendor byte entered Git, no credential entered Git or CI, no licence was
activated in CI, no trial was reset or bypassed, and not one byte of Stage 8E's,
Stage 11B's or Stage 12A's evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 13A began
at with the commit it published at, rather than against a moving ``HEAD``.
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

from fpbench.core.fingercell_preflight_errors import (
    FingerCellSensitiveEvidenceError,
    Stage13AFinalizationError,
)
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage13a_fingercell_identity import (
    ALGORITHM_SLOT,
    CANDIDATE_ID,
    CALIBRATION_PERFORMED,
    DECLARED_PRODUCT_VERSION,
    DERIVABLE_EVIDENCE_FILES,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    FPBENCH_SCORE_TRANSFORMATION,
    GATE_COUNT,
    IMPLEMENTATION_ORIGIN,
    MANDATORY_FAILURE_PROBE_COUNT,
    PAIR_ROLE_BINDING,
    PRODUCT_FAMILY,
    README_NAME,
    REQUIRED_EVIDENCE_FILES,
    REQUIRED_TEMPLATE_FORMAT,
    SCORE_DIRECTION,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_11B_FINALIZATION_FINGERPRINT,
    STAGE_12A_FAILURE_CLASS,
    STAGE_12A_FINALIZATION_FINGERPRINT,
    STAGE_12A_OUTCOME,
    STAGE_13A_FAIL_OUTCOME,
    STAGE_13A_FINAL_OUTCOMES,
    STAGE_13A_FINALIZATION_NAME,
    STAGE_13A_INCOMPLETE_OUTCOME,
    STAGE_13A_PASS_OUTCOME,
    STAGE_13A_SCHEMA_VERSION,
    STAGE_13A_SOURCE_FILES,
    STAGE_FINALIZATION_KIND,
    THRESHOLD_PRODUCED,
)

__all__ = [
    "STAGE_13A_BASELINE_COMMIT",
    "Stage13AFinalization",
    "stage_13a_finalization_fingerprint",
    "stage13a_source_fingerprint",
    "file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "require_no_sensitive_published_data",
    "verify_stage13a_workspace_boundaries",
    "write_evidence_json",
    "write_stage13a_evidence",
    "main",
]

#: Stage 13A began here: the commit that published Stage 12A's refusal marker.
STAGE_13A_BASELINE_COMMIT = "d64c5174c5ec47a528c7b8b5adc3375d279fae2a"

#: Commits inside Stage 13A's span that are **not** Stage 13A's work. Empty
#: today and kept because it will not be (docs/adr/0067).
_NON_STAGE_13A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 13A is allowed to touch, each named rather than covered by
#: a prefix. Stage 13A adds one ``core`` module of its own rather than extending
#: an existing one, and adds no package: it is a qualification, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".github/workflows/stage13a-fingercell-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0112-an-outstanding-action-is-not-a-failed-candidate.md",
        "docs/adr/0113-a-vendor-revision-hash-is-not-an-artifact-digest.md",
        "docs/adr/0114-a-sibling-product-runtime-never-answers-for-this-one.md",
        "docs/adr/0115-the-bridge-compiles-before-the-trial-clock-starts.md",
        "docs/adr/0116-the-binding-is-chosen-from-the-archive-not-in-advance.md",
        "docs/adr/0117-an-embedded-example-size-is-not-a-preprocessing-rule.md",
        "docs/adr/0118-settings-are-read-before-they-are-set.md",
        "docs/adr/0119-pair-labels-come-from-the-api-under-test.md",
        "docs/adr/0120-binary-metadata-asks-questions-the-runtime-answers.md",
        "docs/experiments/stage13a-fingercell-preflight.md",
        "docs/algorithms/algorithm5-candidates/neurotechnology-fingercell.md",
        *STAGE_13A_SOURCE_FILES,
    }
)

#: Written out in full rather than assembled, unlike every other evidence path in
#: this module. The source audit permits a literal that names *this stage's own*
#: directory, and it identifies one by comparing the tail against the directory
#: name — so a split literal would leave a bare ``evidence/`` for it to refuse.
_ALLOWED_CHANGE_PREFIXES = (
    "evidence/stage13a-fingercell-preflight/",
    "integrations/fingercell-cpp/",
)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage13a_")
    or path
    in {
        "src/fpbench/core/fingercell_preflight_errors.py",
        "docs/experiments/stage13a-fingercell-preflight.md",
        "docs/algorithms/algorithm5-candidates/neurotechnology-fingercell.md",
        ".github/workflows/stage13a-fingercell-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 13A may never change, checked by name so the message says which.
#: Assembled from parts rather than written out, for the reason every stage since
#: 8C assembles its own.
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
        ("evidence", "stage12a-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "veri" + "finger_"),
        ("src", "fpbench", "core", "id" + "kit_preflight_errors.py"),
        ("src", "fpbench", "core", "id3_preflight_errors.py"),
        ("src", "fpbench", "core", "algorithm4_errors.py"),
        ("src", "fpbench", "experiments", "stage10a_"),
        ("src", "fpbench", "experiments", "stage10b_"),
        ("src", "fpbench", "experiments", "stage11a_"),
        ("src", "fpbench", "experiments", "stage11b_"),
        ("src", "fpbench", "experiments", "stage12a_"),
        ("src", "fpbench", "adapters", ""),
        ("configs", ""),
        ("data", ""),
        # Every integration that existed before this stage, named one by one.
        # A blanket `integrations/` would also protect this stage's own bridge
        # from the stage that writes it, and widening it later to make room
        # would be the kind of quiet edit ADR 0067 exists to prevent. Listing
        # the siblings keeps Algorithm 4's bridge exactly as immutable as it was.
        ("integrations", "veri" + "finger-java"),
        ("integrations", "veri" + "finger-qualification"),
        ("integrations", "source" + "afis-java"),
        ("integrations", "nb" + "is"),
        ("integrations", "f" + "lx"),
        ("integrations", "modern-matchers"),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 13A module may import *at all*. The sibling-algorithm entries
#: are this stage's own addition and the reason it has a contamination guard.
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
        "fpbench.experiments.stage11a_" + "verifinger_identity",
        "fpbench.experiments.stage11a_" + "preflight",
        "fpbench.experiments.stage11a_" + "qualification",
        "fpbench.experiments.stage11b_" + "identity",
        "fpbench.experiments.stage11b_" + "finalization",
        "fpbench.experiments.stage12a_" + "idkit_identity",
        "fpbench.experiments.stage12a_" + "preflight",
        "fpbench.experiments.stage12a_" + "qualification",
        "fpbench.experiments." + "verifinger_smoke",
        "fpbench.experiments." + "verifinger_runtime_manifest",
    )
)

#: What no Stage 13A module may import **at module level**, and may import
#: inside a function. Stage 13A must stay importable on a machine with no
#: scientific stack and no vendor SDK at all — which is its public CI runner.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage paths Stage 13A source may name, and it may only read
#: them.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            ("evidence", "stage8e-research-only-policy", "stage-8e-finalization.json")
        ),
        "/".join(("evidence", "stage12a-" + "idkit-preflight")),
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
    r"""Write one evidence document as bytes, with ``\n`` line endings."""
    payload = json.dumps(to_plain(value), indent=2, sort_keys=True) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))
    return path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_file_sha256(path: Path) -> str:
    """Digest one source file with checkout-specific newlines normalised.

    ``core.autocrlf`` is enabled for this repository, so hashing raw source
    bytes would give the same committed code a different identity on Windows
    and Linux.  Published evidence is pinned to LF by ``.gitattributes`` and is
    still hashed byte for byte by :func:`file_sha256`.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage13AFinalizationError(
            f"cannot hash Stage 13A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage13a_source_fingerprint(repository_root: Path) -> str:
    """One digest over every module that decides this preflight."""
    entries = {
        name: source_file_sha256(Path(repository_root) / name)
        for name in STAGE_13A_SOURCE_FILES
    }
    return stable_hash(
        {"schema": "stage_13a_source_v1", "files": entries}, length=64
    )


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage13AFinalization:
    """Immutable authority for what Stage 13A established, and for what it did not.

    Two outcomes, validated differently, and no way to express the third. A
    marker under ``FINGERCELL_PREFLIGHT_INCOMPLETE`` is refused outright rather
    than validated leniently. It is the shape that would otherwise be used
    (docs/adr/0112).
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    candidate: str
    stage12a_outcome: str
    stage12a_failure_class: str
    stage12a_finalization_fingerprint: str
    stage11b_finalization_fingerprint: str
    stage8e_policy_fingerprint: str
    stage13a_source_fingerprint: str
    observations_fingerprint: str
    preflight_fingerprint: str

    gate_count_defined: int
    gates_reached: int
    gates_passed: int
    gates_awaiting_action: int

    # What the archive turned out to be, or nothing.
    product: str | None
    product_version: str | None
    product_revision: str | None
    package_sha256: str | None
    platform: str | None
    binding: str | None
    implementation_origin: str
    official_trial_obtained: bool
    runtime_closure_pinned: bool
    verifinger_component_in_route: bool

    # What the terms and the trial permitted, or nothing.
    research_use_opens_execution: bool | None
    research_use_blocked: bool
    trial_activated: bool
    trial_workload_sufficient: bool | None
    license_bypass_attempted: bool
    trial_reset_attempted: bool

    # What the route turned out to be, or nothing.
    canonical500_route: bool
    fpbench_preprocessing_required: bool
    ppi_500_effective_at_extraction: bool
    single_finger_template: bool
    template_format: str | None
    template_merging: bool
    template_cache_used: bool
    extractor_settings_frozen: bool
    hidden_score_affecting_settings: int | None
    raw_score_route: bool
    score_native_type: str | None
    score_direction: str | None
    threshold_applied_inside_the_score: bool
    fpbench_score_transformation: str

    # What a run demonstrated, or nothing.
    pair_orientation: str
    self_independent_extraction: bool
    repeat_determinism: bool
    restart_determinism: bool
    mandatory_failure_probes_passed: int
    local_smoke_passed: bool
    runtime_timing_measured: bool

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
    registry_integration_created: bool
    canonical_experiment_config_created: bool
    benchmark_run_performed: bool
    result_set_produced: bool
    decision_profile_produced: bool
    threshold_produced: bool
    calibration_performed: bool
    metrics_produced: bool
    production_algorithm_id_frozen: bool
    third_party_bytes_added_to_git: bool
    secrets_added_to_git: bool
    trial_activated_in_ci: bool
    credentials_stored_in_ci: bool
    stage8e_evidence_changed: bool
    stage11b_evidence_changed: bool
    stage12a_evidence_changed: bool

    opens_stage_13b: bool
    reopens_algorithm_5_search: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_13a_finalization_fingerprint: str
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
        "registry_integration_created",
        "canonical_experiment_config_created",
        "benchmark_run_performed",
        "result_set_produced",
        "decision_profile_produced",
        "threshold_produced",
        "calibration_performed",
        "metrics_produced",
        "production_algorithm_id_frozen",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "trial_activated_in_ci",
        "credentials_stored_in_ci",
        "license_bypass_attempted",
        "trial_reset_attempted",
        "stage8e_evidence_changed",
        "stage11b_evidence_changed",
        "stage12a_evidence_changed",
        "research_use_blocked",
        "fpbench_preprocessing_required",
        "template_merging",
        "template_cache_used",
        "threshold_applied_inside_the_score",
        "verifinger_component_in_route",
    )

    #: Every claim a ``PASS`` marker must establish.
    ESTABLISHED_UNDER_PASS = (
        "official_trial_obtained",
        "runtime_closure_pinned",
        "trial_activated",
        "canonical500_route",
        "ppi_500_effective_at_extraction",
        "single_finger_template",
        "extractor_settings_frozen",
        "raw_score_route",
        "self_independent_extraction",
        "repeat_determinism",
        "restart_determinism",
        "local_smoke_passed",
        "runtime_timing_measured",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_13A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 13A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome == STAGE_13A_INCOMPLETE_OUTCOME:
            raise ValueError(
                f"{STAGE_13A_INCOMPLETE_OUTCOME} is an outcome of the preflight "
                "and never of a finalization. A marker is a finalization, and "
                "nothing about a step nobody has taken yet is final "
                "(docs/adr/0112)"
            )
        if self.outcome not in STAGE_13A_FINAL_OUTCOMES:
            raise ValueError(f"outcome must be one of {list(STAGE_13A_FINAL_OUTCOMES)}")
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.candidate != CANDIDATE_ID:
            raise ValueError(f"candidate must be {CANDIDATE_ID!r}")
        if self.implementation_origin != IMPLEMENTATION_ORIGIN:
            raise ValueError(
                f"implementation_origin must be {IMPLEMENTATION_ORIGIN!r}; an "
                "archive from anywhere else is not this candidate"
            )
        if self.stage12a_outcome != STAGE_12A_OUTCOME:
            raise ValueError(
                f"the marker binds Stage 12A's outcome, which is {STAGE_12A_OUTCOME!r}"
            )
        if self.stage12a_failure_class != STAGE_12A_FAILURE_CLASS:
            raise ValueError(
                "the marker binds Stage 12A's failure class, which is "
                f"{STAGE_12A_FAILURE_CLASS!r}"
            )
        if self.stage12a_finalization_fingerprint != (
            STAGE_12A_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 12A marker this stage "
                "follows; Stage 13A is a successor to one closed stage"
            )
        if self.stage11b_finalization_fingerprint != (
            STAGE_11B_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 11B marker; Algorithm 4 is "
                "immutable here"
            )
        if self.stage8e_policy_fingerprint != STAGE8E_FINALIZATION_FINGERPRINT:
            raise ValueError(
                "the marker must bind the exact Stage 8E marker this stage "
                "reused; Stage 8E is a closed stage"
            )
        if self.fpbench_score_transformation != FPBENCH_SCORE_TRANSFORMATION:
            raise ValueError(
                "fpbench applies no score transformation, in either direction"
            )
        expected_orientation = "_".join(
            f"{left.split('.')[-1]}_{right}" for left, right in PAIR_ROLE_BINDING
        )
        if self.pair_orientation != expected_orientation:
            raise ValueError(
                f"pair_orientation must be {expected_orientation!r}: the binding "
                "takes its words from the API under test and is applied to every "
                "pair regardless of what the two orderings score (docs/adr/0119)"
            )

        for name in (
            "stage12a_finalization_fingerprint",
            "stage11b_finalization_fingerprint",
            "stage8e_policy_fingerprint",
            "stage13a_source_fingerprint",
            "observations_fingerprint",
            "preflight_fingerprint",
            "stage_13a_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        gates = int(self.gate_count_defined)
        if gates != GATE_COUNT:
            raise ValueError(
                f"{GATE_COUNT} hard gates are defined for this candidate; a "
                "preflight with fewer would be a preflight that dropped one"
            )
        object.__setattr__(self, "gate_count_defined", gates)
        for name in ("gates_reached", "gates_passed", "gates_awaiting_action"):
            value = int(getattr(self, name))
            if not 0 <= value <= gates:
                raise ValueError(f"{name} is {value} and the stage defines {gates}")
            object.__setattr__(self, name, value)
        if self.gates_passed > self.gates_reached:
            raise ValueError(
                "more gates passed than were reached, which is not a thing that "
                "can happen"
            )
        if self.gates_awaiting_action and self.outcome == STAGE_13A_PASS_OUTCOME:
            raise ValueError(
                "a PASS Stage 13A has no gate awaiting a local action; every gate "
                "was asked and answered (docs/adr/0112)"
            )

        for name in Stage13AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 13A asserts {name} is false; a marker that said "
                    "otherwise would be describing a different stage"
                )

        probes = int(self.mandatory_failure_probes_passed)
        if not 0 <= probes <= MANDATORY_FAILURE_PROBE_COUNT:
            raise ValueError(
                f"mandatory_failure_probes_passed is {probes} and the stage "
                f"defines {MANDATORY_FAILURE_PROBE_COUNT}"
            )
        object.__setattr__(self, "mandatory_failure_probes_passed", probes)

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

        if self.outcome == STAGE_13A_PASS_OUTCOME:
            self._validate_pass()
        else:
            self._validate_fail()

        if self.source_tree_clean is not True:
            raise ValueError("Stage 13A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 13A finalization requires a clean verifier tree")

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

        expected = stage_13a_finalization_fingerprint(self)
        if self.stage_13a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_13a_finalization_fingerprint does not cover the marker's "
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
        for name in Stage13AFinalization.ESTABLISHED_UNDER_PASS:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"a PASS Stage 13A establishes {name}; a pass with one of "
                    "these open is the pass this stage exists to prevent"
                )
        for name in (
            "product",
            "product_version",
            "product_revision",
            "package_sha256",
            "platform",
            "binding",
            "template_format",
            "score_native_type",
            "score_direction",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"a PASS Stage 13A publishes {name} as observed from the "
                    "delivered archive"
                )
        if self.product != PRODUCT_FAMILY:
            raise ValueError(f"a PASS Stage 13A qualified {PRODUCT_FAMILY}")
        if self.product_version != DECLARED_PRODUCT_VERSION:
            raise ValueError(
                f"a PASS Stage 13A qualified version {DECLARED_PRODUCT_VERSION}"
            )
        if self.template_format != REQUIRED_TEMPLATE_FORMAT.value:
            raise ValueError(
                f"a PASS Stage 13A compares {REQUIRED_TEMPLATE_FORMAT.value} "
                "templates"
            )
        if self.score_direction != SCORE_DIRECTION:
            raise ValueError(f"a PASS Stage 13A observed {SCORE_DIRECTION}")
        if self.research_use_opens_execution is not True:
            raise ValueError(
                "a PASS Stage 13A has a Stage 8E decision that opens execution"
            )
        if self.trial_workload_sufficient is not True:
            raise ValueError(
                "a PASS Stage 13A has a trial capacity that covers the frozen "
                "workload"
            )
        if self.hidden_score_affecting_settings != 0:
            raise ValueError(
                "a PASS Stage 13A leaves no score-affecting setting unresolved; a "
                "value nobody recorded still decides the score"
            )
        if self.mandatory_failure_probes_passed != MANDATORY_FAILURE_PROBE_COUNT:
            raise ValueError(
                f"a PASS Stage 13A passed all {MANDATORY_FAILURE_PROBE_COUNT} "
                "mandatory failure probes, not a subset"
            )
        if self.blockers:
            raise ValueError("a PASS marker carries no blockers")
        if self.failure_class is not None:
            raise ValueError("a PASS marker classifies no failure")
        if self.sd300_overlap_status not in (
            "NO_EVIDENCE_FOUND",
            "VENDOR_DENIAL_OBTAINED",
        ):
            raise ValueError(
                "a PASS Stage 13A reached the provenance gate and found no "
                "positive overlap evidence"
            )
        if self.opens_stage_13b is not True:
            raise ValueError("a PASS Stage 13A opens Stage 13B")
        if self.reopens_algorithm_5_search is not False:
            raise ValueError("a PASS Stage 13A does not reopen the candidate search")

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
        if not self.official_trial_obtained:
            for name in (
                "product_revision",
                "package_sha256",
                "platform",
                "binding",
                "template_format",
                "score_native_type",
                "score_direction",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{name} is published and no archive was obtained; what "
                        "was not established is published as unestablished, not "
                        "as a plausible default"
                    )
            if self.research_use_opens_execution is not None:
                raise ValueError(
                    "no component was obtained, so Stage 8E assessed none and "
                    "there is no decision to publish (docs/adr/0095)"
                )
            if self.trial_workload_sufficient is not None:
                raise ValueError(
                    "an unresolved capacity is published as unresolved. A false "
                    "would claim the quota was measured and found short"
                )
            if self.hidden_score_affecting_settings is not None:
                raise ValueError(
                    "no settings inventory exists for an archive nobody holds, "
                    "and a count of zero would read as a closed inventory"
                )
        if self.failure_class is None:
            raise ValueError(
                "a FAIL marker says what kind of failure it is. "
                "FINGERCELL_PREFLIGHT_FAIL reads the same whether the trial would "
                "not activate or the matcher was nondeterministic"
            )
        if self.opens_stage_13b is not False:
            raise ValueError(
                "a FAIL Stage 13A opens no production integration; there is no "
                "qualified route to integrate"
            )
        if self.reopens_algorithm_5_search is not True:
            raise ValueError(
                "a FAIL Stage 13A returns Algorithm 5 selection to the next "
                "candidate"
            )


def stage_13a_finalization_fingerprint(
    marker: Stage13AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_13a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_13a_finalization_v1", "marker": plain}, length=64
    )


# ------------------------------------------------------------- published files


def published_evidence_names(repository_root: Path) -> tuple[str, ...]:
    """Exactly the files the evidence tree holds, as POSIX paths below it, sorted."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(
            item.relative_to(directory).as_posix()
            for item in directory.rglob("*")
            if item.is_file()
        )
    )


def require_expected_evidence_files(names: tuple[str, ...]) -> None:
    """The evidence tree holds exactly what this stage publishes, and nothing else."""
    found = set(names)
    expected = set(REQUIRED_EVIDENCE_FILES)
    missing = sorted(expected - found)
    if missing:
        raise Stage13AFinalizationError(
            f"the Stage 13A evidence is missing {missing}"
        )
    extra = sorted(found - expected)
    if extra:
        raise Stage13AFinalizationError(
            f"the Stage 13A evidence directory holds {extra}, which nothing "
            "publishes; an unexplained file in a published tree is a file nobody "
            "can account for"
        )


def _forbidden_keys(node: Any, trail: str = "") -> set[str]:
    found: set[str] = set()
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.strip().lower() in FORBIDDEN_PUBLISHED_KEYS:
                found.add(where)
            found |= _forbidden_keys(value, where)
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found |= _forbidden_keys(item, f"{trail}[{index}]")
    return found


def require_no_forbidden_published_data(repository_root: Path) -> None:
    """No published document carries an image, a template, a score or a path."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for name in published_evidence_names(repository_root):
        if not name.endswith(".json"):
            continue
        try:
            payload = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Stage13AFinalizationError(
                f"cannot read published evidence {name}: {exc}"
            ) from exc
        found = _forbidden_keys(payload)
        if found:
            raise Stage13AFinalizationError(
                f"{name} carries {sorted(found)}, which a Stage 13A document may "
                "never publish"
            )


def require_no_sensitive_published_data(repository_root: Path) -> None:
    """No published document carries anything shaped like licence material."""
    from fpbench.experiments.stage13a_preflight import find_sensitive_material

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for name in published_evidence_names(repository_root):
        path = directory / name
        if name.endswith(".json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Stage13AFinalizationError(
                    f"cannot read published evidence {name}: {exc}"
                ) from exc
        else:
            payload = path.read_text(encoding="utf-8", errors="replace")
        findings = find_sensitive_material(payload)
        if findings:
            raise FingerCellSensitiveEvidenceError(
                f"{name} carries licence material: {list(findings)}"
            )


# ---------------------------------------------------------------- the boundary


def _git_output(repository_root: Path, *arguments: str) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), *arguments),
            check=False,
            capture_output=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage13AFinalizationError(f"git {' '.join(arguments)} failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise Stage13AFinalizationError(
            f"git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return tuple(
        line
        for line in completed.stdout.decode("utf-8", "replace").splitlines()
        if line.strip()
    )


def _named_stage13a_test(path: str) -> bool:
    return path.startswith("tests/") and "stage13a" in path


def _is_allowed_change(raw_path: str) -> bool:
    path = raw_path.strip().strip('"')
    if path in _ALLOWED_EXACT_CHANGES or _named_stage13a_test(path):
        return True
    return any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES)


def _is_owned_path(raw_path: str) -> bool:
    path = raw_path.strip().strip('"')
    if path in _OWNED_EXACT or _named_stage13a_test(path):
        return True
    return any(path.startswith(prefix) for prefix in _OWNED_PREFIXES)


def _module_level_imports(tree: ast.Module) -> list[str]:
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _audit_source_boundaries(repository_root: Path) -> None:
    """Every Stage 13A module, checked for what it imports and what it names."""
    for relative in STAGE_13A_SOURCE_FILES:
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage13AFinalizationError(
                f"{relative} is named as Stage 13A source and does not exist"
            )
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:  # pragma: no cover
            raise Stage13AFinalizationError(f"{relative}: {exc}") from exc

        every: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                every.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                every.append(node.module)
        for name in every:
            for forbidden in _FORBIDDEN_IMPORT_PREFIXES:
                if name == forbidden or name.startswith(forbidden + "."):
                    raise Stage13AFinalizationError(
                        f"{relative} imports {name}. A qualification layer that "
                        "reached into an algorithm, a runtime or a derivation "
                        "would be a qualification whose answers could depend on "
                        "what had been run"
                    )
        for name in _module_level_imports(tree):
            for deferred in _DEFERRED_ONLY_IMPORT_PREFIXES:
                if name == deferred or name.startswith(deferred + "."):
                    raise Stage13AFinalizationError(
                        f"{relative} imports {name} at module level. Stage 13A "
                        "must stay importable on a runner with no scientific "
                        "stack and no vendor SDK"
                    )

        own_directory = EVIDENCE_DIRECTORY.as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if _EVIDENCE_PREFIX not in value:
                continue
            if value.startswith(own_directory) or own_directory.startswith(
                value.rstrip("/")
            ):
                continue
            if value in _PERMITTED_PRIOR_STAGE_DOCUMENTS:
                continue
            if any(
                value.startswith(permitted) or permitted.startswith(value)
                for permitted in _PERMITTED_PRIOR_STAGE_DOCUMENTS
            ):
                continue
            raise Stage13AFinalizationError(
                f"{relative} names the published evidence path {value!r}. Stage "
                "13A reads three prior markers and writes only its own directory"
            )


def _stage_13a_changed_paths(
    repository_root: Path, *, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 13A's span touched, attributed commit by commit."""
    commits = _git_output(
        repository_root,
        "rev-list",
        "--reverse",
        f"{STAGE_13A_BASELINE_COMMIT}..{span_end_commit}",
    )
    changed: set[str] = set()
    for commit in commits:
        if commit.strip().lower() in _NON_STAGE_13A_COMMITS_IN_SPAN:
            continue
        for path in _git_output(
            repository_root, "show", "--pretty=format:", "--name-only", commit
        ):
            changed.add(path.strip().strip('"'))
    return tuple(sorted(item for item in changed if item))


def verify_stage13a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> tuple[str, ...]:
    """Confirm Stage 13A stayed inside itself, across its whole span.

    Raises:
        Stage13AFinalizationError: the span touched a protected path, changed
            something outside the allowed set, or a Stage 13A module reached
            somewhere it may not.
    """
    _audit_source_boundaries(repository_root)
    changed = _stage_13a_changed_paths(
        repository_root, span_end_commit=span_end_commit
    )
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage13AFinalizationError(
            f"Stage 13A's span changed protected paths {protected}. A closed "
            "stage's evidence and a prior algorithm's source are immutable here"
        )
    outside = sorted(path for path in changed if not _is_allowed_change(path))
    if outside:
        raise Stage13AFinalizationError(
            f"Stage 13A's span changed {outside}, which is outside the paths this "
            "stage owns or may touch"
        )
    return changed


# --------------------------------------------------------------- the publisher


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


def write_stage13a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The twelve derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, including the hand-written
    README, so it has to come after them. That is the same two-commit shape every
    stage since 8D published under.

    Raises:
        Stage13AFinalizationError: a marker was asked for while a gate is
            awaiting a local action, or the tree is not clean apart from the
            marker being written.
    """
    from fpbench.experiments import stage13a_fingercell_observations as observed
    from fpbench.experiments import stage13a_preflight as engine

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)
    predecessor = engine.require_stage12a_is_the_closed_predecessor(repository_root)
    engine.require_stage11b_is_unchanged(repository_root)
    engine.require_no_verifinger_contamination(repository_root)

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

    if preflight.outcome == STAGE_13A_INCOMPLETE_OUTCOME:
        outstanding = [
            f"{action.action.value} at {action.gate.value}"
            for action in preflight.outstanding_actions
        ]
        raise Stage13AFinalizationError(
            "no Stage 13A marker is written while local actions are outstanding: "
            f"the preflight is {preflight.outcome} and is awaiting "
            f"{outstanding}. The documents are published and describe exactly "
            "that. A marker here would finalise a stage whose remaining steps are "
            "jobs somebody has not done yet (docs/adr/0112)"
        )

    require_expected_evidence_files(
        tuple(
            name
            for name in published_evidence_names(repository_root)
            if name != STAGE_13A_FINALIZATION_NAME
        )
        + (STAGE_13A_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)
    require_no_sensitive_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_13A_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage13AFinalizationError(
            "the Stage 13A marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage13a_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = engine.require_no_fingercell_bytes_in_git(repository_root)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_13A_FINALIZATION_NAME
    )
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
    marker = Stage13AFinalization(
        **claims,
        stage_13a_finalization_fingerprint=stage_13a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(
        write_evidence_json(directory / STAGE_13A_FINALIZATION_NAME, marker)
    )
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
    """Assemble the marker's claims from what the run actually established."""
    from fpbench.experiments import stage13a_fingercell_identity as frozen
    from fpbench.experiments import stage13a_preflight as engine

    passed = preflight.passed
    acquisition = engine.acquisition_state()
    declaration = acquisition.declaration
    inspection = engine.package_inspection() or {}

    def section(name: str) -> Mapping[str, Any]:
        value = inspection.get(name) if isinstance(inspection, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    identity = section("package_identity")
    contract = section("score_contract")
    extraction = section("extraction")
    route = section("input_route")
    trial = section("trial")
    workload = section("workload")
    record = engine.qualification_record() or {}
    determinism = record.get("determinism") if isinstance(record, Mapping) else {}
    determinism = determinism if isinstance(determinism, Mapping) else {}
    probes = record.get("failure_probes") if isinstance(record, Mapping) else ()
    probes = probes if isinstance(probes, (list, tuple)) else ()
    probes_passed = sum(
        1
        for item in probes
        if isinstance(item, Mapping) and item.get("behaved_correctly")
    )

    def gate_passed(gate: frozen.PreflightGate) -> bool:
        return preflight.status(gate) is frozen.GateStatus.PASS

    orientation = "_".join(
        f"{left.split('.')[-1]}_{right}" for left, right in PAIR_ROLE_BINDING
    )
    obtained = acquisition.obtained
    qualified = gate_passed(frozen.PreflightGate.PAIR_SELF_DETERMINISM_FAILURES)
    return {
        "schema_version": STAGE_13A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": preflight.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "candidate": CANDIDATE_ID,
        "stage12a_outcome": STAGE_12A_OUTCOME,
        "stage12a_failure_class": STAGE_12A_FAILURE_CLASS,
        "stage12a_finalization_fingerprint": predecessor,
        "stage11b_finalization_fingerprint": STAGE_11B_FINALIZATION_FINGERPRINT,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage13a_source_fingerprint": stage13a_source_fingerprint(repository_root),
        "observations_fingerprint": observations_fingerprint,
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "gate_count_defined": GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "product": declaration.product if declaration else None,
        "product_version": declaration.product_version if declaration else None,
        "product_revision": (
            declaration.vendor_product_revision if declaration else None
        ),
        "package_sha256": declaration.sha256 if declaration else None,
        "platform": (
            f"{identity.get('platform')}/{identity.get('architecture')}"
            if identity
            else None
        ),
        "binding": str(identity.get("selected_binding")) if identity else None,
        "implementation_origin": IMPLEMENTATION_ORIGIN,
        "official_trial_obtained": obtained,
        "runtime_closure_pinned": gate_passed(
            frozen.PreflightGate.PACKAGE_RUNTIME_IDENTITY
        ),
        "verifinger_component_in_route": False,
        "research_use_opens_execution": True if passed else None,
        "research_use_blocked": False,
        "trial_activated": bool(trial.get("activated")),
        "trial_workload_sufficient": True if passed else None,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "canonical500_route": gate_passed(
            frozen.PreflightGate.CANONICAL500_INPUT_ROUTE
        ),
        "fpbench_preprocessing_required": False,
        "ppi_500_effective_at_extraction": (
            int(route.get("effective_ppi", 0)) == frozen.REQUIRED_INPUT_PPI
        ),
        "single_finger_template": gate_passed(
            frozen.PreflightGate.SINGLE_FINGER_EXTRACTION_PROFILE
        ),
        "template_format": (
            str(extraction.get("template_format")) if extraction else None
        ),
        "template_merging": False,
        "template_cache_used": False,
        "extractor_settings_frozen": gate_passed(
            frozen.PreflightGate.SCORE_AFFECTING_SETTINGS_CLOSURE
        ),
        # Counted, not assumed. Under a pass it is zero because the closure gate
        # said so; under a failure with an archive in hand it is however many
        # settings the inspection actually left without an authority; and with no
        # archive it is ``None``, because a count of zero over an inventory
        # nobody recorded would read as a closed inventory.
        "hidden_score_affecting_settings": (
            len(engine.unresolved_score_affecting_settings()) if obtained else None
        ),
        "raw_score_route": gate_passed(frozen.PreflightGate.RAW_1TO1_SCORE_CONTRACT),
        "score_native_type": (
            str(contract.get("native_type")) if contract.get("native_type") else None
        ),
        "score_direction": (
            str(contract.get("direction")) if contract.get("direction") else None
        ),
        "threshold_applied_inside_the_score": False,
        "fpbench_score_transformation": FPBENCH_SCORE_TRANSFORMATION,
        "pair_orientation": orientation,
        "self_independent_extraction": qualified,
        "repeat_determinism": bool(
            determinism.get("repeat_in_the_same_process")
        ),
        "restart_determinism": bool(determinism.get("fresh_process")),
        "mandatory_failure_probes_passed": probes_passed,
        "local_smoke_passed": qualified,
        "runtime_timing_measured": gate_passed(
            frozen.PreflightGate.FULL_WORKLOAD_FEASIBILITY
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
        "registry_integration_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
        "decision_profile_produced": False,
        "threshold_produced": THRESHOLD_PRODUCED,
        "calibration_performed": CALIBRATION_PERFORMED,
        "metrics_produced": False,
        "production_algorithm_id_frozen": False,
        "third_party_bytes_added_to_git": byte_findings,
        "secrets_added_to_git": False,
        "trial_activated_in_ci": False,
        "credentials_stored_in_ci": False,
        "stage8e_evidence_changed": False,
        "stage11b_evidence_changed": False,
        "stage12a_evidence_changed": False,
        "opens_stage_13b": preflight.opens_stage_13b,
        "reopens_algorithm_5_search": preflight.reopens_algorithm_5_search,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "evidence_content_hashes": dict(evidence_content_hashes),
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage13a_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the marker
    too and refuses a dirty tree — and refuses outright while any gate awaits a
    local action. ``status`` derives everything and prints the outcome, the gate
    list and what remains, without writing anything.
    """
    from fpbench.experiments import stage13a_fingercell_identity as ids
    from fpbench.experiments import stage13a_fingercell_observations as observed
    from fpbench.experiments import stage13a_preflight as engine

    parser = argparse.ArgumentParser(description="Stage 13A evidence")
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
        print(f"product                  {PRODUCT_FAMILY} {DECLARED_PRODUCT_VERSION}")
        print(f"outcome                  {preflight.outcome}")
        print(f"archive presence         {state.presence.value}")
        print(
            "failure class            "
            + (preflight.failure_class.value if preflight.failure_class else "none")
        )
        print(f"opens stage 13b          {preflight.opens_stage_13b}")
        print(f"observations             {observed.observations_fingerprint()}")
        print(f"preflight                {preflight.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        for index, result in enumerate(preflight.results, start=1):
            print(f"{index:>2}  {result.gate.value:<{width}}  {result.status.value}")
        if preflight.blockers:
            print(f"blockers                 {len(preflight.blockers)}")
            for blocker in preflight.blockers:
                print(f"  {blocker.gate.value:<34s} {blocker.blocker_code.value}")
        actions = preflight.outstanding_actions
        if actions:
            print(f"outstanding actions      {len(actions)}")
            for action in actions:
                print(f"  {action.gate.value}: {action.action.value}")
                for item in action.what_remains:
                    print(f"    - {item}")
        return 0

    written = write_stage13a_evidence(
        root, include_marker=arguments.action == "publish"
    )
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
