"""Where a metric set lives, and the rules that keep it immutable.

Layout, beneath the run whose decisions it counts::

    results/<run_id>/evaluations/<metric_set_id>/
    ├── definition.json               what was pinned before anything was counted
    ├── metric-policy.json            the exact metric definitions applied
    ├── report-profile.json           how the numbers are rendered
    ├── manifest.json                 the identity
    ├── counts.parquet                every aggregate table, at every scope
    ├── observations.parquet          every metric, at every scope
    ├── summary.json                  the machine-readable rendering
    ├── report.md                     the human-readable rendering
    ├── evaluation-receipt.json       the committable statement
    └── evaluation-finalization.json  written last; without it, none of it counts

**The policy is stored beside the numbers**, not merely referenced. The config
file it was read from lives in a repository that will keep changing, and a metric
set pointing at "the policy in configs/" would silently mean something different
after the next edit. The copy here is what the counts were actually taken under.

**Write order matters.** Definition, policy, report profile, rows, then the
manifest. The manifest is the marker that says the set is complete, so a crash
leaves a visibly unfinished directory rather than an identity pointing at rows
that were never written. The report, summary and receipt come later still, and
the finalization marker last of all.

**No overwrite.** The same set again is a no-op; a different set under the same
id is a conflict. Since the id is derived from the decisions, the policy and the
metric code, a genuinely different evaluation lands in a different directory and
cannot collide.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from fpbench.core.enums import MetricDenominator, MetricNumerator
from fpbench.core.errors import MetricSetConflictError, StorageError
from fpbench.core.evaluation_models import (
    EvaluationFinalizationMarker,
    EvaluationReceipt,
    EvaluationSummary,
    MetricDerivationDefinition,
    evaluation_receipt_fingerprint,
)
from fpbench.core.metric_models import (
    METRIC_SET_SCHEMA_VERSION,
    CountFamily,
    EvaluationCountRecord,
    MetricDefinition,
    MetricObservation,
    MetricPolicy,
    MetricSetManifest,
    ReportProfile,
    ordered_count_records_hash,
    ordered_observations_hash,
    scope_sort_key,
)
from fpbench.core.serialization import read_json, write_json
from fpbench.storage import layout, metric_schemas

__all__ = ["MetricSetStore", "write_text_atomically"]

_DEFINITION = "definition.json"
_POLICY = "metric-policy.json"
_REPORT_PROFILE = "report-profile.json"
_MANIFEST = "manifest.json"
_COUNTS = "counts.parquet"
_OBSERVATIONS = "observations.parquet"
_SUMMARY = "summary.json"
_REPORT = "report.md"
_RECEIPT = "evaluation-receipt.json"
_FINALIZATION = "evaluation-finalization.json"


def write_text_atomically(path: Path, text: str) -> Path:
    """Write text the same way :func:`write_json` does, and as atomically.

    Line endings go through Python's text-mode translation, exactly as
    ``write_json`` does, so a report written here and its committed evidence copy
    are byte-identical on the same platform — which is what
    ``evidence/`` requires (spec section 84).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


