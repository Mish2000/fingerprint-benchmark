"""FLARE's artifacts, described by their bytes and decided by Stage 8E.

Two jobs, and the split between them is the point.

**What upstream says, and what this project may do about it.** Every FLARE
component gets one :class:`~fpbench.core.third_party_models.LicenseObservation`,
which is passed to :func:`~fpbench.third_party.policy.assess_research_use` and
comes back with a decision nobody here chose. Stage 9A adds no licence system,
no second vocabulary and no per-algorithm policy: Stage 8E is a closed stage and
this module is one of its callers (docs/adr/0082, docs/adr/0084).

**Where the bytes are, and whether they are the right ones.** A
:class:`~fpbench.core.third_party_models.LocalArtifactPlacement` per artifact
whose identity has been established, resolved against
``FPBENCH_THIRD_PARTY_ROOT`` at runtime and verified by size and then digest.
Nothing here is committed and nothing here is published.

**Enrollment is not verification.** The first time an artifact arrives there is
no expected digest to check it against, so the two operations are different
functions with different names. :func:`enroll_artifact` acquires, checks that
what arrived is structurally the kind of thing that was asked for, and *reports*
a digest and a size. Freezing them is a human edit to
:mod:`fpbench.experiments.stage9a_flare_identity`, reviewed like any other.
:func:`verify_artifact` then checks the bytes against what was frozen
(spec section 14).

**A Drive file id is a locator.** It is not an identity and this module never
treats it as one: the identity is the SHA-256 and the exact size, and until
those exist the artifact's ``identity_established`` is ``False`` and
:func:`~fpbench.third_party.policy.assess_research_use` blocks it — which is the
correct answer, not an inconvenience (spec section 15).

Acquisition runs on the project owner's machine and nowhere else. There is no
CI path into any function in this module that opens a socket, and the Stage 9A
workflow runs none of them (spec section 13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

from fpbench.core.flare_errors import FlareArtifactError, Stage9AFinalizationError
from fpbench.core.serialization import stable_hash
from fpbench.core.third_party_models import (
    LicenseEvidence,
    LicenseObservation,
    LicenseObservationStatus,
    LocalArtifactPlacement,
    NonBlockingRestriction,
    OwnerRiskAcceptance,
    RedistributionDecision,
    ResearchUseAssessment,
    ResearchUseDecision,
    ThirdPartyComponentKind,
    ThirdPartyUsageManifest,
    ThirdPartyUsageRecord,
    UpstreamIdentity,
)
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.third_party import (
    ArtifactVerification,
    PlausibleReading,
    assess_research_use,
    build_placement,
    build_usage_manifest,
    build_usage_record,
    policy_fingerprint,
    project_purpose,
    resolve_placement_path,
    resolve_third_party_root,
    verify_placed_artifact,
    verify_usage_record,
)

# ``file_sha256`` is not among the names Stage 8E's package re-exports, and
# Stage 8E is closed: widening its ``__init__`` to suit this stage is exactly
# the edit spec section 3 forbids. Importing the submodule is the alternative.
from fpbench.third_party.artifacts import file_sha256

__all__ = [
    "MANIFEST_ID",
    "OWNER",
    "OWNER_RISK_BASIS",
    "APACHE_NOTICE",
    "README_NOTICE",
    "ArtifactPlausibility",
    "FlareComponentMapping",
    "FlareUsageAudit",
    "ArtifactStatus",
    "ArtifactInventory",
    "require_stage8e_is_the_policy_this_reuses",
    "observation_for",
    "assessment_for",
    "build_flare_usage_audit",
    "placement_for",
    "placements",
    "check_plausibility",
    "acquire_artifact",
    "enroll_artifact",
    "verify_artifact",
    "build_artifact_inventory",
    "upstream_source_manifest",
    "artifact_manifest",
    "third_party_usage_manifest_document",
    "resolve_store_path",
]

MANIFEST_ID = "flare_third_party_usage"

OWNER = "the fpbench project owner"

OWNER_RISK_BASIS = (
    "The artifact was published intentionally by its official authors, is "
    "publicly obtainable without circumventing any access control, is executed "
    "only locally for personal educational research, is not expressly "
    "prohibited by any located term, and no byte of it is redistributed by this "
    "project. The owner accepts the risk of proceeding on that basis; nobody "
    "established a right (docs/adr/0084)."
)

#: The two notices every FLARE component carries, and they do not agree. Stage
#: 9A records both and resolves neither: which one governs is a legal question,
#: and the question this project has to answer is the narrower one of whether
#: every plausible reading permits its exact operation (docs/adr/0082).
APACHE_NOTICE = (
    "the repository's LICENSE file, the unmodified Apache License 2.0 text"
)
README_NOTICE = (
    "the repository README, which states the work is for academic research and "
    "educational purposes only and that commercial use is strictly prohibited"
)

#: Both notices permit one person running one program on one machine for
#: personal educational research and publishing nothing. That is the whole
#: intersection question, and the answer does not require deciding which notice
#: wins (spec section 17).
_INTERSECTION_READINGS: tuple[tuple[str, bool, bool, bool], ...] = (
    (APACHE_NOTICE, True, True, True),
    (README_NOTICE, True, True, True),
)

#: Restrictions the notices state. Real, recorded, respected, and not blockers:
#: none of them touches local non-commercial educational execution that
#: publishes nothing (docs/adr/0081).
_SOURCE_RESTRICTIONS: tuple[NonBlockingRestriction, ...] = (
    NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
    NonBlockingRestriction.EDUCATIONAL_ONLY,
    NonBlockingRestriction.NON_COMMERCIAL_ONLY,
    NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
    NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
    NonBlockingRestriction.COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT,
)

_SOURCE_BASIS = (
    "The repository carries a permissive LICENSE file and a README that limits "
    "use to academic research and education. Stage 9A does not decide which "
    "governs. Under every plausible reading, local non-commercial educational "
    "research that redistributes nothing is permitted, so the intersection "
    "contains this project's exact operation (docs/adr/0082)."
)

_SOURCE_REDISTRIBUTION_BASIS = (
    "Apache-2.0 would permit redistribution with notices retained; the README "
    "would not permit commercial redistribution at all. This project "
    "redistributes nothing, so the two readings do not have to be reconciled "
    "(docs/adr/0083)."
)

_WEIGHTS_BASIS = (
    "The checkpoint is hosted separately from the repository, on a Google Drive "
    "link named in the official README. No checkpoint-specific notice has been "
    "inspected and recorded here, and a repository licence does not "
    "automatically license separately hosted weights (docs/adr/0063). The "
    "project owner accepts the risk of executing it locally; that is not a "
    "finding that the use is permitted (docs/adr/0068)."
)

_WEIGHTS_REDISTRIBUTION_BASIS = (
    "Nothing was established either way, and this project publishes no "
    "checkpoint byte, no state dict, no tensor sample and no descriptor."
)

#: Every checkpoint. Enumerated rather than derived from the component kind so
#: that an artifact added later has to be classified deliberately.
_RISK_ACCEPTED_ARTIFACTS: frozenset[str] = frozenset(
    {
        "flare_fdd_checkpoint",
        "flare_voting_pose_checkpoint",
        "flare_regression_pose_checkpoint",
        "flare_unetenh_checkpoint",
        "flare_priorenh_checkpoint",
        "flare_prior_codebook_checkpoint",
    }
)

#: Bytes that plainly are not the artifact that was asked for. Checked before
#: anything is hashed, so a Drive interstitial is reported as an interstitial
#: rather than as a digest mismatch (spec section 15).
_HTML_PREFIXES: tuple[bytes, ...] = (
    b"<!doctype html",
    b"<!DOCTYPE html",
    b"<html",
    b"<HTML",
    b"\xef\xbb\xbf<!doctype",
)
_GZIP_MAGIC = b"\x1f\x8b"
_ZIP_MAGIC = b"PK\x03\x04"
_TORCH_ZIP_MAGIC = _ZIP_MAGIC
_PICKLE_PROTOCOL_2_MAGIC = b"\x80\x02"
_TAR_USTAR_OFFSET = 257
_MINIMUM_PLAUSIBLE_BYTES = 512


# ------------------------------------------------------------ the closed stage


def require_stage8e_is_the_policy_this_reuses(repository_root: Path) -> None:
    """Confirm the policy Stage 9A calls is the policy it was written against.

    Three checks, and each catches a different way this could go wrong: the
    published Stage 8E marker still says what it said, the live purpose and
    policy still fingerprint to what that marker recorded, and Stage 8E still
    declares that it opens this stage.

    Raises:
        Stage9AFinalizationError: any of the three disagrees. Stage 9A does not
            repair Stage 8E and does not proceed around it — a corrective policy
            stage is the response, not a quiet edit from here (spec section 3).
    """
    relative = (
        "evidence/stage8e-research-only-policy/stage-8e-finalization.json"
    )
    path = Path(repository_root) / PurePosixPath(relative)
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Stage9AFinalizationError(
            f"cannot read the Stage 8E marker Stage 9A reuses at {relative}: {exc}"
        ) from exc
    if not isinstance(marker, dict):
        raise Stage9AFinalizationError("the Stage 8E marker is not a JSON object")

    expected = {
        "outcome": frozen.STAGE8E_OUTCOME,
        "stage_8e_finalization_fingerprint": frozen.STAGE8E_FINALIZATION_FINGERPRINT,
        "purpose_fingerprint": frozen.STAGE8E_PURPOSE_FINGERPRINT,
        "policy_fingerprint": frozen.STAGE8E_POLICY_FINGERPRINT,
    }
    for key, value in expected.items():
        found = marker.get(key)
        if found != value:
            raise Stage9AFinalizationError(
                f"the Stage 8E marker's {key} is {found!r} and Stage 9A was "
                f"written against {value!r}. Stage 8E is a closed stage; a "
                "capability it lacks is a corrective policy stage, not an edit "
                "from here (spec section 3)"
            )
    if marker.get("opens_stage_9a") is not True:
        raise Stage9AFinalizationError(
            "the Stage 8E marker does not open Stage 9A"
        )

    declaration = project_purpose()
    if declaration.purpose_fingerprint != frozen.STAGE8E_PURPOSE_FINGERPRINT:
        raise Stage9AFinalizationError(
            "the live project purpose no longer fingerprints to what Stage 8E "
            "published; every FLARE decision would be taken under a different "
            "premise"
        )
    if policy_fingerprint() != frozen.STAGE8E_POLICY_FINGERPRINT:
        raise Stage9AFinalizationError(
            "the live third-party policy no longer fingerprints to what Stage "
            "8E published"
        )


# ----------------------------------------------------- observation and decision


def _repository_for(artifact: frozen.RequiredArtifact) -> frozen.UpstreamRepository:
    for repository in frozen.UPSTREAM_REPOSITORIES:
        if repository.repository_id == artifact.repository_id:
            return repository
    raise FlareArtifactError(
        f"{artifact.artifact_id} names repository {artifact.repository_id!r}, "
        "which Stage 9A has not pinned"
    )


def observation_for(artifact: frozen.RequiredArtifact) -> LicenseObservation:
    """What upstream's notices say about one FLARE component. Nothing more.

    Two shapes, because there are two situations and they are not the same one:

    * anything that ships **inside** a pinned repository carries that
      repository's two notices, and they conflict — ``CONFLICTING_NOTICES``,
      with both documents cited by digest;
    * a checkpoint hosted **outside** it carries nothing this project has
      inspected — ``UNKNOWN``, which says nobody has looked, rather than
      ``NO_LICENSE_FOUND``, which would claim an inspection that has not
      happened (docs/adr/0082).
    """
    repository = _repository_for(artifact)
    if artifact.locator_kind == "google_drive_file":
        return LicenseObservation(
            observation_id=f"{artifact.artifact_id}_observation",
            component_kind=artifact.component_kind,
            subject=artifact.subject,
            status=LicenseObservationStatus.UNKNOWN,
            evidence=(),
            notes=(
                "Hosted outside the repository that documents it. The Drive "
                "file id is a locator, not an identity.",
            ),
        )
    return LicenseObservation(
        observation_id=f"{artifact.artifact_id}_observation",
        component_kind=artifact.component_kind,
        subject=artifact.subject,
        status=LicenseObservationStatus.CONFLICTING_NOTICES,
        declared_license_names=("Apache License 2.0", "Academic Research License"),
        spdx_identifiers=("Apache-2.0",),
        evidence=(
            LicenseEvidence(
                locator=f"{repository.html_locator}/blob/{repository.commit}/LICENSE",
                description=APACHE_NOTICE,
                document_sha256=repository.license_document_sha256,
            ),
            LicenseEvidence(
                locator=f"{repository.html_locator}/blob/{repository.commit}/README.md",
                description=README_NOTICE,
                document_sha256=repository.readme_document_sha256,
            ),
        ),
        stated_restrictions=(
            "Apache-2.0 requires notices to be retained in a distribution.",
            "The README limits use to academic research and educational "
            "purposes and prohibits commercial use.",
        ),
    )


def assessment_for(
    artifact: frozen.RequiredArtifact, observation: LicenseObservation
) -> ResearchUseAssessment:
    """Derive the one decision that follows. Stage 9A supplies facts, not verdicts."""
    acceptance = None
    if artifact.artifact_id in _RISK_ACCEPTED_ARTIFACTS:
        acceptance = OwnerRiskAcceptance(
            published_intentionally_by_official_authors=True,
            publicly_obtainable_without_circumvention=True,
            intended_operation_is_local_research_only=True,
            no_located_term_expressly_prohibits_the_use=True,
            no_bytes_will_be_redistributed=True,
            accepted_by=OWNER,
            basis=OWNER_RISK_BASIS,
        )
        readings = None
        restrictions: tuple[NonBlockingRestriction, ...] = ()
        basis = _WEIGHTS_BASIS
    else:
        readings = tuple(
            PlausibleReading(
                notice_locator=locator,
                permits_local_execution=local,
                permits_non_commercial_use=non_commercial,
                permits_educational_research=educational,
            )
            for locator, local, non_commercial, educational in _INTERSECTION_READINGS
        )
        restrictions = _SOURCE_RESTRICTIONS
        basis = _SOURCE_BASIS
    return assess_research_use(
        observation,
        assessment_id=f"{artifact.artifact_id}_research_use",
        basis=basis,
        non_blocking_restrictions=restrictions,
        identity_established=artifact.identity_established,
        intersection_readings=readings,
        owner_risk_acceptance=acceptance,
    )


@dataclass(frozen=True, slots=True)
class FlareComponentMapping:
    """One FLARE component, run through the engine Stage 8E froze."""

    artifact_id: str
    component_role: str
    observation: LicenseObservation
    assessment: ResearchUseAssessment
    record: ThirdPartyUsageRecord


@dataclass(frozen=True, slots=True)
class FlareUsageAudit:
    """Every FLARE component, mapped, verified and counted.

    Publishes identities, statuses and decisions. It publishes no licence text,
    no upstream source, no checkpoint byte and no tensor — the digests in it are
    expectations about files that live outside this repository.
    """

    mappings: tuple[FlareComponentMapping, ...]
    manifest: ThirdPartyUsageManifest
    audit_fingerprint: str

    def by_decision(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.assessment.decision.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def by_status(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.observation.status.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def by_kind(self) -> Mapping[str, int]:
        counts: dict[str, int] = {}
        for mapping in self.mappings:
            key = mapping.record.component_kind.value
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    @property
    def blocked(self) -> tuple[FlareComponentMapping, ...]:
        return tuple(
            mapping
            for mapping in self.mappings
            if mapping.assessment.decision is ResearchUseDecision.BLOCKED
        )

    @property
    def opens_execution(self) -> bool:
        """Whether every required component may be executed under the policy."""
        return not self.blocked

    def mapping(self, artifact_id: str) -> FlareComponentMapping:
        for mapping in self.mappings:
            if mapping.artifact_id == artifact_id:
                return mapping
        raise KeyError(artifact_id)


def build_flare_usage_audit() -> FlareUsageAudit:
    """Map every FLARE component, then verify each mapping re-derives.

    Raises:
        Stage9AFinalizationError: a mapping does not survive its own
            verification. Publishing a decision nobody had checked would be
            worse than publishing none.
    """
    mappings: list[FlareComponentMapping] = []
    for artifact in frozen.REQUIRED_ARTIFACTS:
        observation = observation_for(artifact)
        assessment = assessment_for(artifact, observation)
        record = build_usage_record(
            record_id=artifact.artifact_id,
            observation=observation,
            assessment=assessment,
            upstream_identity=UpstreamIdentity(
                upstream_name=artifact.upstream_name,
                upstream_locator=artifact.locator,
                exact_version=_repository_for(artifact).commit,
                upstream_commit=_repository_for(artifact).commit,
                artifact_filename=PurePosixPath(
                    artifact.upstream_relative_path
                ).name
                if artifact.upstream_relative_path != "."
                else _repository_for(artifact).archive_filename,
                artifact_sha256=artifact.expected_sha256,
                artifact_size_bytes=artifact.expected_size_bytes,
                identity_established=artifact.identity_established,
            ),
            redistribution_decision=(
                RedistributionDecision.NOT_ESTABLISHED
                if artifact.artifact_id in _RISK_ACCEPTED_ARTIFACTS
                else RedistributionDecision.CONDITIONAL
            ),
            redistribution_basis=(
                _WEIGHTS_REDISTRIBUTION_BASIS
                if artifact.artifact_id in _RISK_ACCEPTED_ARTIFACTS
                else _SOURCE_REDISTRIBUTION_BASIS
            ),
            notes=artifact.notes,
        )
        report = verify_usage_record(record, observation, assessment)
        if not report.verified:
            raise Stage9AFinalizationError(
                f"{artifact.artifact_id}: the mapping does not survive "
                f"re-derivation: {report.findings}"
            )
        mappings.append(
            FlareComponentMapping(
                artifact_id=artifact.artifact_id,
                component_role=artifact.component_role,
                observation=observation,
                assessment=assessment,
                record=record,
            )
        )

    ordered = tuple(sorted(mappings, key=lambda item: item.artifact_id))
    manifest = build_usage_manifest(
        manifest_id=MANIFEST_ID,
        subject=(
            "every third-party component of the full FLARE route: two official "
            "source repositories, six checkpoints and two inference "
            "configurations"
        ),
        records=tuple(mapping.record for mapping in ordered),
    )
    return FlareUsageAudit(
        mappings=ordered,
        manifest=manifest,
        audit_fingerprint=stable_hash(
            {
                "schema": "stage_9a_flare_usage_audit_v1",
                "records": [
                    {
                        "artifact_id": mapping.artifact_id,
                        "observation_fingerprint": (
                            mapping.observation.observation_fingerprint
                        ),
                        "assessment_fingerprint": (
                            mapping.assessment.assessment_fingerprint
                        ),
                        "usage_fingerprint": mapping.record.usage_fingerprint,
                    }
                    for mapping in ordered
                ],
                "manifest": manifest.manifest_fingerprint,
            },
            length=64,
        ),
    )


# ------------------------------------------------------------------ placements


def placement_for(artifact: frozen.RequiredArtifact) -> LocalArtifactPlacement:
    """Where one artifact's bytes belong, expressed without naming a machine.

    Raises:
        FlareArtifactError: the artifact's identity has not been established.
            A placement carries the digest and the size the bytes must have, and
            an artifact nobody has enrolled has neither (spec section 14).
    """
    if not artifact.identity_established:
        raise FlareArtifactError(
            f"{artifact.artifact_id}: no placement, because no identity. Enroll "
            "it from its official locator first; a placement with no expected "
            "digest would verify anything"
        )
    return build_placement(
        placement_id=f"{artifact.artifact_id}_placement",
        component_role=artifact.component_role,
        component_kind=artifact.component_kind,
        relative_location=artifact.store_relative_location,
        expected_sha256=str(artifact.expected_sha256),
        expected_size_bytes=int(artifact.expected_size_bytes or 0),
        upstream_identity=UpstreamIdentity(
            upstream_name=artifact.upstream_name,
            upstream_locator=artifact.locator,
            exact_version=_repository_for(artifact).commit,
            upstream_commit=_repository_for(artifact).commit,
            artifact_filename=PurePosixPath(artifact.store_relative_location).name,
            artifact_sha256=artifact.expected_sha256,
            artifact_size_bytes=artifact.expected_size_bytes,
            identity_established=True,
        ),
    )


def placements() -> tuple[LocalArtifactPlacement, ...]:
    """A placement for every artifact whose identity has been established."""
    return tuple(
        placement_for(artifact)
        for artifact in frozen.REQUIRED_ARTIFACTS
        if artifact.identity_established
    )


# ----------------------------------------------------------------- plausibility


@dataclass(frozen=True, slots=True)
class ArtifactPlausibility:
    """Whether what arrived is the *kind* of thing that was asked for.

    A structural check, run before anything is hashed. Its whole job is to make
    "Google served an interstitial HTML page instead of a checkpoint" say that,
    rather than say "digest mismatch" — which is true and useless
    (spec section 15).
    """

    artifact_id: str
    plausible: bool
    observed_size_bytes: int
    detected_form: str
    findings: tuple[str, ...] = ()


def _detect_form(head: bytes, tail_probe: bytes) -> str:
    if any(head.lower().startswith(prefix.lower()) for prefix in _HTML_PREFIXES):
        return "html_document"
    if head.startswith(_GZIP_MAGIC):
        return "gzip_archive"
    if head.startswith(_ZIP_MAGIC):
        return "zip_container"
    if head.startswith(_PICKLE_PROTOCOL_2_MAGIC):
        return "pickle_stream"
    if tail_probe[:5] == b"ustar":
        return "tar_archive"
    return "unrecognised"


def _expected_forms(artifact: frozen.RequiredArtifact) -> tuple[str, ...]:
    if artifact.locator_kind == "https_archive":
        return ("gzip_archive",)
    if artifact.locator_kind == "in_source_tree":
        return ("unrecognised",)  # a small YAML file has no magic number
    # A torch checkpoint is either a zip container (torch >= 1.6) or a raw
    # pickle stream (older). Both are legitimate and upstream pins neither.
    return ("zip_container", "pickle_stream", "gzip_archive", "tar_archive")


def check_plausibility(
    artifact: frozen.RequiredArtifact, path: Path
) -> ArtifactPlausibility:
    """Look at the first and last bytes of a file, and say what it appears to be."""
    path = Path(path)
    findings: list[str] = []
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(1024)
            if size > _TAR_USTAR_OFFSET + 8:
                stream.seek(_TAR_USTAR_OFFSET)
                tail_probe = stream.read(8)
            else:
                tail_probe = b""
    except OSError as exc:
        raise FlareArtifactError(
            f"{artifact.artifact_id}: cannot inspect {path.name}: {exc}"
        ) from exc

    if size == 0:
        findings.append("the file is empty")
    elif size < _MINIMUM_PLAUSIBLE_BYTES and artifact.locator_kind != "in_source_tree":
        findings.append(
            f"{size} bytes is too small to be {artifact.component_role}"
        )

    form = _detect_form(head, tail_probe)
    if form == "html_document":
        findings.append(
            "an HTML document arrived, which is what a download portal serves "
            "instead of a file"
        )
    expected = _expected_forms(artifact)
    if form not in expected and form != "html_document":
        findings.append(
            f"the bytes look like {form} and this locator yields one of "
            f"{sorted(expected)}"
        )
    if (
        artifact.expected_size_bytes is not None
        and size != artifact.expected_size_bytes
    ):
        findings.append(
            f"{size} bytes arrived and the frozen identity expects "
            f"{artifact.expected_size_bytes}"
        )
    return ArtifactPlausibility(
        artifact_id=artifact.artifact_id,
        plausible=not findings,
        observed_size_bytes=size,
        detected_form=form,
        findings=tuple(findings),
    )


# ------------------------------------------------------------------ acquisition


def acquire_artifact(
    artifact: frozen.RequiredArtifact,
    *,
    root: Path | None = None,
    repository_root: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Fetch one artifact from its official locator into the local store.

    Local only. Nothing in the Stage 9A test suite or workflow calls this, and
    the frozen policy says CI downloads no restricted artifact (spec section
    13).

    Google Drive is fetched through its own confirmation flow, because a large
    Drive file answers the first request with an interstitial page rather than
    with bytes. The result is checked by :func:`check_plausibility` before it is
    kept, so an interstitial that slipped through is deleted and named.

    Raises:
        FlareArtifactError: the download failed, or what arrived is not
            structurally the kind of thing this locator yields.
    """
    import urllib.error
    import urllib.request

    store = resolve_third_party_root(repository_root=repository_root)
    if root is not None:
        store = Path(root)
    destination = store / PurePosixPath(artifact.store_relative_location)
    if destination.exists() and not overwrite:
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")

    try:
        if artifact.locator_kind == "google_drive_file":
            _download_drive_file(artifact.locator.split(":", 1)[1], temporary)
        else:
            with urllib.request.urlopen(artifact.locator, timeout=600) as response:
                temporary.write_bytes(response.read())
    except (OSError, urllib.error.URLError, ValueError) as exc:
        temporary.unlink(missing_ok=True)
        raise FlareArtifactError(
            f"{artifact.artifact_id}: acquisition from its official locator "
            f"failed: {exc}"
        ) from exc

    plausibility = check_plausibility(artifact, temporary)
    if not plausibility.plausible:
        temporary.unlink(missing_ok=True)
        raise FlareArtifactError(
            f"{artifact.artifact_id}: what arrived is not "
            f"{artifact.component_role}: {list(plausibility.findings)}"
        )
    temporary.replace(destination)
    return destination


