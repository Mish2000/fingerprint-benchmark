"""What every result of a run over a materialised input set must claim.

None of this is about an algorithm. "The stored result names an artefact that
exists in this exact prepared-image set, with this width, this height, this file
digest and this raster digest" is the same question whether the comparison was
carried out by SourceAFIS, by a two-executable pipeline, or by something that has
not been written yet — and answering it twice, once per algorithm, is how the two
answers eventually diverge.

So the expectations live here, in a module no algorithm owns.

The model was called ``CanonicalPreparationExpectations`` while there was exactly
one canonical profile to expect. The name is kept as an alias — imports that use
it keep working, and the stage 6A code reads the same — but the honest name is
:class:`PreparedInputExpectations`: it describes any materialised input set, and
the canonical-500 profile is one instance of one (spec section 25).

Present for a run over a prepared set and ``None`` for a run over the delivered
bytes. That asymmetry is deliberate rather than a gap: the identity preparer
materialises nothing, so there is no set for its results to be checked against,
and inventing one would make thousands of already-stored results fail a check
they were never subject to (spec section 61).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from fpbench.core.enums import IntegrityIssueCode, IntegritySeverity
from fpbench.core.identifiers import ImageId, PairId
from fpbench.core.imaging_models import PreparedImageEntry
from fpbench.core.models import ComparisonPair
from fpbench.core.result_models import RawResultRecord
from fpbench.core.run_state_models import IntegrityIssue

__all__ = [
    "PreparedInputExpectations",
    "CanonicalPreparationExpectations",
    "check_prepared_inputs",
    "check_release_source_resolutions",
]


@dataclass(frozen=True, slots=True)
class PreparedInputExpectations:
    """The input-set identity every result of one run has to agree with.

    Holding the entry index here is what turns "the result says it used prepared
    pixels" into "the result names an artefact that exists in this exact set,
    with this width, this height, this file digest and this raster digest"
    (spec section 75).
    """

    execution_profile_id: str
    preparer_id: str
    preparer_version: str
    runner_metadata_schema: str

    preparation_set_id: str
    preparation_set_fingerprint: str

    transform_profile_id: str
    transform_profile_fingerprint: str
    transform_runtime_fingerprint: str

    target_ppi: int

    entries: Mapping[ImageId, PreparedImageEntry]

    #: Which source resolution each release is entitled to have been scaled
    #: from. Empty disables the release-aware check, which is what a synthetic
    #: world with invented release names wants.
    expected_source_ppi: Mapping[str, int] = field(default_factory=dict)

    def run_level_metadata(self) -> Mapping[str, str]:
        """The runner-metadata keys that are the same for every comparison."""
        return {
            "preparer_id": self.preparer_id,
            "preparer_version": self.preparer_version,
            "runner_metadata_schema": self.runner_metadata_schema,
            "preparation_set_id": self.preparation_set_id,
            "preparation_set_fingerprint": self.preparation_set_fingerprint,
            "transform_profile_id": self.transform_profile_id,
            "transform_profile_fingerprint": self.transform_profile_fingerprint,
            "transform_runtime_fingerprint": self.transform_runtime_fingerprint,
        }


#: The name this model had while only one profile used it. Same class, so
#: ``isinstance`` and equality behave as they always did.
CanonicalPreparationExpectations = PreparedInputExpectations


# ------------------------------------------------------------------- checks
#
# Moved here from the SourceAFIS validator unchanged: same codes, same messages,
# same order, and therefore the same validation fingerprint for the results
# already stored. There is a regression test that says so, because "I moved it
# carefully" is not evidence (spec sections 26 and 27).


def check_prepared_inputs(
    record: RawResultRecord, preparation: PreparedInputExpectations
) -> Iterable[IntegrityIssue]:
    """Does this result name an artefact that actually exists in the set?

    Every check here is against the *entries*, not against another copy of the
    same claim. A result that recorded a preparation-set fingerprint and nothing
    else would prove only that somebody typed the fingerprint; a result whose
    recorded entry hash, file digest, raster digest and dimensions all match the
    entry for its own image id could not have been produced from anything else
    (spec section 75).

    Nothing here is algorithm-specific. "The left side is the artefact this set
    says it is" reads the same whether the comparison was carried out by a Java
    matcher, by two command-line tools, or by something not yet written.
    """
    job_id = record.job_id
    metadata = record.runner_metadata

    for key, expected in preparation.run_level_metadata().items():
        actual = metadata.get(key)
        if actual is None:
            yield _issue(
                IntegrityIssueCode.RESULT_METADATA_MISSING,
                f"result {job_id} does not record {key}; it cannot be attributed "
                "to the input set that produced it",
                job_id=job_id,
            )
        elif actual != expected:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id} records {key}={str(actual)[:16]}..., expected "
                f"{str(expected)[:16]}...",
                job_id=job_id,
            )

    for side, image_id in (
        ("left", record.left_image_id),
        ("right", record.right_image_id),
    ):
        entry = preparation.entries.get(image_id)
        if entry is None:
            yield _issue(
                IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                f"result {job_id}'s {side} image has no entry in prepared-image set "
                f"{preparation.preparation_set_id}",
                job_id=job_id,
            )
            continue

        for suffix, expected in (
            ("preparation_entry_hash", entry.entry_hash),
            ("prepared_sha256", entry.output_encoded_sha256),
            ("pixel_sha256", entry.output_pixel_sha256),
            ("source_ppi", str(entry.source_effective_ppi)),
            ("output_ppi", str(entry.output_effective_ppi)),
            ("output_width", str(entry.output_width)),
            ("output_height", str(entry.output_height)),
        ):
            key = f"{side}_{suffix}"
            actual = metadata.get(key)
            if actual is None:
                yield _issue(
                    IntegrityIssueCode.RESULT_METADATA_MISSING,
                    f"result {job_id} does not record {key}",
                    job_id=job_id,
                )
            elif actual != str(expected):
                yield _issue(
                    IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    f"result {job_id} records {key}={str(actual)[:16]}..., but the "
                    f"prepared-image set says {str(expected)[:16]}...",
                    job_id=job_id,
                )

        if entry.output_effective_ppi != preparation.target_ppi:
            yield _issue(
                IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                f"result {job_id}'s {side} artefact is "
                f"{entry.output_effective_ppi} ppi; this profile targets "
                f"{preparation.target_ppi}",
                job_id=job_id,
            )
        if entry.source_effective_ppi < entry.output_effective_ppi:
            yield _issue(  # pragma: no cover - the entry model forbids it
                IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                f"result {job_id}'s {side} artefact was upsampled",
                job_id=job_id,
            )


def check_release_source_resolutions(
    *,
    pairs: Mapping[PairId, ComparisonPair],
    preparation: PreparedInputExpectations,
    expected_source_ppi: Mapping[str, int],
) -> Iterable[IntegrityIssue]:
    """Every SD300A entry came from 500 ppi, every B from 1000, every C from 2000.

    Joined back through the pair manifest rather than read off adapter metadata,
    which by construction says one value for every release after canonicalisation
    (spec section 76).
    """
    for pair in pairs.values():
        expected = expected_source_ppi.get(pair.release)
        if expected is None:
            continue
        for side, image_id in (
            ("left", pair.left_image_id),
            ("right", pair.right_image_id),
        ):
            entry = preparation.entries.get(image_id)
            if entry is None:
                yield _issue(
                    IntegrityIssueCode.RESULT_PIPELINE_MISMATCH,
                    f"pair {pair.pair_id}'s {side} image has no prepared entry",
                )
                continue
            if entry.source_effective_ppi != expected:
                yield _issue(
                    IntegrityIssueCode.RESULT_RESOLUTION_MISMATCH,
                    f"pair {pair.pair_id}'s {side} artefact was scaled from "
                    f"{entry.source_effective_ppi} ppi; {pair.release} is used at "
                    f"{expected}",
                )


def _issue(
    code: IntegrityIssueCode,
    message: str,
    *,
    severity: IntegritySeverity = IntegritySeverity.ERROR,
    job_id: str | None = None,
    **details: str,
) -> IntegrityIssue:
    return IntegrityIssue(
        code=code,
        severity=severity,
        message=message,
        job_id=job_id,
        details=details,
    )
