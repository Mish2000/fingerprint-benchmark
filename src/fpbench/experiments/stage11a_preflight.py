"""The seventeen hard gates, run in order, and the verdict that follows.

The engine has no verdict parameter, for the reason Stage 8E's decision engine
has none and Stage 10B's preflight has none: an engine that accepted an outcome
and then validated it would be a very elaborate way of writing the outcome down.
It reads the frozen record in
:mod:`fpbench.experiments.stage11a_verifinger_observations`, the state of the
local artifact store, and Stage 8E's own policy, applies the order frozen in
:mod:`fpbench.experiments.stage11a_verifinger_identity`, and reports what follows.

**Fail-fast is the design, not an optimisation.** The candidate stops at the
first gate it fails and every later gate is published ``NOT_REACHED``. The order
is the specification's: the artifact first, because every other question is a
question about an artifact; the raw score before latency and provenance, because
a route with no scalar score is not worth measuring (spec section 44).

**A gate is answered from the artifact or it is not answered.** Every runner
below reaches its conclusion from bytes that were pinned by digest — the archive,
the manual that ships inside it, upstream's own tutorials — or from the state of
this machine. Where the answer needs a *running licensed engine*, the runner says
so and does not substitute documentation for it: what a manual says a default is
worth is not what the engine was constructed with.

Nothing here reads SD300, reads a prior algorithm's scores, downloads anything,
activates a licence, loads a vendor library or produces a score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.serialization import stable_hash
from fpbench.core.verifinger_preflight_errors import (
    Stage11AFinalizationError,
    VeriFingerGateError,
    VeriFingerSensitiveEvidenceError,
)
from fpbench.experiments import stage11a_artifacts as store
from fpbench.experiments import stage11a_verifinger_identity as frozen
from fpbench.experiments import stage11a_verifinger_observations as observed
from fpbench.third_party import (
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    NonBlockingRestriction,
    PlausibleReading,
    RedistributionDecision,
    RedistributionRecord,
    ResearchUseAssessment,
    ThirdPartyComponentKind,
    assess_research_use,
    policy_fingerprint,
    project_purpose,
)

__all__ = [
    "Blocker",
    "GateResult",
    "VeriFingerPreflight",
    "require_stage8e_is_the_policy_this_reuses",
    "require_stage10b_is_the_closed_predecessor",
    "license_observation",
    "research_use_assessment",
    "redistribution_record",
    "unresolved_score_affecting_settings",
    "run_preflight",
    "evidence_document",
    "marker_blocker_rows",
    "find_sensitive_material",
    "require_no_sensitive_material",
]


# ------------------------------------------------------------ the closed stages


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 11A reuses is the policy it was written against.

    Raises:
        Stage11AFinalizationError: the published Stage 8E marker, the live
            purpose or the live policy has moved. Stage 11A does not repair
            Stage 8E and does not proceed around it — a corrective policy stage
            is the response, not a quiet edit from here.
    """
    relative = "evidence/stage8e-research-only-policy/stage-8e-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 8E")
    expected = {
        "outcome": frozen.STAGE8E_OUTCOME,
        "stage_8e_finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
        "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage11AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 11A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here"
            )
    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage11AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every Stage 11A decision would be taken under a "
            "different premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage11AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage 8E "
            "published"
        )