def _download_drive_file(file_id: str, destination: Path) -> None:
    """Fetch one public Drive file, following its confirmation once.

    No credential is used and no access control is circumvented: these are files
    the official README publishes links to, and the confirmation page is the
    ordinary interstitial Drive serves for anything large enough to skip a virus
    scan (docs/adr/0084).
    """
    import http.cookiejar
    import urllib.parse
    import urllib.request

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    base = "https://drive.usercontent.google.com/download"
    query = urllib.parse.urlencode({"id": file_id, "export": "download"})
    with opener.open(f"{base}?{query}", timeout=600) as response:
        payload = response.read()

    if any(payload[:64].lower().startswith(prefix.lower()) for prefix in _HTML_PREFIXES):
        text = payload.decode("utf-8", "replace")
        fields = dict(_confirmation_fields(text))
        if not fields:
            raise ValueError(
                "Drive answered with a page that carries no confirmation form; "
                "the file may not be publicly shared"
            )
        with opener.open(
            f"{base}?{urllib.parse.urlencode(fields)}", timeout=600
        ) as response:
            payload = response.read()
    destination.write_bytes(payload)


def _confirmation_fields(text: str) -> Iterable[tuple[str, str]]:
    import re

    for match in re.finditer(
        r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', text
    ):
        yield match.group(1), match.group(2)


