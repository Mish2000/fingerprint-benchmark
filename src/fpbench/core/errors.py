"""Exception hierarchy shared by the project.

These are *programming and configuration* errors — conditions under which the
harness cannot proceed. They are deliberately not the vocabulary for biometric
outcomes: an algorithm that fails to extract a template is a recorded result,
not an exception (see docs/adr/0006).
"""

from __future__ import annotations

__all__ = [
    "FpbenchError",
    "ConfigurationError",
    "DatasetError",
    "DatasetLayoutError",
    "ProtocolError",
    "InsufficientCohortError",
    "StorageError",
    "ManifestExistsError",
    "ResultConflictError",
    "RuntimeBundleConflictError",
    "ResultSetConflictError",
    "ImagePreparationError",
    "ExecutionError",
    "PreflightError",
    "ResearchPreflightError",
    "PlanningError",
    "PlanConflictError",
    "RunIntegrityError",
    "IncompleteRunError",
    "RuntimeDriftError",
    "DerivationError",
    "DecisionProfileError",
    "DecisionProfileApplicabilityError",
    "DecisionDerivationError",
    "DecisionSetConflictError",
    "DecisionSetIntegrityError",
    "SelfMappingError",
    "EligibilityIntegrityError",
    "EvaluationViewIntegrityError",
    "DecisionFinalizationError",
    "MetricError",
    "MetricPolicyError",
    "MetricDerivationError",
    "MetricSetConflictError",
    "MetricSetIntegrityError",
    "EvaluationReportError",
    "EvaluationFinalizationError",
    "ImagingError",
    "TransformProfileError",
    "SourceImageContractError",
    "PreparedImageSetConflictError",
    "PreparationDerivationError",
    "PreparationIntegrityError",
    "PreparationFinalizationError",
    "PreparedImageDriftError",
]


class FpbenchError(Exception):
    """Base class for every error raised by this project."""


class ConfigurationError(FpbenchError):
    """A configuration file is missing, malformed or internally inconsistent."""


class DatasetError(FpbenchError):
    """The dataset on disk does not match what the dataset provider expects."""


class DatasetLayoutError(DatasetError):
    """A required directory or index file is missing from the dataset root."""


class ProtocolError(FpbenchError):
    """The protocol cannot be constructed from the available images."""


class InsufficientCohortError(ProtocolError):
    """Fewer eligible subjects exist than the protocol requires."""


class StorageError(FpbenchError):
    """A manifest or result could not be read or written."""


class ManifestExistsError(StorageError):
    """Refused to overwrite an existing manifest (see docs/adr/0005)."""


class ResultConflictError(StorageError):
    """A stored artefact exists but describes something else.

    Raised when a run manifest or a job result is already on disk under an
    identifier that should have been unique, and its fingerprint disagrees with
    what is being written. Never resolved by overwriting: the correct response
    is a new run, not a lost result (docs/adr/0009).
    """


class RuntimeBundleConflictError(StorageError):
    """A different runtime bundle is already stored under this bundle id.

    A bundle id is the first twelve characters of a digest over its assets'
    contents, so this normally means the stored bundle was tampered with or a
    fingerprint rule changed. Never resolved by overwriting: the executable a
    finished run was produced with must stay exactly as it was
    (docs/adr/0018).
    """


class ResultSetConflictError(StorageError):
    """A different result set is already stored under this run.

    Raised when the ordered collection of raw result hashes on disk disagrees
    with the one being written. Two different sets of scores are two different
    result sets, and the second must never be able to overwrite the first
    (docs/adr/0019).
    """


class ImagePreparationError(FpbenchError):
    """An image could not be made ready for an adapter.

    Raised by an :class:`~fpbench.imaging.base.ImagePreparer`. The runner turns
    it into a recorded ``PREPARATION_FAILED`` result rather than letting it
    abort the run.
    """


class ExecutionError(FpbenchError):
    """A run could not be carried out as defined."""


class PreflightError(ExecutionError):
    """The runner's inputs disagree with the run definition.

    A run-level fault — a mismatched adapter, an unavailable environment, the
    wrong preparer. It must stop the run before any job executes, rather than
    producing thousands of identical per-pair failures.
    """