def require_stage10b_is_the_closed_predecessor(repository_root: Path) -> str:
    """Confirm Stage 10B still says what Stage 11A was written after.

    Stage 11A exists because Stage 10B failed on access and opened a candidate
    search. Binding that marker's fingerprint is what makes "Stage 10B was not
    re-opened to admit VeriFinger" a checkable claim rather than an intention.

    Returns:
        The predecessor fingerprint, for the marker to carry.

    Raises:
        Stage11AFinalizationError: Stage 10B's marker has moved.
    """
    relative = f"{frozen.STAGE_10B_EVIDENCE_DIRECTORY}/stage-10b-finalization.json"
    marker = _read_marker(repository_root, relative, "Stage 10B")
    expected = {
        "outcome": frozen.STAGE_10B_OUTCOME,
        "stage_10b_finalization_fingerprint": (
            frozen.STAGE_10B_FINALIZATION_FINGERPRINT
        ),
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage11AFinalizationError(
                f"the Stage 10B marker's {key} is {found!r} and Stage 11A was "
                f"written after {value!r}. Stage 10B is immutable here"
            )
    if marker.get("opens_candidate_search") is not True:
        raise Stage11AFinalizationError(
            "Stage 10B's marker no longer opens a candidate search, and a "
            "candidate search is the only thing Stage 11A is a response to"
        )
    if marker.get("stage_10c_reserved_for_this_candidate") is not True:
        raise Stage11AFinalizationError(
            "Stage 10B reserved Stage 10C for id3, and Stage 11A exists as a "
            "separate number precisely so that reservation holds"
        )
    return frozen.STAGE_10B_FINALIZATION_FINGERPRINT


def _read_marker(
    repository_root: Path, relative: str, stage: str
) -> Mapping[str, Any]:
    import json

    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage11AFinalizationError(
            f"cannot read the {stage} marker Stage 11A binds at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage11AFinalizationError(f"the {stage} marker is not a JSON object")
    return marker


# ------------------------------------------------------------------- Stage 8E


#: Every licence notice this stage read, each inside the pinned archive and each
#: cited by the digest of the document it was read from.
_LICENSE_EVIDENCE = (
    LicenseEvidence(
        locator="Neurotec_Biometric_2025_2_SDK/Documentation/SDK License.html",
        description=(
            "the SDK licence agreement shipped inside the pinned archive, headed "
            "'VeriFinger 2025.2, VeriLook 2025.2, VeriEye 2025.2, VeriSpeak "
            "2025.2, MegaMatcher 2025.2 SDK'"
        ),
        document_sha256=(
            "e630df7aa7d72f7f030875cf911ffab7f2a2e1fd3b99de26b8f803a95e7aee10"
        ),
    ),
    LicenseEvidence(
        locator="Neurotec_Biometric_2025_2_SDK/Documentation/Activation.pdf",
        description=(
            "the activation guide shipped inside the same archive, which states "
            "the trial terms and that engaging with the products through trial "
            "or activation constitutes agreement to the licence agreement"
        ),
        document_sha256=(
            "7bfd029689c56796bcb7f5b5e3a2d94daefe325eb8e904afeb5a2e36ae2162b3"
        ),
    ),
)

#: The restrictions the agreement actually states, in Stage 8E's shared
#: vocabulary. Every one is recorded, respected, and not a blocker: none of them
#: touches one person running one program on one machine and publishing no bytes
#: (docs/adr/0081).
_NON_BLOCKING_RESTRICTIONS = (
    NonBlockingRestriction.NON_COMMERCIAL_ONLY,
    NonBlockingRestriction.NO_REDISTRIBUTION,
    NonBlockingRestriction.NO_SUBLICENSING,
    NonBlockingRestriction.COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT,
    NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
)


def license_observation() -> LicenseObservation:
    """What Neurotechnology's notices say about the acquired archive.

    ``NON_COMMERCIAL`` is the narrowest member of Stage 8E's closed vocabulary
    that is *true of the route this stage acquired*. The agreement is a
    proprietary commercial SDK licence, and the vocabulary has no member for one;
    but the artifact here was obtained under the trial, and the vendor's own
    activation guide states that the purpose of a trial product is to explore SDK
    functionality rather than end-user deployment, with a commercial licence
    required for anything beyond it. Recording that as ``NON_COMMERCIAL`` with
    ``COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT`` beside it states
    both halves.

    Stage 8E is closed, so its vocabulary was not extended to add a proprietary
    member; the mismatch is published in the usage-binding document instead of
    being resolved by editing a finished stage (docs/adr/0099).
    """
    return LicenseObservation(
        observation_id="verifinger_2025_2_sdk_trial_license",
        component_kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the VeriFinger 2025.2 SDK as delivered in the pinned "
            "Neurotec_Biometric_2025_2_SDK archive, under its trial licence"
        ),
        status=LicenseObservationStatus.NON_COMMERCIAL,
        declared_license_names=("Neurotechnology SDK License Agreement",),
        evidence=_LICENSE_EVIDENCE,
        stated_restrictions=(
            "a personal, non-exclusive licence to use the SDK for designing, "
            "developing, testing and distributing Licensee Products",
            "the SDK may only be used for a purpose or in a manner for which it "
            "was designed",
            "sharing, publishing, renting, leasing or transferring the software "
            "is forbidden, as is redistribution other than as prescribed",
            "reverse engineering, decompiling and deriving the algorithms is "
            "forbidden, as is circumventing the protection mechanisms",
            "copyright and attribution notices may not be removed or obscured",
            "the trial is a 30-day period whose purpose is to explore SDK "
            "functionality rather than end-user deployment",
        ),
        notes=(
            "Read from the agreement inside the pinned archive rather than from "
            "a licence page on the vendor's website, so the terms and the "
            "runtime cannot drift apart.",
            "Stage 11A executes nothing, so this observation records permission "
            "and not performance.",
        ),
    )


#: How a reasonable reader could understand the notices. Both notices are read
#: separately, because "the EULA permits development and testing" and "the trial
#: is for exploring functionality" are different sentences in different documents
#: and the conservative answer is the intersection of them.
_PLAUSIBLE_READINGS = (
    PlausibleReading(
        notice_locator=(
            "Neurotec_Biometric_2025_2_SDK/Documentation/SDK License.html"
        ),
        permits_local_execution=True,
        permits_non_commercial_use=True,
        permits_educational_research=True,
    ),
    PlausibleReading(
        notice_locator=(
            "Neurotec_Biometric_2025_2_SDK/Documentation/Activation.pdf"
        ),
        permits_local_execution=True,
        permits_non_commercial_use=True,
        permits_educational_research=True,
    ),
)


def research_use_assessment() -> ResearchUseAssessment:
    """Whether fpbench may execute this component locally, under its purpose.

    Derived rather than asserted: the caller supplies the observation, the
    restrictions and the readings, and Stage 8E's own engine returns the one
    decision that follows (docs/adr/0082).
    """
    return assess_research_use(
        license_observation(),
        assessment_id="verifinger_2025_2_local_research_execution",
        basis=(
            "One person, on one machine, runs the vendor's own 1:1 verification "
            "route over fingerprint images, keeps every byte of the SDK outside "
            "this public repository, publishes no template and sells nothing. "
            "Every plausible reading of both notices permits local execution for "
            "non-commercial educational research: the agreement grants use for "
            "designing, developing and testing, and the trial exists to explore "
            "the SDK's functionality. The restrictions that do bite — no "
            "redistribution, no sublicensing, a commercial licence for "
            "deployment, notice retention — are recorded and respected, and none "
            "of them touches this operation (docs/adr/0081, docs/adr/0082)."
        ),
        non_blocking_restrictions=_NON_BLOCKING_RESTRICTIONS,
        intersection_readings=_PLAUSIBLE_READINGS,
        identity_established=True,
    )


def redistribution_record() -> RedistributionRecord:
    """What upstream permits by way of redistribution, and what fpbench does."""
    return RedistributionRecord(
        decision=RedistributionDecision.NOT_ALLOWED,
        basis=(
            "The agreement forbids sharing, publishing, renting or leasing the "
            "software and any redistribution other than as prescribed. fpbench "
            "redistributes nothing in any case: the archive, the manual, the "
            "data files and every native library stay in the local artifact "
            "store, outside the working tree, and the repository holds only "
            "descriptions of them — a locator, a size, a digest (docs/adr/0083)."
        ),
        redistributed_by_fpbench=False,
    )


# ------------------------------------------------------------------- the gates


@dataclass(frozen=True, slots=True)
class Blocker:
    """One reason VeriFinger cannot enter fpbench as Algorithm 4.

    ``how_this_would_be_lifted`` is mandatory. A blocker nobody can act on is a
    blocker nobody can lift, and every blocker this stage can raise is one a
    person could lift deliberately.
    """

    gate: frozen.PreflightGate
    blocker_code: frozen.BlockerCode
    affected_component: str
    evidence: str
    why_this_blocks_algorithm_4: str
    how_this_would_be_lifted: str

    def __post_init__(self) -> None:
        permitted = dict(frozen.GATE_BLOCKERS)[self.gate]
        if self.blocker_code not in permitted:
            raise VeriFingerGateError(
                f"{self.blocker_code.value} does not belong to "
                f"{self.gate.value}; it belongs to "
                f"{[item.value for item in frozen.gate_of_blocker(self.blocker_code)]}"
                " and raising it here would put the reason in the wrong place"
            )
        for name in (
            "affected_component",
            "evidence",
            "why_this_blocks_algorithm_4",
            "how_this_would_be_lifted",
        ):
            if not str(getattr(self, name)).strip():
                raise VeriFingerGateError(f"{self.blocker_code.value}: {name} is empty")


@dataclass(frozen=True, slots=True)
class GateResult:
    """One gate's conclusion."""

    gate: frozen.PreflightGate
    status: frozen.GateStatus
    summary: str
    blockers: tuple[Blocker, ...] = ()

    def __post_init__(self) -> None:
        if self.status is frozen.GateStatus.PASS and self.blockers:
            raise VeriFingerGateError(
                f"{self.gate.value}: a gate that passed carries no blockers; a "
                "blocker is not a reservation to be weighed"
            )
        if self.status is frozen.GateStatus.FAIL and not self.blockers:
            raise VeriFingerGateError(f"{self.gate.value}: a gate that failed names why")
        if self.status is frozen.GateStatus.NOT_REACHED and self.blockers:
            raise VeriFingerGateError(
                f"{self.gate.value}: a gate that was never reached cannot have "
                "found anything"
            )
        for blocker in self.blockers:
            if blocker.gate is not self.gate:
                raise VeriFingerGateError(
                    f"{self.gate.value}: carries a blocker raised at "
                    f"{blocker.gate.value}"
                )


def unresolved_score_affecting_settings() -> tuple[observed.PublishedSetting, ...]:
    """Every score-affecting setting with no upstream authority behind a value.

    The count this returns is the stage's central finding about configuration. A
    setting nobody recorded still decides the score, and "it was whatever the
    engine happened to be constructed with" is not an upstream authority — it
    becomes one only when somebody reads it off a running engine and records it
    as a ``DELIVERED_RUNTIME_DEFAULT`` (spec section 15).
    """
    return tuple(
        item
        for item in (
            *observed.PUBLISHED_EXTRACTOR_SETTINGS,
            *observed.PUBLISHED_MATCHER_SETTINGS,
        )
        if item.is_unresolved_score_affecting_default
    )


def _unresolved(items: tuple[observed.PublishedSetting, ...]) -> tuple[str, ...]:
    return tuple(
        item.name for item in items if item.is_unresolved_score_affecting_default
    )


def _execution_blocker(
    gate: frozen.PreflightGate,
    *,
    component: str,
    why: str,
    code: frozen.BlockerCode = frozen.BlockerCode.LOCAL_SMOKE_FAILED,
) -> Blocker:
    """The one blocker shape seven gates share.

    Written once rather than seven times, because seven copies of the same
    sentence drift into seven slightly different claims, and the claim matters:
    nothing here failed. Nothing ran.
    """
    state = store.qualification_run_state()
    return Blocker(
        gate=gate,
        blocker_code=code,
        affected_component=component,
        evidence=(
            f"{state.reason}. The artifact is present and verified, and the "
            "documentation describes the intended behaviour, but a documented "
            "intention is not a measurement: this gate is about what a running "
            "licensed engine does."
        ),
        why_this_blocks_algorithm_4=why,
        how_this_would_be_lifted=(
            "The maintainer activates the 30-day trial on one chosen platform — "
            "the vendor's documented route is Trial = true in the licensing "
            "configuration and starting the licensing service, with no serial "
            "number and no personal information — runs the bounded qualification "
            "harness on fixtures that are not SD300, and re-runs this stage. No "
            "licence is bypassed, no trial is reset and no protection mechanism "
            "is touched (spec section 32)."
        ),
    )


# ------------------------------------------------------------------ gate 1


def _gate_official_artifact_acquisition() -> GateResult:
    """Gate 1. Is an exact official artifact here?

    The gate Stage 10B could not pass, and the reason this stage exists in the
    shape it does: Neurotechnology publishes a direct locator, so the answer is
    settled by fetching the bytes and hashing them rather than by reading a page
    about how to request them (docs/adr/0100).
    """
    state = store.acquisition_state()
    if state.obtained:
        return GateResult(
            gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{len(state.states)} official artifacts obtained from "
                "Neurotechnology's own download host and verified by size and "
                "SHA-256: the "
                f"{observed.SDK_ARCHIVE.size_bytes}-byte 2025.2 SDK archive and "
                f"the {observed.DOCUMENTATION_PDF.size_bytes}-byte manual, which "
                "is byte-for-byte the manual inside the archive. One route was "
                f"chosen — {observed.SDK_ARCHIVE.route.value} — and "
                f"{len(observed.REJECTED_ROUTES)} was not."
            ),
        )
    detail = "; ".join(
        f"{item.filename}: {item.presence.value} — {item.detail}"
        for item in state.unverified
    )
    return GateResult(
        gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        status=frozen.GateStatus.FAIL,
        blockers=(
            Blocker(
                gate=frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
                blocker_code=frozen.BlockerCode.OFFICIAL_ARTIFACT_NOT_OBTAINABLE,
                affected_component="the official VeriFinger 2025.2 artifacts",
                evidence=(
                    "acquisition-manifest.json names the locator, filename, byte "
                    f"size and SHA-256 of each artifact. On this machine: {detail}"
                ),
                why_this_blocks_algorithm_4=(
                    "Every remaining gate is a question about the artifact's own "
                    "bytes — its identity, its models, its input route, its "
                    "profiles, its score API. None of them can be answered "
                    "about an archive nobody holds, and answering them from a "
                    "product page would be publishing a benchmark route this "
                    "project had never opened."
                ),
                how_this_would_be_lifted=(
                    "Fetch the artifacts from the recorded official locators "
                    "into the local artifact store under this stage's prefix, "
                    "and re-run. The locators need no account, no form and no "
                    "vendor approval."
                ),
            ),
        ),
        summary=(
            "the frozen artifacts are not present and verified in the local "
            "artifact store"
        ),
    )


# ------------------------------------------------------------------ gate 2


def _gate_runtime_identity() -> GateResult:
    """Gate 2. Is the thing that would compute a score exactly identified?

    The requirement is that a version printed on a web page is not an algorithm
    identity (spec section 6). What answers it here is stronger than a page and
    weaker than a running engine: the version compiled into each native library's
    own resource block, the archive's own revision file, the licence agreement's
    own heading, and upstream's own tutorial declaring the version it is written
    for. Four independent statements inside the pinned bytes, all saying 2025.2.

    The one field that a running engine would add — a version string emitted by a
    loaded library — is published as not read, rather than quietly counted as
    though the binary's resource block had been printed by the binary.
    """
    libraries = observed.WINDOWS_X64_NATIVE_LIBRARIES
    versions = {item.product_version for item in libraries}
    if len(versions) != 1:
        return GateResult(
            gate=frozen.PreflightGate.RUNTIME_IDENTITY,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.RUNTIME_IDENTITY,
                    blocker_code=frozen.BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED,
                    affected_component="the native libraries of the chosen platform",
                    evidence=(
                        "the libraries do not agree about their own version: "
                        f"{sorted(versions)}"
                    ),
                    why_this_blocks_algorithm_4=(
                        "A route assembled from libraries of different builds is "
                        "a route with no identity to pin."
                    ),
                    how_this_would_be_lifted=(
                        "Re-acquire the archive and re-read the version "
                        "resources; a mixture means the inspected tree is not "
                        "the delivered one."
                    ),
                ),
            ),
            summary="the native libraries disagree about their own version",
        )
    return GateResult(
        gate=frozen.PreflightGate.RUNTIME_IDENTITY,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.IMPLEMENTATION_ORIGIN}: "
            f"{observed.PRODUCT_IDENTITY_CLAIM.product_name} by "
            f"{observed.PRODUCT_IDENTITY_CLAIM.vendor}, identified from inside "
            f"the pinned bytes by {len(observed.PRODUCT_IDENTITY_CLAIM.supporting_sources)} "
            f"independent statements. {len(libraries)} native libraries of the "
            f"chosen platform carry ProductVersion {sorted(versions)[0]!r}, and "
            "the archive declares revision 20260612. No version here was read "
            "from a web page, and none was read from a running library."
        ),
    )


# ------------------------------------------------------------------ gate 3