@dataclass(frozen=True, slots=True)
class ArtifactStatus:
    """One artifact, as this machine finds it.

    ``identity_frozen`` and ``verified`` are different claims and the gap
    between them is the whole of enrollment: an artifact can be present and
    correct on this machine while the repository still holds no expectation
    about it.
    """

    artifact_id: str
    component_role: str
    identity_frozen: bool
    present: bool
    verified: bool
    observed_size_bytes: int | None = None
    findings: tuple[str, ...] = ()


def enroll_artifact(
    artifact: frozen.RequiredArtifact,
    *,
    root: Path | None = None,
    repository_root: Path | None = None,
) -> tuple[str, int]:
    """Establish an identity for an artifact that does not have one yet.

    Returns the ``(sha256, size)`` that would have to be frozen in
    :mod:`fpbench.experiments.stage9a_flare_identity` for this artifact to be
    verifiable. It does **not** write them: a digest that the code minted for
    itself and then checked against itself would prove nothing, and freezing an
    identity is a reviewed edit (spec section 14).

    Raises:
        FlareArtifactError: the file is absent, or is not structurally the kind
            of thing the locator yields.
    """
    store = Path(root) if root is not None else resolve_third_party_root(
        repository_root=repository_root
    )
    path = store / PurePosixPath(artifact.store_relative_location)
    if not path.is_file():
        raise FlareArtifactError(
            f"{artifact.artifact_id}: nothing at "
            f"{artifact.store_relative_location} in the local artifact store. "
            "Acquire it from its official locator first"
        )
    plausibility = check_plausibility(artifact, path)
    if not plausibility.plausible:
        raise FlareArtifactError(
            f"{artifact.artifact_id}: refusing to enroll bytes that are not "
            f"{artifact.component_role}: {list(plausibility.findings)}"
        )
    return file_sha256(path), plausibility.observed_size_bytes


