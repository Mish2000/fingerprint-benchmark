"""Changing upstream source without forking it into a public repository.

Sometimes upstream cannot be called as it is. An import fails on a version it
predates, a hard-coded device string has to become a parameter, an entry point
expects a directory layout this project does not have. The tempting answer is to
copy the source into ``integrations/<name>/vendor/``, fix it, and commit — which
publishes somebody else's code from a public repository and replaces a pinned
upstream digest with "whatever is in our tree now".

The ladder, in the order it must be tried:

1. **A wrapper that changes no upstream byte.** Almost always possible, and it
   keeps the upstream digest meaningful.
2. **A project-owned transformation recipe.** A rule this project wrote, applied
   locally to bytes this project did not write. The repository stores the rule
   and two digests.
3. **A local patch.** Same recording obligations, applied outside the tree.

What the repository holds for rungs 2 and 3 is a
:class:`~fpbench.core.third_party_models.UpstreamTransformation`: the preimage
digest, the rule, the postimage digest, the reason, and a classification. Not one
line of upstream source. A reviewer can see exactly what was done and confirm the
result reproduces; a reader of the public repository still receives no upstream
code (docs/adr/0083).

``INTEGRATION_ONLY`` is the only classification this stage's policy permits
without further argument. Anything that could move a score is
``BEHAVIOUR_AFFECTING``, and that is an ADR before it is a commit — because
preprocessing is part of the algorithm, and so is everything else that changes
what the algorithm sees (docs/adr/0064).
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from fpbench.core.third_party_errors import UpstreamTransformationError
from fpbench.core.third_party_models import (
    TransformationClassification,
    UpstreamModificationStrategy,
    UpstreamTransformation,
)

__all__ = [
    "MODIFICATION_LADDER",
    "choose_modification_strategy",
    "record_transformation",
    "transformation_over_bytes",
    "require_integration_only",
]

#: The ladder as data, so that "we tried the cheaper rung first" is checkable.
MODIFICATION_LADDER: tuple[UpstreamModificationStrategy, ...] = (
    UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION,
    UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE,
    UpstreamModificationStrategy.LOCAL_PATCH,
)


def choose_modification_strategy(
    *,
    wrapper_is_sufficient: bool,
    transformation_recipe_is_sufficient: bool,
) -> UpstreamModificationStrategy:
    """The highest rung that works, which is the lowest number that is ``True``.

    Deliberately takes two booleans rather than a preferred strategy. A caller
    that could name its preference would name ``LOCAL_PATCH`` on the day the
    other two looked like more work, and the ladder would become a comment.
    """
    if type(wrapper_is_sufficient) is not bool or type(
        transformation_recipe_is_sufficient
    ) is not bool:
        raise UpstreamTransformationError(
            "the ladder is walked on facts, not on truthy values"
        )
    if wrapper_is_sufficient:
        return UpstreamModificationStrategy.WRAPPER_WITHOUT_UPSTREAM_MODIFICATION
    if transformation_recipe_is_sufficient:
        return UpstreamModificationStrategy.PROJECT_OWNED_TRANSFORMATION_RECIPE
    return UpstreamModificationStrategy.LOCAL_PATCH


def record_transformation(
    *,
    transformation_id: str,
    strategy: UpstreamModificationStrategy,
    subject: str,
    preimage_sha256: str,
    postimage_sha256: str,
    transformation_rule: str,
    reason: str,
    classification: TransformationClassification = (
        TransformationClassification.INTEGRATION_ONLY
    ),
) -> UpstreamTransformation:
    """A transformation, with its identity derived rather than supplied."""
    return UpstreamTransformation(
        transformation_id=transformation_id,
        strategy=strategy,
        subject=subject,
        preimage_sha256=preimage_sha256,
        postimage_sha256=postimage_sha256,
        transformation_rule=transformation_rule,
        reason=reason,
        classification=classification,
    )


def transformation_over_bytes(
    preimage: bytes,
    postimage: bytes,
    *,
    transformation_id: str,
    strategy: UpstreamModificationStrategy,
    subject: str,
    transformation_rule: str,
    reason: str,
    classification: TransformationClassification = (
        TransformationClassification.INTEGRATION_ONLY
    ),
) -> UpstreamTransformation:
    """Record a transformation by hashing the two versions, not by storing them.

    The bytes go in and two digests come out. Nothing here writes upstream source
    anywhere, and in particular nothing here returns it — a helper that handed
    back the postimage would be one refactor away from a committed fork.
    """
    if not isinstance(preimage, (bytes, bytearray)) or not isinstance(
        postimage, (bytes, bytearray)
    ):
        raise UpstreamTransformationError(
            "a transformation is recorded over exact bytes, not over text whose "
            "encoding and line endings depend on the checkout"
        )
    return record_transformation(
        transformation_id=transformation_id,
        strategy=strategy,
        subject=subject,
        preimage_sha256=hashlib.sha256(bytes(preimage)).hexdigest(),
        postimage_sha256=hashlib.sha256(bytes(postimage)).hexdigest(),
        transformation_rule=transformation_rule,
        reason=reason,
        classification=classification,
    )


def require_integration_only(
    transformations: Sequence[UpstreamTransformation],
) -> None:
    """Refuse a transformation that could change what an algorithm computes.

    Raises:
        UpstreamTransformationError: one of them is ``BEHAVIOUR_AFFECTING``. That
            is not forbidden forever — it is forbidden until it is argued for in
            an ADR, because a transformation that moves a score is a change to
            the algorithm's identity and has to be visible as one
            (docs/adr/0014, docs/adr/0064).
    """
    offending = sorted(
        item.transformation_id
        for item in transformations
        if item.classification is not TransformationClassification.INTEGRATION_ONLY
    )
    if offending:
        raise UpstreamTransformationError(
            f"these transformations can change what the algorithm computes: "
            f"{offending}. A behaviour-affecting change to upstream is an ADR "
            "before it is a commit"
        )
