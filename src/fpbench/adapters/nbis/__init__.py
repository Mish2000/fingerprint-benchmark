"""NIST NBIS 5.0.0 — MINDTCT into BOZORTH3 — as one algorithm identity.

Importing this package costs nothing and requires no NBIS: the adapter reports
its own environment as ``UNAVAILABLE`` when the build is absent or the platform is
not one this stage certified, so listing the registry stays cheap on a machine
that has never built it.

See ``docs/algorithms/nbis-mindtct-bozorth3.md`` for what this route is,
``docs/architecture/nbis-input-and-ppi-policy.md`` for why it runs on canonical
500 ppi PNGs only, and ``docs/architecture/nbis-build-provenance.md`` for how a
build becomes citable.
"""

from __future__ import annotations

from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    ALGORITHM_ID,
    IMPLEMENTATION_VERSION,
    PIPELINE,
    PIPELINE_METADATA,
    RESULT_METADATA,
    NbisAdapter,
)
from fpbench.adapters.nbis.build_manifest import (
    EXPECTED_NBIS_VERSION,
    EXPECTED_PNG_PPI_POLICY,
    SUPPORTED_TARGETS,
    NbisBuildManifest,
    NbisBuildManifestError,
    NbisOfficialTestSummary,
    read_build_manifest,
    verify_against_repository,
    verify_build_manifest,
)
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    NbisConfig,
)
from fpbench.adapters.nbis.png_input import NbisInputRejected, require_gray8_500ppi_png
from fpbench.adapters.nbis.score import ScoreFormatError, parse_bozorth3_score
from fpbench.adapters.nbis.xyt import NbisMinutia, XytFormatError, parse_xyt, read_xyt

__all__ = [
    "NbisAdapter",
    "NbisConfig",
    "NbisMinutia",
    "NbisBuildManifest",
    "NbisBuildManifestError",
    "NbisOfficialTestSummary",
    "NbisInputRejected",
    "ScoreFormatError",
    "XytFormatError",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "ALGORITHM_ID",
    "IMPLEMENTATION_VERSION",
    "EXPECTED_NBIS_VERSION",
    "EXPECTED_PNG_PPI_POLICY",
    "SUPPORTED_TARGETS",
    "PIPELINE",
    "PIPELINE_METADATA",
    "RESULT_METADATA",
    "MINDTCT_ROLE",
    "BOZORTH3_ROLE",
    "BUILD_MANIFEST_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "parse_xyt",
    "read_xyt",
    "parse_bozorth3_score",
    "read_build_manifest",
    "require_gray8_500ppi_png",
    "verify_build_manifest",
    "verify_against_repository",
]