def verify_artifact(
    artifact: frozen.RequiredArtifact,
    *,
    root: Path | None = None,
    repository_root: Path | None = None,
) -> ArtifactVerification:
    """Check the bytes on this machine against the bytes the manifest expects."""
    store = Path(root) if root is not None else resolve_third_party_root(
        repository_root=repository_root
    )
    return verify_placed_artifact(placement_for(artifact), root=store)


@dataclass(frozen=True, slots=True)
class ArtifactInventory:
    """Every required artifact, and what this machine has of it."""

    statuses: tuple[ArtifactStatus, ...]
    required_count: int
    identity_established_count: int
    locally_verified_count: int
    store_present: bool

    @property
    def all_identities_established(self) -> bool:
        return self.identity_established_count == self.required_count

    @property
    def all_locally_verified(self) -> bool:
        return self.locally_verified_count == self.required_count

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(
            status.artifact_id for status in self.statuses if not status.verified
        )


def build_artifact_inventory(
    *, root: Path | None = None, repository_root: Path | None = None
) -> ArtifactInventory:
    """Look for every required artifact, without requiring any of them to be here.

    Absence is an ordinary state — it is true of every CI runner by design — so
    it is reported rather than raised. What is *not* ordinary is a file of the
    right name whose bytes are different, and that appears as a finding.
    """
    try:
        store = Path(root) if root is not None else resolve_third_party_root(
            repository_root=repository_root
        )
        store_present = store.is_dir()
    except Exception:  # pragma: no cover - an unusable store is simply absent
        store = None
        store_present = False

    statuses: list[ArtifactStatus] = []
    for artifact in frozen.REQUIRED_ARTIFACTS:
        if not artifact.identity_established:
            statuses.append(
                ArtifactStatus(
                    artifact_id=artifact.artifact_id,
                    component_role=artifact.component_role,
                    identity_frozen=False,
                    present=False,
                    verified=False,
                    findings=(
                        "no identity has been established for this artifact; "
                        "its Drive file id is a locator and not a digest",
                    ),
                )
            )
            continue
        if store is None:
            statuses.append(
                ArtifactStatus(
                    artifact_id=artifact.artifact_id,
                    component_role=artifact.component_role,
                    identity_frozen=True,
                    present=False,
                    verified=False,
                    findings=("no local artifact store is resolvable here",),
                )
            )
            continue
        verification = verify_placed_artifact(placement_for(artifact), root=store)
        findings: list[str] = []
        if not verification.present:
            findings.append("absent from the local artifact store")
        else:
            if not verification.size_matches:
                findings.append(
                    f"{verification.observed_size_bytes} bytes on disk and "
                    f"{artifact.expected_size_bytes} expected"
                )
            if not verification.digest_matches:
                findings.append("the bytes on disk are not the bytes expected")
        statuses.append(
            ArtifactStatus(
                artifact_id=artifact.artifact_id,
                component_role=artifact.component_role,
                identity_frozen=True,
                present=verification.present,
                verified=verification.verified,
                observed_size_bytes=verification.observed_size_bytes,
                findings=tuple(findings),
            )
        )

    ordered = tuple(sorted(statuses, key=lambda item: item.artifact_id))
    return ArtifactInventory(
        statuses=ordered,
        required_count=len(frozen.REQUIRED_ARTIFACTS),
        identity_established_count=sum(1 for item in ordered if item.identity_frozen),
        locally_verified_count=sum(1 for item in ordered if item.verified),
        store_present=store_present,
    )