class MetricSetStore:
    """Immutable storage for metric sets beneath one run."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ paths

    def evaluations_root(self, run_id: str) -> Path:
        return layout.evaluations_root(self.root, run_id)

    def metric_set_dir(self, run_id: str, metric_set_id: str) -> Path:
        return layout.metric_set_directory(self.root, run_id, metric_set_id)

    def definition_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _DEFINITION

    def policy_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _POLICY

    def report_profile_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _REPORT_PROFILE

    def manifest_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _MANIFEST

    def counts_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _COUNTS

    def observations_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _OBSERVATIONS

    def summary_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _SUMMARY

    def report_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _REPORT

    def receipt_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _RECEIPT

    def finalization_path(self, run_id: str, metric_set_id: str) -> Path:
        return self.metric_set_dir(run_id, metric_set_id) / _FINALIZATION

    def has_metric_set(self, run_id: str, metric_set_id: str) -> bool:
        return self.manifest_path(run_id, metric_set_id).is_file()

    def has_summary(self, run_id: str, metric_set_id: str) -> bool:
        return self.summary_path(run_id, metric_set_id).is_file()

    def has_report(self, run_id: str, metric_set_id: str) -> bool:
        return self.report_path(run_id, metric_set_id).is_file()

    def has_receipt(self, run_id: str, metric_set_id: str) -> bool:
        return self.receipt_path(run_id, metric_set_id).is_file()

    def has_finalization(self, run_id: str, metric_set_id: str) -> bool:
        return self.finalization_path(run_id, metric_set_id).is_file()

    def metric_set_ids(self, run_id: str) -> tuple[str, ...]:
        directory = self.evaluations_root(run_id)
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in directory.iterdir()
                if (path / _MANIFEST).is_file()
            )
        )

    # ------------------------------------------------------------------ write

    def ensure_metric_set(
        self,
        *,
        definition: MetricDerivationDefinition,
        policy: MetricPolicy,
        report_profile: ReportProfile,
        manifest: MetricSetManifest,
        counts: tuple[EvaluationCountRecord, ...],
        observations: tuple[MetricObservation, ...],
    ) -> Path:
        """Store the set, or confirm the stored one is already it.

        Raises:
            StorageError: the manifest, policy, counts and observations do not
                describe one another.
            MetricSetConflictError: a different set is already stored here.
        """
        counts = tuple(counts)
        observations = tuple(observations)
        self._require_coherent(
            definition=definition,
            policy=policy,
            report_profile=report_profile,
            manifest=manifest,
            counts=counts,
            observations=observations,
        )

        run_id = manifest.run_id
        set_id = manifest.metric_set_id
        manifest_path = self.manifest_path(run_id, set_id)

        if manifest_path.is_file():
            stored = self.read_manifest(run_id, set_id)
            if stored.metric_set_fingerprint != manifest.metric_set_fingerprint:
                raise MetricSetConflictError(
                    f"run {run_id} already holds metric set {stored.metric_set_id} "
                    f"({stored.metric_set_fingerprint[:12]}...); refusing to replace "
                    f"it with {manifest.metric_set_fingerprint[:12]}..."
                )
            return manifest_path.parent

        write_json(self.definition_path(run_id, set_id), definition)
        write_json(self.policy_path(run_id, set_id), policy)
        write_json(self.report_profile_path(run_id, set_id), report_profile)
        self._write_counts(manifest, counts)
        self._write_observations(manifest, observations)
        write_json(manifest_path, manifest)
        return manifest_path.parent

    def ensure_summary(
        self, *, run_id: str, metric_set_id: str, summary: EvaluationSummary
    ) -> Path:
        """Write the machine-readable rendering once, or confirm it matches.

        Compared on the content hash, which excludes ``generated_utc``: the same
        verified metric set summarised twice is the same summary, and a
        re-finalisation must be a no-op.
        """
        from fpbench.core.evaluation_models import evaluation_summary_content_hash

        path = self.summary_path(run_id, metric_set_id)
        if path.is_file():
            stored = self.read_summary(run_id, metric_set_id)
            if evaluation_summary_content_hash(
                stored
            ) != evaluation_summary_content_hash(summary):
                raise MetricSetConflictError(
                    f"{path} already carries a different evaluation summary"
                )
            return path
        return write_json(path, summary)

    def ensure_report(self, *, run_id: str, metric_set_id: str, markdown: str) -> Path:
        """Write the report once, byte-identically or not at all."""
        from fpbench.core.evaluation_models import report_content_hash

        path = self.report_path(run_id, metric_set_id)
        if path.is_file():
            stored = self.read_report(run_id, metric_set_id)
            if report_content_hash(stored) != report_content_hash(markdown):
                raise MetricSetConflictError(
                    f"{path} already carries a different evaluation report"
                )
            return path
        return write_text_atomically(path, markdown)

    def ensure_receipt(
        self, *, run_id: str, metric_set_id: str, receipt: EvaluationReceipt
    ) -> Path:
        """Write the sanitised receipt once, or confirm the stored one matches.

        Compared on the *semantic* fingerprint, which excludes ``created_utc``.
        The stronger content hash — timestamp included — is what the finalization
        marker binds, and it binds the bytes actually stored here.
        """
        path = self.receipt_path(run_id, metric_set_id)
        if path.is_file():
            stored = self.read_receipt(run_id, metric_set_id)
            if evaluation_receipt_fingerprint(
                stored
            ) != evaluation_receipt_fingerprint(receipt):
                raise MetricSetConflictError(
                    f"{path} already carries a different evaluation receipt"
                )
            return path
        return write_json(path, receipt)

    def ensure_finalization(
        self,
        *,
        run_id: str,
        metric_set_id: str,
        marker: EvaluationFinalizationMarker,
    ) -> Path:
        """Write the last file, the one that makes the rest authoritative."""
        path = self.finalization_path(run_id, metric_set_id)
        if path.is_file():
            stored = self.read_finalization(run_id, metric_set_id)
            if stored.finalization_fingerprint != marker.finalization_fingerprint:
                raise MetricSetConflictError(
                    f"{path} already finalises a different evaluation"
                )
            return path
        return write_json(path, marker)

    # ------------------------------------------------------------------- read

    def read_definition(
        self, run_id: str, metric_set_id: str
    ) -> MetricDerivationDefinition:
        path = self.definition_path(run_id, metric_set_id)
        payload = self._read_json(path, "metric derivation definition")
        try:
            return MetricDerivationDefinition(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable metric derivation definition ({exc})"
            ) from exc

    def read_policy(self, run_id: str, metric_set_id: str) -> MetricPolicy:
        path = self.policy_path(run_id, metric_set_id)
        payload = self._read_json(path, "metric policy")
        try:
            definitions = tuple(
                MetricDefinition(
                    metric_id=item["metric_id"],
                    metric_family=item["metric_family"],
                    numerator=MetricNumerator(item["numerator"]),
                    denominator=MetricDenominator(item["denominator"]),
                    source_view_kind=item["source_view_kind"],
                    source_protocol_stage=item["source_protocol_stage"],
                    interpretation=item["interpretation"],
                    prohibited_labels=tuple(item["prohibited_labels"]),
                )
                for item in payload["metric_definitions"]
            )
            return MetricPolicy(
                policy_id=payload["policy_id"],
                policy_fingerprint=payload["policy_fingerprint"],
                policy_version=payload["policy_version"],
                unit_of_analysis=payload["unit_of_analysis"],
                pooled_aggregation=payload["pooled_aggregation"],
                metric_definitions=definitions,
                percentage_decimal_places=payload["percentage_decimal_places"],
                always_show_fraction=payload["always_show_fraction"],
                zero_format=payload["zero_format"],
                metadata=payload["metadata"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable metric policy ({exc})") from exc

    def read_report_profile(self, run_id: str, metric_set_id: str) -> ReportProfile:
        path = self.report_profile_path(run_id, metric_set_id)
        payload = self._read_json(path, "report profile")
        try:
            return ReportProfile(
                report_profile_id=payload["report_profile_id"],
                report_profile_fingerprint=payload["report_profile_fingerprint"],
                percentage_decimal_places=payload["percentage_decimal_places"],
                always_show_fraction=payload["always_show_fraction"],
                include_pooled=payload["include_pooled"],
                release_order=tuple(payload["release_order"]),
                language=payload["language"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable report profile ({exc})") from exc

    def read_manifest(self, run_id: str, metric_set_id: str) -> MetricSetManifest:
        path = self.manifest_path(run_id, metric_set_id)
        payload = self._read_json(path, "metric-set manifest")
        try:
            return MetricSetManifest(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable metric-set manifest ({exc})"
            ) from exc

    def read_counts(
        self, run_id: str, metric_set_id: str
    ) -> tuple[EvaluationCountRecord, ...]:
        path = self.counts_path(run_id, metric_set_id)
        table = self._read_parquet(path, "evaluation counts")
        try:
            return tuple(metric_schemas.table_to_counts(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable count records ({exc})") from exc

    def read_observations(
        self, run_id: str, metric_set_id: str
    ) -> tuple[MetricObservation, ...]:
        path = self.observations_path(run_id, metric_set_id)
        table = self._read_parquet(path, "metric observations")
        try:
            return tuple(metric_schemas.table_to_observations(table))
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable metric observations ({exc})"
            ) from exc

    def read_summary(self, run_id: str, metric_set_id: str) -> EvaluationSummary:
        path = self.summary_path(run_id, metric_set_id)
        payload = self._read_json(path, "evaluation summary")
        try:
            return EvaluationSummary(
                metric_set_id=payload["metric_set_id"],
                algorithm_id=payload["algorithm_id"],
                implementation_version=payload["implementation_version"],
                execution_profile_id=payload["execution_profile_id"],
                decision_profile_id=payload["decision_profile_id"],
                threshold=payload["threshold"],
                releases=tuple(payload["releases"]),
                count_records=tuple(_rehydrate_counts(payload["count_records"])),
                observations=tuple(
                    _rehydrate_observations(payload["observations"])
                ),
                generated_utc=payload["generated_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable evaluation summary ({exc})"
            ) from exc

    def read_report(self, run_id: str, metric_set_id: str) -> str:
        path = self.report_path(run_id, metric_set_id)
        if not path.is_file():
            raise StorageError(f"evaluation report not found: {path}")
        return path.read_text(encoding="utf-8")

    def read_receipt(self, run_id: str, metric_set_id: str) -> EvaluationReceipt:
        path = self.receipt_path(run_id, metric_set_id)
        payload = self._read_json(path, "evaluation receipt")
        try:
            return EvaluationReceipt(
                schema_version=payload["schema_version"],
                run_id=payload["run_id"],
                result_set_id=payload["result_set_id"],
                decision_profile_id=payload["decision_profile_id"],
                decision_set_id=payload["decision_set_id"],
                eligibility_set_id=payload["eligibility_set_id"],
                metric_policy_id=payload["metric_policy_id"],
                metric_policy_fingerprint=payload["metric_policy_fingerprint"],
                metric_set_id=payload["metric_set_id"],
                metric_set_fingerprint=payload["metric_set_fingerprint"],
                metric_source_commit=payload["metric_source_commit"],
                metric_source_tree_clean=payload["metric_source_tree_clean"],
                releases=tuple(payload["releases"]),
                structural_counts=payload["structural_counts"],
                metrics=payload["metrics"],
                statement=payload["statement"],
                created_utc=payload["created_utc"],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable evaluation receipt ({exc})"
            ) from exc

    def read_finalization(
        self, run_id: str, metric_set_id: str
    ) -> EvaluationFinalizationMarker:
        path = self.finalization_path(run_id, metric_set_id)
        payload = self._read_json(path, "evaluation finalization marker")
        try:
            return EvaluationFinalizationMarker(**payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise StorageError(
                f"{path}: unreadable evaluation finalization marker ({exc})"
            ) from exc

    def read_metric_set(
        self, run_id: str, metric_set_id: str
    ) -> tuple[
        MetricDerivationDefinition,
        MetricPolicy,
        ReportProfile,
        MetricSetManifest,
        tuple[EvaluationCountRecord, ...],
        tuple[MetricObservation, ...],
    ]:
        """Read every part and confirm they describe one another."""
        definition = self.read_definition(run_id, metric_set_id)
        policy = self.read_policy(run_id, metric_set_id)
        report_profile = self.read_report_profile(run_id, metric_set_id)
        manifest = self.read_manifest(run_id, metric_set_id)
        counts = self.read_counts(run_id, metric_set_id)
        observations = self.read_observations(run_id, metric_set_id)
        self._require_coherent(
            definition=definition,
            policy=policy,
            report_profile=report_profile,
            manifest=manifest,
            counts=counts,
            observations=observations,
        )
        return definition, policy, report_profile, manifest, counts, observations

    def verify_metric_set(self, run_id: str, metric_set_id: str) -> MetricSetManifest:
        """Re-read everything and re-check what storage is able to check.

        Ordering, ordinals, ordered hashes, the manifest's own fingerprint, and
        agreement between the manifest, the policy and the definition. It does
        *not* re-derive the counts from the decisions — that needs the source
        chain, and it lives in :func:`fpbench.metrics.verify.verify_metric_set`.
        A metric set is not evidence of itself, and neither is this method.
        """
        _, _, _, manifest, _, _ = self.read_metric_set(run_id, metric_set_id)
        return manifest

    def record_metadata(self, run_id: str, metric_set_id: str) -> Mapping[str, str]:
        path = self.observations_path(run_id, metric_set_id)
        if not path.is_file():
            raise StorageError(f"metric observations not found: {path}")
        try:
            metadata = pq.read_schema(path).metadata or {}
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc
        return {key.decode(): value.decode() for key, value in metadata.items()}

    # --------------------------------------------------------------- internal

    def _read_json(self, path: Path, what: str):
        if not path.is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            return read_json(path)
        except (OSError, ValueError) as exc:
            raise StorageError(f"{path}: unreadable {what} ({exc})") from exc

    def _read_parquet(self, path: Path, what: str) -> pa.Table:
        if not path.is_file():
            raise StorageError(f"{what} not found: {path}")
        try:
            with pq.ParquetFile(path) as reader:
                return reader.read()
        except (pa.ArrowInvalid, OSError) as exc:
            raise StorageError(f"{path}: unreadable parquet ({exc})") from exc

    def _require_coherent(
        self,
        *,
        definition: MetricDerivationDefinition,
        policy: MetricPolicy,
        report_profile: ReportProfile,
        manifest: MetricSetManifest,
        counts: tuple[EvaluationCountRecord, ...],
        observations: tuple[MetricObservation, ...],
    ) -> None:
        """Structural agreement. Re-derivation lives in ``metrics.verify``."""
        if not counts:
            raise StorageError("a metric set with no count records is not one")
        if not observations:
            raise StorageError("a metric set with no observations is not one")
        if len(counts) != manifest.total_count_records:
            raise StorageError(
                f"metric set declares {manifest.total_count_records} count records "
                f"but carries {len(counts)}"
            )
        if len(observations) != manifest.total_observations:
            raise StorageError(
                f"metric set declares {manifest.total_observations} observations "
                f"but carries {len(observations)}"
            )

        if [record.ordinal for record in counts] != list(range(len(counts))):
            raise StorageError(
                "count ordinals must be 0..n-1 with no gaps and no repeats"
            )
        if [item.ordinal for item in observations] != list(range(len(observations))):
            raise StorageError(
                "observation ordinals must be 0..n-1 with no gaps and no repeats"
            )

        keys = [
            (record.count_family, record.scope.scope_kind.value, record.scope.release)
            for record in counts
        ]
        if len(set(keys)) != len(keys):
            raise StorageError("two count records cover the same family and scope")
        observation_keys = [
            (item.metric_id, item.scope.scope_kind.value, item.scope.release)
            for item in observations
        ]
        if len(set(observation_keys)) != len(observation_keys):
            raise StorageError("two observations cover the same metric and scope")

        releases = report_profile.release_order
        expected_counts = sorted(
            range(len(counts)),
            key=lambda index: (
                CountFamily.index(counts[index].count_family),
                scope_sort_key(counts[index].scope, releases),
            ),
        )
        if expected_counts != list(range(len(counts))):
            raise StorageError(
                "count records are not in canonical order (family, release, pooled)"
            )
        expected_observations = sorted(
            range(len(observations)),
            key=lambda index: (
                policy.definition_index(observations[index].metric_id),
                scope_sort_key(observations[index].scope, releases),
            ),
        )
        if expected_observations != list(range(len(observations))):
            raise StorageError(
                "observations are not in canonical order (metric, release, pooled)"
            )

        if ordered_count_records_hash(counts) != manifest.ordered_count_records_hash:
            raise StorageError(
                "the manifest's ordered count-records hash does not cover these rows"
            )
        if ordered_observations_hash(observations) != manifest.ordered_observations_hash:
            raise StorageError(
                "the manifest's ordered observations hash does not cover these rows"
            )

        if policy.policy_fingerprint != manifest.metric_policy_fingerprint:
            raise StorageError(
                "the stored policy is not the policy the manifest names"
            )
        if policy.policy_id != manifest.metric_policy_id:
            raise StorageError(
                "the stored policy id is not the one the manifest names"
            )
        if (
            report_profile.report_profile_fingerprint
            != manifest.report_profile_fingerprint
        ):
            raise StorageError(
                "the stored report profile is not the one the manifest names"
            )
        # The policy's display block is deliberately outside its fingerprint, so
        # that re-rendering at a different precision does not look like a new
        # measurement. That leaves those fields unbound by anything — unless the
        # report profile, which *is* fingerprinted, is required to agree with
        # them. It is: the two are read from one source and a divergence means
        # one of the files was edited (spec section 23).
        for label, policy_value, profile_value in (
            (
                "percentage_decimal_places",
                policy.percentage_decimal_places,
                report_profile.percentage_decimal_places,
            ),
            (
                "always_show_fraction",
                policy.always_show_fraction,
                report_profile.always_show_fraction,
            ),
        ):
            if policy_value != profile_value:
                raise StorageError(
                    f"the stored policy and report profile disagree about "
                    f"{label}: {policy_value!r} != {profile_value!r}"
                )
        for label, actual, expected in (
            ("metric policy", definition.metric_policy_fingerprint, policy.policy_fingerprint),
            (
                "report profile",
                definition.report_profile_fingerprint,
                report_profile.report_profile_fingerprint,
            ),
            (
                "decision set",
                definition.decision_set_fingerprint,
                manifest.decision_set_fingerprint,
            ),
            (
                "eligibility set",
                definition.eligibility_set_fingerprint,
                manifest.eligibility_set_fingerprint,
            ),
            (
                "metric software",
                definition.metric_software_fingerprint,
                manifest.metric_software_fingerprint,
            ),
            (
                "metric source commit",
                definition.metric_source_commit,
                manifest.metric_source_revision,
            ),
        ):
            if actual != expected:
                raise StorageError(
                    f"the stored definition names a different {label} than the "
                    f"manifest: {actual!r} != {expected!r}"
                )

        for observation in observations:
            if observation.metric_policy_fingerprint != policy.policy_fingerprint:
                raise StorageError(
                    f"observation {observation.metric_id} was computed under a "
                    "different policy than the one stored beside it"
                )
            policy.definition(observation.metric_id)

    def _write_counts(
        self, manifest: MetricSetManifest, counts: tuple[EvaluationCountRecord, ...]
    ) -> Path:
        table = metric_schemas.counts_to_table(counts)
        return self._write_parquet(
            self.counts_path(manifest.run_id, manifest.metric_set_id),
            table,
            manifest,
            extra={b"row_kind": b"evaluation_counts"},
            rows=len(counts),
        )

    def _write_observations(
        self, manifest: MetricSetManifest, observations: tuple[MetricObservation, ...]
    ) -> Path:
        table = metric_schemas.observations_to_table(observations)
        return self._write_parquet(
            self.observations_path(manifest.run_id, manifest.metric_set_id),
            table,
            manifest,
            extra={b"row_kind": b"metric_observations"},
            rows=len(observations),
        )

    def _write_parquet(
        self,
        path: Path,
        table: pa.Table,
        manifest: MetricSetManifest,
        *,
        extra: Mapping[bytes, bytes],
        rows: int,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)

        from fpbench import __version__

        stamped = table.replace_schema_metadata(
            {
                **(table.schema.metadata or {}),
                **dict(extra),
                b"schema_version": METRIC_SET_SCHEMA_VERSION.encode(),
                b"metric_set_id": manifest.metric_set_id.encode(),
                b"metric_set_fingerprint": manifest.metric_set_fingerprint.encode(),
                b"ordered_count_records_hash": (
                    manifest.ordered_count_records_hash.encode()
                ),
                b"ordered_observations_hash": (
                    manifest.ordered_observations_hash.encode()
                ),
                b"run_id": manifest.run_id.encode(),
                b"decision_set_id": manifest.decision_set_id.encode(),
                b"decision_set_fingerprint": manifest.decision_set_fingerprint.encode(),
                b"eligibility_set_fingerprint": (
                    manifest.eligibility_set_fingerprint.encode()
                ),
                b"metric_policy_id": manifest.metric_policy_id.encode(),
                b"metric_policy_fingerprint": (
                    manifest.metric_policy_fingerprint.encode()
                ),
                b"metric_source_revision": manifest.metric_source_revision.encode(),
                b"row_count": str(rows).encode(),
                b"fpbench_version": __version__.encode(),
                b"created_utc": _dt.datetime.now(_dt.timezone.utc)
                .isoformat(timespec="seconds")
                .encode(),
            }
        )

        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            pq.write_table(stamped, tmp, compression="zstd")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        return path


# --------------------------------------------------------- summary rehydration


def _rehydrate_counts(payload) -> list[EvaluationCountRecord]:
    from fpbench.core.enums import MetricScopeKind
    from fpbench.core.metric_models import MetricScope

    return [
        EvaluationCountRecord(
            ordinal=item["ordinal"],
            count_family=item["count_family"],
            scope=MetricScope(
                scope_kind=MetricScopeKind(item["scope"]["scope_kind"]),
                release=item["scope"]["release"],
            ),
            total_count=item["total_count"],
            counts=item["counts"],
            source_fingerprint=item["source_fingerprint"],
            count_record_hash=item["count_record_hash"],
        )
        for item in payload
    ]


def _rehydrate_observations(payload) -> list[MetricObservation]:
    from fpbench.core.enums import MetricObservationStatus, MetricScopeKind
    from fpbench.core.metric_models import MetricScope

    return [
        MetricObservation(
            ordinal=item["ordinal"],
            metric_id=item["metric_id"],
            scope=MetricScope(
                scope_kind=MetricScopeKind(item["scope"]["scope_kind"]),
                release=item["scope"]["release"],
            ),
            numerator_count=item["numerator_count"],
            denominator_count=item["denominator_count"],
            status=MetricObservationStatus(item["status"]),
            fraction_text=item["fraction_text"],
            source_decision_set_fingerprint=item["source_decision_set_fingerprint"],
            source_eligibility_set_fingerprint=item[
                "source_eligibility_set_fingerprint"
            ],
            source_view_fingerprint=item["source_view_fingerprint"],
            metric_policy_fingerprint=item["metric_policy_fingerprint"],
            observation_hash=item["observation_hash"],
        )
        for item in payload
    ]