def _gate_research_use_permission() -> GateResult:
    """Gate 3. Does Stage 8E permit executing this component locally?

    Answered through Stage 8E's own mechanism and not beside it: an observation
    of what the notices say, an assessment derived from it, and a redistribution
    record. The notices are the ones inside the pinned archive (spec section 7).
    """
    assessment = research_use_assessment()
    if not assessment.decision.opens_execution:
        return GateResult(
            gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
                    blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED,
                    affected_component="the VeriFinger 2025.2 SDK",
                    evidence=(
                        "third-party-usage-binding.json: Stage 8E returned "
                        f"{assessment.decision.value} over the notices inside the "
                        "pinned archive, with blockers "
                        f"{[item.value for item in assessment.blockers]}"
                    ),
                    why_this_blocks_algorithm_4=(
                        "A component this project may not execute cannot be "
                        "qualified by executing it, and a benchmark route nobody "
                        "is permitted to run is not a route."
                    ),
                    how_this_would_be_lifted=(
                        "Only upstream can lift it, by terms that permit the "
                        "declared use. It is not lifted by reading the notices "
                        "again more optimistically (docs/adr/0082)."
                    ),
                ),
            ),
            summary=f"Stage 8E returned {assessment.decision.value}",
        )
    return GateResult(
        gate=frozen.PreflightGate.RESEARCH_USE_PERMISSION,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{assessment.decision.value} with intended-use permission "
            f"{assessment.intended_use_permission_status.value}: every plausible "
            f"reading of {len(_PLAUSIBLE_READINGS)} notices inside the pinned "
            "archive permits one person executing this locally for non-commercial "
            f"educational research. {len(_NON_BLOCKING_RESTRICTIONS)} restrictions "
            "are recorded and respected, and redistribution is "
            f"{redistribution_record().decision.value} — which changes nothing, "
            "because fpbench redistributes nothing."
        ),
    )


# ------------------------------------------------------------------ gate 4


def _gate_artifact_closure() -> GateResult:
    """Gate 4. Is the runtime dependency closure complete?

    The question is whether anything the route needs lives outside the pinned
    bytes. It does not: the fingerprint algorithm's two data files ship inside
    the archive, and there is no model download at first use to pin separately
    (spec section 9).
    """
    data_files = observed.FINGER_DATA_FILES
    if not data_files:  # pragma: no cover - a constant-table mistake
        return GateResult(
            gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
                    blocker_code=(
                        frozen.BlockerCode.REQUIRED_RUNTIME_COMPONENT_MISSING
                    ),
                    affected_component="the fingerprint algorithm's data files",
                    evidence="no fingerprint data file was found in the archive",
                    why_this_blocks_algorithm_4=(
                        "An algorithm whose model is fetched from somewhere else "
                        "is an algorithm that can change without the pinned "
                        "package changing."
                    ),
                    how_this_would_be_lifted=(
                        "Locate the model, pin it by size and digest as an "
                        "artifact in its own right, and re-run."
                    ),
                ),
            ),
            summary="the closure could not be completed",
        )
    total = sum(item.size_bytes for item in data_files)
    return GateResult(
        gate=frozen.PreflightGate.ARTIFACT_CLOSURE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"closed over {observed.ARCHIVE_MEMBER_COUNT} archive members "
            f"totalling {observed.ARCHIVE_UNCOMPRESSED_BYTES} bytes, every one "
            f"hashed. The fingerprint algorithm's {len(data_files)} data files — "
            f"{total} bytes — are inside the pinned archive, so nothing is "
            f"fetched at first use and the {frozen.EMBEDDED_MODEL_MARKER} case "
            "does not arise for them. No external model, service or accelerator "
            "is required."
        ),
    )


# ------------------------------------------------------------------ gate 5


def _gate_canonical500_input_route() -> GateResult:
    """Gate 5. Can ``canonical_500`` enter through an official route unchanged?

    Three things have to hold: the container is in the official input domain, the
    resolution the benchmark already carries is the resolution the SDK works in,
    and the official route asks fpbench to do nothing to the pixels
    (spec sections 11 and 12).
    """
    if frozen.BENCHMARK_INPUT_PIXEL_FORMAT != "gray8":  # pragma: no cover
        raise VeriFingerGateError("the benchmark input profile has changed")
    if "PNG" not in observed.SUPPORTED_IMAGE_CONTAINERS:  # pragma: no cover
        return GateResult(
            gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
            status=frozen.GateStatus.FAIL,
            blockers=(
                Blocker(
                    gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
                    blocker_code=(
                        frozen.BlockerCode.CANONICAL500_INPUT_ROUTE_UNRESOLVED
                    ),
                    affected_component="the canonical_500 PNG input",
                    evidence="PNG is not in the official input domain",
                    why_this_blocks_algorithm_4=(
                        "Converting the benchmark's images to suit a candidate "
                        "would be fpbench choosing a preprocessing step."
                    ),
                    how_this_would_be_lifted=(
                        "An upstream statement that the container is supported."
                    ),
                ),
            ),
            summary="PNG is not in the official input domain",
        )
    return GateResult(
        gate=frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
        status=frozen.GateStatus.PASS,
        summary=(
            "the pinned manual puts PNG in the official input domain, requires "
            "resolution attributes on a fingerprint image, and expresses minutia "
            "coordinates in 500 DPI units — which is what canonical_500 already "
            "is. Upstream's own 1:1 tutorial sets a file name and verifies: no "
            f"crop, no resize, no rotation, no enhancement. All "
            f"{len(frozen.REFUSED_PREPROCESSING)} refused preprocessing steps "
            "stay refused, and the segmentation and quality processing the SDK "
            "performs internally needs no external choice from fpbench."
        ),
    )


# ------------------------------------------------------------------ gate 6


def _gate_extraction_profile() -> GateResult:
    """Gate 6. Is every extraction setting that can change a template frozen?

    Two halves, and both are required. The *inventory* is closed: the pinned
    manual publishes the complete set of fingerprint extraction settings the
    engine exposes, and this stage enumerated it rather than guessing at names.
    The *values* are not: the manual states a default for the face-side settings
    and states none for the fingerprint-side ones, so a value for each would have
    to be read off a constructed engine and recorded as a delivered runtime
    default (spec sections 14 and 15, docs/adr/0101).

    Passing on a closed inventory alone would be the failure the whole apparatus
    exists to prevent: a profile called frozen while most of the settings that
    decide the score have no recorded value at all.
    """
    settings = observed.PUBLISHED_EXTRACTOR_SETTINGS
    unresolved = _unresolved(settings)
    resolved = tuple(
        item.name
        for item in settings
        if item.is_score_affecting and item.provenance.is_upstream_authority
    )
    if not unresolved:
        return GateResult(
            gate=frozen.PreflightGate.EXTRACTION_PROFILE,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{len(settings)} published extraction settings inventoried, and "
                "every score-affecting one carries a value with an upstream "
                "provenance"
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.EXTRACTION_PROFILE,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.EXTRACTION_PROFILE,
                code=frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,
                component=(
                    f"{len(unresolved)} score-affecting extraction settings: "
                    + ", ".join(unresolved)
                ),
                why=(
                    "Each of these changes the template, and therefore the score. "
                    "The pinned manual gives every one of them a type and a "
                    "meaning and states a default for none of them — while it "
                    "does state defaults for the face-side settings in the same "
                    "tables, so the absence is a property of the document rather "
                    "than of the reading. A value nobody recorded still decides "
                    "the score, and a profile with "
                    f"{len(unresolved)} unrecorded values is not frozen. What "
                    f"is settled is the inventory itself and the "
                    f"{len(resolved)} setting whose value upstream's own 1:1 "
                    "tutorial chooses explicitly (docs/adr/0101)."
                ),
            ),
        ),
        summary=(
            f"the inventory is closed over {len(settings)} published extraction "
            f"settings and {len(unresolved)} score-affecting values have no "
            "upstream authority behind them"
        ),
    )


# ------------------------------------------------------------------ gate 7


def _gate_representation_profile() -> GateResult:
    """Gate 7. Which representation is actually compared?

    The pinned manual and upstream's own tutorials answer it: the matchers
    receive the proprietary template, and ISO and ANSI records are export formats
    the enrolment tutorial writes only when asked. Choosing ISO because it is
    easier to store would be choosing a different algorithm (spec section 18).
    """
    return GateResult(
        gate=frozen.PreflightGate.REPRESENTATION_PROFILE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value}: the "
            "manual states that a packed proprietary template is what the "
            "matchers should receive, and upstream's 1:1 tutorial exports "
            "nothing. ISO and ANSI are export formats and MINEX is a separate "
            "matching scenario, so an interoperable route would be a different "
            f"profile with its own identity. Only "
            f"{len(frozen.PUBLISHABLE_REPRESENTATION_FACTS)} facts about a "
            "template are publishable and the template itself is not among them."
        ),
    )


# ------------------------------------------------------------------ gate 8


def _gate_matcher_profile() -> GateResult:
    """Gate 8. Is every matching setting that can change the score frozen?

    The same two halves as extraction, and the same answer: the inventory is
    closed and the values are not. ``FingersMatchingSpeed`` is the preset family
    the specification warns about — Low, Medium and High, documented as an
    accuracy trade-off — and it is not chosen by trying all three and keeping the
    prettiest. Upstream's own 1:1 tutorial sets ``LOW`` explicitly, which is an
    authority; the rest have none (spec sections 17 and 20).
    """
    settings = observed.PUBLISHED_MATCHER_SETTINGS
    unresolved = _unresolved(settings)
    if not unresolved:
        return GateResult(
            gate=frozen.PreflightGate.MATCHER_PROFILE,
            status=frozen.GateStatus.PASS,
            summary=(
                f"{len(settings)} published matching settings inventoried, and "
                "every score-affecting one carries a value with an upstream "
                "provenance"
            ),
        )
    return GateResult(
        gate=frozen.PreflightGate.MATCHER_PROFILE,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.MATCHER_PROFILE,
                code=frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,
                component=(
                    f"{len(unresolved)} score-affecting matching settings: "
                    + ", ".join(unresolved)
                ),
                why=(
                    "Rotation tolerance and the matching scenario change the "
                    "score directly, and the manual states no default for "
                    "either. The preset that is settled is settled by upstream "
                    "rather than by fpbench: the vendor's own 1:1 tutorial sets "
                    "FingersMatchingSpeed to LOW, and no preset here was picked "
                    "by comparing score distributions (spec section 17)."
                ),
            ),
        ),
        summary=(
            f"the inventory is closed over {len(settings)} published matching "
            f"settings and {len(unresolved)} score-affecting values have no "
            "upstream authority behind them"
        ),
    )


# ------------------------------------------------------------------ gate 9