# ------------------------------------------------------------ published documents


def upstream_source_manifest() -> Mapping[str, object]:
    """The two repositories, pinned. No branch is an identity here."""
    return {
        "schema": "stage_9a_upstream_source_manifest_v1",
        "required_source_repositories": frozen.REQUIRED_SOURCE_REPOSITORIES,
        "repositories": [
            {
                "repository_id": repository.repository_id,
                "upstream_name": repository.upstream_name,
                "upstream_locator": repository.html_locator,
                "role": repository.role,
                "default_branch_observed_at_acquisition": (
                    repository.default_branch_observed
                ),
                "upstream_commit": repository.commit,
                "source_archive_locator": repository.archive_locator,
                "source_archive_filename": repository.archive_filename,
                "source_archive_sha256": repository.archive_sha256,
                "source_archive_size_bytes": repository.archive_size_bytes,
                "license_document_sha256": repository.license_document_sha256,
                "readme_document_sha256": repository.readme_document_sha256,
                "acquisition_timestamp_utc": repository.acquisition_timestamp_utc,
            }
            for repository in frozen.UPSTREAM_REPOSITORIES
        ],
        "upstream_state_observed_at": {
            repository.repository_id: repository.commit
            for repository in frozen.UPSTREAM_REPOSITORIES
        },
        "branch_names_are_not_identities": True,
        "notes": [
            "Both archives were acquired twice, independently, from the same "
            "locator and were byte-identical, which is what makes a generated "
            "tarball usable as an identity here.",
            "The FDD checkpoint load in extract_FDD.py is present and active at "
            "the pinned FLARE commit. An earlier reading of this repository, "
            "against an earlier upstream state, recorded it as disabled; that "
            "is why a commit is pinned rather than a branch.",
        ],
    }


