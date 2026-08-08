"""What upstream terms say, what this project decided to do, and never both at once.

Stage 8E's whole contribution is a separation that the earlier stages kept
collapsing. Three questions live here, in three vocabularies that do not mix:

**What does upstream licensing say?** A :class:`LicenseObservation`. It is a
*description* — a status, the notices it was read from, and the restrictions
those notices state. It reaches no conclusion, and the class refuses to carry
one. ``CONFLICTING_NOTICES`` is a perfectly ordinary observation and is not a
problem waiting to be resolved (docs/adr/0082).

**May fpbench execute it locally, under this project's purpose?** A
:class:`ResearchUseAssessment`. It cites exactly one observation, states one
decision, and names its basis. A restriction that has nothing to do with the
intended use — no commercial deployment, no redistribution, no sublicensing,
copyleft — is recorded and is not a blocker, because this project does none of
those things (docs/adr/0081).

**May fpbench redistribute it?** A :class:`RedistributionRecord`, and the answer
this project gives is always the same one: it does not, whatever the terms allow
(docs/adr/0083).

A fourth thing lives here because it is the premise of the second: the frozen
:class:`ProjectPurposeDeclaration`. Every research-use decision is taken under
it, and a decision that cited a different purpose would be a decision nobody
could reproduce.

The dataclasses live in ``core`` because the storage layer persists them and
``storage`` may only import ``core``. The rules that *derive* them live in
:mod:`fpbench.third_party`, which re-exports the containers — the same split
:mod:`fpbench.calibration` and :mod:`fpbench.decisions` use.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from fpbench.core.identifiers import validate_id
from fpbench.core.serialization import require_exact_int, stable_hash, to_plain
from fpbench.core.third_party_errors import (
    LicenseObservationError,
    RedistributionError,
    ResearchUseDecisionError,
    ThirdPartyArtifactError,
    ThirdPartyPurposeError,
    ThirdPartyUsageError,
    UpstreamTransformationError,
)

__all__ = [
    "PROJECT_PURPOSE_SCHEMA_VERSION",
    "LICENSE_OBSERVATION_SCHEMA_VERSION",
    "RESEARCH_USE_ASSESSMENT_SCHEMA_VERSION",
    "THIRD_PARTY_USAGE_SCHEMA_VERSION",
    "THIRD_PARTY_POLICY_SCHEMA_VERSION",
    "ProjectPurpose",
    "ThirdPartyComponentKind",
    "LicenseObservationStatus",
    "ResearchUseDecision",
    "RedistributionDecision",
    "ResearchUseBlocker",
    "NonBlockingRestriction",
    "IntendedUsePermissionStatus",
    "ArtifactStorageClass",
    "UpstreamModificationStrategy",
    "TransformationClassification",
    "ProjectPurposeDeclaration",
    "UpstreamIdentity",
    "LicenseEvidence",
    "LicenseObservation",
    "OwnerRiskAcceptance",
    "ResearchUseAssessment",
    "RedistributionRecord",
    "ThirdPartyUsageRecord",
    "ThirdPartyUsageManifest",
    "ThirdPartyPolicy",
    "LocalArtifactPlacement",
    "UpstreamTransformation",
    "project_purpose_fingerprint",
    "license_observation_fingerprint",
    "research_use_assessment_fingerprint",
    "third_party_usage_fingerprint",
    "third_party_usage_manifest_fingerprint",
    "third_party_policy_fingerprint",
    "local_artifact_placement_fingerprint",
    "upstream_transformation_fingerprint",
    "require_digest",
    "require_optional_digest",
    "require_exact_bool",
    "require_text",
    "require_text_tuple",
    "strict_json_document",
    "require_exact_keys",
    "read_str",
    "read_bool",
    "read_int",
    "read_digest",
    "read_enum",
    "read_str_tuple",
    "read_project_purpose_declaration",
    "read_license_observation",
    "read_research_use_assessment",
    "read_third_party_usage_record",
    "read_third_party_policy",
]

#: Five independent versions rather than one. A purpose declaration and a usage
#: record are not obliged to evolve together, and a stage that had to bump every
#: schema to change one of them would be a stage nobody could review.
PROJECT_PURPOSE_SCHEMA_VERSION = "1"
LICENSE_OBSERVATION_SCHEMA_VERSION = "1"
RESEARCH_USE_ASSESSMENT_SCHEMA_VERSION = "1"
THIRD_PARTY_USAGE_SCHEMA_VERSION = "1"
THIRD_PARTY_POLICY_SCHEMA_VERSION = "1"

_HEX = frozenset("0123456789abcdef")


# ------------------------------------------------------------------- strictness


def require_digest(value: object, field_name: str) -> str:
    """A 64-character lowercase hexadecimal digest, or a refusal."""
    digest = str(value).strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise ValueError(f"{field_name} must be a 64-character hexadecimal digest")
    return digest


def require_optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return require_digest(value, field_name)


def require_exact_bool(value: object, field_name: str) -> bool:
    """A ``bool``, without accepting ``1``, ``"true"`` or a truthy object.

    Load-bearing here in a way it rarely is elsewhere: the flags below are the
    ones that say this project does not redistribute, does not commercialise and
    stores no third-party byte in Git. A coercion would let a document make a
    claim its bytes do not support.
    """
    if type(value) is not bool:
        raise ValueError(
            f"{field_name} must be a boolean, got {type(value).__name__}"
        )
    return value


def require_text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    text = str(value).strip()
    if not text and not allow_empty:
        raise ValueError(f"{field_name} must not be empty")
    return text


def require_text_tuple(values: Iterable[Any] | None, field_name: str) -> tuple[str, ...]:
    """A tuple of non-empty strings, deduplicated and sorted.

    Sorted so that the fingerprint of a record does not depend on the order
    somebody happened to list its evidence in; deduplicated because the same
    notice cited twice is one notice.
    """
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence of strings, not one string")
    items = {require_text(item, f"{field_name}[]") for item in values}
    return tuple(sorted(items))


def _enum_tuple(values: Iterable[Any] | None, enum_type: type, field_name: str) -> tuple:
    if values is None:
        return ()
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_name} must be a sequence, not one string")
    items = []
    for item in values:
        if not isinstance(item, enum_type):
            raise ValueError(
                f"{field_name} must hold {enum_type.__name__} members; "
                f"a bare string is a value nothing validated"
            )
        items.append(item)
    unique = {item.value: item for item in items}
    return tuple(unique[value] for value in sorted(unique))


def strict_json_document(text: str) -> Mapping[str, Any]:
    """Parse JSON into a mapping, refusing duplicate keys.

    ``json.loads`` keeps the last of two identical keys and says nothing. A
    document whose meaning depends on which duplicate survived is a document two
    readers can disagree about while holding the same bytes.
    """

    def _no_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        seen: dict[str, Any] = {}
        for key, value in pairs:
            if key in seen:
                raise ValueError(f"duplicate key {key!r} in a third-party document")
            seen[key] = value
        return seen

    document = json.loads(text, object_pairs_hook=_no_duplicates)
    if not isinstance(document, dict):
        raise ValueError("a third-party document must be a JSON object")
    return document


def require_exact_keys(
    document: Mapping[str, Any], expected: Iterable[str], *, what: str
) -> None:
    present = set(document)
    wanted = set(expected)
    missing = sorted(wanted - present)
    extra = sorted(present - wanted)
    if missing:
        raise ValueError(f"{what} is missing {missing}")
    if extra:
        raise ValueError(f"{what} carries keys nothing accounts for: {extra}")


def read_str(document: Mapping[str, Any], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def read_bool(document: Mapping[str, Any], key: str) -> bool:
    return require_exact_bool(document.get(key), key)


def read_int(document: Mapping[str, Any], key: str) -> int:
    return require_exact_int(document.get(key), key)


def read_digest(document: Mapping[str, Any], key: str) -> str:
    return require_digest(document.get(key), key)


def read_enum(document: Mapping[str, Any], key: str, enum_type: type):
    raw = read_str(document, key)
    try:
        return enum_type(raw)
    except ValueError:
        allowed = sorted(member.value for member in enum_type)
        raise ValueError(f"{key} must be one of {allowed}, got {raw!r}") from None


def read_str_tuple(document: Mapping[str, Any], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a JSON array")
    return require_text_tuple(value, key)


def _read_enum_tuple(
    document: Mapping[str, Any], key: str, enum_type: type
) -> tuple:
    value = document.get(key)
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a JSON array")
    members = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} must hold strings")
        try:
            members.append(enum_type(item))
        except ValueError:
            allowed = sorted(member.value for member in enum_type)
            raise ValueError(f"{key} must hold members of {allowed}") from None
    return _enum_tuple(members, enum_type, key)


def _fingerprint(schema: str, payload: Any, *, drop: Sequence[str] = ()) -> str:
    plain = dict(to_plain(payload))
    for name in drop:
        plain.pop(name, None)
    return stable_hash({"schema": schema, "claims": plain}, length=64)


# ------------------------------------------------------------------ vocabulary


class ProjectPurpose(str, Enum):
    """What fpbench is for, and the only value the system accepts.

    One member on purpose. ``academic`` is deliberately not among them: this
    project is not carried out within any institution, and a vocabulary that
    offered the word would eventually see it used (docs/adr/0081).
    """

    PERSONAL_EDUCATIONAL_RESEARCH = "PERSONAL_EDUCATIONAL_RESEARCH"


class ThirdPartyComponentKind(str, Enum):
    """The unit a licence applies to.

    A repository licence is not a checkpoint licence is not a dataset licence.
    Stage 8A already learned this for one candidate (docs/adr/0063); Stage 8E
    makes it the shape of every record.
    """

    SOURCE_CODE = "SOURCE_CODE"
    MODEL_WEIGHTS = "MODEL_WEIGHTS"
    RUNTIME_BINARY = "RUNTIME_BINARY"
    PACKAGE_DEPENDENCY = "PACKAGE_DEPENDENCY"
    DATASET = "DATASET"
    DOCUMENTATION = "DOCUMENTATION"
    OTHER_ARTIFACT = "OTHER_ARTIFACT"


class LicenseObservationStatus(str, Enum):
    """What the notices say. A description, never an outcome.

    ``NO_LICENSE_FOUND`` and ``UNKNOWN`` are different claims and are not
    interchangeable: the first means the artifact was inspected and carried no
    terms, the second means no inspection has been recorded here.
    """

    OPEN_SOURCE_PERMISSIVE = "OPEN_SOURCE_PERMISSIVE"
    OPEN_SOURCE_COPYLEFT = "OPEN_SOURCE_COPYLEFT"
    ACADEMIC_ONLY = "ACADEMIC_ONLY"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    NON_COMMERCIAL = "NON_COMMERCIAL"
    SOURCE_AVAILABLE = "SOURCE_AVAILABLE"
    CONFLICTING_NOTICES = "CONFLICTING_NOTICES"
    NO_LICENSE_FOUND = "NO_LICENSE_FOUND"
    UNKNOWN = "UNKNOWN"

    @property
    def identifies_terms(self) -> bool:
        """Whether one coherent set of terms was actually identified."""
        return self not in (
            LicenseObservationStatus.CONFLICTING_NOTICES,
            LicenseObservationStatus.NO_LICENSE_FOUND,
            LicenseObservationStatus.UNKNOWN,
        )

    @property
    def limits_field_of_use(self) -> bool:
        """Whether the identified terms restrict *what for*, rather than *how*."""
        return self in (
            LicenseObservationStatus.ACADEMIC_ONLY,
            LicenseObservationStatus.RESEARCH_ONLY,
            LicenseObservationStatus.NON_COMMERCIAL,
            LicenseObservationStatus.SOURCE_AVAILABLE,
        )


class ResearchUseDecision(str, Enum):
    """Whether fpbench may execute a component locally, under its stated purpose.

    Separate from the observation above, and separate from redistribution below.
    The three never collapse into one field (docs/adr/0082).
    """

    ALLOWED = "ALLOWED"
    ALLOWED_UNDER_RESTRICTIVE_INTERSECTION = "ALLOWED_UNDER_RESTRICTIVE_INTERSECTION"
    OWNER_RISK_ACCEPTED = "OWNER_RISK_ACCEPTED"
    BLOCKED = "BLOCKED"

    @property
    def opens_execution(self) -> bool:
        return self is not ResearchUseDecision.BLOCKED


class RedistributionDecision(str, Enum):
    """What upstream permits by way of redistribution.

    Recorded because it is a fact about the component, and then ignored: this
    project redistributes nothing regardless of the value here (docs/adr/0083).
    """

    ALLOWED = "ALLOWED"
    CONDITIONAL = "CONDITIONAL"
    NOT_ALLOWED = "NOT_ALLOWED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"


class ResearchUseBlocker(str, Enum):
    """The closed list of things that do stop a component being executed here.

    Short by design. Everything absent from it — non-commercial, research-only,
    no redistribution, no sublicensing, copyleft — is recorded as a restriction
    and changes nothing, because this project's use touches none of it.
    """

    INTENDED_RESEARCH_USE_EXPRESSLY_PROHIBITED = (
        "INTENDED_RESEARCH_USE_EXPRESSLY_PROHIBITED"
    )
    BIOMETRIC_USE_EXPRESSLY_PROHIBITED = "BIOMETRIC_USE_EXPRESSLY_PROHIBITED"
    MODIFICATION_PROHIBITED_BUT_REQUIRED = "MODIFICATION_PROHIBITED_BUT_REQUIRED"
    ACCESS_TERMS_CANNOT_BE_SATISFIED = "ACCESS_TERMS_CANNOT_BE_SATISFIED"
    OBTAINED_BY_CIRCUMVENTING_A_TECHNICAL_RESTRICTION = (
        "OBTAINED_BY_CIRCUMVENTING_A_TECHNICAL_RESTRICTION"
    )
    TERMS_INCOMPATIBLE_WITH_LOCAL_EXECUTION = (
        "TERMS_INCOMPATIBLE_WITH_LOCAL_EXECUTION"
    )
    ARTIFACT_IDENTITY_NOT_ESTABLISHED = "ARTIFACT_IDENTITY_NOT_ESTABLISHED"
    DATASET_ACCESS_TERMS_NOT_SATISFIED = "DATASET_ACCESS_TERMS_NOT_SATISFIED"
    #: The absence of permission, left as an absence. Silence is not a grant —
    #: with no licence at all, default copyright applies and nobody has given
    #: anybody anything. A component may still be executed here under
    #: :class:`OwnerRiskAcceptance`; where the owner has *not* accepted that
    #: risk, this is what remains (docs/adr/0084).
    PERMISSION_UNRESOLVED_AND_NOT_RISK_ACCEPTED = (
        "PERMISSION_UNRESOLVED_AND_NOT_RISK_ACCEPTED"
    )


class NonBlockingRestriction(str, Enum):
    """Restrictions this project records, respects, and is not stopped by.

    Each one is a real term. None of them touches "one person runs this on one
    machine, publishes no bytes, and sells nothing" — which is the entire
    operation fpbench performs (docs/adr/0081).
    """

    NON_COMMERCIAL_ONLY = "NON_COMMERCIAL_ONLY"
    ACADEMIC_OR_RESEARCH_ONLY = "ACADEMIC_OR_RESEARCH_ONLY"
    EDUCATIONAL_ONLY = "EDUCATIONAL_ONLY"
    NO_REDISTRIBUTION = "NO_REDISTRIBUTION"
    NO_SUBLICENSING = "NO_SUBLICENSING"
    COPYLEFT = "COPYLEFT"
    STRONG_COPYLEFT = "STRONG_COPYLEFT"
    WEIGHTS_MAY_NOT_BE_REDISTRIBUTED = "WEIGHTS_MAY_NOT_BE_REDISTRIBUTED"
    COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT = (
        "COMMERCIAL_LICENSE_REQUIRED_FOR_COMMERCIAL_DEPLOYMENT"
    )
    NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION = (
        "NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION"
    )
    ATTRIBUTION_AND_NOTICE_RETENTION = "ATTRIBUTION_AND_NOTICE_RETENTION"

    @property
    def limits_field_of_use(self) -> bool:
        return self in (
            NonBlockingRestriction.NON_COMMERCIAL_ONLY,
            NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
            NonBlockingRestriction.EDUCATIONAL_ONLY,
            NonBlockingRestriction.NOTICE_CONFLICT_WITH_PERMISSIVE_INTERSECTION,
        )


class IntendedUsePermissionStatus(str, Enum):
    """Whether permission for *this project's exact operation* is established.

    Not a statement about the licence. A component whose notices conflict can
    still have established permission for one narrow use, if every plausible
    reading of every notice permits it; a component with no notices at all
    cannot, however comfortable the owner is proceeding (docs/adr/0084).
    """

    ESTABLISHED = "ESTABLISHED"
    UNRESOLVED = "UNRESOLVED"


class ArtifactStorageClass(str, Enum):
    """Where an artifact is allowed to live.

    ``REPOSITORY_METADATA`` is the description of a thing — a URL, a commit, a
    digest, a size. ``LOCAL_ARTIFACT_STORE`` is the thing itself, and it lives
    outside the working tree on whatever machine is running (docs/adr/0083).
    """

    REPOSITORY_METADATA = "REPOSITORY_METADATA"
    LOCAL_ARTIFACT_STORE = "LOCAL_ARTIFACT_STORE"


class UpstreamModificationStrategy(str, Enum):
    """The ladder, in the order it must be tried.

    A committed fork of upstream source is the outcome all three rungs exist to
    avoid: it publishes somebody else's code from a public repository and it
    destroys the provenance the digests were for.
    """

    WRAPPER_WITHOUT_UPSTREAM_MODIFICATION = "WRAPPER_WITHOUT_UPSTREAM_MODIFICATION"
    PROJECT_OWNED_TRANSFORMATION_RECIPE = "PROJECT_OWNED_TRANSFORMATION_RECIPE"
    LOCAL_PATCH = "LOCAL_PATCH"

    @property
    def rung(self) -> int:
        return {
            UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION: 1,
            UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE: 2,
            UpstreamModificationStrategy.LOCAL_PATCH: 3,
        }[self]


class TransformationClassification(str, Enum):
    """What a transformation is allowed to be.

    ``INTEGRATION_ONLY`` — it makes upstream callable and changes nothing an
    algorithm would notice. Anything that could move a score is
    ``BEHAVIOUR_AFFECTING`` and is a different conversation, held in an ADR
    before it is held in code (docs/adr/0064).
    """

    INTEGRATION_ONLY = "INTEGRATION_ONLY"
    BEHAVIOUR_AFFECTING = "BEHAVIOUR_AFFECTING"


# --------------------------------------------------------------------- purpose


@dataclass(frozen=True, slots=True)
class ProjectPurposeDeclaration:
    """The premise every research-use decision below is taken under.

    Every flag is ``False`` and every one is checked rather than merely stored.
    A declaration that said otherwise would not be a variant of this project's
    purpose — it would be a different project, whose third-party analysis would
    have to be redone from the beginning (docs/adr/0081).
    """

    purpose: ProjectPurpose
    statement: str

    commercial_use_by_project_owner: bool
    commercial_deployment: bool
    commercial_service: bool
    third_party_redistribution: bool
    third_party_sublicensing: bool
    benchmark_publication_as_academic_work: bool

    purpose_fingerprint: str = ""
    schema_version: str = PROJECT_PURPOSE_SCHEMA_VERSION

    #: Every flag above, named so that a flag added to the class is either
    #: checked here or is visibly absent from this list.
    DENIED_FLAGS = (
        "commercial_use_by_project_owner",
        "commercial_deployment",
        "commercial_service",
        "third_party_redistribution",
        "third_party_sublicensing",
        "benchmark_publication_as_academic_work",
    )

    def __post_init__(self) -> None:
        version = require_text(self.schema_version, "schema_version")
        if version != PROJECT_PURPOSE_SCHEMA_VERSION:
            raise ThirdPartyPurposeError(
                f"unsupported project-purpose schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        if not isinstance(self.purpose, ProjectPurpose):
            raise ThirdPartyPurposeError(
                "purpose must be a ProjectPurpose; the term this project uses is "
                "PERSONAL_EDUCATIONAL_RESEARCH and it is not a free-text field"
            )
        object.__setattr__(
            self, "statement", require_text(self.statement, "statement")
        )

        for name in ProjectPurposeDeclaration.DENIED_FLAGS:
            value = require_exact_bool(getattr(self, name), name)
            if value is not False:
                raise ThirdPartyPurposeError(
                    f"the declared purpose sets {name} to false; a declaration "
                    "that said otherwise would be describing a different project "
                    "(docs/adr/0081)"
                )
            object.__setattr__(self, name, value)

        # Derived, never taken on trust. A caller may pass the digest it expects
        # — a strict reader does, because a stored document has to carry one —
        # and the two are compared; passing nothing simply mints it.
        expected = project_purpose_fingerprint(self)
        if self.purpose_fingerprint and (
            require_digest(self.purpose_fingerprint, "purpose_fingerprint") != expected
        ):
            raise ThirdPartyPurposeError(
                "purpose_fingerprint does not cover the declaration's claims"
            )
        object.__setattr__(self, "purpose_fingerprint", expected)


def project_purpose_fingerprint(
    declaration: ProjectPurposeDeclaration | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_project_purpose_v1", declaration, drop=("purpose_fingerprint",)
    )


# -------------------------------------------------------------- upstream identity


@dataclass(frozen=True, slots=True)
class UpstreamIdentity:
    """Which exact upstream thing a record is about.

    Deliberately has no local-path field. The repository says *what* an artifact
    is and *which bytes* it must be; where it sits on any given machine is that
    machine's business, and a manifest carrying an absolute path would be a
    manifest that worked on one computer (docs/adr/0083).
    """

    upstream_name: str
    upstream_locator: str
    exact_version: str

    upstream_commit: str | None = None
    artifact_filename: str | None = None
    artifact_sha256: str | None = None
    artifact_size_bytes: int | None = None
    identity_established: bool = True

    def __post_init__(self) -> None:
        for name in ("upstream_name", "upstream_locator", "exact_version"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for name in ("upstream_commit", "artifact_filename"):
            value = getattr(self, name)
            object.__setattr__(
                self, name, None if value is None else require_text(value, name)
            )
        object.__setattr__(
            self,
            "artifact_sha256",
            require_optional_digest(self.artifact_sha256, "artifact_sha256"),
        )
        if self.artifact_size_bytes is not None:
            size = require_exact_int(self.artifact_size_bytes, "artifact_size_bytes")
            if size <= 0:
                raise ThirdPartyArtifactError("artifact_size_bytes must be positive")
            object.__setattr__(self, "artifact_size_bytes", size)
        object.__setattr__(
            self,
            "identity_established",
            require_exact_bool(self.identity_established, "identity_established"),
        )
        if (
            self.artifact_filename is not None
            and self.artifact_sha256 is not None
            and self.artifact_size_bytes is None
        ):
            raise ThirdPartyArtifactError(
                f"{self.upstream_name}: a *file* pinned by digest is pinned by "
                "size too; a digest alone cannot say a truncated download is "
                "wrong before it is hashed. A digest with no filename identifies "
                "a lock or a manifest rather than a file, and needs no size"
            )
        if _looks_like_a_local_path(self.upstream_locator):
            raise ThirdPartyArtifactError(
                f"{self.upstream_name}: upstream_locator "
                f"{self.upstream_locator!r} is a local path. An upstream identity "
                "is a URL, a coordinate or a commit — never a place on one machine"
            )


def _looks_like_a_local_path(value: str) -> bool:
    """Whether a string names a place on one machine rather than an identity.

    Covers POSIX absolute paths, Windows drive letters, UNC shares, and ``~``.
    Deliberately does not try to catch a relative path: those are how this
    repository names its *own* files, and refusing them would refuse the
    manifests too.
    """
    text = value.strip()
    if not text:
        return False
    if text.startswith(("/", "\\", "~")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[2] in "\\/"


# ---------------------------------------------------------------- the observation


@dataclass(frozen=True, slots=True)
class LicenseEvidence:
    """One notice that was actually read, and where it was read from.

    A licence status with no evidence behind it is somebody's recollection. The
    digest is optional because a notice embedded at the top of a source file has
    no document of its own to hash; the locator never is.
    """

    locator: str
    description: str
    document_sha256: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "locator", require_text(self.locator, "locator"))
        object.__setattr__(
            self, "description", require_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "document_sha256",
            require_optional_digest(self.document_sha256, "document_sha256"),
        )


@dataclass(frozen=True, slots=True)
class LicenseObservation:
    """What upstream's notices say about one component. Nothing more.

    There is no field on this class for what fpbench may do, and that absence is
    the point: an observation that could also carry a conclusion is an
    observation that will eventually be *read* as one (docs/adr/0082).

    The refusals below are all of the same kind — they stop a status from
    claiming more than the evidence supports:

    * ``NO_LICENSE_FOUND`` may not name a licence;
    * a status that identifies terms must name at least one document or notice;
    * ``CONFLICTING_NOTICES`` needs at least two notices to conflict;
    * ``UNKNOWN`` may not carry a restriction, because a restriction is
      something a reader saw, and this status says nobody has looked.
    """

    observation_id: str
    component_kind: ThirdPartyComponentKind
    subject: str
    status: LicenseObservationStatus

    declared_license_names: tuple[str, ...] = ()
    spdx_identifiers: tuple[str, ...] = ()
    evidence: tuple[LicenseEvidence, ...] = ()
    stated_restrictions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    observation_fingerprint: str = ""
    schema_version: str = LICENSE_OBSERVATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = require_text(self.schema_version, "schema_version")
        if version != LICENSE_OBSERVATION_SCHEMA_VERSION:
            raise LicenseObservationError(
                f"unsupported licence-observation schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.observation_id)
        if not isinstance(self.component_kind, ThirdPartyComponentKind):
            raise LicenseObservationError(
                "component_kind must be a ThirdPartyComponentKind: a repository "
                "licence is not a checkpoint licence (docs/adr/0063)"
            )
        if not isinstance(self.status, LicenseObservationStatus):
            raise LicenseObservationError(
                "status must be a LicenseObservationStatus"
            )
        object.__setattr__(self, "subject", require_text(self.subject, "subject"))

        for name in ("declared_license_names", "spdx_identifiers", "stated_restrictions", "notes"):
            object.__setattr__(
                self, name, require_text_tuple(getattr(self, name), name)
            )

        evidence = tuple(self.evidence)
        for item in evidence:
            if not isinstance(item, LicenseEvidence):
                raise LicenseObservationError(
                    "every entry of evidence must be a LicenseEvidence"
                )
        object.__setattr__(
            self, "evidence", tuple(sorted(evidence, key=lambda item: item.locator))
        )

        if self.status is LicenseObservationStatus.NO_LICENSE_FOUND and (
            self.declared_license_names or self.spdx_identifiers
        ):
            raise LicenseObservationError(
                f"{self.observation_id}: NO_LICENSE_FOUND names a licence. It "
                "means the artifact was inspected and carried none"
            )
        if self.status is LicenseObservationStatus.UNKNOWN and (
            self.declared_license_names
            or self.spdx_identifiers
            or self.stated_restrictions
        ):
            raise LicenseObservationError(
                f"{self.observation_id}: UNKNOWN means no inspection has been "
                "recorded here, so there is nothing it can have observed. Use "
                "NO_LICENSE_FOUND for an artifact that was inspected and carried "
                "no terms"
            )
        if self.status.identifies_terms and not self.evidence:
            raise LicenseObservationError(
                f"{self.observation_id}: a status of {self.status.value} names "
                "terms, and terms come from a notice somebody read"
            )
        if (
            self.status is LicenseObservationStatus.CONFLICTING_NOTICES
            and len(self.evidence) < 2
        ):
            raise LicenseObservationError(
                f"{self.observation_id}: CONFLICTING_NOTICES needs at least two "
                "notices to conflict"
            )

        expected = license_observation_fingerprint(self)
        if self.observation_fingerprint and (
            require_digest(self.observation_fingerprint, "observation_fingerprint")
            != expected
        ):
            raise LicenseObservationError(
                f"{self.observation_id}: observation_fingerprint does not cover "
                "what the observation says"
            )
        object.__setattr__(self, "observation_fingerprint", expected)


def license_observation_fingerprint(
    observation: LicenseObservation | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_license_observation_v1",
        observation,
        drop=("observation_fingerprint",),
    )


# ------------------------------------------------------------------ the decision


@dataclass(frozen=True, slots=True)
class OwnerRiskAcceptance:
    """The five conditions, all of them, or this is not available.

    What it is: the project owner stating that they are proceeding with a local
    research operation despite an ambiguity nobody resolved. What it is **not**:
    a finding that the use is permitted. Stage 8B established that distinction
    for one checkpoint (docs/adr/0068); this generalises it without weakening it
    (docs/adr/0084).
    """

    published_intentionally_by_official_authors: bool
    publicly_obtainable_without_circumvention: bool
    intended_operation_is_local_research_only: bool
    no_located_term_expressly_prohibits_the_use: bool
    no_bytes_will_be_redistributed: bool
    accepted_by: str
    basis: str

    CONDITIONS = (
        "published_intentionally_by_official_authors",
        "publicly_obtainable_without_circumvention",
        "intended_operation_is_local_research_only",
        "no_located_term_expressly_prohibits_the_use",
        "no_bytes_will_be_redistributed",
    )

    def __post_init__(self) -> None:
        unmet = []
        for name in OwnerRiskAcceptance.CONDITIONS:
            value = require_exact_bool(getattr(self, name), name)
            object.__setattr__(self, name, value)
            if value is not True:
                unmet.append(name)
        if unmet:
            raise ResearchUseDecisionError(
                "owner risk acceptance requires every condition, and these are "
                f"unmet: {sorted(unmet)}. A partial acceptance is a decision to "
                "block (docs/adr/0084)"
            )
        object.__setattr__(self, "accepted_by", require_text(self.accepted_by, "accepted_by"))
        object.__setattr__(self, "basis", require_text(self.basis, "basis"))


@dataclass(frozen=True, slots=True)
class ResearchUseAssessment:
    """Whether fpbench may execute one component locally, and why.

    Cites exactly one :class:`LicenseObservation` by fingerprint, so the
    description it rests on cannot be edited underneath it. Every rule below is
    mechanical: given the observation and the named restrictions, exactly one
    decision is well-formed, which is the whole reason the vocabulary was split
    in the first place (docs/adr/0082).
    """

    assessment_id: str
    observation_fingerprint: str
    component_kind: ThirdPartyComponentKind
    purpose: ProjectPurpose
    purpose_fingerprint: str
    intended_operation: str

    decision: ResearchUseDecision
    basis: str
    intended_use_permission_status: IntendedUsePermissionStatus

    non_blocking_restrictions: tuple[NonBlockingRestriction, ...] = ()
    blockers: tuple[ResearchUseBlocker, ...] = ()
    intersection_permits_intended_use: bool = False
    owner_risk_acceptance: OwnerRiskAcceptance | None = None
    dataset_access_terms_satisfied: bool | None = None

    assessment_fingerprint: str = ""
    schema_version: str = RESEARCH_USE_ASSESSMENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = require_text(self.schema_version, "schema_version")
        if version != RESEARCH_USE_ASSESSMENT_SCHEMA_VERSION:
            raise ResearchUseDecisionError(
                f"unsupported research-use schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.assessment_id)
        object.__setattr__(
            self,
            "observation_fingerprint",
            require_digest(self.observation_fingerprint, "observation_fingerprint"),
        )
        object.__setattr__(
            self,
            "purpose_fingerprint",
            require_digest(self.purpose_fingerprint, "purpose_fingerprint"),
        )
        if not isinstance(self.component_kind, ThirdPartyComponentKind):
            raise ResearchUseDecisionError("component_kind must be a ThirdPartyComponentKind")
        if self.purpose is not ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH:
            raise ResearchUseDecisionError(
                "every research-use decision is taken under the one declared "
                "purpose (docs/adr/0081)"
            )
        if not isinstance(self.decision, ResearchUseDecision):
            raise ResearchUseDecisionError("decision must be a ResearchUseDecision")
        if not isinstance(
            self.intended_use_permission_status, IntendedUsePermissionStatus
        ):
            raise ResearchUseDecisionError(
                "intended_use_permission_status must be an IntendedUsePermissionStatus"
            )
        for name in ("intended_operation", "basis"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))

        object.__setattr__(
            self,
            "non_blocking_restrictions",
            _enum_tuple(
                self.non_blocking_restrictions,
                NonBlockingRestriction,
                "non_blocking_restrictions",
            ),
        )
        object.__setattr__(
            self,
            "blockers",
            _enum_tuple(self.blockers, ResearchUseBlocker, "blockers"),
        )
        object.__setattr__(
            self,
            "intersection_permits_intended_use",
            require_exact_bool(
                self.intersection_permits_intended_use,
                "intersection_permits_intended_use",
            ),
        )
        if self.owner_risk_acceptance is not None and not isinstance(
            self.owner_risk_acceptance, OwnerRiskAcceptance
        ):
            raise ResearchUseDecisionError(
                "owner_risk_acceptance must be an OwnerRiskAcceptance"
            )

        self._require_dataset_field_matches_kind()
        self._require_decision_follows_from_its_parts()
        self._require_permission_status_matches_the_decision()

        expected = research_use_assessment_fingerprint(self)
        if self.assessment_fingerprint and (
            require_digest(self.assessment_fingerprint, "assessment_fingerprint")
            != expected
        ):
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: assessment_fingerprint does not cover the "
                "decision it accompanies"
            )
        object.__setattr__(self, "assessment_fingerprint", expected)

    # -- the rules ---------------------------------------------------------

    def _require_dataset_field_matches_kind(self) -> None:
        """A dataset carries an access-terms verdict; nothing else does.

        Stage 8E is a policy about software, models and runtimes. Dataset access
        terms, privacy and data-use conditions are a different subject and this
        stage changes none of them, so a dataset record has to answer the
        dataset question explicitly rather than inherit the software answer
        (spec section 11).
        """
        is_dataset = self.component_kind is ThirdPartyComponentKind.DATASET
        if is_dataset:
            if self.dataset_access_terms_satisfied is None:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: a dataset record states whether its "
                    "access terms are satisfied. Stage 8E did not make dataset "
                    "restrictions non-blocking (spec section 11)"
                )
            object.__setattr__(
                self,
                "dataset_access_terms_satisfied",
                require_exact_bool(
                    self.dataset_access_terms_satisfied,
                    "dataset_access_terms_satisfied",
                ),
            )
        elif self.dataset_access_terms_satisfied is not None:
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: dataset_access_terms_satisfied belongs to "
                "a dataset record and this is a "
                f"{self.component_kind.value} record"
            )

    def _require_decision_follows_from_its_parts(self) -> None:
        decision = self.decision
        if decision is ResearchUseDecision.BLOCKED:
            if not self.blockers:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: BLOCKED names which blocker applies. "
                    "A block nobody can point at is a block nobody can lift"
                )
            return

        if self.blockers:
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: {decision.value} alongside "
                f"{sorted(item.value for item in self.blockers)}. A blocker is "
                "not a restriction to be weighed; it blocks"
            )

        if self.component_kind is ThirdPartyComponentKind.DATASET:
            if decision is ResearchUseDecision.OWNER_RISK_ACCEPTED:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: dataset rights are not risk-accepted. "
                    "Biometric access terms, privacy and data-use conditions are "
                    "outside this policy and stay blocking (spec section 11)"
                )
            if self.dataset_access_terms_satisfied is not True:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: a dataset may only be used where its "
                    "own access terms are satisfied"
                )

        if decision is ResearchUseDecision.OWNER_RISK_ACCEPTED:
            if self.owner_risk_acceptance is None:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: OWNER_RISK_ACCEPTED requires the "
                    "acceptance itself, with all five conditions "
                    "(docs/adr/0084)"
                )
            if self.status_requires_identified_terms():
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: OWNER_RISK_ACCEPTED is for an "
                    "ambiguity nobody resolved. Terms were identified here, so "
                    "the answer follows from them"
                )
            return

        if self.owner_risk_acceptance is not None:
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: {decision.value} carries an owner risk "
                "acceptance. Risk is accepted where permission is unresolved, and "
                "here it is not"
            )

        if decision is ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION:
            if not self.intersection_permits_intended_use:
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: the intersection decision requires the "
                    "intersection to permit the intended use"
                )
            if not any(
                restriction.limits_field_of_use
                for restriction in self.non_blocking_restrictions
            ):
                raise ResearchUseDecisionError(
                    f"{self.assessment_id}: an intersection over nothing is an "
                    "ordinary ALLOWED. Name the restriction that made the "
                    "intersection necessary"
                )
            return

        # ALLOWED.
        if any(
            restriction.limits_field_of_use
            for restriction in self.non_blocking_restrictions
        ):
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: ALLOWED alongside a field-of-use "
                "restriction. That is ALLOWED_UNDER_RESTRICTIVE_INTERSECTION, and "
                "the difference is what a later reader needs to see"
            )
        if self.intersection_permits_intended_use:
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: ALLOWED does not rest on an intersection"
            )

    def status_requires_identified_terms(self) -> bool:
        """Whether this assessment's own fields imply terms were identified.

        Derived from the restrictions rather than from the observation, because
        the observation is not reachable from here — only its fingerprint is.
        :func:`fpbench.third_party.policy.assess_research_use` checks the
        stronger version against the observation itself.
        """
        return bool(self.non_blocking_restrictions)

    def _require_permission_status_matches_the_decision(self) -> None:
        expected = {
            ResearchUseDecision.ALLOWED: IntendedUsePermissionStatus.ESTABLISHED,
            ResearchUseDecision.ALLOWED_UNDER_RESTRICTIVE_INTERSECTION: (
                IntendedUsePermissionStatus.ESTABLISHED
            ),
            ResearchUseDecision.OWNER_RISK_ACCEPTED: (
                IntendedUsePermissionStatus.UNRESOLVED
            ),
            ResearchUseDecision.BLOCKED: IntendedUsePermissionStatus.UNRESOLVED,
        }[self.decision]
        if self.intended_use_permission_status is not expected:
            raise ResearchUseDecisionError(
                f"{self.assessment_id}: {self.decision.value} carries "
                f"intended_use_permission_status "
                f"{self.intended_use_permission_status.value}, and the only "
                f"consistent value is {expected.value}. Under "
                "OWNER_RISK_ACCEPTED in particular, permission stays UNRESOLVED: "
                "the owner accepted a risk, nobody established a right "
                "(docs/adr/0084)"
            )


def research_use_assessment_fingerprint(
    assessment: ResearchUseAssessment | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_research_use_v1",
        assessment,
        drop=("assessment_fingerprint",),
    )


# ------------------------------------------------------------- redistribution


@dataclass(frozen=True, slots=True)
class RedistributionRecord:
    """What upstream permits, and what this project does anyway.

    ``redistributed_by_fpbench`` has one legal value. The field exists so the
    answer is visible in every document rather than inferred from the absence of
    a checkpoint (docs/adr/0083).
    """

    decision: RedistributionDecision
    basis: str
    redistributed_by_fpbench: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.decision, RedistributionDecision):
            raise RedistributionError("decision must be a RedistributionDecision")
        object.__setattr__(self, "basis", require_text(self.basis, "basis"))
        value = require_exact_bool(
            self.redistributed_by_fpbench, "redistributed_by_fpbench"
        )
        if value is not False:
            raise RedistributionError(
                "fpbench redistributes no third-party bytes, whatever upstream "
                "permits. There is no code path that sets this to true, and this "
                "is what a caller gets for trying (docs/adr/0083)"
            )
        object.__setattr__(self, "redistributed_by_fpbench", value)


# ------------------------------------------------------------- the usage record


@dataclass(frozen=True, slots=True)
class ThirdPartyUsageRecord:
    """One component, one observation, one decision, one storage answer.

    This is the contract every future algorithm fills in instead of relitigating
    licensing from scratch. Stage 9A onward writes one of these per component
    and the gate is mechanical: the decision either follows from the observation
    or the record does not construct.
    """

    record_id: str
    purpose: ProjectPurpose
    purpose_fingerprint: str
    component_kind: ThirdPartyComponentKind
    upstream_identity: UpstreamIdentity

    license_observation_fingerprint: str
    license_observation_status: LicenseObservationStatus
    license_evidence_locators: tuple[str, ...]

    research_use_decision: ResearchUseDecision
    research_use_basis: str
    research_use_assessment_fingerprint: str
    owner_risk_acceptance: bool

    redistribution: RedistributionRecord
    storage_class: ArtifactStorageClass

    stored_in_git: bool = False
    stored_in_ci_artifacts: bool = False
    notes: tuple[str, ...] = ()

    usage_fingerprint: str = ""
    schema_version: str = THIRD_PARTY_USAGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = require_text(self.schema_version, "schema_version")
        if version != THIRD_PARTY_USAGE_SCHEMA_VERSION:
            raise ThirdPartyUsageError(
                f"unsupported third-party usage schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.record_id)
        if self.purpose is not ProjectPurpose.PERSONAL_EDUCATIONAL_RESEARCH:
            raise ThirdPartyUsageError(
                "a usage record is written under the one declared purpose"
            )
        for name in (
            "purpose_fingerprint",
            "license_observation_fingerprint",
            "research_use_assessment_fingerprint",
        ):
            object.__setattr__(
                self, name, require_digest(getattr(self, name), name)
            )
        if not isinstance(self.component_kind, ThirdPartyComponentKind):
            raise ThirdPartyUsageError("component_kind must be a ThirdPartyComponentKind")
        if not isinstance(self.upstream_identity, UpstreamIdentity):
            raise ThirdPartyUsageError("upstream_identity must be an UpstreamIdentity")
        if not isinstance(self.license_observation_status, LicenseObservationStatus):
            raise ThirdPartyUsageError(
                "license_observation_status must be a LicenseObservationStatus"
            )
        if not isinstance(self.research_use_decision, ResearchUseDecision):
            raise ThirdPartyUsageError(
                "research_use_decision must be a ResearchUseDecision"
            )
        if not isinstance(self.redistribution, RedistributionRecord):
            raise ThirdPartyUsageError("redistribution must be a RedistributionRecord")
        if not isinstance(self.storage_class, ArtifactStorageClass):
            raise ThirdPartyUsageError("storage_class must be an ArtifactStorageClass")

        object.__setattr__(
            self, "research_use_basis", require_text(self.research_use_basis, "research_use_basis")
        )
        for name in ("license_evidence_locators", "notes"):
            object.__setattr__(
                self, name, require_text_tuple(getattr(self, name), name)
            )
        for name in ("owner_risk_acceptance", "stored_in_git", "stored_in_ci_artifacts"):
            object.__setattr__(
                self, name, require_exact_bool(getattr(self, name), name)
            )

        if self.owner_risk_acceptance != (
            self.research_use_decision is ResearchUseDecision.OWNER_RISK_ACCEPTED
        ):
            raise ThirdPartyUsageError(
                f"{self.record_id}: owner_risk_acceptance and research_use_decision "
                "disagree about whether a risk was accepted"
            )
        if self.stored_in_git is not False:
            raise ThirdPartyUsageError(
                f"{self.record_id}: third-party bytes are never stored in Git, "
                "whatever the licence permits (docs/adr/0083)"
            )
        if self.stored_in_ci_artifacts is not False:
            raise ThirdPartyUsageError(
                f"{self.record_id}: third-party bytes are never uploaded as CI "
                "artifacts, including from a failing job (docs/adr/0083)"
            )
        if self.storage_class is ArtifactStorageClass.REPOSITORY_METADATA and (
            self.component_kind
            in (
                ThirdPartyComponentKind.MODEL_WEIGHTS,
                ThirdPartyComponentKind.RUNTIME_BINARY,
                ThirdPartyComponentKind.DATASET,
            )
        ):
            raise ThirdPartyUsageError(
                f"{self.record_id}: a {self.component_kind.value} component is "
                "bytes, and bytes live in the local artifact store"
            )

        expected = third_party_usage_fingerprint(self)
        if self.usage_fingerprint and (
            require_digest(self.usage_fingerprint, "usage_fingerprint") != expected
        ):
            raise ThirdPartyUsageError(
                f"{self.record_id}: usage_fingerprint does not cover the record"
            )
        object.__setattr__(self, "usage_fingerprint", expected)


def third_party_usage_fingerprint(
    record: ThirdPartyUsageRecord | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_usage_record_v1", record, drop=("usage_fingerprint",)
    )


@dataclass(frozen=True, slots=True)
class ThirdPartyUsageManifest:
    """Every component of one integration, under one purpose and one policy."""

    manifest_id: str
    subject: str
    purpose_fingerprint: str
    policy_fingerprint: str
    records: tuple[ThirdPartyUsageRecord, ...]
    manifest_fingerprint: str = ""

    def __post_init__(self) -> None:
        validate_id(self.manifest_id)
        object.__setattr__(self, "subject", require_text(self.subject, "subject"))
        for name in ("purpose_fingerprint", "policy_fingerprint"):
            object.__setattr__(
                self, name, require_digest(getattr(self, name), name)
            )
        records = tuple(self.records)
        if not records:
            raise ThirdPartyUsageError(
                f"{self.manifest_id}: a manifest with no components describes "
                "nothing"
            )
        for record in records:
            if not isinstance(record, ThirdPartyUsageRecord):
                raise ThirdPartyUsageError(
                    "every entry must be a ThirdPartyUsageRecord"
                )
            if record.purpose_fingerprint != self.purpose_fingerprint:
                raise ThirdPartyUsageError(
                    f"{record.record_id} was assessed under a different declared "
                    "purpose from the manifest that holds it"
                )
        identifiers = [record.record_id for record in records]
        duplicates = sorted({name for name in identifiers if identifiers.count(name) > 1})
        if duplicates:
            raise ThirdPartyUsageError(
                f"{self.manifest_id}: two records share an id: {duplicates}"
            )
        object.__setattr__(
            self, "records", tuple(sorted(records, key=lambda item: item.record_id))
        )

        expected = third_party_usage_manifest_fingerprint(self)
        if self.manifest_fingerprint and (
            require_digest(self.manifest_fingerprint, "manifest_fingerprint") != expected
        ):
            raise ThirdPartyUsageError(
                f"{self.manifest_id}: manifest_fingerprint does not cover its records"
            )
        object.__setattr__(self, "manifest_fingerprint", expected)

    @property
    def blocked_records(self) -> tuple[ThirdPartyUsageRecord, ...]:
        return tuple(
            record
            for record in self.records
            if record.research_use_decision is ResearchUseDecision.BLOCKED
        )

    @property
    def opens_execution(self) -> bool:
        """Whether every component of this integration may be executed locally."""
        return not self.blocked_records


def third_party_usage_manifest_fingerprint(
    manifest: ThirdPartyUsageManifest | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_usage_manifest_v1", manifest, drop=("manifest_fingerprint",)
    )


# ----------------------------------------------------------------- the policy


@dataclass(frozen=True, slots=True)
class ThirdPartyPolicy:
    """The repository-wide rule, frozen as a document rather than as prose.

    Everything in it is a list somebody can diff. The point is that Stage 9A and
    every stage after it stop arguing about licensing per algorithm: they fill in
    a :class:`ThirdPartyUsageRecord` and this document decides.
    """

    policy_id: str
    policy_version: str
    statement: str
    purpose_fingerprint: str

    non_blocking_restrictions: tuple[NonBlockingRestriction, ...]
    blocking_conditions: tuple[ResearchUseBlocker, ...]
    owner_risk_conditions: tuple[str, ...]

    vendoring_default: str
    repository_permitted_content: tuple[str, ...]
    repository_forbidden_content: tuple[str, ...]
    modification_strategy_order: tuple[UpstreamModificationStrategy, ...]

    ci_downloads_restricted_artifacts: bool
    ci_uploads_third_party_bytes: bool
    publishes_container_images_with_third_party_artifacts: bool
    dataset_rights_unchanged: bool

    policy_fingerprint: str = ""
    schema_version: str = THIRD_PARTY_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        version = require_text(self.schema_version, "schema_version")
        if version != THIRD_PARTY_POLICY_SCHEMA_VERSION:
            raise ThirdPartyUsageError(
                f"unsupported third-party policy schema version {version!r}"
            )
        object.__setattr__(self, "schema_version", version)

        validate_id(self.policy_id)
        for name in ("policy_version", "statement", "vendoring_default"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "purpose_fingerprint",
            require_digest(self.purpose_fingerprint, "purpose_fingerprint"),
        )
        if self.vendoring_default != "DO_NOT_VENDOR":
            raise ThirdPartyUsageError(
                "the vendoring default is DO_NOT_VENDOR, and it holds even where "
                "upstream is MIT, BSD or Apache (docs/adr/0083)"
            )

        object.__setattr__(
            self,
            "non_blocking_restrictions",
            _enum_tuple(
                self.non_blocking_restrictions,
                NonBlockingRestriction,
                "non_blocking_restrictions",
            ),
        )
        object.__setattr__(
            self,
            "blocking_conditions",
            _enum_tuple(
                self.blocking_conditions, ResearchUseBlocker, "blocking_conditions"
            ),
        )
        strategies = tuple(self.modification_strategy_order)
        if tuple(item.rung for item in strategies) != (1, 2, 3):
            raise ThirdPartyUsageError(
                "the modification strategies are an ordered ladder: wrapper, "
                "then a project-owned transformation, then a local patch"
            )
        object.__setattr__(self, "modification_strategy_order", strategies)

        for name in (
            "owner_risk_conditions",
            "repository_permitted_content",
            "repository_forbidden_content",
        ):
            values = require_text_tuple(getattr(self, name), name)
            if not values:
                raise ThirdPartyUsageError(f"{name} must not be empty")
            object.__setattr__(self, name, values)

        overlap = sorted(
            set(self.repository_permitted_content)
            & set(self.repository_forbidden_content)
        )
        if overlap:
            raise ThirdPartyUsageError(
                f"the policy both permits and forbids {overlap} in the repository"
            )

        for name, must_be in (
            ("ci_downloads_restricted_artifacts", False),
            ("ci_uploads_third_party_bytes", False),
            ("publishes_container_images_with_third_party_artifacts", False),
            ("dataset_rights_unchanged", True),
        ):
            value = require_exact_bool(getattr(self, name), name)
            if value is not must_be:
                raise ThirdPartyUsageError(
                    f"the frozen policy sets {name} to "
                    f"{str(must_be).lower()}; a document that said otherwise "
                    "would be a different policy"
                )
            object.__setattr__(self, name, value)

        expected = third_party_policy_fingerprint(self)
        if self.policy_fingerprint and (
            require_digest(self.policy_fingerprint, "policy_fingerprint") != expected
        ):
            raise ThirdPartyUsageError(
                "policy_fingerprint does not cover what the policy says"
            )
        object.__setattr__(self, "policy_fingerprint", expected)


def third_party_policy_fingerprint(
    policy: ThirdPartyPolicy | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_policy_v1", policy, drop=("policy_fingerprint",)
    )


# ------------------------------------------------------------ local placement


@dataclass(frozen=True, slots=True)
class LocalArtifactPlacement:
    """Where an artifact sits, expressed without naming any machine.

    A role, the digest and size the bytes must have, and the upstream identity
    they came from. The resolver in :mod:`fpbench.third_party.artifacts` turns
    that into a path at runtime, from an environment variable and a default
    under the user's cache directory — so the same manifest works on every
    machine and the repository still knows exactly which bytes it expects.
    """

    placement_id: str
    component_role: str
    component_kind: ThirdPartyComponentKind
    relative_location: str
    expected_sha256: str
    expected_size_bytes: int
    upstream_identity: UpstreamIdentity
    storage_class: ArtifactStorageClass = ArtifactStorageClass.LOCAL_ARTIFACT_STORE
    placement_fingerprint: str = ""

    def __post_init__(self) -> None:
        validate_id(self.placement_id)
        for name in ("component_role", "relative_location"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        if not isinstance(self.component_kind, ThirdPartyComponentKind):
            raise ThirdPartyArtifactError("component_kind must be a ThirdPartyComponentKind")
        if not isinstance(self.upstream_identity, UpstreamIdentity):
            raise ThirdPartyArtifactError("upstream_identity must be an UpstreamIdentity")
        if self.storage_class is not ArtifactStorageClass.LOCAL_ARTIFACT_STORE:
            raise ThirdPartyArtifactError(
                "a placement describes the local artifact store; repository "
                "metadata has no placement because it has no bytes"
            )
        object.__setattr__(
            self,
            "expected_sha256",
            require_digest(self.expected_sha256, "expected_sha256"),
        )
        size = require_exact_int(self.expected_size_bytes, "expected_size_bytes")
        if size <= 0:
            raise ThirdPartyArtifactError("expected_size_bytes must be positive")
        object.__setattr__(self, "expected_size_bytes", size)

        location = self.relative_location.replace("\\", "/")
        if _looks_like_a_local_path(location) or ".." in location.split("/"):
            raise ThirdPartyArtifactError(
                f"{self.placement_id}: relative_location {self.relative_location!r} "
                "names a machine or escapes the store. A placement is relative to "
                "the store root and nothing else (docs/adr/0083)"
            )
        object.__setattr__(self, "relative_location", location)

        expected = local_artifact_placement_fingerprint(self)
        if self.placement_fingerprint and (
            require_digest(self.placement_fingerprint, "placement_fingerprint") != expected
        ):
            raise ThirdPartyArtifactError(
                f"{self.placement_id}: placement_fingerprint does not cover the placement"
            )
        object.__setattr__(self, "placement_fingerprint", expected)


def local_artifact_placement_fingerprint(
    placement: LocalArtifactPlacement | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_local_placement_v1", placement, drop=("placement_fingerprint",)
    )


# --------------------------------------------------------- upstream transformation


@dataclass(frozen=True, slots=True)
class UpstreamTransformation:
    """A mechanical change to upstream source, recorded as a recipe.

    Two digests and a rule, never the source itself. The repository can say
    exactly what it did to somebody else's code — and prove the result — without
    publishing a line of it (docs/adr/0083).
    """

    transformation_id: str
    strategy: UpstreamModificationStrategy
    subject: str
    preimage_sha256: str
    postimage_sha256: str
    transformation_rule: str
    reason: str
    classification: TransformationClassification = (
        TransformationClassification.INTEGRATION_ONLY
    )
    transformation_fingerprint: str = ""

    def __post_init__(self) -> None:
        validate_id(self.transformation_id)
        if not isinstance(self.strategy, UpstreamModificationStrategy):
            raise UpstreamTransformationError(
                "strategy must be an UpstreamModificationStrategy"
            )
        if self.strategy is (
            UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION
        ):
            raise UpstreamTransformationError(
                f"{self.transformation_id}: a wrapper changes no upstream byte, so "
                "it has no preimage and no postimage. Recording one as a "
                "transformation would make the ladder's first rung look like its "
                "second"
            )
        if not isinstance(self.classification, TransformationClassification):
            raise UpstreamTransformationError(
                "classification must be a TransformationClassification"
            )
        for name in ("subject", "transformation_rule", "reason"):
            object.__setattr__(self, name, require_text(getattr(self, name), name))
        for name in ("preimage_sha256", "postimage_sha256"):
            object.__setattr__(
                self, name, require_digest(getattr(self, name), name)
            )
        if self.preimage_sha256 == self.postimage_sha256:
            raise UpstreamTransformationError(
                f"{self.transformation_id}: the preimage and the postimage are the "
                "same bytes, so nothing was transformed"
            )

        expected = upstream_transformation_fingerprint(self)
        if self.transformation_fingerprint and (
            require_digest(
                self.transformation_fingerprint, "transformation_fingerprint"
            )
            != expected
        ):
            raise UpstreamTransformationError(
                f"{self.transformation_id}: transformation_fingerprint does not "
                "cover the recipe"
            )
        object.__setattr__(self, "transformation_fingerprint", expected)


def upstream_transformation_fingerprint(
    transformation: UpstreamTransformation | Mapping[str, Any],
) -> str:
    return _fingerprint(
        "third_party_upstream_transformation_v1",
        transformation,
        drop=("transformation_fingerprint",),
    )


# ------------------------------------------------------------- strict readers
#
# These live in ``core`` beside the containers, for the reason Stage 8D's reader
# does: the storage layer has to reconstruct a stored document and ``storage``
# may import only ``core``. A store that reached into ``fpbench.third_party`` for
# its parser would invert the layering the whole split rests on.


def read_project_purpose_declaration(
    document: Mapping[str, Any],
) -> ProjectPurposeDeclaration:
    require_exact_keys(
        document,
        (
            "schema_version",
            "purpose",
            "statement",
            *ProjectPurposeDeclaration.DENIED_FLAGS,
            "purpose_fingerprint",
        ),
        what="a project-purpose declaration",
    )
    return ProjectPurposeDeclaration(
        schema_version=read_str(document, "schema_version"),
        purpose=read_enum(document, "purpose", ProjectPurpose),
        statement=read_str(document, "statement"),
        **{
            name: read_bool(document, name)
            for name in ProjectPurposeDeclaration.DENIED_FLAGS
        },
        purpose_fingerprint=read_digest(document, "purpose_fingerprint"),
    )


def _read_evidence(document: Mapping[str, Any]) -> tuple[LicenseEvidence, ...]:
    raw = document.get("evidence")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ValueError("evidence must be a JSON array")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("every evidence entry must be a JSON object")
        require_exact_keys(
            entry,
            ("locator", "description", "document_sha256"),
            what="a licence evidence entry",
        )
        digest = entry.get("document_sha256")
        items.append(
            LicenseEvidence(
                locator=read_str(entry, "locator"),
                description=read_str(entry, "description"),
                document_sha256=None if digest is None else require_digest(
                    digest, "document_sha256"
                ),
            )
        )
    return tuple(items)


def read_license_observation(document: Mapping[str, Any]) -> LicenseObservation:
    require_exact_keys(
        document,
        (
            "schema_version",
            "observation_id",
            "component_kind",
            "subject",
            "status",
            "declared_license_names",
            "spdx_identifiers",
            "evidence",
            "stated_restrictions",
            "notes",
            "observation_fingerprint",
        ),
        what="a licence observation",
    )
    return LicenseObservation(
        schema_version=read_str(document, "schema_version"),
        observation_id=read_str(document, "observation_id"),
        component_kind=read_enum(document, "component_kind", ThirdPartyComponentKind),
        subject=read_str(document, "subject"),
        status=read_enum(document, "status", LicenseObservationStatus),
        declared_license_names=read_str_tuple(document, "declared_license_names"),
        spdx_identifiers=read_str_tuple(document, "spdx_identifiers"),
        evidence=_read_evidence(document),
        stated_restrictions=read_str_tuple(document, "stated_restrictions"),
        notes=read_str_tuple(document, "notes"),
        observation_fingerprint=read_digest(document, "observation_fingerprint"),
    )


def read_research_use_assessment(
    document: Mapping[str, Any],
) -> ResearchUseAssessment:
    require_exact_keys(
        document,
        (
            "schema_version",
            "assessment_id",
            "observation_fingerprint",
            "component_kind",
            "purpose",
            "purpose_fingerprint",
            "intended_operation",
            "decision",
            "basis",
            "intended_use_permission_status",
            "non_blocking_restrictions",
            "blockers",
            "intersection_permits_intended_use",
            "owner_risk_acceptance",
            "dataset_access_terms_satisfied",
            "assessment_fingerprint",
        ),
        what="a research-use assessment",
    )
    raw_acceptance = document.get("owner_risk_acceptance")
    acceptance: OwnerRiskAcceptance | None = None
    if raw_acceptance is not None:
        if not isinstance(raw_acceptance, dict):
            raise ValueError("owner_risk_acceptance must be a JSON object or null")
        require_exact_keys(
            raw_acceptance,
            (*OwnerRiskAcceptance.CONDITIONS, "accepted_by", "basis"),
            what="an owner risk acceptance",
        )
        acceptance = OwnerRiskAcceptance(
            **{
                name: read_bool(raw_acceptance, name)
                for name in OwnerRiskAcceptance.CONDITIONS
            },
            accepted_by=read_str(raw_acceptance, "accepted_by"),
            basis=read_str(raw_acceptance, "basis"),
        )
    dataset_flag = document.get("dataset_access_terms_satisfied")
    return ResearchUseAssessment(
        schema_version=read_str(document, "schema_version"),
        assessment_id=read_str(document, "assessment_id"),
        observation_fingerprint=read_digest(document, "observation_fingerprint"),
        component_kind=read_enum(document, "component_kind", ThirdPartyComponentKind),
        purpose=read_enum(document, "purpose", ProjectPurpose),
        purpose_fingerprint=read_digest(document, "purpose_fingerprint"),
        intended_operation=read_str(document, "intended_operation"),
        decision=read_enum(document, "decision", ResearchUseDecision),
        basis=read_str(document, "basis"),
        intended_use_permission_status=read_enum(
            document, "intended_use_permission_status", IntendedUsePermissionStatus
        ),
        non_blocking_restrictions=_read_enum_tuple(
            document, "non_blocking_restrictions", NonBlockingRestriction
        ),
        blockers=_read_enum_tuple(document, "blockers", ResearchUseBlocker),
        intersection_permits_intended_use=read_bool(
            document, "intersection_permits_intended_use"
        ),
        owner_risk_acceptance=acceptance,
        dataset_access_terms_satisfied=(
            None
            if dataset_flag is None
            else require_exact_bool(dataset_flag, "dataset_access_terms_satisfied")
        ),
        assessment_fingerprint=read_digest(document, "assessment_fingerprint"),
    )


def _read_upstream_identity(document: Mapping[str, Any]) -> UpstreamIdentity:
    require_exact_keys(
        document,
        (
            "upstream_name",
            "upstream_locator",
            "exact_version",
            "upstream_commit",
            "artifact_filename",
            "artifact_sha256",
            "artifact_size_bytes",
            "identity_established",
        ),
        what="an upstream identity",
    )
    size = document.get("artifact_size_bytes")
    return UpstreamIdentity(
        upstream_name=read_str(document, "upstream_name"),
        upstream_locator=read_str(document, "upstream_locator"),
        exact_version=read_str(document, "exact_version"),
        upstream_commit=(
            None if document.get("upstream_commit") is None else read_str(document, "upstream_commit")
        ),
        artifact_filename=(
            None
            if document.get("artifact_filename") is None
            else read_str(document, "artifact_filename")
        ),
        artifact_sha256=require_optional_digest(
            document.get("artifact_sha256"), "artifact_sha256"
        ),
        artifact_size_bytes=(
            None if size is None else require_exact_int(size, "artifact_size_bytes")
        ),
        identity_established=read_bool(document, "identity_established"),
    )


def read_third_party_usage_record(
    document: Mapping[str, Any],
) -> ThirdPartyUsageRecord:
    require_exact_keys(
        document,
        (
            "schema_version",
            "record_id",
            "purpose",
            "purpose_fingerprint",
            "component_kind",
            "upstream_identity",
            "license_observation_fingerprint",
            "license_observation_status",
            "license_evidence_locators",
            "research_use_decision",
            "research_use_basis",
            "research_use_assessment_fingerprint",
            "owner_risk_acceptance",
            "redistribution",
            "storage_class",
            "stored_in_git",
            "stored_in_ci_artifacts",
            "notes",
            "usage_fingerprint",
        ),
        what="a third-party usage record",
    )
    identity = document.get("upstream_identity")
    if not isinstance(identity, dict):
        raise ValueError("upstream_identity must be a JSON object")
    redistribution = document.get("redistribution")
    if not isinstance(redistribution, dict):
        raise ValueError("redistribution must be a JSON object")
    require_exact_keys(
        redistribution,
        ("decision", "basis", "redistributed_by_fpbench"),
        what="a redistribution record",
    )
    return ThirdPartyUsageRecord(
        schema_version=read_str(document, "schema_version"),
        record_id=read_str(document, "record_id"),
        purpose=read_enum(document, "purpose", ProjectPurpose),
        purpose_fingerprint=read_digest(document, "purpose_fingerprint"),
        component_kind=read_enum(document, "component_kind", ThirdPartyComponentKind),
        upstream_identity=_read_upstream_identity(identity),
        license_observation_fingerprint=read_digest(
            document, "license_observation_fingerprint"
        ),
        license_observation_status=read_enum(
            document, "license_observation_status", LicenseObservationStatus
        ),
        license_evidence_locators=read_str_tuple(document, "license_evidence_locators"),
        research_use_decision=read_enum(
            document, "research_use_decision", ResearchUseDecision
        ),
        research_use_basis=read_str(document, "research_use_basis"),
        research_use_assessment_fingerprint=read_digest(
            document, "research_use_assessment_fingerprint"
        ),
        owner_risk_acceptance=read_bool(document, "owner_risk_acceptance"),
        redistribution=RedistributionRecord(
            decision=read_enum(redistribution, "decision", RedistributionDecision),
            basis=read_str(redistribution, "basis"),
            redistributed_by_fpbench=read_bool(
                redistribution, "redistributed_by_fpbench"
            ),
        ),
        storage_class=read_enum(document, "storage_class", ArtifactStorageClass),
        stored_in_git=read_bool(document, "stored_in_git"),
        stored_in_ci_artifacts=read_bool(document, "stored_in_ci_artifacts"),
        notes=read_str_tuple(document, "notes"),
        usage_fingerprint=read_digest(document, "usage_fingerprint"),
    )


def read_third_party_policy(document: Mapping[str, Any]) -> ThirdPartyPolicy:
    require_exact_keys(
        document,
        (
            "schema_version",
            "policy_id",
            "policy_version",
            "statement",
            "purpose_fingerprint",
            "non_blocking_restrictions",
            "blocking_conditions",
            "owner_risk_conditions",
            "vendoring_default",
            "repository_permitted_content",
            "repository_forbidden_content",
            "modification_strategy_order",
            "ci_downloads_restricted_artifacts",
            "ci_uploads_third_party_bytes",
            "publishes_container_images_with_third_party_artifacts",
            "dataset_rights_unchanged",
            "policy_fingerprint",
        ),
        what="a third-party policy",
    )
    return ThirdPartyPolicy(
        schema_version=read_str(document, "schema_version"),
        policy_id=read_str(document, "policy_id"),
        policy_version=read_str(document, "policy_version"),
        statement=read_str(document, "statement"),
        purpose_fingerprint=read_digest(document, "purpose_fingerprint"),
        non_blocking_restrictions=_read_enum_tuple(
            document, "non_blocking_restrictions", NonBlockingRestriction
        ),
        blocking_conditions=_read_enum_tuple(
            document, "blocking_conditions", ResearchUseBlocker
        ),
        owner_risk_conditions=read_str_tuple(document, "owner_risk_conditions"),
        vendoring_default=read_str(document, "vendoring_default"),
        repository_permitted_content=read_str_tuple(
            document, "repository_permitted_content"
        ),
        repository_forbidden_content=read_str_tuple(
            document, "repository_forbidden_content"
        ),
        modification_strategy_order=_read_ordered_strategies(document),
        ci_downloads_restricted_artifacts=read_bool(
            document, "ci_downloads_restricted_artifacts"
        ),
        ci_uploads_third_party_bytes=read_bool(document, "ci_uploads_third_party_bytes"),
        publishes_container_images_with_third_party_artifacts=read_bool(
            document, "publishes_container_images_with_third_party_artifacts"
        ),
        dataset_rights_unchanged=read_bool(document, "dataset_rights_unchanged"),
        policy_fingerprint=read_digest(document, "policy_fingerprint"),
    )


def _read_ordered_strategies(
    document: Mapping[str, Any],
) -> tuple[UpstreamModificationStrategy, ...]:
    """The ladder, in the order the document wrote it.

    Read positionally rather than through :func:`_read_enum_tuple`, because the
    order *is* the meaning here: sorting it would silently repair a document that
    had put a local patch first.
    """
    raw = document.get("modification_strategy_order")
    if not isinstance(raw, list):
        raise ValueError("modification_strategy_order must be a JSON array")
    strategies = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("modification_strategy_order must hold strings")
        try:
            strategies.append(UpstreamModificationStrategy(item))
        except ValueError:
            allowed = sorted(member.value for member in UpstreamModificationStrategy)
            raise ValueError(
                f"modification_strategy_order must hold members of {allowed}"
            ) from None
    return tuple(strategies)