def _gate_raw_score_route() -> GateResult:
    """Gate 9. Is there exactly one scalar raw score, with no threshold in it?

    The decisive gate, and the artifact answers it. The manual defines the result
    of a comparison as a similarity score, higher meaning more similar; publishes
    the score-to-FAR correspondence explicitly; and keeps the threshold in a
    separate settable engine property. Upstream's own 1:1 tutorial reads the
    integer score under ``MATCH_NOT_FOUND`` as well as under ``OK``, which is the
    proof that the number survives a negative decision rather than being replaced
    by one (spec sections 21 to 24, docs/adr/0102).
    """
    return GateResult(
        gate=frozen.PreflightGate.RAW_SCORE_ROUTE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.value}: one "
            f"{observed.DOCUMENTED_SCORE_TYPE} per attempt, "
            f"{observed.DOCUMENTED_SCORE_DIRECTION}, on the vendor's own "
            "claimed-FAR scale with "
            f"{len(observed.DOCUMENTED_SCORE_ANCHORS)} published anchor points. "
            "The threshold is a separate engine property and the sample reads "
            "the score under both outcomes, so no threshold is inside the "
            "number. fpbench converts nothing in either direction."
        ),
    )


# ------------------------------------------------------------------ gates 10-13


def _gate_pair_orientation() -> GateResult:
    """Gate 10. Does ``score(A, B)`` equal ``score(B, A)``?

    A question about behaviour, and only running answers it. The API names its
    arguments reference and candidate and returns the result on the reference
    side, so the roles are distinguished — but whether the number depends on
    which side is which is not something a manual can be read off (spec 25).
    """
    return GateResult(
        gate=frozen.PreflightGate.PAIR_ORIENTATION,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.PAIR_ORIENTATION,
                code=frozen.BlockerCode.PAIR_ORDER_SEMANTICS_UNRESOLVED,
                component="the reference/probe contract of the 1:1 route",
                why=(
                    "If the two orderings differ, a run that fed pairs in "
                    "whichever order they came in would be averaging two "
                    "different measurements without saying so. fpbench may "
                    "neither average the two nor take their maximum, so the "
                    "orientation has to be discovered and preserved."
                ),
            ),
        ),
        summary="both orderings must be run on fixtures, and nothing has been run",
    )


def _gate_self_semantics() -> GateResult:
    """Gate 11. Can ``SELF(A, A)`` be executed as two independent extractions?"""
    return GateResult(
        gate=frozen.PreflightGate.SELF_SEMANTICS,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.SELF_SEMANTICS,
                component="SELF(A, A) as two independent extractions",
                why=(
                    "A pairwise route makes this easy to get wrong: an engine "
                    "that noticed the two sides were the same file could return "
                    "a constant, and that constant would be a number about "
                    "fpbench's own plumbing rather than about the algorithm. The "
                    "rule is frozen either way — two loads, two extractions, no "
                    "representation reuse — and demonstrating that the engine "
                    "obeys it needs the engine (docs/adr/0070)."
                ),
            ),
        ),
        summary="the SELF rule is frozen and its demonstration needs a running engine",
    )


def _gate_score_determinism() -> GateResult:
    """Gate 12. Is the score identical at all three levels?"""
    return GateResult(
        gate=frozen.PreflightGate.SCORE_DETERMINISM,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.SCORE_DETERMINISM,
                component=(
                    "the same fixture pair's score at all "
                    f"{len(frozen.DETERMINISM_LEVELS)} levels"
                ),
                why=(
                    "A benchmark whose numbers move between runs is not a "
                    "benchmark. The templates themselves may vary without that "
                    "being a failure — this stage qualifies a verification "
                    "route, not byte-identical proprietary templates — but the "
                    "score may not (spec sections 28 and 29)."
                ),
            ),
        ),
        summary="determinism is measured, and nothing has been measured",
    )


def _gate_failure_semantics() -> GateResult:
    """Gate 13. What does each failure class actually return?"""
    return GateResult(
        gate=frozen.PreflightGate.FAILURE_SEMANTICS,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.FAILURE_SEMANTICS,
                component=(
                    f"the {len(frozen.FAILURE_SEMANTICS_CLASSES)} failure classes "
                    "and what each one returns"
                ),
                why=(
                    "A failure that arrives as a score of 0 is a false match "
                    "rate computed over comparisons that never happened. The API "
                    "has a status type beside the score, which is the right "
                    "shape — but which status each failure produces, and whether "
                    "a score is present beside it, is behaviour."
                ),
            ),
        ),
        summary="failure behaviour is observed, and nothing has been observed",
    )


# ------------------------------------------------------------------ gate 14


def _gate_network_dependency() -> GateResult:
    """Gate 14. Is the network in the licence check or in the computation?

    The distinction that decides whether the route is reproducible at all, and
    the pinned notices answer it. Internet Activation is defined in the agreement
    as storing a licence file locally that lets the component run *on that
    computer* after a licence check, with a connection needed briefly at least
    once in seven days. The extraction and matching components are native
    libraries in the archive and the data files they load are beside them; the
    server-side components the agreement lists are separately licensed and the
    1:1 route does not use them (docs/adr/0103).
    """
    return GateResult(
        gate=frozen.PreflightGate.NETWORK_DEPENDENCY,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.NetworkRole.LICENSE_VALIDATION_ONLY.value}: a constant "
            "connection is required during evaluation and the pinned agreement "
            "defines what it is for — checking a licence that permits the "
            "component to run on this computer. The biometric computation is "
            "local native code over local data files, so no part of the score "
            "depends on a service that could change without the pinned package "
            "changing."
        ),
    )


# ------------------------------------------------------------------ gate 15


def _gate_runtime_feasibility() -> GateResult:
    """Gate 15. Does the route run here, at a workable cost?"""
    return GateResult(
        gate=frozen.PreflightGate.RUNTIME_FEASIBILITY,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.RUNTIME_FEASIBILITY,
                component=(
                    f"the {len(frozen.RUNTIME_FEASIBILITY_MEASUREMENTS)} "
                    "feasibility measurements"
                ),
                why=(
                    "A route that takes a second per extraction turns the frozen "
                    f"workload's {frozen.FROZEN_WORKLOAD.extraction_invocations} "
                    "extractions into hours, and that is a fact worth knowing "
                    "before the run rather than during it. This is an order of "
                    "magnitude on fixtures, not a benchmark and not a comparison "
                    "with any other algorithm."
                ),
            ),
        ),
        summary="latency and memory are measured, and nothing has been measured",
    )


# ------------------------------------------------------------------ gate 16


def _gate_license_capacity() -> GateResult:
    """Gate 16. Can the licence carry the whole frozen workload?

    Unlike Stage 10B's candidate there is a number: thirty days, stated in the
    pinned activation guide, with no API-call quota stated anywhere in it. What
    is not established is the other half of the question — whether the workload
    fits inside those thirty days — because that depends on the latency the
    feasibility gate would have measured (spec section 35).
    """
    terms = observed.TRIAL_TERMS
    load = frozen.FROZEN_WORKLOAD
    return GateResult(
        gate=frozen.PreflightGate.LICENSE_CAPACITY,
        status=frozen.GateStatus.FAIL,
        blockers=(
            _execution_blocker(
                frozen.PreflightGate.LICENSE_CAPACITY,
                code=frozen.BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT,
                component=(
                    f"the {terms.duration_days}-day trial against "
                    f"{load.extraction_invocations} extractions and "
                    f"{load.matcher_invocations} matches"
                ),
                why=(
                    "The expiry is known and the per-operation cost is not, so "
                    "whether the workload fits inside the window cannot be "
                    "decided yet. Two further terms bear on it and are recorded "
                    "rather than assumed away: the trial requires a constant "
                    "internet connection, and it excludes simultaneous use of "
                    "licensed Neurotechnology products on the same computer. No "
                    "API-call quota is stated anywhere in the pinned activation "
                    "guide — which is an absence in the documentation and is not "
                    "read as permission."
                ),
            ),
        ),
        summary=(
            f"a {terms.duration_days}-day trial with no stated call quota, and a "
            "per-operation cost nobody has measured"
        ),
    )


# ------------------------------------------------------------------ gate 17


def _gate_training_provenance() -> GateResult:
    """Gate 17. Was this algorithm developed on the evaluation cohort?

    A commercial vendor is not asked to publish its training corpus as a
    condition of entry; that condition would exclude every commercial matcher by
    accident rather than by decision. What is required is that the record says
    plainly what is undisclosed, and never converts silence into absence
    (spec sections 36 to 38).
    """
    return GateResult(
        gate=frozen.PreflightGate.TRAINING_PROVENANCE,
        status=frozen.GateStatus.PASS,
        summary=(
            f"{frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value} "
            f"with {frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND.value}: no pinned "
            "source mentions SD300 in any role, and none describes the corpus the "
            "algorithm was developed on. That is an absence of evidence, recorded "
            "as one and never converted into PROVEN_ABSENT. No score distribution "
            "was consulted to answer it."
        ),
    )


_GATE_RUNNERS = {
    frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION: (
        _gate_official_artifact_acquisition
    ),
    frozen.PreflightGate.RUNTIME_IDENTITY: _gate_runtime_identity,
    frozen.PreflightGate.RESEARCH_USE_PERMISSION: _gate_research_use_permission,
    frozen.PreflightGate.ARTIFACT_CLOSURE: _gate_artifact_closure,
    frozen.PreflightGate.CANONICAL500_INPUT_ROUTE: _gate_canonical500_input_route,
    frozen.PreflightGate.EXTRACTION_PROFILE: _gate_extraction_profile,
    frozen.PreflightGate.REPRESENTATION_PROFILE: _gate_representation_profile,
    frozen.PreflightGate.MATCHER_PROFILE: _gate_matcher_profile,
    frozen.PreflightGate.RAW_SCORE_ROUTE: _gate_raw_score_route,
    frozen.PreflightGate.PAIR_ORIENTATION: _gate_pair_orientation,
    frozen.PreflightGate.SELF_SEMANTICS: _gate_self_semantics,
    frozen.PreflightGate.SCORE_DETERMINISM: _gate_score_determinism,
    frozen.PreflightGate.FAILURE_SEMANTICS: _gate_failure_semantics,
    frozen.PreflightGate.NETWORK_DEPENDENCY: _gate_network_dependency,
    frozen.PreflightGate.RUNTIME_FEASIBILITY: _gate_runtime_feasibility,
    frozen.PreflightGate.LICENSE_CAPACITY: _gate_license_capacity,
    frozen.PreflightGate.TRAINING_PROVENANCE: _gate_training_provenance,
}


def _unreached_reason(stopped_at: frozen.PreflightGate) -> str:
    return (
        f"the candidate stopped at {stopped_at.value}, so this question was "
        "never asked"
    )