def artifact_manifest(inventory: ArtifactInventory) -> Mapping[str, object]:
    """Every artifact the full route needs, and what is known about each."""
    return {
        "schema": "stage_9a_artifact_manifest_v1",
        "artifact_store_environment_variable": "FPBENCH_THIRD_PARTY_ROOT",
        "artifact_store_prefix": frozen.ARTIFACT_STORE_PREFIX,
        "manifests_hold_no_absolute_path": True,
        "required_artifact_count": inventory.required_count,
        "identity_established_count": inventory.identity_established_count,
        "locally_verified_count": inventory.locally_verified_count,
        "transitive_discovery": [
            {
                "discovered_from": source,
                "key": key,
                "artifact_id": discovered,
            }
            for source, key, discovered in frozen.TRANSITIVE_ARTIFACT_SOURCES
        ],
        "artifacts": [
            {
                "artifact_id": artifact.artifact_id,
                "component_role": artifact.component_role,
                "component_kind": artifact.component_kind.value,
                "subject": artifact.subject,
                "upstream_name": artifact.upstream_name,
                "upstream_locator": artifact.locator,
                "locator_kind": artifact.locator_kind,
                "upstream_relative_path": artifact.upstream_relative_path,
                "store_relative_location": artifact.store_relative_location,
                "repository_id": artifact.repository_id,
                "required_by": list(artifact.required_by),
                "discovered_from": artifact.discovered_from,
                "expected_sha256": artifact.expected_sha256,
                "expected_size_bytes": artifact.expected_size_bytes,
                "identity_established": artifact.identity_established,
                "notes": list(artifact.notes),
            }
            for artifact in frozen.REQUIRED_ARTIFACTS
        ],
        "local_status": [
            {
                "artifact_id": status.artifact_id,
                "identity_frozen": status.identity_frozen,
                "present": status.present,
                "verified": status.verified,
                "findings": list(status.findings),
            }
            for status in inventory.statuses
        ],
    }