class ResearchPreflightError(PreflightError):
    """A research run's provenance preconditions are not met.

    Distinct from an ordinary :class:`PreflightError` because it is never about
    the machine being wrong — it is about the *evidence* being insufficient: an
    uncommitted working tree, a different commit than the run was defined under,
    a dataset whose checksums were never verified. There is no override. Code
    that is not committed cannot be recovered from a receipt written a year
    later, so the fix is to commit it, not to record that it was dirty
    (docs/adr/0017).
    """


class RuntimeDriftError(FpbenchError):
    """The pinned executable changed while a run was using it.

    Deliberately *not* an :class:`ExecutionError` subclass that a runner might
    reasonably record: this is never a comparison failure. A result written
    after the bytes underneath the adapter changed would claim provenance it
    does not have, so this exception is fatal to the whole invocation and must
    reach the caller unrecorded (docs/adr/0018).
    """


class PlanningError(ExecutionError):
    """An execution plan cannot be built from the given inputs.

    Duplicated pairs, or a pair manifest that does not belong to the run.
    Building a plan anyway would produce a run whose results cannot be
    attributed to any particular set of comparisons (docs/adr/0011).
    """


class PlanConflictError(ExecutionError):
    """A different plan is already stored under this run.

    Plans are immutable. Since a run's identity already covers its pair
    manifest, this normally means the stored plan was edited or a fingerprint
    rule changed — never something to resolve by overwriting.
    """


class RunIntegrityError(ExecutionError):
    """Stored results contradict the plan or each other.

    Distinct from a comparison that failed: that is a valid recorded result and
    a run full of them can still be complete (docs/adr/0013). This is a missing
    result, an extra one, a corrupt file, or provenance that does not match —
    conditions under which continuing would mix incomparable results together.
    """


class IncompleteRunError(ExecutionError):
    """An operation needed every planned job to have a result, and some do not."""


# ------------------------------------------------------------------ derivation
#
# Everything below belongs to the layer that turns stored raw scores into
# decisions, eligibility and evaluation views. None of it is a biometric
# vocabulary either: a comparison that scored below a threshold is a perfectly
# ordinary NON_MATCH, not an error. These are the conditions under which a
# *derivation* cannot honestly be produced (docs/adr/0021).


class DerivationError(FpbenchError):
    """A derivation over stored results cannot be carried out as defined."""


class DecisionProfileError(DerivationError):
    """A decision profile is missing, malformed or internally inconsistent.

    A threshold that is not a finite canonical decimal, a comparator that
    contradicts the algorithm's score direction, or a profile claiming to be
    calibrated with no calibration manifest behind it.
    """


class DecisionProfileApplicabilityError(DerivationError):
    """This profile may not be applied to this run.

    A different algorithm, a different build of the same algorithm, or an
    execution profile the decision profile does not cover. There is deliberately
    no warn-and-continue path: applying a threshold across builds would produce
    decisions nobody could attribute (docs/adr/0022).
    """


class DecisionDerivationError(DerivationError):
    """Decisions could not be derived from the results they cite.

    The source run is not research-ready, a stored result no longer hashes to
    what the result set records, or a planned job has no result to decide.
    """


class DecisionSetConflictError(StorageError):
    """A different decision set is already stored under this identity.

    Decisions are a pure function of scores, profile and derivation code, so
    this means one of those changed while the identity did not — never something
    to resolve by overwriting.
    """


class DecisionSetIntegrityError(DerivationError):
    """A stored decision set does not survive re-derivation.

    A decision set is not evidence of itself: verification recomputes every
    decision from the raw score it cites and compares (docs/adr/0022).
    """


class SelfMappingError(DerivationError):
    """The SELF comparisons of a release/subject/finger unit do not line up.

    A missing PLAIN SELF, a duplicate ROLL SELF, a pair linking two releases or
    two fingers. The mapping is derived from the frozen pair manifest, so any of
    these means the manifest and the protocol disagree (docs/adr/0023).
    """


class EligibilityIntegrityError(DerivationError):
    """A stored eligibility set does not survive re-derivation."""


class EvaluationViewIntegrityError(DerivationError):
    """A stored evaluation view does not survive re-derivation."""


class DecisionFinalizationError(DerivationError):
    """A derivation could not be finalised, or its marker no longer holds.

    Until the marker is written the intermediates are retryable and not
    authoritative; once it is written, it must keep naming exactly the chain it
    was issued over (docs/adr/0020, applied to derivations).
    """