@dataclass(frozen=True, slots=True)
class VeriFingerPreflight:
    """The whole preflight: every gate, the verdict, and the outcome."""

    results: tuple[GateResult, ...]
    stopped_at: frozen.PreflightGate | None
    preflight_fingerprint: str

    def __post_init__(self) -> None:
        seen = tuple(result.gate for result in self.results)
        if seen != frozen.GATE_ORDER:
            raise VeriFingerGateError(
                f"the gates were reported as {seen} and the frozen order is "
                f"{frozen.GATE_ORDER}"
            )
        failed = [
            result.gate
            for result in self.results
            if result.status is frozen.GateStatus.FAIL
        ]
        if len(failed) > 1:
            raise VeriFingerGateError(
                f"fail-fast means one failing gate, and these failed: {failed}"
            )
        if failed and failed[0] is not self.stopped_at:
            raise VeriFingerGateError(
                f"the stopping gate is {self.stopped_at} and the failing gate is "
                f"{failed[0]}"
            )
        if not failed and self.stopped_at is not None:
            raise VeriFingerGateError(f"stopped at {self.stopped_at} with no failure")

    @property
    def passed(self) -> bool:
        """Every gate passed. Not "no gate failed": NOT_REACHED is not a pass."""
        return all(result.status is frozen.GateStatus.PASS for result in self.results)

    @property
    def verdict(self) -> str:
        return (
            frozen.CANDIDATE_PASS_VERDICT if self.passed else frozen.CANDIDATE_FAIL_VERDICT
        )

    @property
    def outcome(self) -> str:
        return (
            frozen.STAGE_11A_SELECTED_OUTCOME
            if self.passed
            else frozen.STAGE_11A_BLOCKED_OUTCOME
        )

    @property
    def selected_candidate(self) -> str | None:
        return frozen.CANDIDATE_ID if self.passed else None

    @property
    def failure_class(self) -> frozen.FailureClass | None:
        """What kind of failure this is, derived from where it stopped.

        ``VERIFINGER_PREFLIGHT_FAIL`` reads the same whether the artifact could
        not be had, its terms forbade the use, or the route was opened, read and
        found to need a measurement nobody has taken. Those are very different
        results, and the marker says which one this is.
        """
        if self.passed:
            return None
        codes = {blocker.blocker_code for blocker in self.blockers}
        if frozen.BlockerCode.OFFICIAL_ARTIFACT_NOT_OBTAINABLE in codes:
            return frozen.FailureClass.ARTIFACT_NOT_OBTAINED
        if frozen.BlockerCode.RESEARCH_USE_BLOCKED in codes:
            return frozen.FailureClass.RESEARCH_USE_REFUSED
        if frozen.BlockerCode.SD300_TRAINING_OVERLAP_FOUND in codes:
            return frozen.FailureClass.SD300_DEVELOPMENT_OVERLAP
        if codes & {
            frozen.BlockerCode.LOCAL_SMOKE_FAILED,
            frozen.BlockerCode.HIDDEN_SCORE_AFFECTING_DEFAULT_UNRESOLVED,
            frozen.BlockerCode.PAIR_ORDER_SEMANTICS_UNRESOLVED,
            frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED,
            frozen.BlockerCode.LICENSE_WORKLOAD_CAPACITY_INSUFFICIENT,
        }:
            return frozen.FailureClass.EXECUTION_NOT_ESTABLISHED
        return frozen.FailureClass.ROUTE_NOT_QUALIFIABLE

    @property
    def artifact_was_opened(self) -> bool:
        """Whether this stage's conclusions rest on the artifact's own bytes.

        The one claim that most distinguishes Stage 11A from its predecessor, and
        it is derived from the acquisition gate rather than asserted.
        """
        return (
            self.status(frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION)
            is frozen.GateStatus.PASS
        )

    @property
    def sd300_overlap_status(self) -> frozen.SD300OverlapStatus:
        if (
            self.status(frozen.PreflightGate.TRAINING_PROVENANCE)
            is frozen.GateStatus.NOT_REACHED
        ):
            return frozen.SD300OverlapStatus.NOT_REACHED
        return frozen.SD300OverlapStatus.NO_EVIDENCE_FOUND

    @property
    def gates_reached(self) -> int:
        return sum(
            1
            for result in self.results
            if result.status is not frozen.GateStatus.NOT_REACHED
        )

    @property
    def gates_passed(self) -> int:
        return sum(
            1 for result in self.results if result.status is frozen.GateStatus.PASS
        )

    @property
    def blockers(self) -> tuple[Blocker, ...]:
        return tuple(
            sorted(
                (blocker for result in self.results for blocker in result.blockers),
                key=lambda item: item.blocker_code.value,
            )
        )

    def result(self, gate: frozen.PreflightGate) -> GateResult:
        for item in self.results:
            if item.gate is gate:
                return item
        raise KeyError(gate)  # pragma: no cover - GATE_ORDER is exhaustive

    def status(self, gate: frozen.PreflightGate) -> frozen.GateStatus:
        return self.result(gate).status


def run_preflight() -> VeriFingerPreflight:
    """Run the gate order and stop at the first failure."""
    results: list[GateResult] = []
    stopped_at: frozen.PreflightGate | None = None
    for gate in frozen.GATE_ORDER:
        if stopped_at is not None:
            results.append(
                GateResult(
                    gate=gate,
                    status=frozen.GateStatus.NOT_REACHED,
                    summary=_unreached_reason(stopped_at),
                )
            )
            continue
        runner = _GATE_RUNNERS.get(gate)
        if runner is None:  # pragma: no cover - the table is exhaustive
            raise VeriFingerGateError(
                f"the candidate survived to {gate.value} and Stage 11A has no "
                "runner for it. A gate without a runner is an unanswered "
                "question, not a passed one"
            )
        result = runner()
        results.append(result)
        if result.status is frozen.GateStatus.FAIL:
            stopped_at = gate
    return VeriFingerPreflight(
        results=tuple(results),
        stopped_at=stopped_at,
        preflight_fingerprint=stable_hash(
            {
                "schema": "stage_11a_preflight_v1",
                "candidate_id": frozen.CANDIDATE_ID,
                "gates": [
                    (result.gate.value, result.status.value) for result in results
                ],
                "blockers": sorted(
                    blocker.blocker_code.value
                    for result in results
                    for blocker in result.blockers
                ),
                "observations": observed.observations_fingerprint(),
            },
            length=64,
        ),
    )


# --------------------------------------------------------------- the secret guard

_SENSITIVE_PATTERNS = tuple(
    (name, re.compile(source)) for name, source in frozen.SENSITIVE_VALUE_PATTERNS
)


def find_sensitive_material(node: Any, trail: str = "") -> tuple[str, ...]:
    """Every place a document carries a credential, by key or by value shape.

    Walks the document as *data*. A key match is reported wherever it appears; a
    value match is reported for any string, at any depth, including inside a
    list.
    """
    found: list[str] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            name = str(key)
            where = f"{trail}.{name}" if trail else name
            if name.strip().lower() in frozen.SENSITIVE_EVIDENCE_KEYS:
                found.append(f"{where}: a key that names licence material")
            found.extend(find_sensitive_material(value, where))
    elif isinstance(node, (list, tuple)):
        for index, item in enumerate(node):
            found.extend(find_sensitive_material(item, f"{trail}[{index}]"))
    elif isinstance(node, str):
        for name, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(node):
                found.append(f"{trail or '<root>'}: a value shaped like {name}")
    return tuple(sorted(set(found)))


def require_no_sensitive_material(node: Any, *, where: str) -> None:
    """The raising form, for the publisher.

    Raises:
        VeriFingerSensitiveEvidenceError: the document carries, or is about to
            carry, something shaped like licence material. The publisher stops
            rather than redacting: a redaction that silently succeeds is how the
            second one gets missed (spec section 43).
    """
    findings = find_sensitive_material(node)
    if findings:
        raise VeriFingerSensitiveEvidenceError(
            f"{where} carries licence material and will not be published: "
            f"{list(findings)}"
        )


# --------------------------------------------------------- published documents


def _gate_header(
    preflight: VeriFingerPreflight, gate: frozen.PreflightGate, schema: str
) -> dict[str, Any]:
    result = preflight.result(gate)
    return {
        "schema": schema,
        "candidate": frozen.CANDIDATE_ID,
        "gate": gate.value,
        "gate_status": result.status.value,
        "gate_summary": result.summary,
        "blocker_codes": [item.blocker_code.value for item in result.blockers],
    }


def _candidate_identity_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    claim = observed.PRODUCT_IDENTITY_CLAIM
    load = frozen.FROZEN_WORKLOAD
    return {
        "schema": "stage_11a_candidate_identity_v1",
        "algorithm_slot": frozen.ALGORITHM_SLOT,
        "question": (
            "does an official, exact VeriFinger 2025.2 artifact let fpbench take "
            "canonical_500 in and get a reproducible raw 1:1 score out, with "
            "every externally selectable behaviour that can affect that score "
            "defined by Neurotechnology rather than invented here"
        ),
        "candidate_id": frozen.CANDIDATE_ID,
        "candidate_id_is_provisional": True,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "production_algorithm_id_frozen": frozen.PRODUCTION_ALGORITHM_ID_FROZEN,
        "final_identity_would_have_to_name": list(frozen.FINAL_IDENTITY_COMPONENTS),
        "product_name": claim.product_name,
        "vendor": claim.vendor,
        "declared_version": claim.declared_version,
        "identity_sources_inside_the_artifact": list(claim.supporting_sources),
        "declared_non_candidates": [
            {"identity": name, "description": description}
            for name, description in frozen.DECLARED_NON_CANDIDATES
        ],
        "predecessor": {
            "stage": "stage_10b",
            "outcome": frozen.STAGE_10B_OUTCOME,
            "finalization_fingerprint": frozen.STAGE_10B_FINALIZATION_FINGERPRINT,
            "relation": (
                "Stage 10B preflighted the id3 Finger SDK, failed at its "
                "acquisition gate, reserved Stage 10C for that candidate and "
                "opened a candidate search. Stage 11A is that search's next "
                "candidate and adds nothing to Stage 10B."
            ),
            "stage_10b_evidence_modified_by_stage_11a": False,
        },
        "gate_order": [gate.value for gate in frozen.GATE_ORDER],
        "gates_are_conjunctive_and_unweighted": True,
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "benchmark_input": {
            "profile": frozen.BENCHMARK_INPUT_PROFILE,
            "ppi": frozen.BENCHMARK_INPUT_PPI,
            "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
        },
        "frozen_workload": {
            "participating_images": load.participating_images,
            "participating_images_is_a_cohort_not_an_operation_count": True,
            "comparison_attempts": load.comparison_attempts,
            "extractions_per_comparison": 2,
            "extraction_invocations": load.extraction_invocations,
            "matcher_invocations": load.matcher_invocations,
            "execution_semantics_source": (
                "the Stage 8C execution semantics, which published 12,000 "
                "logical extractions over the same 6,000 comparisons"
            ),
        },
        "setting_provenance_vocabulary": [
            item.value
            for item in frozen.SettingProvenance
            if item is not frozen.SettingProvenance.UNRESOLVED
        ],
        "refused_setting_provenance": frozen.REFUSED_SETTING_PROVENANCE,
        "non_goals": list(frozen.NON_GOALS),
        "production_integration_not_created": [
            {"surface": name, "created": False}
            for name in frozen.PRODUCTION_INTEGRATION_NOT_CREATED
        ],
        "stage_11b_scope_if_this_passes": list(frozen.STAGE_11B_SCOPE),
        "observations_fingerprint": observed.observations_fingerprint(),
    }


