"""Everything Stage 8E froze before the policy engine was written.

These constants are the stage's contract with itself. They are asserted by the
contract tests, checked against the published evidence of the stage they restate,
and republished in the Stage 8E finalization. A later change to any of them is a
different stage with a different identity rather than a quiet correction to this
one.

Nothing here is derived at import time, nothing reads a workspace, and nothing is
a fingerprint image, a score or an upstream byte. The legacy component facts
below are exactly that — *facts already published in this repository*: a Maven
coordinate, two NIST archive digests, an LGPL licence document digest, a
checkpoint digest that names a file living outside the tree. Every one of them
appears verbatim in a committed document, and the audit re-reads those documents
and refuses on any disagreement.

This module exists for the reason :mod:`fpbench.experiments.stage8d_identity`
does: the legacy audit, the repository audit and the finalization marker all need
the frozen values, and a shared constant module is the alternative to an import
cycle between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fpbench.core.identifiers import validate_id
from fpbench.core.third_party_models import (
    LicenseObservationStatus,
    NonBlockingRestriction,
    RedistributionDecision,
    ThirdPartyComponentKind,
)

__all__ = [
    "STAGE_8E_SCHEMA_VERSION",
    "STAGE_FINALIZATION_KIND",
    "STAGE_8E_OUTCOME",
    "EVIDENCE_DIRECTORY",
    "STAGE_8E_FINALIZATION_NAME",
    "PROJECT_PURPOSE_NAME",
    "THIRD_PARTY_POLICY_NAME",
    "LEGACY_COMPONENT_AUDIT_NAME",
    "REPOSITORY_ARTIFACT_AUDIT_NAME",
    "POLICY_CONTRACT_REPORT_NAME",
    "REQUIRED_EVIDENCE_FILES",
    "STAGE8D_FINALIZATION_FINGERPRINT",
    "STAGE8D_OUTCOME",
    "LegacyComponent",
    "LEGACY_COMPONENTS",
    "LEGACY_ROUTES",
    "LEGACY_SOURCE_DOCUMENTS",
    "FORBIDDEN_PUBLISHED_KEYS",
    "THIRD_PARTY_PACKAGE_MODULES",
    "STAGE_8E_SOURCE_FILES",
    "POLICY_DOCUMENTS",
    "STAGE_8E_ADRS",
    "all_frozen_identifiers",
]

STAGE_8E_SCHEMA_VERSION = "1"
STAGE_FINALIZATION_KIND = "stage_8e_finalization"

#: What a complete Stage 8E asserts, and the exact spelling of it. It says a
#: repository-wide policy exists, was applied to every component this project
#: already depends on, and is enforced against the public repository. It does not
#: say that any upstream licence question was resolved (docs/adr/0082).
STAGE_8E_OUTCOME = "RESEARCH_ONLY_THIRD_PARTY_POLICY_READY"

EVIDENCE_DIRECTORY = Path("evidence") / "stage8e-research-only-policy"

#: The last-written authority, and the last file committed.
STAGE_8E_FINALIZATION_NAME = "stage-8e-finalization.json"
PROJECT_PURPOSE_NAME = "project-purpose.json"
THIRD_PARTY_POLICY_NAME = "third-party-policy.json"
LEGACY_COMPONENT_AUDIT_NAME = "legacy-component-audit.json"
REPOSITORY_ARTIFACT_AUDIT_NAME = "repository-artifact-audit.json"
POLICY_CONTRACT_REPORT_NAME = "policy-contract-report.json"

#: Exactly what the evidence directory holds. An extra file is a finding.
REQUIRED_EVIDENCE_FILES = (
    "README.md",
    PROJECT_PURPOSE_NAME,
    THIRD_PARTY_POLICY_NAME,
    LEGACY_COMPONENT_AUDIT_NAME,
    REPOSITORY_ARTIFACT_AUDIT_NAME,
    POLICY_CONTRACT_REPORT_NAME,
    STAGE_8E_FINALIZATION_NAME,
)

# ----------------------------------------------------------- the closed stage
#
# Restated from evidence/stage8d-calibration-infrastructure/. Stage 8E reads that
# marker to confirm the stage it follows is the stage it thinks it follows, and
# refuses on disagreement. Nothing under that directory is edited.
STAGE8D_FINALIZATION_FINGERPRINT = (
    "06265f90893fa8ba182935cfa67ac2bb159f3d92e58122fa3e7a86e109d23106"
)
STAGE8D_OUTCOME = "CALIBRATION_INFRASTRUCTURE_READY"


# ------------------------------------------------------- the legacy components


@dataclass(frozen=True, slots=True)
class LegacyComponent:
    """One already-integrated third-party component, as Stage 8E finds it.

    Input to the audit, not a persisted artifact — which is why it lives here
    rather than in ``core``. What the audit *produces* is persisted: an
    observation, an assessment and a usage record, derived from these by the
    same engine a future algorithm will use.

    Every field is copied from a document already committed to this repository,
    and :data:`LEGACY_SOURCE_DOCUMENTS` says which one. The audit re-reads those
    documents and refuses if a value has drifted, so this is a reviewable copy of
    an authority rather than a second authority.
    """

    record_id: str
    route: str
    kind: ThirdPartyComponentKind
    subject: str
    upstream_name: str
    upstream_locator: str
    exact_version: str
    status: LicenseObservationStatus
    evidence: tuple[tuple[str, str, str | None], ...]
    basis: str
    redistribution: RedistributionDecision
    redistribution_basis: str

    upstream_commit: str | None = None
    artifact_filename: str | None = None
    artifact_sha256: str | None = None
    artifact_size_bytes: int | None = None
    license_names: tuple[str, ...] = ()
    spdx: tuple[str, ...] = ()
    stated_restrictions: tuple[str, ...] = ()
    restrictions: tuple[NonBlockingRestriction, ...] = ()
    #: ``(notice locator, permits local execution, permits non-commercial use,
    #: permits educational research)`` for each way a reasonable reader could
    #: understand the notices. Supplied only where something restricts the field
    #: of use or where notices conflict; the audit computes the conservative
    #: answer from them rather than asserting one (docs/adr/0082).
    intersection_readings: tuple[tuple[str, bool, bool, bool], ...] = ()
    notes: tuple[str, ...] = ()
    risk_accepted: bool = False
    dataset_access_terms_satisfied: bool | None = None


#: The three routes this project has executed, plus the dataset every one of them
#: read. Named so the audit can report per route without parsing record ids.
LEGACY_ROUTES: tuple[str, ...] = ("sourceafis", "nbis", "flx", "dataset")

#: Every third-party component this repository already depends on, mapped into
#: the Stage 8E vocabulary. Historical evidence is **not** rewritten: Stage 8A's
#: ``LICENSE_BLOCKED`` and Stage 8B's ``weights_license_status: unresolved``
#: remain exactly as published, and this is a new mapping beside them
#: (docs/adr/0084).
LEGACY_COMPONENTS: tuple[LegacyComponent, ...] = (
    # ------------------------------------------------------------- SourceAFIS
    LegacyComponent(
        record_id="sourceafis_java_library",
        route="sourceafis",
        kind=ThirdPartyComponentKind.PACKAGE_DEPENDENCY,
        subject="SourceAFIS for Java 3.18.1, the matcher itself",
        upstream_name="SourceAFIS for Java",
        upstream_locator="com.machinezoo.sourceafis:sourceafis",
        exact_version="3.18.1",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("Apache License 2.0",),
        spdx=("Apache-2.0",),
        evidence=(
            (
                "integrations/sourceafis-java/THIRD_PARTY_NOTICES.md",
                "this repository's own enumeration of the coordinate and its licence",
                None,
            ),
            (
                "https://sourceafis.machinezoo.com/",
                "the upstream project page the coordinate resolves from",
                None,
            ),
        ),
        stated_restrictions=(
            "Apache-2.0 requires notices to be retained in a distribution.",
        ),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "Apache-2.0 permits use without restricting the field of endeavour. "
            "Its conditions attach to distribution, and this project distributes "
            "nothing."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis=(
            "Apache-2.0 permits redistribution subject to notice retention. This "
            "project does not exercise that permission."
        ),
    ),
    LegacyComponent(
        record_id="sourceafis_shaded_dependency_closure",
        route="sourceafis",
        kind=ThirdPartyComponentKind.PACKAGE_DEPENDENCY,
        subject=(
            "the thirteen artifacts the shaded bridge jar bundles beside "
            "SourceAFIS"
        ),
        upstream_name="the SourceAFIS bridge dependency closure",
        upstream_locator="org.fpbench:fpbench-sourceafis-bridge (shade plugin output)",
        exact_version="1.0.0",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("Apache License 2.0", "MIT License"),
        spdx=("Apache-2.0", "MIT"),
        evidence=(
            (
                "integrations/sourceafis-java/THIRD_PARTY_NOTICES.md",
                "every bundled artifact, its version and its declared licence, "
                "enumerated from the shade plugin's own output",
                None,
            ),
            (
                "integrations/sourceafis-java/pom.xml",
                "the pinned direct dependencies the closure is resolved from",
                None,
            ),
        ),
        stated_restrictions=(
            "Apache-2.0 and MIT both require notices to be retained in a "
            "distribution.",
        ),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "Every bundled artifact is Apache-2.0 or MIT. Neither restricts the "
            "field of endeavour, and their conditions attach to distribution."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis=(
            "Permitted with notices retained; the shaded jar preserves the "
            "META-INF licence and notice entries. This project redistributes no "
            "jar."
        ),
    ),
    LegacyComponent(
        record_id="sourceafis_bridge_shaded_jar",
        route="sourceafis",
        kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the locally built shaded jar, which contains upstream bytes even "
            "though this project wrote the bridge classes"
        ),
        upstream_name="fpbench SourceAFIS bridge, shaded",
        upstream_locator="built locally from integrations/sourceafis-java",
        exact_version="1.0.0",
        artifact_filename="fpbench-sourceafis-bridge.jar",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("Apache License 2.0", "MIT License"),
        spdx=("Apache-2.0", "MIT"),
        evidence=(
            (
                "integrations/sourceafis-java/THIRD_PARTY_NOTICES.md",
                "the notice that anyone receiving this jar receives every "
                "bundled artifact with it",
                None,
            ),
        ),
        stated_restrictions=(
            "Anyone receiving the shaded jar receives all bundled artifacts and "
            "their notice obligations.",
        ),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "The bundle is built from source on every machine and in CI. It is a "
            "runtime artifact, so it lives outside the tree and its digest is "
            "part of the environment fingerprint of every run that used it "
            "(docs/adr/0018)."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis=(
            "Redistributable in principle with notices retained. Never committed: "
            "integrations/*/target/ is ignored and the jar is rebuilt rather than "
            "shipped."
        ),
        notes=(
            "27 MB of compiled bytes; a committed jar would be a binary nobody "
            "could review.",
        ),
    ),
    # ------------------------------------------------------------------- NBIS
    LegacyComponent(
        record_id="nbis_release_archive",
        route="nbis",
        kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="NIST NBIS Release 5.0.0, the source MINDTCT and BOZORTH3 are built from",
        upstream_name="NIST Biometric Image Software 5.0.0",
        upstream_locator="https://nigos.nist.gov/nist/nbis/nbis_v5_0_0.zip",
        exact_version="5.0.0",
        artifact_filename="nbis_v5_0_0.zip",
        artifact_sha256=(
            "0adf8ab0f6b0e4208de50ca00ba21d3d77112ecd66288757ddfed21f6bee92c3"
        ),
        artifact_size_bytes=52595795,
        status=LicenseObservationStatus.UNKNOWN,
        evidence=(),
        basis=(
            "No licence document from the NBIS distribution has been inspected "
            "and recorded in this repository, so no terms are claimed. The "
            "archive was obtained from NIST's own distribution index, sealed by "
            "digest from the bytes on disk, and is executed locally only."
        ),
        redistribution=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis=(
            "Nothing was established either way, and this project redistributes "
            "the archive to nobody."
        ),
        risk_accepted=True,
        notes=(
            "integrations/nbis/README.md refuses any source but NIST's own "
            "distribution: not a distribution package, not a fork, not a "
            "third-party image.",
        ),
    ),
    LegacyComponent(
        record_id="nbis_test_archive",
        route="nbis",
        kind=ThirdPartyComponentKind.OTHER_ARTIFACT,
        subject="NIST NBIS Test 5.0.0, the corpus NIST's own tests run against",
        upstream_name="NIST Biometric Image Software Test 5.0.0",
        upstream_locator="https://nigos.nist.gov/nist/nbis/test_v5_0_0.zip",
        exact_version="5.0.0",
        artifact_filename="test_v5_0_0.zip",
        artifact_sha256=(
            "5a1e0f7cb06ecb3ab7936e39bde97802a364f1398e37054ed195bff052b9ff00"
        ),
        artifact_size_bytes=400099537,
        status=LicenseObservationStatus.UNKNOWN,
        evidence=(),
        basis=(
            "Same position as the release archive it accompanies. Used once, "
            "locally, to certify that a build reproduces NIST's own expected "
            "outputs."
        ),
        redistribution=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis=(
            "Nothing was established, and 400 MB of NIST's test corpus is not "
            "something this repository holds."
        ),
        risk_accepted=True,
    ),
    LegacyComponent(
        record_id="nbis_certified_build",
        route="nbis",
        kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject="the locally compiled MINDTCT and BOZORTH3 binaries a score is attributed to",
        upstream_name="NBIS 5.0.0, compiled locally",
        upstream_locator="built locally from the sealed NIST release archive",
        exact_version="5.0.0",
        status=LicenseObservationStatus.UNKNOWN,
        evidence=(),
        basis=(
            "Derived from the release archive and inherits its position exactly. "
            "The build is certified against NIST's own tests and pinned by "
            "digest; it lives outside the working tree, as it always has."
        ),
        redistribution=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis=(
            "A compiled upstream binary is never committed and never published "
            "by this project, whatever its terms turn out to permit."
        ),
        risk_accepted=True,
        notes=(
            "The patch series is empty: series.json records no modification to "
            "upstream source, which is the first rung of the modification "
            "ladder.",
        ),
    ),
    # -------------------------------------------------------------------- flx
    LegacyComponent(
        record_id="flx_source_archive",
        route="flx",
        kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject=(
            "the fixed-length extractor source at the pinned commit, as a git "
            "archive"
        ),
        upstream_name="fixed-length-fingerprint-extractors",
        upstream_locator=(
            "https://codeload.github.com/tim-rohwedder/"
            "fixed-length-fingerprint-extractors/tar.gz/"
            "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13"
        ),
        exact_version="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        upstream_commit="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        artifact_filename="fixed-length-fingerprint-extractors-7accfca.tar.gz",
        artifact_sha256=(
            "60fa2c8894ea90efe2bb0553cd331d8ef84611b973b6126eaf6d162d1aa9b7e2"
        ),
        artifact_size_bytes=7149830,
        status=LicenseObservationStatus.OPEN_SOURCE_COPYLEFT,
        license_names=("GNU Lesser General Public License v3.0",),
        spdx=("LGPL-3.0-only",),
        evidence=(
            (
                "https://raw.githubusercontent.com/tim-rohwedder/"
                "fixed-length-fingerprint-extractors/"
                "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13/LICENSE",
                "the pinned LICENSE bytes, inspected independently of the "
                "checkpoint",
                "f831e7eed577481687a9bc0b48024e5e40b6f655fcde073ede964b50be5d55d9",
            ),
        ),
        stated_restrictions=(
            "LGPL notices and relinking and source obligations remain applicable.",
        ),
        restrictions=(
            NonBlockingRestriction.COPYLEFT,
            NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,
        ),
        basis=(
            "The LGPL's obligations attach to conveying the work. Running it and "
            "making local copies is not conveying, so nothing here is triggered "
            "by local execution."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis=(
            "Permitted under the LGPL's own conditions. This project does not "
            "exercise that permission and does not vendor the source."
        ),
    ),
    LegacyComponent(
        record_id="flx_checkpoint",
        route="flx",
        kind=ThirdPartyComponentKind.MODEL_WEIGHTS,
        subject=(
            "best_model.pyt, the DeepPrint_TexMinu_512_without_localization "
            "checkpoint"
        ),
        upstream_name="fixed-length extractor checkpoint",
        upstream_locator="google-drive-file:1R9v73hFBuy0iihz7v8eDlBcGrMDmQ9TH",
        exact_version="DeepPrint_TexMinu_512_without_localization",
        artifact_filename="best_model.pyt",
        artifact_sha256=(
            "2683a04427bacd54adc00cfdc97474625b1e11e5a9e6672c5129f033018f8a28"
        ),
        artifact_size_bytes=875770140,
        status=LicenseObservationStatus.NO_LICENSE_FOUND,
        evidence=(),
        basis=(
            "The file was inspected and no checkpoint-specific licence or terms "
            "accompanied it. The repository's source licence does not "
            "automatically license separately hosted weights (docs/adr/0063). "
            "The project owner accepted the risk of executing it locally; that "
            "is not a finding that the use is permitted (docs/adr/0068)."
        ),
        redistribution=RedistributionDecision.NOT_ESTABLISHED,
        redistribution_basis=(
            "Unchanged from Stage 8B: not established, and never exercised. No "
            "checkpoint byte, embedding or representation appears under "
            "evidence/."
        ),
        risk_accepted=True,
        notes=(
            "Stage 8A's LICENSE_BLOCKED and Stage 8B's weights_license_status: "
            "unresolved stand exactly as published; this record sits beside them.",
            "Upstream training provenance is unresolved — the state dict exposes "
            "8000 classifier classes and the paper text reports a conflicting "
            "identity count. No training dataset was obtained or used here.",
        ),
    ),
    LegacyComponent(
        record_id="flx_inception_v4_source",
        route="flx",
        kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="flx/models/InceptionV4.py, third-party source inside the pinned tree",
        upstream_name="InceptionV4 reference implementation",
        upstream_locator=(
            "https://raw.githubusercontent.com/tim-rohwedder/"
            "fixed-length-fingerprint-extractors/"
            "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13/flx/models/InceptionV4.py"
        ),
        exact_version="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        upstream_commit="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("BSD 3-Clause License",),
        spdx=("BSD-3-Clause",),
        evidence=(
            (
                "https://raw.githubusercontent.com/tim-rohwedder/"
                "fixed-length-fingerprint-extractors/"
                "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13/flx/models/InceptionV4.py",
                "the BSD text embedded at the top of the pinned source file",
                "b27cecb06296fe541fba97156a741891c5a0217afce94fc4106655bc19511e3d",
            ),
        ),
        stated_restrictions=("Retain copyright and licence notices.",),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "BSD-3-Clause restricts nothing about the field of endeavour and its "
            "conditions attach to distribution."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis="Permitted with notices retained; not exercised.",
    ),
    LegacyComponent(
        record_id="flx_iso_encoder_decoder",
        route="flx",
        kind=ThirdPartyComponentKind.SOURCE_CODE,
        subject="flx/data/iso_encoder_decoder, a separately licensed subtree",
        upstream_name="ISO template encoder and decoder",
        upstream_locator=(
            "https://raw.githubusercontent.com/tim-rohwedder/"
            "fixed-length-fingerprint-extractors/"
            "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13/flx/data/"
            "iso_encoder_decoder/LICENSE"
        ),
        exact_version="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        upstream_commit="7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13",
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("Apache License 2.0",),
        spdx=("Apache-2.0",),
        evidence=(
            (
                "https://raw.githubusercontent.com/tim-rohwedder/"
                "fixed-length-fingerprint-extractors/"
                "7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13/flx/data/"
                "iso_encoder_decoder/LICENSE",
                "a separate Apache-2.0 licence file present in the pinned subtree",
                "1eb85fc97224598dad1852b5d6483bbcf0aa8608790dcc657a5a2a761ae9c8c6",
            ),
        ),
        stated_restrictions=(
            "Retain notices and state modifications where applicable.",
        ),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "A subtree licence that differs from the repository licence is a "
            "separate observation, and this one permits the intended use "
            "outright."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis="Permitted with notices retained; not exercised.",
    ),
    LegacyComponent(
        record_id="flx_cpu_runtime_bundle",
        route="flx",
        kind=ThirdPartyComponentKind.RUNTIME_BINARY,
        subject=(
            "the pinned CPU runtime bundle the extractor executes inside — torch, "
            "torchvision, numpy and their locked dependency closure"
        ),
        upstream_name="flx CPU runtime bundle",
        upstream_locator="https://pypi.org/simple",
        exact_version="flx_cpu_linux_x86_64_v1",
        artifact_sha256=(
            "e0ee3a5f902a84df000310d2d495cb433e1cd8bb3bc98d48475f9f552036d392"
        ),
        status=LicenseObservationStatus.OPEN_SOURCE_PERMISSIVE,
        license_names=("BSD 3-Clause License", "Apache License 2.0", "MIT License"),
        spdx=("BSD-3-Clause", "Apache-2.0", "MIT"),
        evidence=(
            (
                "evidence/stage8b-flx-runtime-qualification/runtime-manifest.json",
                "every wheel in the bundle, by name, version and digest, with the "
                "lock digest that pins the set",
                None,
            ),
        ),
        stated_restrictions=(
            "The permissive licences in the closure require notices to be "
            "retained in a distribution.",
        ),
        restrictions=(NonBlockingRestriction.ATTRIBUTION_AND_NOTICE_RETENTION,),
        basis=(
            "A locked set of permissively licensed wheels, executed locally. The "
            "bundle is pinned by bytes (docs/adr/0072) and lives outside the "
            "working tree."
        ),
        redistribution=RedistributionDecision.CONDITIONAL,
        redistribution_basis=(
            "Each wheel is redistributable under its own permissive terms. This "
            "project ships no bundle."
        ),
        notes=(
            "artifact_sha256 here is the dependency-lock digest, which is what "
            "pins the set. There is no filename and no size because the bundle "
            "is a directory of wheels rather than one file.",
        ),
    ),
    # ---------------------------------------------------------------- dataset
    LegacyComponent(
        record_id="nist_sd300",
        route="dataset",
        kind=ThirdPartyComponentKind.DATASET,
        subject="NIST Special Database 300, releases A, B and C",
        upstream_name="NIST Special Database 300",
        upstream_locator="https://www.nist.gov/srd/nist-special-database-300",
        exact_version="the delivery this project audited",
        artifact_sha256=(
            "c2ab03a5bb20ccef2c00e5f0522b641941cb93e2676a506eae192b6251813ba9"
        ),
        status=LicenseObservationStatus.SOURCE_AVAILABLE,
        license_names=("NIST SD 300 delivery terms",),
        evidence=(
            (
                "data/README.md",
                "the SD300 README's requirement that users adhere to all terms "
                "agreed on obtaining SD 300",
                None,
            ),
            (
                ".gitignore",
                "the tracked rule that keeps every image, and every image format, "
                "out of this repository",
                None,
            ),
        ),
        stated_restrictions=(
            "Users of SD 300 shall adhere to all terms agreed to upon obtaining "
            "SD 300.",
        ),
        restrictions=(
            NonBlockingRestriction.NO_REDISTRIBUTION,
            NonBlockingRestriction.ACADEMIC_OR_RESEARCH_ONLY,
        ),
        basis=(
            "The delivery terms were accepted on obtaining the database and are "
            "satisfied by this use: local research, no redistribution. Stage 8E "
            "changes nothing about dataset rights — a dataset is the one "
            "component kind this policy may not risk-accept (spec section 11)."
        ),
        redistribution=RedistributionDecision.NOT_ALLOWED,
        redistribution_basis=(
            "No fingerprint imagery is stored in this repository and none is "
            "published (docs/adr/0004)."
        ),
        intersection_readings=(
            (
                "the SD300 README sentence quoted in data/README.md",
                True,
                True,
                True,
            ),
            (
                "the delivery terms agreed on obtaining SD 300, which this "
                "repository does not hold a copy of, read conservatively",
                True,
                True,
                True,
            ),
        ),
        dataset_access_terms_satisfied=True,
        notes=(
            "artifact_sha256 here is the image-manifest hash of the audited "
            "delivery, which is the only identity this project gave the dataset.",
        ),
    ),
)

#: Where each legacy fact is published, and which keys of that document carry it.
#: The audit reads exactly these and refuses on disagreement, which is what makes
#: the constants above a reviewable copy rather than a second source of truth.
LEGACY_SOURCE_DOCUMENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "integrations/nbis/nbis-5.0.0.lock.json",
        ("release.url", "release.sha256", "release.size_bytes", "tests.url",
         "tests.sha256", "tests.size_bytes"),
    ),
    (
        "evidence/stage8b-flx-runtime-qualification/runtime-manifest.json",
        ("runtime_profile_id", "dependency_lock_sha256"),
    ),
    (
        "evidence/stage8b-flx-runtime-qualification/artifact-binding.json",
        ("source_archive_sha256", "checkpoint_sha256"),
    ),
    (
        "evidence/sd300-canonical500-images/prepset_be560e047991.json",
        ("dataset_id", "image_manifest_hash"),
    ),
)

# ------------------------------------------------------------- what is refused
#
# Refused at any depth of a published Stage 8E document. Each one would mean an
# upstream byte, a fingerprint image, a score or a machine-specific path had
# reached the evidence of a stage whose entire subject is that none of them do.
#
# One constraint on this list, enforced by the contract suite: it may not contain
# any value of a published vocabulary. Stage 8E's own documents count components
# into maps keyed by enum value — ``by_component_kind: {"SOURCE_CODE": 4}`` — so a
# forbidden key named ``source_code`` would refuse a count of source-code
# components rather than a body of source code. ``source_text``, ``file_contents``
# and ``contents`` cover the thing this was meant to catch.
FORBIDDEN_PUBLISHED_KEYS: frozenset[str] = frozenset(
    {
        "license_text",
        "license_body",
        "source_text",
        "file_contents",
        "contents",
        "payload",
        "blob",
        "base64",
        "weights",
        "state_dict",
        "checkpoint_bytes",
        "embedding",
        "embeddings",
        "descriptor",
        "descriptors",
        "image_bytes",
        "score",
        "scores",
        "raw_score",
        "raw_scores",
        "threshold",
        "thresholds",
        "subject_id",
        "subject_ids",
        "pair_id",
        "pair_ids",
        "image_id",
        "image_ids",
        "absolute_path",
        "local_path",
        "artifact_root",
        "home_directory",
    }
)

#: The modules the third-party package consists of. Named rather than globbed so
#: that a new module has to be added here deliberately, and so the structural
#: tests fail loudly if one is deleted.
THIRD_PARTY_PACKAGE_MODULES: tuple[str, ...] = (
    "__init__.py",
    "purpose.py",
    "policy.py",
    "manifest.py",
    "artifacts.py",
    "transformations.py",
    "repository_guard.py",
    "verify.py",
)

#: Every source file Stage 8E owns outright, audited for import boundaries.
STAGE_8E_SOURCE_FILES: tuple[str, ...] = (
    *(f"src/fpbench/third_party/{name}" for name in THIRD_PARTY_PACKAGE_MODULES),
    "src/fpbench/core/third_party_models.py",
    "src/fpbench/core/third_party_errors.py",
    "src/fpbench/experiments/stage8e_identity.py",
    "src/fpbench/experiments/stage8e_research_only_policy.py",
    "src/fpbench/experiments/stage8e_finalization.py",
)

#: The three policy documents this stage adds, and the one thing they are not: a
#: LICENSE. A purpose policy and a copyright licence are different objects, and
#: writing a bespoke "research only licence" would create a new legal question
#: rather than answer one (docs/adr/0081).
POLICY_DOCUMENTS: tuple[str, ...] = (
    "docs/policy/research-only-purpose.md",
    "docs/policy/third-party-usage.md",
    "docs/policy/third-party-artifact-handling.md",
)

STAGE_8E_ADRS: tuple[str, ...] = (
    "docs/adr/0081-fpbench-is-personal-educational-research-only.md",
    "docs/adr/0082-third-party-license-observation-is-separate-from-local-research-use.md",
    "docs/adr/0083-third-party-bytes-are-never-redistributed-by-fpbench.md",
    "docs/adr/0084-ambiguous-upstream-rights-may-be-risk-accepted-without-becoming-a-license-finding.md",
)


def all_frozen_identifiers() -> tuple[str, ...]:
    """Every Stage 8E identifier, validated as a safe path and key component."""
    identifiers = (
        STAGE_FINALIZATION_KIND,
        *(component.record_id for component in LEGACY_COMPONENTS),
        *LEGACY_ROUTES,
    )
    for identifier in identifiers:
        validate_id(identifier)
    return identifiers