# --------------------------------------------------------------------- metrics
#
# The layer that counts decisions. Still not a biometric vocabulary: a metric
# that comes out low is a finding, not an error. These are the conditions under
# which a *count* cannot honestly be turned into a rate, or a rate into a
# published report (docs/adr/0026).


class MetricError(FpbenchError):
    """Metrics could not be computed or published as defined."""


class MetricPolicyError(MetricError):
    """A metric policy is missing, malformed or internally inconsistent.

    A denominator that names no known population, a metric id claiming a
    general false-match rate, a pooling rule that averages percentages, a unit
    of analysis nobody argued for (docs/adr/0028, docs/adr/0030).
    """


class MetricDerivationError(MetricError):
    """Counts could not be derived from the artefacts they cite.

    The source derivation is not decision-ready, a view holds a release the
    experiment does not expect, a SELF decision is missing for an eligibility
    unit, or a pooled total disagrees with the release totals it should be the
    sum of.
    """


class MetricSetConflictError(StorageError):
    """A different metric set is already stored under this identity.

    Metrics are a pure function of the decisions, the policy and the metric
    code, so this means one of those changed while the identity did not — never
    something to resolve by overwriting.
    """


class MetricSetIntegrityError(MetricError):
    """A stored metric set does not survive re-derivation.

    A metric set is not evidence of itself: verification recomputes every count,
    every numerator, every denominator and every pooled sum from the decisions
    and views they cite, and compares (spec section 46).
    """


class EvaluationReportError(MetricError):
    """A report could not be rendered from verified numbers.

    Never raised because a result was disappointing. Raised when a report would
    have to invent something: a percentage with no denominator behind it, a
    metric the policy does not define, a release the profile does not order.
    """


class EvaluationFinalizationError(MetricError):
    """An evaluation could not be finalised, or its marker no longer holds.

    The same contract as a derivation one layer down: everything before the
    marker is retryable, and once the marker exists it must keep naming exactly
    the metric set, summary, report and receipt it was issued over.
    """


# --------------------------------------------------------------------- imaging
#
# The layer that turns delivered source images into one shared canonical input
# set. None of this is a biometric vocabulary either: an image that resamples
# cleanly to 500 ppi has not been judged, and one that cannot be resampled has
# not failed a comparison. These are the conditions under which a *prepared
# artefact* cannot honestly be produced or believed (docs/adr/0031).


class ImagingError(FpbenchError):
    """A shared image transformation could not be carried out as defined."""


class TransformProfileError(ImagingError):
    """A transform profile is missing, malformed or internally inconsistent.

    A resampler nobody named, a target resolution above the source, a forbidden
    operation left undeclared, an output pixel format the profile does not pin.
    There is deliberately no default: an unstated resampling rule is a rule
    every algorithm would be free to read differently (docs/adr/0031).
    """


class SourceImageContractError(ImagingError):
    """A source image is not the single-frame 8-bit grayscale PNG it must be.

    Raised rather than silently converted. An RGB image flattened quietly, or a
    16-bit image truncated quietly, would change what the experiment measured
    without changing anything the experiment records (spec section 14).
    """


class PreparedImageSetConflictError(StorageError):
    """A different prepared artefact is already stored under this identity.

    A canonical image is a pure function of the source bytes, the transform
    profile and the pinned resampler, so this means one of those changed while
    the identity did not — never something to resolve by overwriting.
    """


class PreparationDerivationError(ImagingError):
    """A prepared-image set could not be derived from the inputs it cites.

    A participating image absent from the manifest, a source checksum that was
    never verified, a runtime that changed half way through materialisation.
    """


class PreparationIntegrityError(ImagingError):
    """A stored prepared-image set does not survive re-verification.

    A prepared-image set is not evidence of itself: verification re-reads every
    source record, re-hashes every output raster and re-derives every entry hash
    from the bytes on disk (docs/adr/0033).
    """


class PreparationFinalizationError(ImagingError):
    """A preparation could not be finalised, or its marker no longer holds."""


class PreparedImageDriftError(RuntimeDriftError):
    """A prepared artefact changed while a run was comparing against it.

    Deliberately a :class:`RuntimeDriftError`, so the runner's existing rule
    applies unchanged: it is re-raised unrecorded and is fatal to the whole
    invocation. A result written after the canonical PNG underneath it changed
    would claim an input it did not have, and no later run can salvage it — the
    fix is a new preparation set and a new run (docs/adr/0033).
    """
