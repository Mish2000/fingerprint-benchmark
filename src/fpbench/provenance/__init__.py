"""Which build of the harness, and which executable, produced a result.

Dependency rule: ``provenance`` imports ``core`` and the standard library only.
It is imported by ``execution`` and by the experiment entry points, never the
other way round.
"""

from fpbench.core.provenance_models import (
    PROVENANCE_KIND_GIT,
    PROVENANCE_KIND_UNAVAILABLE,
    SoftwareProvenance,
    software_provenance_fingerprint,
)
from fpbench.provenance.environment import build_research_environment
from fpbench.provenance.software import (
    capture_software_provenance,
    dependency_versions,
)

__all__ = [
    "PROVENANCE_KIND_GIT",
    "PROVENANCE_KIND_UNAVAILABLE",
    "SoftwareProvenance",
    "build_research_environment",
    "capture_software_provenance",
    "dependency_versions",
    "software_provenance_fingerprint",
]
