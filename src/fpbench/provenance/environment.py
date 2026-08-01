"""Folding source and runtime provenance into an environment report.

A run's identity already covers its environment fingerprint, and its
environment fingerprint already covers everything an adapter chose to report.
So the cheapest correct way to make a run identify its own source revision and
its own pinned executable is to put both *into the environment* before the run
is derived — no new field on ``RunDefinition``, no second fingerprint to keep in
step, and every existing check that compares environments keeps working
unchanged (docs/adr/0017).

The function is deliberately additive and deliberately strict. It never edits
the adapter's report — it builds a new one — and it refuses rather than
overwrites when the adapter has already declared a value that disagrees with
the bundle. An adapter that says it is running jar *A* while the bundle says
*B* is not a report to be tidied up; it is a contradiction that must stop the
run.
"""

from __future__ import annotations

from typing import Mapping

from fpbench.core.enums import EnvironmentStatus
from fpbench.core.errors import ResearchPreflightError
from fpbench.core.execution_models import EnvironmentReport
from fpbench.core.provenance_models import SoftwareProvenance
from fpbench.core.runtime_models import RuntimeBundleDefinition

__all__ = [
    "build_research_environment",
    "RUNTIME_KEYS",
    "DEPENDENCY_KEYS",
    "asset_digest_key",
    "asset_size_key",
]

#: The runtime facts a research environment adds on top of the adapter's own.
RUNTIME_KEYS = (
    "python.version",
    "python.implementation",
    "fpbench.source.kind",
    "fpbench.source.revision",
    "fpbench.source.clean",
    "fpbench.integration.id",
    "fpbench.integration.fingerprint",
)

#: The dependency facts it adds. Per-asset digests are named separately, since
#: how many there are depends on the bundle.
DEPENDENCY_KEYS = (
    "fpbench.package",
    "runtime.bundle.id",
    "runtime.bundle.fingerprint",
)


def asset_digest_key(role: str) -> str:
    return f"runtime.asset.{role}.sha256"


def asset_size_key(role: str) -> str:
    return f"runtime.asset.{role}.size"


def build_research_environment(
    *,
    adapter_environment: EnvironmentReport,
    software: SoftwareProvenance,
    runtime_bundle: RuntimeBundleDefinition,
    integration_id: str | None = None,
    integration_fingerprint: str | None = None,
) -> EnvironmentReport:
    """Return a new report carrying the adapter's environment plus provenance.

    Raises:
        ResearchPreflightError: the adapter cannot run here, the source
            revision is not research-grade, or the adapter has already declared
            a runtime value that contradicts the bundle.
    """
    if adapter_environment.status is not EnvironmentStatus.READY:
        raise ResearchPreflightError(
            "a research environment cannot be built on an adapter that reports "
            f"{adapter_environment.status.value}: "
            f"{adapter_environment.message or 'no detail given'}"
        )
    if not software.is_research_grade:
        raise ResearchPreflightError(
            "a research environment needs a committed, clean source revision; "
            f"got kind={software.provenance_kind!r}, clean={software.source_tree_clean}"
        )

    runtime = dict(adapter_environment.runtime)
    dependencies = dict(adapter_environment.dependencies)

    additions_runtime = {
        "python.version": software.python_version,
        "python.implementation": software.python_implementation,
        "fpbench.source.kind": software.provenance_kind,
        "fpbench.source.revision": software.source_revision,
        # Lower-case so the value reads the same whichever language writes it.
        "fpbench.source.clean": "true" if software.source_tree_clean else "false",
    }
    integration_claims = (integration_id, integration_fingerprint)
    if any(value is not None for value in integration_claims):
        if not all(value is not None for value in integration_claims):
            raise ResearchPreflightError(
                "research integration id and fingerprint must be supplied together"
            )
        additions_runtime.update(
            {
                "fpbench.integration.id": str(integration_id),
                "fpbench.integration.fingerprint": str(integration_fingerprint),
            }
        )

    additions_dependencies: dict[str, str] = {
        "fpbench.package": software.package_version,
        "runtime.bundle.id": runtime_bundle.bundle_id,
        "runtime.bundle.fingerprint": runtime_bundle.bundle_fingerprint,
    }
    additions_dependencies.update(software.dependency_versions)
    for asset in runtime_bundle.assets:
        additions_dependencies[asset_digest_key(asset.role)] = asset.sha256
        additions_dependencies[asset_size_key(asset.role)] = str(asset.size_bytes)

    _require_no_contradiction(runtime, additions_runtime, "runtime")
    _require_no_contradiction(dependencies, additions_dependencies, "dependencies")

    runtime.update(additions_runtime)
    dependencies.update(additions_dependencies)

    return EnvironmentReport(
        status=adapter_environment.status,
        implementation_version=adapter_environment.implementation_version,
        runtime=runtime,
        dependencies=dependencies,
        message=adapter_environment.message,
    )


def _require_no_contradiction(
    existing: Mapping[str, str], additions: Mapping[str, str], section: str
) -> None:
    """Refuse to paper over a disagreement between the adapter and the bundle."""
    for key, value in additions.items():
        current = existing.get(key)
        if current is not None and current != value:
            raise ResearchPreflightError(
                f"the adapter reports {section}[{key}] = {current!r} but the "
                f"research provenance says {value!r}; refusing to overwrite an "
                "environment fact rather than resolve the contradiction"
            )