def _acquisition_manifest_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        "stage_11a_acquisition_manifest_v1",
    )
    state = store.acquisition_state()
    document["acquisition_status"] = state.status.value
    document["possession"] = state.possession.value
    document["artifact_route_chosen"] = observed.SDK_ARCHIVE.route.value
    document["routes_are_never_mixed"] = True
    document["pin_fields_required_before_import"] = list(
        frozen.ACQUISITION_PIN_FIELDS
    )
    document["excluded_from_evidence"] = list(frozen.EXCLUDED_FROM_EVIDENCE)
    document["acquired_artifacts"] = [
        {
            "artifact_id": item.artifact_id,
            "route": item.route.value,
            "official_locator_category": item.official_locator_category,
            "locator": item.locator,
            "filename": item.filename,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "downloaded_utc": item.downloaded_utc,
            "declared_version": item.declared_version,
            "target_operating_systems": list(item.target_operating_systems),
            "target_architectures": list(item.target_architectures),
            "role": item.role,
            "local_verification": state.state(item.artifact_id).presence.value,
        }
        for item in observed.ACQUIRED_ARTIFACTS
    ]
    document["rejected_routes"] = [
        {
            "route": item.route.value,
            "locator": item.locator,
            "filename": item.filename,
            "size_bytes": item.size_bytes,
            "declared_version": item.declared_version,
            "why_not_this_route": item.why_not_this_route,
            "bytes_downloaded": 0,
        }
        for item in observed.REJECTED_ROUTES
    ]
    document["documentation_is_a_separate_pinned_artifact"] = True
    document["documentation_matches_the_copy_inside_the_archive"] = True
    document["observations"] = observed.observation_rows(
        observed.ACQUISITION_OBSERVATIONS
    )
    document["notes"] = [
        "Stage 10B's candidate published no self-service download and the honest "
        "result was that nobody had walked the route. This vendor publishes a "
        "direct locator, so the first act of this stage was the download "
        "(docs/adr/0100).",
        "No signed URL, token, cookie or credential took part in either "
        "transfer, and the artifact class has no field one could be recorded in.",
    ]
    return document


def _artifact_manifest_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.OFFICIAL_ARTIFACT_ACQUISITION,
        "stage_11a_artifact_manifest_v1",
    )
    closure = preflight.result(frozen.PreflightGate.ARTIFACT_CLOSURE)
    document["closure_gate"] = frozen.PreflightGate.ARTIFACT_CLOSURE.value
    document["closure_gate_status"] = closure.status.value
    document["closure_gate_summary"] = closure.summary
    document["archive_member_count"] = observed.ARCHIVE_MEMBER_COUNT
    document["archive_uncompressed_bytes"] = observed.ARCHIVE_UNCOMPRESSED_BYTES
    document["every_member_was_hashed"] = True
    document["artifact_classes_inventoried"] = list(frozen.ARTIFACT_CLOSURE_CLASSES)
    document["external_model_downloads_required"] = 0
    document["embedded_model_marker"] = frozen.EMBEDDED_MODEL_MARKER
    document["checkpoint_file_required"] = False
    document["why_no_checkpoint_is_required"] = (
        "This is a black-box commercial matcher. Its algorithm data ships as "
        "vendor data files inside the pinned archive, and where a model has no "
        "separate file at all the correct record is "
        f"{frozen.EMBEDDED_MODEL_MARKER} rather than a missing artifact "
        "(spec section 10)."
    )
    document["fingerprint_data_files"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
            "inside_the_pinned_archive": True,
        }
        for item in observed.FINGER_DATA_FILES
    ]
    document["cited_members"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
        }
        for item in observed.CITED_ARCHIVE_MEMBERS
    ]
    document["java_binding_jars"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "role": item.role,
        }
        for item in observed.JAVA_BINDING_JARS
    ]
    document["rare_dependency_rule"] = frozen.RARE_DEPENDENCY_RULE
    document["accelerator_required"] = False
    document["further_proprietary_service_required"] = False
    document["bytes_of_any_of_this_in_git"] = 0
    document["observations"] = observed.observation_rows(
        observed.CLOSURE_OBSERVATIONS
    )
    return document


def _runtime_identity_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RUNTIME_IDENTITY,
        "stage_11a_runtime_identity_v1",
    )
    document["identity_fields_required"] = list(frozen.RUNTIME_IDENTITY_FIELDS)
    document["identity_source"] = "PINNED_ARTIFACT_BINARIES_AND_DOCUMENTS"
    document["a_web_page_version_is_not_an_algorithm_identity"] = True
    document["web_page_version_used_as_identity"] = False
    document["runtime_reported_version_read_by_execution"] = False
    document["why_not_read_by_execution"] = (
        store.qualification_run_state().reason
    )
    document["declared_version"] = observed.PRODUCT_IDENTITY_CLAIM.declared_version
    document["archive_revision_number"] = "20260612"
    document["archive_revision_hash"] = (
        "0738caf6a69459241bff6e800789cd61c160bbce"
    )
    document["language_bindings_in_the_archive"] = list(
        observed.LANGUAGE_BINDINGS_IN_ARCHIVE
    )
    document["python_binding_in_main_sdk"] = observed.PYTHON_BINDING_IN_MAIN_SDK
    document["python_package_version"] = None
    document["python_abi"] = None
    document["why_the_python_fields_are_null"] = (
        "The main 2025.2 archive ships no Python binding, so there is no Python "
        "package version and no Python ABI to record for this route. The "
        "vendor's Python distribution is version 2025.1 and is a different "
        "artifact, refused at the route decision (spec section 3)."
    )
    document["operating_systems_available"] = list(
        observed.SDK_ARCHIVE.target_operating_systems
    )
    document["architectures_available"] = list(
        observed.SDK_ARCHIVE.target_architectures
    )
    document["platform_locked"] = False
    document["why_platform_not_locked"] = (
        "The trial is single-platform, so the target is a decision taken before "
        "activation. No activation has been attempted, so no platform has been "
        "locked, and alternating between two platforms under one algorithm "
        "fingerprint is refused whichever one is eventually chosen."
    )
    document["native_libraries"] = [
        {
            "relative_path": item.relative_path,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "product_name": item.product_name,
            "file_description": item.file_description,
            "product_version": item.product_version,
        }
        for item in observed.WINDOWS_X64_NATIVE_LIBRARIES
    ]
    document["observations"] = observed.observation_rows(
        observed.IDENTITY_OBSERVATIONS
    )
    return document


def _third_party_usage_binding_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RESEARCH_USE_PERMISSION,
        "stage_11a_third_party_usage_binding_v1",
    )
    observation = license_observation()
    assessment = research_use_assessment()
    redistribution = redistribution_record()
    document["mechanism"] = "stage_8e"
    document["stage_8e_policy_fingerprint"] = frozen.STAGE8E_POLICY_FINGERPRINT
    document["stage_8e_purpose_fingerprint"] = frozen.STAGE8E_PURPOSE_FINGERPRINT
    document["license_observation"] = {
        "observation_id": observation.observation_id,
        "component_kind": observation.component_kind.value,
        "subject": observation.subject,
        "status": observation.status.value,
        "declared_license_names": list(observation.declared_license_names),
        "stated_restrictions": list(observation.stated_restrictions),
        "evidence": [
            {
                "locator": item.locator,
                "description": item.description,
                "document_sha256": item.document_sha256,
            }
            for item in observation.evidence
        ],
        "observation_fingerprint": observation.observation_fingerprint,
    }
    document["research_use_assessment"] = {
        "assessment_id": assessment.assessment_id,
        "observation_fingerprint": assessment.observation_fingerprint,
        "decision": assessment.decision.value,
        "opens_execution": assessment.decision.opens_execution,
        "intended_use_permission_status": (
            assessment.intended_use_permission_status.value
        ),
        "intersection_permits_intended_use": (
            assessment.intersection_permits_intended_use
        ),
        "non_blocking_restrictions": [
            item.value for item in assessment.non_blocking_restrictions
        ],
        "blockers": [item.value for item in assessment.blockers],
        "basis": assessment.basis,
        "assessment_fingerprint": assessment.assessment_fingerprint,
    }
    document["redistribution_record"] = {
        "decision": redistribution.decision.value,
        "redistributed_by_fpbench": redistribution.redistributed_by_fpbench,
        "basis": redistribution.basis,
    }
    document["vocabulary_limitation"] = (
        "Stage 8E's observation vocabulary has no member for a proprietary "
        "commercial SDK licence. NON_COMMERCIAL is the narrowest member that is "
        "true of the route acquired here — the trial, whose stated purpose is to "
        "explore SDK functionality rather than to deploy — and it is published "
        "beside COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT so that "
        "both halves are visible. Stage 8E is closed and was not extended to add "
        "a member (docs/adr/0099)."
    )
    document["open_question_for_stage_11b"] = (
        "The agreement does not address publishing measurements obtained with "
        "the SDK. Stage 11A publishes no score, so the question is not live "
        "here; a stage that published 6,000 of them would have to settle it "
        "first, and it is recorded now rather than discovered then."
    )
    document["usage_manifest_written"] = False
    document["why_no_usage_manifest"] = (
        "A manifest binds components this project executes. Stage 11A executes "
        "nothing, so the record here is the observation, the assessment and the "
        "redistribution position — and a manifest of executed components would "
        "describe an execution that did not happen."
    )
    document["observations"] = observed.observation_rows(observed.LICENSE_OBSERVATIONS)
    return document


