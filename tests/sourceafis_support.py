"""Shared helpers for the SourceAFIS tests.

The environment gate is the interesting part. Tests that need a real JVM and a built
bridge jar skip when neither is present, so the suite still runs on a machine with no
JDK — but if ``FPBENCH_REQUIRE_SOURCEAFIS=1`` is set, the same tests *fail* instead of
skipping. CI sets it. Without that switch a broken build would produce a green run
full of skips, which is worse than a red one.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from fpbench.adapters.sourceafis_java.adapter import SourceAfisJavaAdapter
from fpbench.core.enums import ChecksumStatus, EnvironmentStatus
from fpbench.core.execution_models import (
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
)

__all__ = [
    "REQUIRE_ENV_VAR",
    "require_bridge",
    "prepared_image",
    "comparison_context",
    "PROFILE_ID",
]

REQUIRE_ENV_VAR = "FPBENCH_REQUIRE_SOURCEAFIS"

#: The stage 4A execution profile: identity preparation, native resolution, 60 s.
PROFILE_ID = "native_identity_60s_v1"


def require_bridge() -> tuple[SourceAfisJavaAdapter, EnvironmentReport]:
    """A SourceAFIS adapter whose environment is READY, or skip.

    Returns the report as well, because several tests assert on what it contains.
    """
    adapter = SourceAfisJavaAdapter()
    report = adapter.validate_environment()
    if report.status is not EnvironmentStatus.READY:
        reason = (
            f"SourceAFIS bridge unavailable: {report.message}. "
            "Build it with 'make sourceafis-build'."
        )
        if os.environ.get(REQUIRE_ENV_VAR) == "1":
            pytest.fail(reason)
        pytest.skip(reason)
    return adapter, report


def prepared_image(path: Path, dpi: int, image_id: str) -> PreparedImage:
    """A PreparedImage over a real file, as the identity preparer would produce."""
    resolved = Path(path).resolve()
    return PreparedImage(
        image_id=image_id,
        local_path=resolved,
        effective_ppi=dpi,
        media_type="image/png",
        expected_sha256=hashlib.sha256(resolved.read_bytes()).hexdigest(),
        checksum_status=ChecksumStatus.NOT_VERIFIED,
        preparation_profile_id=PROFILE_ID,
        preparation_hash=hashlib.sha256(image_id.encode("utf-8")).hexdigest(),
    )


def comparison_context(
    tmp_path: Path,
    *,
    job_id: str = "job_0123456789abcdef",
    timeout_seconds: float = 60.0,
) -> ComparisonContext:
    working = Path(tmp_path) / "work"
    artifacts = Path(tmp_path) / "artifacts"
    working.mkdir(parents=True, exist_ok=True)
    artifacts.mkdir(parents=True, exist_ok=True)
    return ComparisonContext(
        run_id="run_abc123abc123",
        job_id=job_id,
        attempt=1,
        working_directory=working,
        artifact_directory=artifacts,
        timeout_seconds=timeout_seconds,
        deterministic_seed=0,
    )
