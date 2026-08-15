"""The Stage 14A marker, the publisher, and the audit that keeps the stage inside itself.

The marker has two legal outcomes and validates differently under each.
``GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_PASS`` names the candidate, requires all four
gates to have passed against a delivered package, requires the package identity
to be published from the artifact rather than from a page, and opens Stage 14B.
``GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL`` requires at least one blocker, requires
every unestablished fact to be published as unestablished rather than as a
plausible default, and opens nothing.

There is no third or fourth marker. ``GRIAULE_PREFLIGHT_PENDING_ACCESS`` and
``GRIAULE_PREFLIGHT_INCOMPLETE`` are published outcomes of the *preflight* and
never of a finalization: a marker is a finalization, and neither "somebody else
has to answer" nor "we have not finished" is final. The publisher refuses both
(docs/adr/0121).

What the marker denies is checked rather than written as prose: no trial was
activated, no score was produced, no SD300 image byte, score or pair manifest was
read, no prior algorithm's scores were consulted, no adapter or registry entry
exists, no threshold, decision or metric was produced, no vendor byte entered
Git, no credential entered Git or CI, and not one byte of Stage 8E's, Stage 11B's
or Stage 13A's evidence changed.

The boundary audit follows docs/adr/0067: it compares the commit Stage 14A began
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

from fpbench.core.griaule_preflight_errors import (
    GriauleSensitiveEvidenceError,
    Stage14AFinalizationError,
)
from fpbench.core.serialization import stable_hash, to_plain
from fpbench.experiments.stage14a_griaule_identity import (
    ALGORITHM_SLOT,
    CALIBRATION_PERFORMED,
    CANDIDATE_ID,
    DERIVABLE_EVIDENCE_FILES,
    EVIDENCE_DIRECTORY,
    FORBIDDEN_PUBLISHED_KEYS,
    FPBENCH_SCORE_TRANSFORMATION,
    GATE_COUNT,
    IMPLEMENTATION_ORIGIN,
    IMPLEMENTATION_VERSION_SENTINEL,
    PRODUCT_FAMILY,
    README_NAME,
    REQUIRED_EVIDENCE_FILES,
    STAGE8E_FINALIZATION_FINGERPRINT,
    STAGE_11B_FINALIZATION_FINGERPRINT,
    STAGE_13A_FAILURE_CLASS,
    STAGE_13A_FINALIZATION_FINGERPRINT,
    STAGE_13A_OUTCOME,
    STAGE_14A_FAIL_OUTCOME,
    STAGE_14A_FINALIZATION_NAME,
    STAGE_14A_FINAL_OUTCOMES,
    STAGE_14A_INCOMPLETE_OUTCOME,
    STAGE_14A_PASS_OUTCOME,
    STAGE_14A_PENDING_OUTCOME,
    STAGE_14A_SCHEMA_VERSION,
    STAGE_14A_SOURCE_FILES,
    STAGE_FINALIZATION_KIND,
    THRESHOLD_PRODUCED,
)

__all__ = [
    "STAGE_14A_BASELINE_COMMIT",
    "Stage14AFinalization",
    "stage_14a_finalization_fingerprint",
    "stage14a_source_fingerprint",
    "file_sha256",
    "published_evidence_names",
    "require_expected_evidence_files",
    "require_no_forbidden_published_data",
    "require_no_sensitive_published_data",
    "verify_stage14a_workspace_boundaries",
    "write_evidence_json",
    "write_stage14a_evidence",
    "main",
]

#: Stage 14A began here: the commit that republished Stage 13A's final marker.
STAGE_14A_BASELINE_COMMIT = "db9cfce269705b542681e38f12e41b93a1601ec0"

#: Commits inside Stage 14A's span that are **not** Stage 14A's work. Empty
#: today and kept because it will not be (docs/adr/0067).
_NON_STAGE_14A_COMMITS_IN_SPAN: frozenset[str] = frozenset()

_HEX = frozenset("0123456789abcdef")

#: Shared files Stage 14A is allowed to touch, each named rather than covered by
#: a prefix. Stage 14A adds one ``core`` module of its own, no package, no
#: integration and no adapter: it is a preflight, not a layer.
_ALLOWED_EXACT_CHANGES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        ".github/workflows/stage14a-griaule-preflight.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
        "docs/adr/README.md",
        "docs/adr/0121-a-wait-and-a-chore-are-not-the-same-non-answer.md",
        "docs/adr/0122-a-blocked-fetch-is-not-a-missing-route.md",
        "docs/adr/0123-acquisition-is-tested-before-the-harness-is-built.md",
        "docs/adr/0124-a-vendor-internal-crop-is-algorithm-behaviour.md",
        "docs/experiments/stage14a-griaule-preflight.md",
        "docs/algorithms/algorithm5-candidates/griaule-gbs-fingerprint-sdk.md",
        *STAGE_14A_SOURCE_FILES,
    }
)

#: Written out in full rather than assembled, unlike every other evidence path in
#: this module. The source audit permits a literal that names *this stage's own*
#: directory, and it identifies one by comparing the tail against the directory
#: name — so a split literal would leave a bare ``evidence/`` for it to refuse.
_ALLOWED_CHANGE_PREFIXES = ("evidence/stage14a-griaule-preflight/",)

_OWNED_EXACT = frozenset(
    path
    for path in _ALLOWED_EXACT_CHANGES
    if path.startswith("src/fpbench/experiments/stage14a_")
    or path
    in {
        "src/fpbench/core/griaule_preflight_errors.py",
        "docs/experiments/stage14a-griaule-preflight.md",
        "docs/algorithms/algorithm5-candidates/griaule-gbs-fingerprint-sdk.md",
        ".github/workflows/stage14a-griaule-preflight.yml",
    }
)
_OWNED_PREFIXES = _ALLOWED_CHANGE_PREFIXES

#: Paths Stage 14A may never change, checked by name so the message says which.
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
        ("evidence", "stage13a-"),
        ("src", "fpbench", "third_party", ""),
        ("src", "fpbench", "core", "third_party_"),
        ("src", "fpbench", "core", "veri" + "finger_"),
        ("src", "fpbench", "core", "id" + "kit_preflight_errors.py"),
        ("src", "fpbench", "core", "id3_preflight_errors.py"),
        ("src", "fpbench", "core", "finger" + "cell_preflight_errors.py"),
        ("src", "fpbench", "core", "algorithm4_errors.py"),
        ("src", "fpbench", "experiments", "stage10a_"),
        ("src", "fpbench", "experiments", "stage10b_"),
        ("src", "fpbench", "experiments", "stage11a_"),
        ("src", "fpbench", "experiments", "stage11b_"),
        ("src", "fpbench", "experiments", "stage12a_"),
        ("src", "fpbench", "experiments", "stage13a_"),
        ("src", "fpbench", "adapters", ""),
        ("integrations", ""),
        ("configs", ""),
        ("data", ""),
        ("src", "fpbench", "f" + "lx", ""),
        ("src", "fpbench", "modern_matchers", ""),
        ("src", "fpbench", "calibration", ""),
    )
)

#: What no Stage 14A module may import *at all*. A preflight that reached into an
#: algorithm, a runtime or a derivation would be a preflight whose answers could
#: depend on what had been run.
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
        "fpbench.experiments.stage11b_" + "identity",
        "fpbench.experiments.stage11b_" + "finalization",
        "fpbench.experiments.stage12a_" + "idkit_identity",
        "fpbench.experiments.stage12a_" + "preflight",
        "fpbench.experiments.stage13a_" + "fingercell_identity",
        "fpbench.experiments.stage13a_" + "preflight",
        "fpbench.experiments.stage13a_" + "qualification",
        "fpbench.experiments." + "verifinger_smoke",
        "fpbench.experiments." + "verifinger_runtime_manifest",
    )
)

#: What no Stage 14A module may import **at module level**, and may import inside
#: a function. Stage 14A must stay importable on a machine with no scientific
#: stack and no vendor SDK at all — which is its public CI runner.
_DEFERRED_ONLY_IMPORT_PREFIXES = ("torch", "numpy", "cv2", "scipy", "PIL", "yaml")

#: The only prior-stage paths Stage 14A source may name, and it may only read them.
_PERMITTED_PRIOR_STAGE_DOCUMENTS = frozenset(
    {
        "/".join(
            ("evidence", "stage8e-research-only-policy", "stage-8e-finalization.json")
        ),
        "/".join(("evidence", "stage13a-" + "fingercell-preflight")),
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

    ``core.autocrlf`` is enabled for this repository, so hashing raw source bytes
    would give the same committed code a different identity on Windows and Linux.
    Published evidence is pinned to LF by ``.gitattributes`` and is still hashed
    byte for byte by :func:`file_sha256`.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage14AFinalizationError(
            f"cannot hash Stage 14A source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def stage14a_source_fingerprint(repository_root: Path) -> str:
    """One digest over every module that decides this preflight."""
    entries = {
        name: source_file_sha256(Path(repository_root) / name)
        for name in STAGE_14A_SOURCE_FILES
    }
    return stable_hash({"schema": "stage_14a_source_v1", "files": entries}, length=64)


# ------------------------------------------------------------------ the marker


@dataclass(frozen=True, slots=True)
class Stage14AFinalization:
    """Immutable authority for what Stage 14A established, and for what it did not.

    Two outcomes, validated differently, and no way to express the other two. A
    marker under ``GRIAULE_PREFLIGHT_PENDING_ACCESS`` or
    ``GRIAULE_PREFLIGHT_INCOMPLETE`` is refused outright rather than validated
    leniently, because those are the shapes that would otherwise be used
    (docs/adr/0121).
    """

    schema_version: str
    kind: str
    outcome: str

    algorithm_slot: str
    candidate: str
    stage13a_outcome: str
    stage13a_failure_class: str
    stage13a_finalization_fingerprint: str
    stage11b_finalization_fingerprint: str
    stage8e_policy_fingerprint: str
    stage14a_source_fingerprint: str
    observations_fingerprint: str
    preflight_fingerprint: str

    gate_count_defined: int
    gates_reached: int
    gates_passed: int
    gates_pending_access: int
    gates_awaiting_action: int

    # What the package turned out to be, or nothing.
    product: str
    implementation_version: str | None
    build_or_revision: str | None
    platform: str | None
    binding: str | None
    package_sha256: str | None
    implementation_origin: str
    official_package_obtained: bool
    acquisition_status: str
    vendor_refused: bool

    # What the terms and the bundled trial permitted, or nothing.
    research_use_opens_execution: bool | None
    research_use_blocked: bool | None
    bundled_trial_present: bool | None
    trial_activated: bool
    license_bypass_attempted: bool
    trial_reset_attempted: bool

    # What the route turned out to be, or nothing.
    canonical500_route: bool | None
    fpbench_preprocessing_required: bool | None
    vendor_internal_crop: bool | None
    single_finger_template: bool | None
    raw_score_route: bool | None
    score_native_type: str | None
    score_direction: str | None
    threshold_applied_inside_the_score: bool | None
    fpbench_score_transformation: str
    route_closed: bool | None
    unresolved_score_affecting_settings: int | None

    failure_class: str | None

    # What the stage did not do.
    scores_produced: int
    sd300_image_bytes_read: bool
    sd300_pair_manifest_read: bool
    sd300_scores_read: bool
    sd300_used: bool
    prior_algorithm_scores_read: bool
    production_adapter_created: bool
    registry_integration_created: bool
    canonical_experiment_config_created: bool
    benchmark_run_performed: bool
    result_set_produced: bool
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
    stage13a_evidence_changed: bool

    opens_stage_14b: bool
    reopens_algorithm_5_search: bool

    blockers: tuple[Mapping[str, str], ...]

    evidence_content_hashes: Mapping[str, str]
    source_commit: str
    source_tree_clean: bool
    verifier_source_commit: str
    verifier_source_tree_clean: bool

    stage_14a_finalization_fingerprint: str
    created_utc: str

    #: Every flag that must be ``False`` under either outcome, named so that a
    #: flag added to the class is either checked here or is visibly absent.
    DENIED_FLAGS = (
        "trial_activated",
        "license_bypass_attempted",
        "trial_reset_attempted",
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
        "threshold_produced",
        "calibration_performed",
        "metrics_produced",
        "production_algorithm_id_frozen",
        "third_party_bytes_added_to_git",
        "secrets_added_to_git",
        "trial_activated_in_ci",
        "credentials_stored_in_ci",
        "stage8e_evidence_changed",
        "stage11b_evidence_changed",
        "stage13a_evidence_changed",
    )

    #: Every claim a ``PASS`` marker must establish.
    ESTABLISHED_UNDER_PASS = (
        "official_package_obtained",
        "canonical500_route",
        "single_finger_template",
        "raw_score_route",
        "route_closed",
    )

    def __post_init__(self) -> None:
        from types import MappingProxyType

        version = str(self.schema_version).strip()
        if version != STAGE_14A_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported Stage 14A finalization schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)
        if self.kind != STAGE_FINALIZATION_KIND:
            raise ValueError(f"kind must be {STAGE_FINALIZATION_KIND!r}")
        if self.outcome in (STAGE_14A_PENDING_OUTCOME, STAGE_14A_INCOMPLETE_OUTCOME):
            raise ValueError(
                f"{self.outcome} is an outcome of the preflight and never of a "
                "finalization. A marker is a finalization, and neither a wait on "
                "somebody else nor a job half done is final (docs/adr/0121)"
            )
        if self.outcome not in STAGE_14A_FINAL_OUTCOMES:
            raise ValueError(f"outcome must be one of {list(STAGE_14A_FINAL_OUTCOMES)}")
        if self.algorithm_slot != ALGORITHM_SLOT:
            raise ValueError(f"algorithm_slot must be {ALGORITHM_SLOT!r}")
        if self.candidate != CANDIDATE_ID:
            raise ValueError(f"candidate must be {CANDIDATE_ID!r}")
        if self.product != PRODUCT_FAMILY:
            raise ValueError(f"product must be {PRODUCT_FAMILY!r}")
        if self.implementation_origin != IMPLEMENTATION_ORIGIN:
            raise ValueError(
                f"implementation_origin must be {IMPLEMENTATION_ORIGIN!r}; a "
                "package from anywhere else is not this candidate"
            )
        if self.stage13a_outcome != STAGE_13A_OUTCOME:
            raise ValueError(
                f"the marker binds Stage 13A's outcome, which is {STAGE_13A_OUTCOME!r}"
            )
        if self.stage13a_failure_class != STAGE_13A_FAILURE_CLASS:
            raise ValueError(
                "the marker binds Stage 13A's failure class, which is "
                f"{STAGE_13A_FAILURE_CLASS!r}"
            )
        if self.stage13a_finalization_fingerprint != (
            STAGE_13A_FINALIZATION_FINGERPRINT
        ):
            raise ValueError(
                "the marker must bind the exact Stage 13A marker this stage "
                "follows; Stage 14A is a successor to one closed stage"
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
                "the marker must bind the exact Stage 8E marker this stage reused; "
                "Stage 8E is a closed stage"
            )
        if self.fpbench_score_transformation != FPBENCH_SCORE_TRANSFORMATION:
            raise ValueError(
                "fpbench applies no score transformation, in either direction"
            )
        if int(self.scores_produced) != 0:
            raise ValueError(
                "Stage 14A produces no score at all; a marker reporting one would "
                "be describing a stage that executed something"
            )

        for name in (
            "stage13a_finalization_fingerprint",
            "stage11b_finalization_fingerprint",
            "stage8e_policy_fingerprint",
            "stage14a_source_fingerprint",
            "observations_fingerprint",
            "preflight_fingerprint",
            "stage_14a_finalization_fingerprint",
        ):
            object.__setattr__(self, name, _require_digest(getattr(self, name), name))

        gates = int(self.gate_count_defined)
        if gates != GATE_COUNT:
            raise ValueError(
                f"{GATE_COUNT} gates are defined for this candidate; a preflight "
                "with more or fewer would be a different stage"
            )
        object.__setattr__(self, "gate_count_defined", gates)
        for name in (
            "gates_reached",
            "gates_passed",
            "gates_pending_access",
            "gates_awaiting_action",
        ):
            value = int(getattr(self, name))
            if not 0 <= value <= gates:
                raise ValueError(f"{name} is {value} and the stage defines {gates}")
            object.__setattr__(self, name, value)
        if self.gates_passed > self.gates_reached:
            raise ValueError(
                "more gates passed than were reached, which is not a thing that "
                "can happen"
            )
        if self.gates_pending_access or self.gates_awaiting_action:
            raise ValueError(
                "a finalized Stage 14A has no gate waiting on a reply and no gate "
                "waiting on a chore. Every gate it reached was asked and answered, "
                "and the two waiting states never reach a marker (docs/adr/0121)"
            )

        for name in Stage14AFinalization.DENIED_FLAGS:
            if getattr(self, name) is not False:
                raise ValueError(
                    f"Stage 14A asserts {name} is false; a marker that said "
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

        if self.outcome == STAGE_14A_PASS_OUTCOME:
            self._validate_pass()
        else:
            self._validate_fail()

        if self.source_tree_clean is not True:
            raise ValueError("Stage 14A evidence is derived from a clean tree")
        if self.verifier_source_tree_clean is not True:
            raise ValueError("Stage 14A finalization requires a clean verifier tree")

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

        expected = stage_14a_finalization_fingerprint(self)
        if self.stage_14a_finalization_fingerprint != expected:
            raise ValueError(
                "stage_14a_finalization_fingerprint does not cover the marker's claims"
            )

    def _validate_pass(self) -> None:
        if self.gates_reached != self.gate_count_defined:
            raise ValueError(
                "a PASS marker reached every gate; a gate that was never reached "
                "is not a gate that passed"
            )
        if self.gates_passed != self.gate_count_defined:
            raise ValueError("a PASS marker passed every gate")
        for name in Stage14AFinalization.ESTABLISHED_UNDER_PASS:
            if getattr(self, name) is not True:
                raise ValueError(
                    f"a PASS Stage 14A establishes {name}; a pass with one of "
                    "these open is the pass this stage exists to prevent"
                )
        for name in (
            "implementation_version",
            "build_or_revision",
            "platform",
            "binding",
            "package_sha256",
            "score_native_type",
            "score_direction",
        ):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"a PASS Stage 14A publishes {name} as observed from the "
                    "delivered package"
                )
        if self.implementation_version == IMPLEMENTATION_VERSION_SENTINEL:
            raise ValueError(
                "a PASS Stage 14A resolved the version from the artifact; the "
                "sentinel means no package settled it (docs/adr/0110)"
            )
        for name in (
            "research_use_opens_execution",
            "bundled_trial_present",
        ):
            if getattr(self, name) is not True:
                raise ValueError(f"a PASS Stage 14A establishes {name}")
        for name in (
            "research_use_blocked",
            "fpbench_preprocessing_required",
            "threshold_applied_inside_the_score",
            "vendor_refused",
        ):
            if getattr(self, name) is not False:
                raise ValueError(
                    f"a PASS Stage 14A establishes {name} is false; null would "
                    "leave the corresponding gate fact unestablished"
                )
        if self.unresolved_score_affecting_settings != 0:
            raise ValueError(
                "a PASS Stage 14A leaves no score-affecting setting unresolved; a "
                "value nobody recorded still decides the score"
            )
        if self.vendor_internal_crop is None:
            raise ValueError(
                "a PASS Stage 14A recorded whether the extractor crops internally; "
                "it is algorithm behaviour and is published rather than assumed "
                "(docs/adr/0124)"
            )
        if self.blockers:
            raise ValueError("a PASS marker carries no blockers")
        if self.failure_class is not None:
            raise ValueError("a PASS marker classifies no failure")
        if self.opens_stage_14b is not True:
            raise ValueError("a PASS Stage 14A opens Stage 14B")
        if self.reopens_algorithm_5_search is not False:
            raise ValueError("a PASS Stage 14A does not reopen the candidate search")

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
        if not self.official_package_obtained:
            for name in (
                "implementation_version",
                "build_or_revision",
                "platform",
                "binding",
                "package_sha256",
                "score_native_type",
                "score_direction",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{name} is published and no package was obtained; what "
                        "was not established is published as unestablished, not "
                        "as a plausible default"
                    )
            if self.research_use_opens_execution is not None:
                raise ValueError(
                    "no component was obtained, so Stage 8E assessed none and "
                    "there is no decision to publish (docs/adr/0095)"
                )
            if self.bundled_trial_present is not None:
                raise ValueError(
                    "no package was obtained, so nobody saw whether the trial is "
                    "inside it. A false would claim it was looked for and missing"
                )
            if self.unresolved_score_affecting_settings is not None:
                raise ValueError(
                    "no settings inventory exists for a package nobody holds, and "
                    "a count of zero would read as a closed inventory"
                )
            for name in (
                "canonical500_route",
                "fpbench_preprocessing_required",
                "vendor_internal_crop",
                "single_finger_template",
                "raw_score_route",
                "threshold_applied_inside_the_score",
                "route_closed",
            ):
                if getattr(self, name) is not None:
                    raise ValueError(
                        f"{name} is published and no package was inspected; the "
                        "route was never observed either way"
                    )
        if self.failure_class is None:
            raise ValueError(
                "a FAIL marker says what kind of failure it is. "
                "GRIAULE_ARTIFACT_ROUTE_PREFLIGHT_FAIL reads the same whether a "
                "vendor refused a package or a delivered header exposed only a "
                "thresholded decision"
            )
        if self.opens_stage_14b is not False:
            raise ValueError(
                "a FAIL Stage 14A opens no runtime qualification; there is no "
                "qualified route to qualify"
            )
        if self.reopens_algorithm_5_search is not True:
            raise ValueError(
                "a FAIL Stage 14A returns Algorithm 5 selection to the next "
                "candidate"
            )


def stage_14a_finalization_fingerprint(
    marker: Stage14AFinalization | Mapping[str, Any],
) -> str:
    """Derive the marker identity without its own identity or a wall clock."""
    plain = dict(to_plain(marker))
    plain.pop("stage_14a_finalization_fingerprint", None)
    plain.pop("created_utc", None)
    return stable_hash(
        {"schema": "stage_14a_finalization_v1", "marker": plain}, length=64
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
        raise Stage14AFinalizationError(f"the Stage 14A evidence is missing {missing}")
    extra = sorted(found - expected)
    if extra:
        raise Stage14AFinalizationError(
            f"the Stage 14A evidence directory holds {extra}, which nothing "
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
    """No published document carries an image, a template, a score or a decision."""
    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for name in published_evidence_names(repository_root):
        if not name.endswith(".json"):
            continue
        try:
            payload = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise Stage14AFinalizationError(
                f"cannot read published evidence {name}: {exc}"
            ) from exc
        found = _forbidden_keys(payload)
        if found:
            raise Stage14AFinalizationError(
                f"{name} carries {sorted(found)}, which a Stage 14A document may "
                "never publish"
            )


def require_no_sensitive_published_data(repository_root: Path) -> None:
    """No published document carries anything shaped like licence or personal material."""
    from fpbench.experiments.stage14a_preflight import find_sensitive_material

    directory = Path(repository_root) / EVIDENCE_DIRECTORY
    for name in published_evidence_names(repository_root):
        path = directory / name
        if name.endswith(".json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise Stage14AFinalizationError(
                    f"cannot read published evidence {name}: {exc}"
                ) from exc
        else:
            payload = path.read_text(encoding="utf-8", errors="replace")
        findings = find_sensitive_material(payload)
        if findings:
            raise GriauleSensitiveEvidenceError(
                f"{name} carries licence or personal material: {list(findings)}"
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
        raise Stage14AFinalizationError(
            f"git {' '.join(arguments)} failed: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise Stage14AFinalizationError(
            f"git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return tuple(
        line
        for line in completed.stdout.decode("utf-8", "replace").splitlines()
        if line.strip()
    )


def _named_stage14a_test(path: str) -> bool:
    return path.startswith("tests/") and "stage14a" in path


def _is_allowed_change(raw_path: str) -> bool:
    path = raw_path.strip().strip('"')
    if path in _ALLOWED_EXACT_CHANGES or _named_stage14a_test(path):
        return True
    return any(path.startswith(prefix) for prefix in _ALLOWED_CHANGE_PREFIXES)


def _is_owned_path(raw_path: str) -> bool:
    path = raw_path.strip().strip('"')
    if path in _OWNED_EXACT or _named_stage14a_test(path):
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
    """Every Stage 14A module, checked for what it imports and what it names."""
    for relative in STAGE_14A_SOURCE_FILES:
        path = Path(repository_root) / relative
        if not path.is_file():
            raise Stage14AFinalizationError(
                f"{relative} is named as Stage 14A source and does not exist"
            )
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:  # pragma: no cover
            raise Stage14AFinalizationError(f"{relative}: {exc}") from exc

        every: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                every.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                every.append(node.module)
        for name in every:
            for forbidden in _FORBIDDEN_IMPORT_PREFIXES:
                if name == forbidden or name.startswith(forbidden + "."):
                    raise Stage14AFinalizationError(
                        f"{relative} imports {name}. A preflight that reached into "
                        "an algorithm, a runtime or a derivation would be a "
                        "preflight whose answers could depend on what had been run"
                    )
        for name in _module_level_imports(tree):
            for deferred in _DEFERRED_ONLY_IMPORT_PREFIXES:
                if name == deferred or name.startswith(deferred + "."):
                    raise Stage14AFinalizationError(
                        f"{relative} imports {name} at module level. Stage 14A "
                        "must stay importable on a runner with no scientific stack "
                        "and no vendor SDK"
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
            if any(
                value.startswith(permitted) or permitted.startswith(value)
                for permitted in _PERMITTED_PRIOR_STAGE_DOCUMENTS
            ):
                continue
            raise Stage14AFinalizationError(
                f"{relative} names the published evidence path {value!r}. Stage "
                "14A reads three prior markers and writes only its own directory"
            )


def _stage_14a_changed_paths(
    repository_root: Path, *, span_end_commit: str
) -> tuple[str, ...]:
    """Every path Stage 14A's span touched, attributed commit by commit."""
    commits = _git_output(
        repository_root,
        "rev-list",
        "--reverse",
        f"{STAGE_14A_BASELINE_COMMIT}..{span_end_commit}",
    )
    changed: set[str] = set()
    for commit in commits:
        if commit.strip().lower() in _NON_STAGE_14A_COMMITS_IN_SPAN:
            continue
        for path in _git_output(
            repository_root, "show", "--pretty=format:", "--name-only", commit
        ):
            changed.add(path.strip().strip('"'))
    return tuple(sorted(item for item in changed if item))


