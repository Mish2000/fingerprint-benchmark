"""Where the upstream binding used to live, and what now answers instead.

The rule moved. :class:`~fpbench.core.third_party_models.BoundUpstreamComponent`
and its vocabulary are in ``core`` with the other persisted third-party models,
and :func:`~fpbench.third_party.manifest.bind_component` is in
``third_party/manifest.py`` beside the builder it guards.

**Why it could not stay here.** Stage 8E published two boundaries that this
module sat outside of: ``fpbench/third_party/`` holds exactly the modules that
stage names, and it imports only ``fpbench.core`` and itself
(``tests/contract/test_stage8e_boundaries.py``). So
:func:`~fpbench.third_party.manifest.build_usage_record` could not import
``fpbench.provenance``, and enforcement written here could only ever sit
*beside* the builder, never inside it — which is exactly why three production
call sites went on using the unbound path for as long as they did.

This module is kept as a re-export so that the name people know still resolves.
It adds nothing and decides nothing.
"""

from __future__ import annotations

from fpbench.core.third_party_models import (
    AttestationMethod,
    BoundUpstreamComponent,
    IdentityLinkBasis,
    PublisherAttestation,
    publisher_attestation_fingerprint,
    upstream_binding_fingerprint,
    upstream_identity_fingerprint,
)
from fpbench.third_party.manifest import bind_component, derive_identity_link

__all__ = [
    "AttestationMethod",
    "BoundUpstreamComponent",
    "IdentityLinkBasis",
    "PublisherAttestation",
    "bind_component",
    "derive_identity_link",
    "publisher_attestation_fingerprint",
    "upstream_binding_fingerprint",
    "upstream_identity_fingerprint",
]