def _input_domain_contract_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.CANONICAL500_INPUT_ROUTE,
        "stage_11a_input_domain_contract_v1",
    )
    document["benchmark_input"] = {
        "profile": frozen.BENCHMARK_INPUT_PROFILE,
        "ppi": frozen.BENCHMARK_INPUT_PPI,
        "pixel_format": frozen.BENCHMARK_INPUT_PIXEL_FORMAT,
    }
    document["required_route"] = list(frozen.CANONICAL500_REQUIRED_ROUTE)
    document["supported_image_containers"] = list(observed.SUPPORTED_IMAGE_CONTAINERS)
    document["png_is_in_the_official_input_domain"] = True
    document["resolution_must_be_declared_on_a_fingerprint_image"] = True
    document["fpbench_preprocessing_performed"] = []
    document["refused_preprocessing"] = list(frozen.REFUSED_PREPROCESSING)
    document["internal_black_box_preprocessing_is_acceptable"] = (
        frozen.INTERNAL_BLACK_BOX_PREPROCESSING_IS_ACCEPTABLE
    )
    document["internal_black_box_note"] = (
        "The SDK performs its own segmentation, alignment and quality "
        "assessment inside the pinned binaries. fpbench has no external choice "
        "about any of it and therefore needs no account of the mathematics; what "
        "must be frozen is every behaviour that *can* be selected from outside "
        "(spec section 13)."
    )
    document["sd300b_1000_ppi_offered_to_this_candidate"] = False
    document["sd300c_2000_ppi_offered_to_this_candidate"] = False
    document["sd300_bytes_read"] = False
    document["observations"] = observed.observation_rows(observed.INPUT_OBSERVATIONS)
    return document


def _profile_document(
    preflight: VeriFingerPreflight,
    gate: frozen.PreflightGate,
    schema: str,
    settings: tuple[observed.PublishedSetting, ...],
    inventory: tuple[str, ...],
    extra_observations: tuple[observed.Observation, ...],
) -> Mapping[str, Any]:
    document = _gate_header(preflight, gate, schema)
    unresolved = _unresolved(settings)
    document["inventory_classes_searched"] = list(inventory)
    document["inventory_closed"] = True
    document["inventory_names_were_discovered_not_assumed"] = True
    document["published_settings"] = observed.setting_rows(settings)
    document["setting_count"] = len(settings)
    document["score_affecting_count"] = sum(
        1 for item in settings if item.is_score_affecting
    )
    document["score_affecting_with_upstream_provenance"] = [
        item.name
        for item in settings
        if item.is_score_affecting and item.provenance.is_upstream_authority
    ]
    document["score_affecting_without_upstream_provenance"] = list(unresolved)
    document["profile_frozen"] = not unresolved
    document["permitted_provenances"] = [
        item.value
        for item in frozen.SettingProvenance
        if item is not frozen.SettingProvenance.UNRESOLVED
    ]
    document["refused_provenance"] = frozen.REFUSED_SETTING_PROVENANCE
    document["settings_chosen_by_fpbench"] = 0
    document["preset_selected_from_score_distributions"] = False
    document["preset_selected_from_vendor_reported_accuracy"] = False
    document["profile_identity_would_name_the_official_sample_route"] = True
    document["why"] = (
        "Where a value comes from upstream's own 1:1 tutorial rather than from a "
        "stated default, the profile is the official-sample route and its "
        "identity says so. Calling it 'the VeriFinger default' would claim "
        "something the manual does not state (spec section 16)."
    )
    document["observations"] = observed.observation_rows(extra_observations)
    return document


def _extraction_profile_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    return _profile_document(
        preflight,
        frozen.PreflightGate.EXTRACTION_PROFILE,
        "stage_11a_extraction_profile_v1",
        observed.PUBLISHED_EXTRACTOR_SETTINGS,
        frozen.EXTRACTOR_PROFILE_INVENTORY,
        observed.EXTRACTION_OBSERVATIONS,
    )


def _matcher_profile_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    return _profile_document(
        preflight,
        frozen.PreflightGate.MATCHER_PROFILE,
        "stage_11a_matcher_profile_v1",
        observed.PUBLISHED_MATCHER_SETTINGS,
        frozen.MATCHER_PROFILE_INVENTORY,
        observed.MATCHER_OBSERVATIONS,
    )


def _representation_profile_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.REPRESENTATION_PROFILE,
        "stage_11a_representation_profile_v1",
    )
    reached = (
        preflight.status(frozen.PreflightGate.REPRESENTATION_PROFILE)
        is not frozen.GateStatus.NOT_REACHED
    )
    document["representation_candidates"] = list(frozen.REPRESENTATION_CANDIDATES)
    document["representation_type"] = (
        frozen.RepresentationType.VENDOR_PROPRIETARY_TEMPLATE.value
        if reached
        else frozen.RepresentationType.NOT_REACHED.value
    )
    document["these_are_observations_not_a_settled_profile"] = not reached
    document["interoperable_format_chosen_for_convenience"] = False
    document["iso_and_ansi_are_export_formats_here"] = True
    document["minex_is_a_separate_matching_scenario"] = True
    document["templates_are_ephemeral"] = True
    document["template_bytes_published"] = 0
    document["publishable_facts"] = list(frozen.PUBLISHABLE_REPRESENTATION_FACTS)
    document["template_size_metadata"] = None
    document["why_size_metadata_is_null"] = (
        "Template size depends on the extraction profile, and the extraction "
        "profile is not frozen. A size published now would describe a "
        "configuration nobody has chosen."
    )
    document["observations"] = observed.observation_rows(
        observed.REPRESENTATION_OBSERVATIONS
    )
    return document


def _score_contract_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RAW_SCORE_ROUTE,
        "stage_11a_score_contract_v1",
    )
    reached = (
        preflight.status(frozen.PreflightGate.RAW_SCORE_ROUTE)
        is not frozen.GateStatus.NOT_REACHED
    )
    document["requirements"] = list(frozen.SCORE_CONTRACT_REQUIREMENTS)
    document["raw_score_route_status"] = (
        frozen.ScoreRouteStatus.NATIVE_TRANSFORMED_SCALAR.value
        if reached
        else frozen.ScoreRouteStatus.NOT_REACHED.value
    )

    # What the pinned manual and upstream's own 1:1 tutorial say. Kept in one
    # labelled block rather than spread across the document as flat fields,
    # because this gate was not reached: a reader who sees `numeric_type:
    # integer` beside `gate_status: NOT_REACHED` should be able to tell in one
    # glance which of the two is a finding. Where the gate *is* reached the same
    # values are promoted to settled fields below.
    documented = {
        "scalar_per_attempt": 1,
        "numeric_type": observed.DOCUMENTED_SCORE_TYPE,
        "direction": observed.DOCUMENTED_SCORE_DIRECTION,
        "nominal_range_published_by_upstream": False,
        "why_no_nominal_range": (
            "Upstream defines the scale by its correspondence with a claimed "
            "false acceptance rate rather than by a maximum. A range invented "
            "here would be fpbench asserting a bound the vendor does not state."
        ),
        "native_transform": observed.DOCUMENTED_SCORE_TRANSFORM,
        "upstream_anchor_points": [
            {"claimed_far": far, "score_value": value}
            for far, value in observed.DOCUMENTED_SCORE_ANCHORS
        ],
        "threshold_is_a_separate_engine_property": True,
        "boolean_only_api": False,
        "official_one_to_one_route": list(observed.OFFICIAL_ONE_TO_ONE_ROUTE),
    }
    document["documented_by_the_pinned_artifact"] = documented
    document["these_are_observations_not_a_settled_contract"] = not reached
    if reached:
        document["settled_contract"] = documented
    else:
        document["settled_contract"] = None
        document["why_nothing_is_settled_here"] = (
            "The gate was never reached, so nothing above it was applied. What "
            "the manual states is recorded because a reader comparing this stage "
            "with the next one needs to see what was already known — and because "
            "publishing it as a conclusion would be exactly the substitution "
            "this stage refuses elsewhere."
        )

    # Requirements and refusals, which hold under either outcome because they are
    # rules rather than findings.
    document["fpbench_conversion_performed"] = False
    document["threshold_applied_inside_the_number"] = False
    document["raw_route_stops_at_the_score"] = True
    document["vendor_threshold_constants_enter_this_stage"] = False
    document["failure_semantics_classes"] = list(frozen.FAILURE_SEMANTICS_CLASSES)
    document["a_failure_may_never_become_a_score_of_zero"] = True
    document["failure_semantics_gate_status"] = preflight.status(
        frozen.PreflightGate.FAILURE_SEMANTICS
    ).value
    document["observations"] = observed.observation_rows(observed.SCORE_OBSERVATIONS)
    document["notes"] = [
        "This is the gate the specification calls decisive, and the artifact "
        "does answer it: a scalar exists, it is not a boolean, and no threshold "
        "has been applied to it. The gate order put an unresolved extraction "
        "profile in front of it, so the answer is recorded and not applied "
        "(docs/adr/0102).",
        "A transformed native quantity is still a raw score. What would not be "
        "is a number fpbench computed from one.",
    ]
    return document


def _pair_semantics_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.PAIR_ORIENTATION,
        "stage_11a_pair_semantics_v1",
    )
    document["requirements"] = list(frozen.PAIR_ORIENTATION_REQUIREMENTS)
    document["api_distinguishes_reference_and_probe"] = True
    document["symmetry_observed"] = None
    document["a_gate_that_did_not_run_publishes_no_boolean"] = True
    document["fpbench_may_average_the_two_orderings"] = False
    document["fpbench_may_take_the_maximum"] = False
    document["self_semantics_requirements"] = list(
        frozen.SELF_SEMANTICS_REQUIREMENTS
    )
    document["self_independent_extraction_required"] = True
    document["self_semantics_gate_status"] = preflight.status(
        frozen.PreflightGate.SELF_SEMANTICS
    ).value
    document["self_demonstrated"] = False
    document["fixtures_that_may_be_used"] = list(frozen.FIXTURE_POLICY)
    document["sd300_used_for_any_of_this"] = False
    document["observations"] = observed.observation_rows(
        observed.EXECUTION_OBSERVATIONS
    )
    return document