def verify_stage14a_workspace_boundaries(
    repository_root: Path, *, span_end_commit: str
) -> tuple[str, ...]:
    """Confirm Stage 14A stayed inside itself, across its whole span.

    Raises:
        Stage14AFinalizationError: the span touched a protected path, changed
            something outside the allowed set, or a Stage 14A module reached
            somewhere it may not.
    """
    _audit_source_boundaries(repository_root)
    changed = _stage_14a_changed_paths(
        repository_root, span_end_commit=span_end_commit
    )
    protected = sorted(
        path
        for path in changed
        if any(path.startswith(prefix) for prefix in _PROTECTED_PREFIXES)
    )
    if protected:
        raise Stage14AFinalizationError(
            f"Stage 14A's span changed protected paths {protected}. A closed "
            "stage's evidence and a prior algorithm's source are immutable here"
        )
    outside = sorted(path for path in changed if not _is_allowed_change(path))
    if outside:
        raise Stage14AFinalizationError(
            f"Stage 14A's span changed {outside}, which is outside the paths this "
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


def write_stage14a_evidence(
    repository_root: Path, *, include_marker: bool = True
) -> tuple[Path, ...]:
    """Derive and write the evidence, in the order the documents depend on.

    The eight derivable documents first, then the marker — which is derived
    against the *exact bytes* of everything else, including the hand-written
    README, so it has to come after them. That is the same two-commit shape every
    stage since 8D published under.

    Raises:
        Stage14AFinalizationError: a marker was asked for while the outcome is
            not final, or the tree is not clean apart from the marker being
            written.
    """
    from fpbench.experiments import stage14a_griaule_observations as observed
    from fpbench.experiments import stage14a_preflight as engine

    repository_root = Path(repository_root)
    engine.require_stage8e_is_the_policy_this_reuses(repository_root)
    predecessor = engine.require_stage13a_is_the_closed_predecessor(repository_root)
    engine.require_stage11b_is_unchanged(repository_root)

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

    if not preflight.is_final:
        waiting = [
            f"{item.kind.value}" for item in preflight.pending_reasons
        ] + [f"{item.action.value} at {item.gate.value}" for item in preflight.outstanding_actions]
        raise Stage14AFinalizationError(
            "no Stage 14A marker is written under a non-final outcome: the "
            f"preflight is {preflight.outcome} and is waiting on {waiting}. The "
            "documents are published and describe exactly that. A marker here "
            "would finalise a stage whose remaining steps are a reply nobody has "
            "sent or a job nobody has done (docs/adr/0121)"
        )

    require_expected_evidence_files(
        tuple(
            name
            for name in published_evidence_names(repository_root)
            if name != STAGE_14A_FINALIZATION_NAME
        )
        + (STAGE_14A_FINALIZATION_NAME,)
    )
    require_no_forbidden_published_data(repository_root)
    require_no_sensitive_published_data(repository_root)

    marker_relative = (EVIDENCE_DIRECTORY / STAGE_14A_FINALIZATION_NAME).as_posix()
    if not _tree_is_clean(repository_root, ignoring=(marker_relative,)):
        raise Stage14AFinalizationError(
            "the Stage 14A marker is derived against a clean tree and the exact "
            "committed bytes of every other document; commit them first"
        )
    commit = _head_commit(repository_root)
    verify_stage14a_workspace_boundaries(repository_root, span_end_commit=commit)
    byte_audit = _byte_audit(repository_root)

    hashed = tuple(
        name for name in REQUIRED_EVIDENCE_FILES if name != STAGE_14A_FINALIZATION_NAME
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
    marker = Stage14AFinalization(
        **claims,
        stage_14a_finalization_fingerprint=stage_14a_finalization_fingerprint(claims),
        created_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    written.append(write_evidence_json(directory / STAGE_14A_FINALIZATION_NAME, marker))
    return tuple(written)


def _byte_audit(repository_root: Path) -> Any:
    from fpbench.experiments.stage14a_acquisition import require_no_griaule_bytes_in_git

    return require_no_griaule_bytes_in_git(repository_root)


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
    from fpbench.experiments import stage14a_griaule_identity as frozen
    from fpbench.experiments import stage14a_preflight as engine
    from fpbench.experiments.stage14a_acquisition import acquisition_state

    acquisition = acquisition_state()
    declaration = acquisition.declaration
    inspection = engine.package_inspection() or {}

    def section(name: str) -> Mapping[str, Any]:
        value = inspection.get(name) if isinstance(inspection, Mapping) else None
        return value if isinstance(value, Mapping) else {}

    route = section("input_route")
    contract = section("score_contract")

    def gate_status(gate: frozen.PreflightGate) -> frozen.GateStatus:
        return preflight.status(gate)

    def gate_passed(gate: frozen.PreflightGate) -> bool:
        return gate_status(gate) is frozen.GateStatus.PASS

    def gate_result(gate: frozen.PreflightGate) -> bool | None:
        """True/false only when the gate observed an answer; otherwise unknown."""
        status = gate_status(gate)
        if status is frozen.GateStatus.PASS:
            return True
        if status is frozen.GateStatus.FAIL:
            return False
        return None

    def observed_at_gate(gate: frozen.PreflightGate, value: Any) -> Any | None:
        if gate_status(gate) in (frozen.GateStatus.PASS, frozen.GateStatus.FAIL):
            return value
        return None

    g1 = frozen.PreflightGate.OFFICIAL_ARTIFACT_AND_TRIAL_ACCESS
    g2 = frozen.PreflightGate.DIRECT_CANONICAL500_INPUT_ROUTE
    g3 = frozen.PreflightGate.SINGLE_FINGER_RAW_1TO1_SCORE_ROUTE
    g4 = frozen.PreflightGate.SCORE_AFFECTING_ROUTE_CLOSURE
    g1_blockers = {blocker.blocker_code for blocker in preflight.result(g1).blockers}
    obtained = acquisition.obtained

    return {
        "schema_version": STAGE_14A_SCHEMA_VERSION,
        "kind": STAGE_FINALIZATION_KIND,
        "outcome": preflight.outcome,
        "algorithm_slot": ALGORITHM_SLOT,
        "candidate": CANDIDATE_ID,
        "stage13a_outcome": STAGE_13A_OUTCOME,
        "stage13a_failure_class": STAGE_13A_FAILURE_CLASS,
        "stage13a_finalization_fingerprint": predecessor,
        "stage11b_finalization_fingerprint": STAGE_11B_FINALIZATION_FINGERPRINT,
        "stage8e_policy_fingerprint": STAGE8E_FINALIZATION_FINGERPRINT,
        "stage14a_source_fingerprint": stage14a_source_fingerprint(repository_root),
        "observations_fingerprint": observations_fingerprint,
        "preflight_fingerprint": preflight.preflight_fingerprint,
        "gate_count_defined": GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates_pending_access": preflight.gates_pending_access,
        "gates_awaiting_action": preflight.gates_awaiting_action,
        "product": PRODUCT_FAMILY,
        "implementation_version": declaration.product_version if declaration else None,
        "build_or_revision": declaration.build_or_revision if declaration else None,
        "platform": declaration.platform if declaration else None,
        "binding": (
            str(section("package_identity").get("binding"))
            if section("package_identity").get("binding")
            else None
        ),
        "package_sha256": declaration.sha256 if declaration else None,
        "implementation_origin": IMPLEMENTATION_ORIGIN,
        "official_package_obtained": obtained,
        "acquisition_status": acquisition.status.value,
        "vendor_refused": acquisition.status.is_refusal,
        "research_use_opens_execution": True if gate_passed(g1) else None,
        "research_use_blocked": (
            True
            if frozen.BlockerCode.RESEARCH_USE_BLOCKED in g1_blockers
            else False
            if gate_passed(g1)
            else None
        ),
        "bundled_trial_present": (
            declaration.bundled_trial_present if declaration else None
        ),
        "trial_activated": False,
        "license_bypass_attempted": False,
        "trial_reset_attempted": False,
        "canonical500_route": gate_result(g2),
        "fpbench_preprocessing_required": observed_at_gate(
            g2, bool(route.get("fpbench_preprocessing_required"))
        ),
        "vendor_internal_crop": observed_at_gate(
            g2, bool(route.get("vendor_internal_crop"))
        ),
        "single_finger_template": observed_at_gate(
            g3, bool(contract.get("single_image_single_template"))
        ),
        "raw_score_route": gate_result(g3),
        "score_native_type": (
            str(contract.get("native_type")) if contract.get("native_type") else None
        ),
        "score_direction": (
            str(contract.get("direction")) if contract.get("direction") else None
        ),
        "threshold_applied_inside_the_score": observed_at_gate(
            g3, bool(contract.get("threshold_changes_the_score"))
        ),
        "fpbench_score_transformation": FPBENCH_SCORE_TRANSFORMATION,
        "route_closed": gate_result(g4),
        # Counted only if G4 actually ran. A zero from an empty, unobserved
        # inventory would falsely publish a closed settings surface.
        "unresolved_score_affecting_settings": observed_at_gate(
            g4, len(engine.unresolved_score_affecting_settings())
        ),
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "scores_produced": 0,
        "sd300_image_bytes_read": False,
        "sd300_pair_manifest_read": False,
        "sd300_scores_read": False,
        "sd300_used": False,
        "prior_algorithm_scores_read": False,
        "production_adapter_created": False,
        "registry_integration_created": False,
        "canonical_experiment_config_created": False,
        "benchmark_run_performed": False,
        "result_set_produced": False,
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
        "stage13a_evidence_changed": False,
        "opens_stage_14b": preflight.opens_stage_14b,
        "reopens_algorithm_5_search": preflight.reopens_algorithm_5_search,
        "blockers": engine.marker_blocker_rows(preflight.blockers),
        "evidence_content_hashes": dict(evidence_content_hashes),
        "source_commit": commit,
        "source_tree_clean": True,
        "verifier_source_commit": commit,
        "verifier_source_tree_clean": True,
    }


def main(argv: list[str] | None = None) -> int:
    """``python -m fpbench.experiments.stage14a_finalization``.

    ``documents`` writes everything but the marker; ``publish`` writes the marker
    too and refuses a dirty tree — and refuses a non-final outcome. ``status``
    derives everything and prints the outcome, the gates and what remains,
    without writing anything.
    """
    from fpbench.experiments import stage14a_griaule_identity as ids
    from fpbench.experiments import stage14a_griaule_observations as observed
    from fpbench.experiments import stage14a_preflight as engine
    from fpbench.experiments.stage14a_acquisition import (
        REQUEST_STATUS,
        acquisition_state,
    )

    parser = argparse.ArgumentParser(description="Stage 14A evidence")
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
        preflight = engine.run_preflight()
        state = acquisition_state()
        print(f"algorithm slot           {ALGORITHM_SLOT}")
        print(f"candidate                {CANDIDATE_ID}")
        print(f"product                  {PRODUCT_FAMILY}")
        print(f"version                  {IMPLEMENTATION_VERSION_SENTINEL}")
        print(f"outcome                  {preflight.outcome}")
        print(f"writes a marker          {preflight.is_final}")
        print(f"request                  {REQUEST_STATUS.value}")
        print(f"acquisition              {state.status.value}")
        print(f"package presence         {state.presence.value}")
        print(
            "failure class            "
            + (preflight.failure_class.value if preflight.failure_class else "none")
        )
        print(f"opens stage 14b          {preflight.opens_stage_14b}")
        print(f"observations             {observed.observations_fingerprint()}")
        print(f"preflight                {preflight.preflight_fingerprint}")
        width = max(len(gate.value) for gate in ids.GATE_ORDER)
        for index, result in enumerate(preflight.results, start=1):
            print(f"{index:>2}  {result.gate.value:<{width}}  {result.status.value}")
        if preflight.blockers:
            print(f"blockers                 {len(preflight.blockers)}")
            for blocker in preflight.blockers:
                print(f"  {blocker.gate.value:<36s} {blocker.blocker_code.value}")
        for pending in preflight.pending_reasons:
            print(f"pending                  {pending.kind.value}")
            for item in pending.what_is_outstanding:
                print(f"    - {item}")
        for action in preflight.outstanding_actions:
            print(f"outstanding action       {action.action.value}")
            for item in action.what_remains:
                print(f"    - {item}")
        return 0

    written = write_stage14a_evidence(
        root, include_marker=arguments.action == "publish"
    )
    for path in written:
        print(path.relative_to(root).as_posix())
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
