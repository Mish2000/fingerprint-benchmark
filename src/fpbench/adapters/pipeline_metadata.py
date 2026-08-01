"""The identity of a *route*, not of a matcher.

docs/adr/0014 already says that an algorithm's identity has to describe the whole
pipeline. Until now that was enforced by one adapter remembering to fill in a
dict literal. NBIS is the case that makes the dict insufficient: it is MINDTCT
feeding Bozorth3, and a descriptor labelled ``bozorth3`` would silently omit the
extractor — so two runs against different MINDTCT builds would share an identity
they are not entitled to.

This model is that dict with the fields named. Filling it in is not optional and
leaving ``extractor_id`` empty is a construction error rather than a missing key
somebody notices a year later.

**It changes no fingerprint.** ``as_descriptor_metadata`` returns a plain
string-to-string mapping, and ``descriptor_fingerprint`` hashes it with
``sort_keys=True``. A pipeline description that produced the same keys and the
same values before produces the same digest after; there is a regression test
that asserts exactly that for SourceAFIS (spec section 70).

``extra`` exists for the keys a particular route needs and no other route has —
SourceAFIS's ``bridge_protocol`` and ``upstream_artifact``, a future adapter's
container digest. It is deliberately last, deliberately optional, and
deliberately unable to overwrite a named field: a route that wanted to redefine
``probe_side`` through the back door would be describing a different experiment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

__all__ = ["AlgorithmPipelineMetadata", "PIPELINE_METADATA_FIELDS"]

#: The keys every route must answer for, in declaration order.
PIPELINE_METADATA_FIELDS: tuple[str, ...] = (
    "family_id",
    "pipeline_kind",
    "extractor_id",
    "extractor_version",
    "matcher_id",
    "matcher_version",
    "implementation_language",
    "integration_mode",
    "input_mode",
    "dpi_policy",
    "probe_side",
    "template_cache",
    "template_persistence",
    "seed_usage",
)


@dataclass(frozen=True, slots=True)
class AlgorithmPipelineMetadata:
    """Everything about a route from two images to a score that could move it."""

    family_id: str
    pipeline_kind: str

    extractor_id: str
    extractor_version: str

    matcher_id: str
    matcher_version: str

    implementation_language: str
    integration_mode: str
    input_mode: str
    dpi_policy: str
    probe_side: str

    template_cache: str
    template_persistence: str
    seed_usage: str

    #: Route-specific keys. Never a place to redeclare a named field.
    extra: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in PIPELINE_METADATA_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} must be a non-empty string; a pipeline that will not "
                    "say what it is cannot be attributed (docs/adr/0014)"
                )
            object.__setattr__(self, name, value.strip())

        extra = {str(key): str(value) for key, value in dict(self.extra).items()}
        collisions = sorted(set(extra) & set(PIPELINE_METADATA_FIELDS))
        if collisions:
            raise ValueError(
                f"extra may not redeclare named pipeline fields: {collisions}"
            )
        for key, value in extra.items():
            if not key.strip() or not value.strip():
                raise ValueError("extra keys and values must not be empty")
        object.__setattr__(self, "extra", MappingProxyType(extra))

    def as_descriptor_metadata(self) -> Mapping[str, str]:
        """The mapping to hand to :class:`AlgorithmDescriptor`.

        Read-only, string to string, and ordered named-fields-then-extra. Order
        is cosmetic: the fingerprint sorts its keys.
        """
        payload = {name: getattr(self, name) for name in PIPELINE_METADATA_FIELDS}
        payload.update(self.extra)
        return MappingProxyType(payload)