def _determinism_report_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.SCORE_DETERMINISM,
        "stage_11a_determinism_report_v1",
    )
    document["levels"] = [
        {"level": name, "verified": False} for name in frozen.DETERMINISM_LEVELS
    ]
    document["scores_compared"] = 0
    document["process_restarts"] = 0
    document["templates_must_be_byte_identical"] = False
    document["why_templates_need_not_be_identical"] = (
        "This stage qualifies a verification route, not a serialisation. If the "
        "proprietary templates vary between extractions while the score does "
        "not, that is acceptable; upstream promises nothing about template bytes "
        "and this project does not require it to (spec section 29)."
    )
    document["score_must_be_identical"] = True
    document["nondeterminism_observed"] = False
    document["nondeterminism_would_be"] = (
        frozen.BlockerCode.SCORE_NONDETERMINISM_OBSERVED.value
    )
    network = preflight.status(frozen.PreflightGate.NETWORK_DEPENDENCY)
    network_reached = network is not frozen.GateStatus.NOT_REACHED
    document["network_dependency_gate_status"] = network.value
    document["network_role"] = (
        frozen.NetworkRole.LICENSE_VALIDATION_ONLY.value
        if network_reached
        else frozen.NetworkRole.NOT_REACHED.value
    )
    document["network_questions"] = list(frozen.NETWORK_DEPENDENCY_QUESTIONS)
    document["remote_service_participates_in_the_score"] = (
        False if network_reached else None
    )
    document["what_the_pinned_notices_say_about_the_network"] = (
        "The licence agreement defines Internet Activation as storing a licence "
        "file locally that allows the component to run on that computer after a "
        "licence check, with a connection needed briefly at least once in seven "
        "days; the extraction and matching components are native libraries in "
        "the archive and their data files are beside them. That is what the gate "
        "would conclude from, and it is recorded as an observation while the "
        "gate is unreached (docs/adr/0103)."
    )
    document["licence_was_disconnected_to_test_this"] = False
    document["why_not"] = (
        "There is no bypass experiment in this stage. The network question is "
        "answered from the pinned agreement and the SDK's own structure, using "
        "documented behaviour only (spec section 32)."
    )
    document["observations"] = observed.observation_rows(observed.NETWORK_OBSERVATIONS)
    return document


def _runtime_feasibility_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.RUNTIME_FEASIBILITY,
        "stage_11a_runtime_feasibility_v1",
    )
    load = frozen.FROZEN_WORKLOAD
    terms = observed.TRIAL_TERMS
    document["measurements_required"] = list(frozen.RUNTIME_FEASIBILITY_MEASUREMENTS)
    document["measurements_taken"] = 0
    document["measured_on_fixtures_only"] = True
    document["this_is_not_a_performance_benchmark"] = True
    document["this_is_not_a_comparison_with_another_algorithm"] = True
    document["rare_dependency_rule"] = frozen.RARE_DEPENDENCY_RULE
    document["accelerator_required"] = False
    document["license_capacity_gate_status"] = preflight.status(
        frozen.PreflightGate.LICENSE_CAPACITY
    ).value
    document["license_capacity_questions"] = list(frozen.LICENSE_CAPACITY_QUESTIONS)
    document["trial_terms"] = {
        "duration_days": terms.duration_days,
        "api_call_quota_stated": terms.api_call_quota_stated,
        "requires_constant_internet": terms.requires_constant_internet,
        "excludes_simultaneous_licensed_products": (
            terms.excludes_simultaneous_licensed_products
        ),
        "activation_mandatory": terms.activation_mandatory,
        "activation_transmits_personal_information": (
            terms.activation_transmits_personal_information
        ),
        "platform_bound": terms.platform_bound,
    }
    document["an_absent_quota_statement_is_not_permission"] = True
    document["frozen_workload_operations"] = {
        "comparison_attempts": load.comparison_attempts,
        "extraction_invocations": load.extraction_invocations,
        "matcher_invocations": load.matcher_invocations,
    }
    document["workload_fits_the_licence_window"] = None
    document["why_null"] = (
        "The window is known and the per-operation cost is not, so the product "
        "of the two is not known either. A false here would claim the workload "
        "had been measured and found not to fit."
    )
    document["observations"] = observed.observation_rows(
        observed.CAPACITY_OBSERVATIONS
    )
    return document


def _training_provenance_document(
    preflight: VeriFingerPreflight,
) -> Mapping[str, Any]:
    document = _gate_header(
        preflight,
        frozen.PreflightGate.TRAINING_PROVENANCE,
        "stage_11a_training_provenance_v1",
    )
    reached = (
        preflight.status(frozen.PreflightGate.TRAINING_PROVENANCE)
        is not frozen.GateStatus.NOT_REACHED
    )
    document["training_provenance_status"] = (
        frozen.TrainingProvenanceStatus.PROPRIETARY_UNDISCLOSED.value
        if reached
        else frozen.TrainingProvenanceStatus.NOT_REACHED.value
    )
    document["full_disclosure_required_of_a_commercial_vendor"] = False
    document["sd300_overlap_status"] = preflight.sd300_overlap_status.value
    document["sd300_training_overlap_found"] = False if reached else None
    document["no_evidence_found_is_not_proven_absent"] = True
    document["proven_absent_would_need_an_upstream_statement"] = True
    document["sd300_data_read_by_this_stage"] = False
    document["performance_used_to_answer_provenance"] = False
    document["why_not"] = (
        "A score distribution that looks good or bad on SD300 says nothing about "
        "whether SD300 was in the development set, and treating it as though it "
        "did would be inventing evidence out of a result (spec section 38)."
    )
    document["observations"] = observed.observation_rows(
        observed.PROVENANCE_OBSERVATIONS
    )
    return document


def _preflight_report_document(preflight: VeriFingerPreflight) -> Mapping[str, Any]:
    return {
        "schema": "stage_11a_preflight_report_v1",
        "candidate": frozen.CANDIDATE_ID,
        "implementation_origin": frozen.IMPLEMENTATION_ORIGIN,
        "verdict": preflight.verdict,
        "outcome": preflight.outcome,
        "failure_class": (
            preflight.failure_class.value if preflight.failure_class else None
        ),
        "artifact_was_obtained_and_opened": preflight.artifact_was_opened,
        "decisive_question": (
            "Does an official, exact VeriFinger 2025.2 artifact let fpbench "
            "take canonical_500 in and get a reproducible raw 1:1 score out, "
            "with every externally selectable behaviour that can affect that "
            "score defined by Neurotechnology?"
        ),
        "decisive_answer": "YES" if preflight.passed else "NOT YET",
        "what_this_outcome_does_not_say": [
            "that the artifact could not be obtained",
            "that Neurotechnology refused anything",
            "that the licence terms forbid research use",
            "that canonical_500 cannot enter the official route",
            "that the raw score is unsuitable",
            "that the algorithm was developed on SD300",
        ],
        "passed_every_hard_gate": preflight.passed,
        "stopped_at_gate": (
            preflight.stopped_at.value if preflight.stopped_at else None
        ),
        "gate_count_defined": frozen.GATE_COUNT,
        "gates_reached": preflight.gates_reached,
        "gates_passed": preflight.gates_passed,
        "gates": [
            {
                "order": index,
                "gate": result.gate.value,
                "status": result.status.value,
                "summary": result.summary,
                "documents": list(frozen.gate_documents(result.gate)),
                "blocker_codes": [
                    blocker.blocker_code.value for blocker in result.blockers
                ],
            }
            for index, result in enumerate(preflight.results, start=1)
        ],
        "blockers": [
            {
                "gate": blocker.gate.value,
                "blocker_code": blocker.blocker_code.value,
                "affected_component": blocker.affected_component,
                "evidence": blocker.evidence,
                "why_this_blocks_algorithm_4": blocker.why_this_blocks_algorithm_4,
                "how_this_would_be_lifted": blocker.how_this_would_be_lifted,
            }
            for blocker in preflight.blockers
        ],
        "no_workaround_was_considered": [
            "no licence bypass",
            "no trial reset",
            "no protection mechanism touched",
            "no redistribution of the artifact",
            "no reconstruction of the algorithm from documentation",
            "no preset chosen from score distributions",
        ],
        "what_this_candidate_cost": {
            "artifact_bytes_downloaded": sum(
                item.size_bytes for item in observed.ACQUIRED_ARTIFACTS
            ),
            "artifact_bytes_added_to_git": 0,
            "licences_activated": 0,
            "sd300_images_read": 0,
            "scores_produced": 0,
        },
        "acceptance_conditions": list(frozen.ACCEPTANCE_CONDITIONS),
        "acceptance_conditions_are_conjunctive": True,
        "acceptance_conditions_met": preflight.passed,
        "opens_stage_11b": preflight.passed,
        "stage_11b_scope": list(frozen.STAGE_11B_SCOPE),
    }


_DOCUMENT_BUILDERS = {
    frozen.CANDIDATE_IDENTITY_NAME: _candidate_identity_document,
    frozen.ACQUISITION_MANIFEST_NAME: _acquisition_manifest_document,
    frozen.ARTIFACT_MANIFEST_NAME: _artifact_manifest_document,
    frozen.RUNTIME_IDENTITY_NAME: _runtime_identity_document,
    frozen.THIRD_PARTY_USAGE_BINDING_NAME: _third_party_usage_binding_document,
    frozen.INPUT_DOMAIN_CONTRACT_NAME: _input_domain_contract_document,
    frozen.EXTRACTION_PROFILE_NAME: _extraction_profile_document,
    frozen.REPRESENTATION_PROFILE_NAME: _representation_profile_document,
    frozen.MATCHER_PROFILE_NAME: _matcher_profile_document,
    frozen.SCORE_CONTRACT_NAME: _score_contract_document,
    frozen.PAIR_SEMANTICS_NAME: _pair_semantics_document,
    frozen.DETERMINISM_REPORT_NAME: _determinism_report_document,
    frozen.RUNTIME_FEASIBILITY_NAME: _runtime_feasibility_document,
    frozen.TRAINING_PROVENANCE_NAME: _training_provenance_document,
    frozen.PREFLIGHT_REPORT_NAME: _preflight_report_document,
}


def evidence_document(
    preflight: VeriFingerPreflight, name: str
) -> Mapping[str, Any]:
    """One derivable document by file name, with the secret guard applied.

    Every document passes the guard before any caller sees it, so a document
    that acquired a credential cannot be written even by a caller that never
    checked (spec section 43).
    """
    builder = _DOCUMENT_BUILDERS.get(name)
    if builder is None:
        raise VeriFingerGateError(f"{name!r} is not a derivable Stage 11A document")
    document = builder(preflight)
    require_no_sensitive_material(document, where=name)
    return document


def marker_blocker_rows(
    blockers: Sequence[Blocker],
) -> tuple[Mapping[str, str], ...]:
    """The blockers in exactly the shape the marker stores them."""
    return tuple(
        dict(
            sorted(
                {
                    "gate": blocker.gate.value,
                    "blocker_code": blocker.blocker_code.value,
                    "affected_component": blocker.affected_component,
                    "evidence": blocker.evidence,
                    "why_this_blocks_algorithm_4": (
                        blocker.why_this_blocks_algorithm_4
                    ),
                    "how_this_would_be_lifted": blocker.how_this_would_be_lifted,
                }.items()
            )
        )
        for blocker in sorted(blockers, key=lambda item: item.blocker_code.value)
    )