def third_party_usage_manifest_document(
    audit: FlareUsageAudit,
) -> Mapping[str, object]:
    """The Stage 8E manifest for FLARE, published in Stage 8E's own vocabulary."""
    return {
        "schema": "stage_9a_third_party_usage_manifest_v1",
        "manifest_id": audit.manifest.manifest_id,
        "subject": audit.manifest.subject,
        "purpose_fingerprint": audit.manifest.purpose_fingerprint,
        "policy_fingerprint": audit.manifest.policy_fingerprint,
        "manifest_fingerprint": audit.manifest.manifest_fingerprint,
        "audit_fingerprint": audit.audit_fingerprint,
        "opens_execution": audit.opens_execution,
        "by_decision": dict(audit.by_decision()),
        "by_license_observation_status": dict(audit.by_status()),
        "by_component_kind": dict(audit.by_kind()),
        "records": [
            {
                "record_id": mapping.record.record_id,
                "component_role": mapping.component_role,
                "component_kind": mapping.record.component_kind.value,
                "license_observation_status": (
                    mapping.record.license_observation_status.value
                ),
                "license_observation_fingerprint": (
                    mapping.record.license_observation_fingerprint
                ),
                "license_evidence_locators": list(
                    mapping.record.license_evidence_locators
                ),
                "research_use_decision": mapping.record.research_use_decision.value,
                "research_use_assessment_fingerprint": (
                    mapping.record.research_use_assessment_fingerprint
                ),
                "intended_use_permission_status": (
                    mapping.assessment.intended_use_permission_status.value
                ),
                "non_blocking_restrictions": [
                    restriction.value
                    for restriction in mapping.assessment.non_blocking_restrictions
                ],
                "blockers": [
                    blocker.value for blocker in mapping.assessment.blockers
                ],
                "intersection_permits_intended_use": (
                    mapping.assessment.intersection_permits_intended_use
                ),
                "owner_risk_acceptance": mapping.record.owner_risk_acceptance,
                "redistribution_decision": (
                    mapping.record.redistribution.decision.value
                ),
                "redistributed_by_fpbench": (
                    mapping.record.redistribution.redistributed_by_fpbench
                ),
                "storage_class": mapping.record.storage_class.value,
                "stored_in_git": mapping.record.stored_in_git,
                "stored_in_ci_artifacts": mapping.record.stored_in_ci_artifacts,
                "usage_fingerprint": mapping.record.usage_fingerprint,
            }
            for mapping in audit.mappings
        ],
        "notes": [
            "Stage 8E decided every one of these. Stage 9A supplied the "
            "observations and the facts and supplied no verdict; there is no "
            "parameter through which it could have (docs/adr/0082).",
            "No licence question about FLARE was resolved here. Both "
            "repositories carry a permissive LICENSE file and a README that "
            "restricts use, and Stage 9A records both without choosing.",
        ],
    }


def resolve_store_path(
    artifact: frozen.RequiredArtifact, *, root: Path
) -> Path:
    """The absolute path of one artifact on this machine, for a local caller.

    The only function here that produces one, and it does so through Stage 8E's
    resolver so that a location which escaped the store is a refusal rather than
    a read somewhere else on the disk. No value it returns reaches published
    evidence (spec section 51).
    """
    return resolve_placement_path(placement_for(artifact), root=Path(root))
