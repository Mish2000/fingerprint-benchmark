"""A decision-ready chain with every outcome chosen by hand.

The metric engine reads decisions, eligibility verdicts and view rows. Producing
those through the real 5A derivation would mean running a protocol, which is
slow, and would mean the *matcher* choosing the outcomes, which is useless: a
test of "eight matches out of nine decided attempts is 8/9" needs eight matches
and one non-match, exactly, and no scripted score can promise that as directly as
writing it down.

So this module builds the artefacts at the record level. Each unit is one
release, one subject, one finger, and the test states its four outcomes:

    UnitScript(plain=MATCH, roll=MATCH, mated=NON_MATCH, negative=NON_MATCH)

Everything downstream follows by the real rules — eligibility from
:func:`eligibility_status_of`, conditional inclusion from eligibility, view
membership from the decisions — so a world that violates the protocol's
invariants cannot be constructed. The models refuse it, which is the point of
testing against them rather than against dictionaries.

**No biometric claim is made or possible here.** Every outcome is a literal in a
test file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.core.decision_models import DecisionRecord, decision_record_hash
from fpbench.core.eligibility_models import (
    SelfEligibilityDecisionRecord,
    eligibility_record_hash,
    eligibility_status_of,
    eligibility_unit_id,
)
from fpbench.core.enums import (
    DecisionApplicationStatus,
    DecisionValue,
    ExecutionStatus,
    GroundTruth,
    ProtocolStage,
    SelfEligibilityStatus,
)
from fpbench.core.evaluation_view_models import (
    MATED_CONDITIONAL_VIEW,
    MATED_UNCONDITIONAL_VIEW,
    NON_MATED_SANITY_VIEW,
    EvaluationViewEntry,
    EvaluationViewManifest,
    ExclusionReason,
    evaluation_entry_hash,
    evaluation_view_fingerprint,
    evaluation_view_id,
    ordered_entries_hash,
)
from fpbench.core.evaluation_models import (
    MetricDerivationDefinition,
    metric_derivation_definition_fingerprint,
)
from fpbench.core.metric_models import (
    MetricSetManifest,
    metric_set_fingerprint,
    metric_set_id,
    ordered_count_records_hash,
    ordered_observations_hash,
)
from fpbench.core.models import ComparisonPair
from fpbench.core.provenance_models import software_provenance_fingerprint
from fpbench.metrics import (
    MetricSources,
    aggregate_count_records,
    build_observations,
    build_report_profile,
    load_metric_policy,
)
from fpbench.metrics.policy import DEFAULT_REPORT_PROFILE_ID
from runworld import research_provenance

__all__ = [
    "UnitScript",
    "MetricWorld",
    "build_metric_world",
    "all_matching",
    "rebuild_observation",
    "rebuild_count_record",
    "rewrite_observations",
    "rewrite_counts",
    "SPEC_EXAMPLE_SCRIPT",
    "REPOSITORY_ROOT",
    "DEFAULT_POLICY_PATH",
]

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = (
    REPOSITORY_ROOT / "configs" / "metrics" / "plain_roll_biometric_metrics_v1.yaml"
)

MATCH = DecisionValue.MATCH
NON_MATCH = DecisionValue.NON_MATCH
UNDECIDABLE = None


@dataclass(frozen=True, slots=True)
class UnitScript:
    """The four comparisons one release/subject/finger contributes.

    ``None`` means the comparison produced no score at all. It is not a third
    decision value; it is the absence of one, and the whole stage exists to keep
    the two apart (docs/adr/0006).
    """

    plain: DecisionValue | None = MATCH
    roll: DecisionValue | None = MATCH
    mated: DecisionValue | None = MATCH
    negative: DecisionValue | None = NON_MATCH


def all_matching(count: int) -> tuple[UnitScript, ...]:
    """``count`` units where everything behaves: SELF and mated match, impostors do not."""
    return tuple(UnitScript() for _ in range(count))


#: The worked example from the stage specification (section 79), whose exact
#: fractions are asserted by ``test_synthetic_exact_values``.
#:
#: Ten units, arranged so that every published fraction is a different number:
#: PLAIN 8/9 decided, ROLL 7/8, eligibility 6/10, unconditional FNMR 2/9,
#: conditional FNMR 1/6, sanity 1/9. A world where they coincided would let a
#: denominator bug pass unnoticed.
SPEC_EXAMPLE_SCRIPT: tuple[UnitScript, ...] = (
    # Units 0-4: eligible, mated match.
    UnitScript(plain=MATCH, roll=MATCH, mated=MATCH, negative=MATCH),
    UnitScript(plain=MATCH, roll=MATCH, mated=MATCH, negative=NON_MATCH),
    UnitScript(plain=MATCH, roll=MATCH, mated=MATCH, negative=NON_MATCH),
    UnitScript(plain=MATCH, roll=MATCH, mated=MATCH, negative=NON_MATCH),
    UnitScript(plain=MATCH, roll=MATCH, mated=MATCH, negative=NON_MATCH),
    # Unit 5: eligible, mated non-match — the one conditional failure.
    UnitScript(plain=MATCH, roll=MATCH, mated=NON_MATCH, negative=NON_MATCH),
    # Units 6-7: ROLL SELF non-match, so ineligible.
    UnitScript(plain=MATCH, roll=NON_MATCH, mated=MATCH, negative=NON_MATCH),
    UnitScript(plain=MATCH, roll=NON_MATCH, mated=MATCH, negative=NON_MATCH),
    # Unit 8: PLAIN SELF non-match and an undecidable ROLL — a non-match wins,
    # so this is ineligible rather than undetermined.
    UnitScript(plain=NON_MATCH, roll=UNDECIDABLE, mated=NON_MATCH, negative=NON_MATCH),
    # Unit 9: PLAIN SELF produced no score at all — undetermined, not ineligible.
    UnitScript(plain=UNDECIDABLE, roll=MATCH, mated=UNDECIDABLE, negative=UNDECIDABLE),
)


@dataclass
class MetricWorld:
    """A scripted decision-ready chain, plus everything derived from it."""

    sources: MetricSources
    releases: tuple[str, ...]
    scripts: Mapping[str, Sequence[UnitScript]]

    run_id: str = "run_scriptedworld"
    run_fingerprint: str = field(default="")
    result_set_id: str = "resultset_scripted"
    result_set_fingerprint: str = field(default="")
    decision_set_id: str = "decisionset_scripted"
    eligibility_set_id: str = "eligibilityset_scripted"
    decision_profile_id: str = "test_documented_profile_v1"
    threshold: str = "40"

    policy: Any = None
    report_profile: Any = None
    software: Any = None

    # ------------------------------------------------------------- derivation

    def counts(self):
        return aggregate_count_records(self.sources, releases=self.releases)

    def observations(self, counts=None):
        return build_observations(
            policy=self.policy,
            records=counts if counts is not None else self.counts(),
            releases=self.releases,
            decision_set_fingerprint=self.sources.decision_set_fingerprint,
            eligibility_set_fingerprint=self.sources.eligibility_set_fingerprint,
            view_fingerprints={
                kind: self.sources.view_fingerprint(kind)
                for kind in (
                    MATED_UNCONDITIONAL_VIEW,
                    MATED_CONDITIONAL_VIEW,
                    NON_MATED_SANITY_VIEW,
                )
            },
        )

    def definition(self) -> MetricDerivationDefinition:
        claims = {
            "run_id": self.run_id,
            "result_set_fingerprint": self.result_set_fingerprint,
            "decision_set_id": self.decision_set_id,
            "decision_set_fingerprint": self.sources.decision_set_fingerprint,
            "eligibility_set_id": self.eligibility_set_id,
            "eligibility_set_fingerprint": self.sources.eligibility_set_fingerprint,
            "unconditional_view_fingerprint": self.sources.view_fingerprint(
                MATED_UNCONDITIONAL_VIEW
            ),
            "conditional_view_fingerprint": self.sources.view_fingerprint(
                MATED_CONDITIONAL_VIEW
            ),
            "non_mated_view_fingerprint": self.sources.view_fingerprint(
                NON_MATED_SANITY_VIEW
            ),
            "metric_policy_id": self.policy.policy_id,
            "metric_policy_fingerprint": self.policy.policy_fingerprint,
            "report_profile_id": self.report_profile.report_profile_id,
            "report_profile_fingerprint": (
                self.report_profile.report_profile_fingerprint
            ),
            "metric_software": self.software,
            "metric_software_fingerprint": software_provenance_fingerprint(
                self.software
            ),
        }
        fingerprint = metric_derivation_definition_fingerprint(claims)
        return MetricDerivationDefinition(
            **claims,
            definition_id=f"metricderivation_{fingerprint[:12]}",
            definition_fingerprint=fingerprint,
            created_utc="2026-01-01T00:00:00+00:00",
        )

    def manifest(self, counts, observations) -> MetricSetManifest:
        counts_hash = ordered_count_records_hash(counts)
        observations_hash = ordered_observations_hash(observations)
        fingerprint = metric_set_fingerprint(
            run_fingerprint=self.run_fingerprint,
            decision_set_fingerprint=self.sources.decision_set_fingerprint,
            eligibility_set_fingerprint=self.sources.eligibility_set_fingerprint,
            unconditional_view_fingerprint=self.sources.view_fingerprint(
                MATED_UNCONDITIONAL_VIEW
            ),
            conditional_view_fingerprint=self.sources.view_fingerprint(
                MATED_CONDITIONAL_VIEW
            ),
            non_mated_view_fingerprint=self.sources.view_fingerprint(
                NON_MATED_SANITY_VIEW
            ),
            metric_policy_fingerprint=self.policy.policy_fingerprint,
            metric_software_fingerprint=software_provenance_fingerprint(self.software),
            ordered_count_records_hash=counts_hash,
            ordered_observations_hash=observations_hash,
        )
        return MetricSetManifest(
            metric_set_id=metric_set_id(fingerprint),
            metric_set_fingerprint=fingerprint,
            run_id=self.run_id,
            run_fingerprint=self.run_fingerprint,
            decision_set_id=self.decision_set_id,
            decision_set_fingerprint=self.sources.decision_set_fingerprint,
            eligibility_set_id=self.eligibility_set_id,
            eligibility_set_fingerprint=self.sources.eligibility_set_fingerprint,
            unconditional_view_fingerprint=self.sources.view_fingerprint(
                MATED_UNCONDITIONAL_VIEW
            ),
            conditional_view_fingerprint=self.sources.view_fingerprint(
                MATED_CONDITIONAL_VIEW
            ),
            non_mated_view_fingerprint=self.sources.view_fingerprint(
                NON_MATED_SANITY_VIEW
            ),
            metric_policy_id=self.policy.policy_id,
            metric_policy_fingerprint=self.policy.policy_fingerprint,
            report_profile_fingerprint=(
                self.report_profile.report_profile_fingerprint
            ),
            metric_software_fingerprint=software_provenance_fingerprint(self.software),
            metric_source_revision=self.software.source_revision,
            total_count_records=len(counts),
            total_observations=len(observations),
            ordered_count_records_hash=counts_hash,
            ordered_observations_hash=observations_hash,
            created_utc="2026-01-01T00:00:00+00:00",
        )

    def metric_set(self):
        """``(definition, policy, profile, manifest, counts, observations)``."""
        counts = self.counts()
        observations = self.observations(counts)
        return (
            self.definition(),
            self.policy,
            self.report_profile,
            self.manifest(counts, observations),
            counts,
            observations,
        )

    def store_metric_set(self, workspace: Path):
        """Write the whole set through the real store and return its parts."""
        from fpbench.storage.metric_set_store import MetricSetStore

        definition, policy, profile, manifest, counts, observations = (
            self.metric_set()
        )
        MetricSetStore(Path(workspace)).ensure_metric_set(
            definition=definition,
            policy=policy,
            report_profile=profile,
            manifest=manifest,
            counts=counts,
            observations=observations,
        )
        return definition, policy, profile, manifest, counts, observations

    # -------------------------------------------------------------- finalize

    def structural_counts(self) -> Mapping[str, int]:
        from fpbench.metrics import structural_counts_of

        return structural_counts_of(
            total_decisions=len(self.sources.decisions),
            total_eligibility_units=len(self.sources.eligibility_records),
            unconditional_rows=len(self.sources.entries(MATED_UNCONDITIONAL_VIEW)),
            conditional_rows=len(self.sources.entries(MATED_CONDITIONAL_VIEW)),
            negative_sanity_rows=len(self.sources.entries(NON_MATED_SANITY_VIEW)),
        )

    def report_context(self, manifest):
        from fpbench.metrics import ReportContext
        from fpbench.metrics.aggregate import NEGATIVE_SANITY_METADATA

        return ReportContext(
            algorithm_id="scripted_matcher",
            implementation_version="test-1",
            adapter_id="scripted_matcher",
            integration_mode="in_process",
            execution_profile_id="test_profile_v1",
            resolution_mode="native",
            decision_profile_id=self.decision_profile_id,
            threshold=self.threshold,
            comparator="greater_than_or_equal",
            threshold_origin="documented_native",
            run_id=self.run_id,
            result_set_id=self.result_set_id,
            decision_set_id=manifest.decision_set_id,
            eligibility_set_id=manifest.eligibility_set_id,
            metric_set_id=manifest.metric_set_id,
            run_source_commit=self.software.source_revision,
            decision_derivation_source_commit=self.software.source_revision,
            metric_derivation_source_commit=manifest.metric_source_revision,
            negative_sanity_metadata=NEGATIVE_SANITY_METADATA,
        )

    def render(self, manifest, counts, observations) -> str:
        from fpbench.metrics import render_report

        return render_report(
            context=self.report_context(manifest),
            manifest=manifest,
            policy=self.policy,
            report_profile=self.report_profile,
            counts=counts,
            observations=observations,
        )

    def finalize(self, workspace: Path, *, marker: bool = True) -> str:
        """Write the whole chain through the real builders and stores.

        Mirrors what ``finalize_evaluation`` does, without its clean-tree
        requirement — a test cannot commit, and the provenance gate is exercised
        by the real experiment instead.

        Returns:
            The metric set id.
        """
        from fpbench.metrics import (
            build_evaluation_finalization_marker,
            build_evaluation_receipt,
            build_evaluation_summary,
        )
        from fpbench.storage.metric_set_store import MetricSetStore

        definition, policy, profile, manifest, counts, observations = (
            self.store_metric_set(workspace)
        )
        store = MetricSetStore(Path(workspace))
        set_id = manifest.metric_set_id

        summary = build_evaluation_summary(
            manifest=manifest,
            run=_FakeRun(self),
            decision_profile=_FakeProfile(self),
            releases=self.releases,
            counts=counts,
            observations=observations,
            generated_utc="2026-01-01T00:00:00+00:00",
        )
        store.ensure_summary(
            run_id=self.run_id, metric_set_id=set_id, summary=summary
        )

        markdown = self.render(manifest, counts, observations)
        store.ensure_report(
            run_id=self.run_id, metric_set_id=set_id, markdown=markdown
        )

        receipt = build_evaluation_receipt(
            manifest=manifest,
            definition=definition,
            policy=policy,
            observations=observations,
            releases=self.releases,
            structural_counts=self.structural_counts(),
            run_id=self.run_id,
            result_set_id=self.result_set_id,
            decision_profile_id=self.decision_profile_id,
            metric_software=self.software,
            created_utc="2026-01-01T00:00:00+00:00",
        )
        store.ensure_receipt(
            run_id=self.run_id, metric_set_id=set_id, receipt=receipt
        )

        if marker:
            stored_marker = build_evaluation_finalization_marker(
                definition=definition,
                manifest=manifest,
                summary=store.read_summary(self.run_id, set_id),
                markdown=store.read_report(self.run_id, set_id),
                receipt=store.read_receipt(self.run_id, set_id),
                decision_finalization_fingerprint=self.decision_finalization,
                metric_software=self.software,
                created_utc="2026-01-01T00:00:00+00:00",
            )
            store.ensure_finalization(
                run_id=self.run_id, metric_set_id=set_id, marker=stored_marker
            )
        return set_id

    @property
    def decision_finalization(self) -> str:
        """Stand-in for the stage 5A marker this evaluation rests on."""
        return _digest("decision-finalization", self.sources.decision_set_fingerprint)

    def inspect(self, workspace: Path, metric_set_id: str | None, **overrides):
        """Run the real status inspector over a scripted world."""
        from fpbench.core.enums import DecisionDerivationStatus
        from fpbench.metrics import inspect_evaluation

        arguments = {
            "run_id": self.run_id,
            "sources": self.sources,
            "decision_status": DecisionDerivationStatus.DECISION_READY,
            "decision_finalization_fingerprint": self.decision_finalization,
            "definition": self.definition(),
            "metric_set_id": metric_set_id,
            "releases": self.releases,
            "structural_counts": self.structural_counts(),
            "result_set_id": self.result_set_id,
            "decision_profile_id": self.decision_profile_id,
            "workspace": Path(workspace),
        }
        arguments.update(overrides)
        return inspect_evaluation(**arguments)

    # ---------------------------------------------------------------- helpers

    def observation(self, observations, metric_id: str, scope_label: str):
        for observation in observations:
            if (
                observation.metric_id == metric_id
                and observation.scope.label == scope_label
            ):
                return observation
        raise AssertionError(f"no observation for {metric_id} at {scope_label}")

    def count_record(self, counts, family: str, scope_label: str):
        for record in counts:
            if record.count_family == family and record.scope.label == scope_label:
                return record
        raise AssertionError(f"no count record for {family} at {scope_label}")


# ------------------------------------------------------------------- builder


def build_metric_world(
    scripts: Mapping[str, Sequence[UnitScript]],
    *,
    policy_path: Path = DEFAULT_POLICY_PATH,
    report_profile_id: str = DEFAULT_REPORT_PROFILE_ID,
    release_order: Sequence[str] | None = None,
) -> MetricWorld:
    """Build a complete, self-consistent chain from per-release unit scripts."""
    releases = tuple(release_order or sorted(scripts))
    software = research_provenance()

    decisions: list[DecisionRecord] = []
    eligibility: list[SelfEligibilityDecisionRecord] = []
    pairs: dict[str, ComparisonPair] = {}

    result_set_fingerprint = _digest("result-set", *releases)
    profile_fingerprint = _digest("decision-profile")
    run_fingerprint = _digest("run", *releases)

    view_rows: dict[str, list[dict]] = {
        MATED_UNCONDITIONAL_VIEW: [],
        MATED_CONDITIONAL_VIEW: [],
        NON_MATED_SANITY_VIEW: [],
    }

    ordinal = 0
    unit_ordinal = 0
    for release in releases:
        for index, script in enumerate(scripts[release]):
            subject = f"{index:08d}"
            finger = (index % 10) + 1
            stem = f"{release.lower()}_{index:04d}"

            per_stage: dict[ProtocolStage, DecisionRecord] = {}
            for stage, verdict, truth in (
                (ProtocolStage.PLAIN_SELF, script.plain, GroundTruth.MATED),
                (ProtocolStage.ROLL_SELF, script.roll, GroundTruth.MATED),
                (ProtocolStage.PLAIN_ROLL_MATED, script.mated, GroundTruth.MATED),
                (
                    ProtocolStage.PLAIN_ROLL_NON_MATED,
                    script.negative,
                    GroundTruth.NON_MATED,
                ),
            ):
                pair_id = f"pair_{stem}_{stage.value}"
                job_id = f"job_{stem}_{stage.value}"
                pairs[pair_id] = ComparisonPair(
                    pair_id=pair_id,
                    dataset_id="sd300",
                    release=release,
                    left_image_id=f"img_{stem}_a",
                    right_image_id=f"img_{stem}_b",
                    ground_truth=truth,
                    protocol_stage=stage,
                )
                record = _decision(
                    ordinal=ordinal,
                    job_id=job_id,
                    pair_id=pair_id,
                    verdict=verdict,
                    result_set_fingerprint=result_set_fingerprint,
                    profile_fingerprint=profile_fingerprint,
                )
                decisions.append(record)
                per_stage[stage] = record
                ordinal += 1

            plain = per_stage[ProtocolStage.PLAIN_SELF]
            roll = per_stage[ProtocolStage.ROLL_SELF]
            mated = per_stage[ProtocolStage.PLAIN_ROLL_MATED]
            negative = per_stage[ProtocolStage.PLAIN_ROLL_NON_MATED]

            status, reasons = eligibility_status_of(
                plain=plain.decision, roll=roll.decision
            )
            unit = _eligibility(
                ordinal=unit_ordinal,
                release=release,
                subject=subject,
                finger=finger,
                plain=plain,
                roll=roll,
                mated=mated,
                status=status,
                reasons=reasons,
            )
            eligibility.append(unit)
            unit_ordinal += 1

            view_rows[MATED_UNCONDITIONAL_VIEW].append(
                {"decision": mated, "unit": None}
            )
            view_rows[MATED_CONDITIONAL_VIEW].append(
                {"decision": mated, "unit": unit}
            )
            view_rows[NON_MATED_SANITY_VIEW].append(
                {"decision": negative, "unit": None}
            )

    decision_set_fingerprint = _digest(
        "decision-set", *(record.decision_record_hash for record in decisions)
    )
    eligibility_set_fingerprint = _digest(
        "eligibility-set", *(unit.eligibility_record_hash for unit in eligibility)
    )

    view_manifests = {}
    view_entries = {}
    for kind, rows in view_rows.items():
        entries = _view_entries(kind, rows)
        manifest = _view_manifest(
            kind=kind,
            entries=entries,
            run_fingerprint=run_fingerprint,
            result_set_fingerprint=result_set_fingerprint,
            decision_set_fingerprint=decision_set_fingerprint,
            eligibility_set_fingerprint=(
                eligibility_set_fingerprint
                if kind == MATED_CONDITIONAL_VIEW
                else None
            ),
        )
        view_manifests[kind] = manifest
        view_entries[kind] = entries

    sources = MetricSources(
        decisions=tuple(decisions),
        decision_set_fingerprint=decision_set_fingerprint,
        eligibility_records=tuple(eligibility),
        eligibility_set_fingerprint=eligibility_set_fingerprint,
        view_manifests=view_manifests,
        view_entries=view_entries,
        pairs=pairs,
    )

    return MetricWorld(
        sources=sources,
        releases=releases,
        scripts=scripts,
        run_fingerprint=run_fingerprint,
        result_set_fingerprint=result_set_fingerprint,
        policy=load_metric_policy(policy_path),
        report_profile=build_report_profile(
            profile_id=report_profile_id, release_order=releases
        ),
        software=software,
    )


# ----------------------------------------------------------------- internals


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _decision(
    *,
    ordinal: int,
    job_id: str,
    pair_id: str,
    verdict: DecisionValue | None,
    result_set_fingerprint: str,
    profile_fingerprint: str,
) -> DecisionRecord:
    undecidable = verdict is None
    fields = {
        "ordinal": ordinal,
        "job_id": job_id,
        "job_fingerprint": _digest("job", job_id),
        "pair_id": pair_id,
        "source_result_hash": _digest("result", job_id),
        "result_set_id": "resultset_scripted",
        "result_set_fingerprint": result_set_fingerprint,
        "decision_profile_id": "test_documented_profile_v1",
        "decision_profile_fingerprint": profile_fingerprint,
        "application_status": (
            DecisionApplicationStatus.UNDECIDABLE
            if undecidable
            else DecisionApplicationStatus.DECIDED
        ),
        "decision": verdict,
        "source_execution_status": (
            ExecutionStatus.FAILURE if undecidable else ExecutionStatus.SUCCESS
        ),
        "source_failure_code": "template_extraction_failed" if undecidable else None,
    }
    probe = _Probe(fields)
    return DecisionRecord(decision_record_hash=decision_record_hash(probe), **fields)


def _eligibility(
    *,
    ordinal: int,
    release: str,
    subject: str,
    finger: int,
    plain: DecisionRecord,
    roll: DecisionRecord,
    mated: DecisionRecord,
    status: SelfEligibilityStatus,
    reasons: tuple,
) -> SelfEligibilityDecisionRecord:
    fields = {
        "ordinal": ordinal,
        "eligibility_unit_id": eligibility_unit_id(
            protocol_id="scripted_protocol",
            cohort_id="scripted_cohort",
            release=release,
            subject_id=subject,
            canonical_finger=finger,
        ),
        "release": release,
        "canonical_finger": finger,
        "plain_self_pair_id": plain.pair_id,
        "plain_self_job_id": plain.job_id,
        "plain_self_decision_hash": plain.decision_record_hash,
        "plain_self_decision": plain.decision,
        "roll_self_pair_id": roll.pair_id,
        "roll_self_job_id": roll.job_id,
        "roll_self_decision_hash": roll.decision_record_hash,
        "roll_self_decision": roll.decision,
        "mated_pair_id": mated.pair_id,
        "mated_job_id": mated.job_id,
        "status": status,
        "reasons": reasons,
    }
    probe = _Probe(fields)
    return SelfEligibilityDecisionRecord(
        eligibility_record_hash=eligibility_record_hash(probe), **fields
    )


def _view_entries(kind: str, rows: Sequence[Mapping[str, Any]]) -> tuple:
    entries = []
    for ordinal, row in enumerate(rows):
        decision: DecisionRecord = row["decision"]
        unit: SelfEligibilityDecisionRecord | None = row["unit"]

        included = True
        exclusion = None
        unit_id = None
        unit_hash = None
        unit_status = None
        if kind == MATED_CONDITIONAL_VIEW and unit is not None:
            unit_id = unit.eligibility_unit_id
            unit_hash = unit.eligibility_record_hash
            unit_status = unit.status
            if unit.status is SelfEligibilityStatus.INELIGIBLE:
                included = False
                exclusion = ExclusionReason.SELF_INELIGIBLE
            elif unit.status is SelfEligibilityStatus.UNDETERMINED:
                included = False
                exclusion = ExclusionReason.SELF_UNDETERMINED

        fields = {
            "ordinal": ordinal,
            "pair_id": decision.pair_id,
            "job_id": decision.job_id,
            "source_result_hash": decision.source_result_hash,
            "decision_record_hash": decision.decision_record_hash,
            "decision_status": decision.application_status,
            "decision": decision.decision,
            "eligibility_unit_id": unit_id,
            "eligibility_record_hash": unit_hash,
            "eligibility_status": unit_status,
            "included": included,
            "exclusion_reason": exclusion,
        }
        probe = _Probe(fields)
        entries.append(
            EvaluationViewEntry(
                evaluation_entry_hash=evaluation_entry_hash(probe), **fields
            )
        )
    return tuple(entries)


def _view_manifest(
    *,
    kind: str,
    entries: tuple,
    run_fingerprint: str,
    result_set_fingerprint: str,
    decision_set_fingerprint: str,
    eligibility_set_fingerprint: str | None,
) -> EvaluationViewManifest:
    from fpbench.evaluation.views import POLICY_FOR_VIEW, POLICY_VERSION, expected_policy_metadata

    policy_id = POLICY_FOR_VIEW[kind]
    metadata = expected_policy_metadata(kind, finger_shift=1)
    fingerprint = evaluation_view_fingerprint(
        view_kind=kind,
        policy_id=policy_id,
        policy_version=POLICY_VERSION,
        run_fingerprint=run_fingerprint,
        result_set_fingerprint=result_set_fingerprint,
        decision_set_fingerprint=decision_set_fingerprint,
        eligibility_set_fingerprint=eligibility_set_fingerprint,
        pair_manifest_hash=_digest("pair-manifest"),
        policy_metadata=metadata,
        entries=entries,
    )
    return EvaluationViewManifest(
        view_id=evaluation_view_id(kind, fingerprint),
        view_fingerprint=fingerprint,
        view_kind=kind,
        policy_id=policy_id,
        policy_version=POLICY_VERSION,
        run_fingerprint=run_fingerprint,
        result_set_fingerprint=result_set_fingerprint,
        decision_set_fingerprint=decision_set_fingerprint,
        eligibility_set_fingerprint=eligibility_set_fingerprint,
        pair_manifest_hash=_digest("pair-manifest"),
        total_rows=len(entries),
        ordered_entries_hash=ordered_entries_hash(entries),
        policy_metadata=metadata,
        created_utc="2026-01-01T00:00:00+00:00",
    )


def rebuild_observation(observation, **overrides):
    """A tampered observation that still hashes to its own (new) contents.

    Needed by the tampering suite: an edit that broke the record's self-hash
    would be caught by the model on read, which proves only that the model
    works. The interesting question is whether an edit that is internally
    *consistent* survives re-derivation, and to ask it the forgery has to be a
    good one.
    """
    from fpbench.core.metric_models import (
        MetricObservation,
        fraction_text,
        metric_observation_hash,
    )

    fields = {
        "ordinal": observation.ordinal,
        "metric_id": observation.metric_id,
        "scope": observation.scope,
        "numerator_count": observation.numerator_count,
        "denominator_count": observation.denominator_count,
        "status": observation.status,
        "source_decision_set_fingerprint": (
            observation.source_decision_set_fingerprint
        ),
        "source_eligibility_set_fingerprint": (
            observation.source_eligibility_set_fingerprint
        ),
        "source_view_fingerprint": observation.source_view_fingerprint,
        "metric_policy_fingerprint": observation.metric_policy_fingerprint,
    }
    fields.update(overrides)
    fields["fraction_text"] = fraction_text(
        fields["numerator_count"], fields["denominator_count"]
    )
    probe = _Probe(fields)
    return MetricObservation(
        observation_hash=metric_observation_hash(probe), **fields
    )


def rebuild_count_record(record, **overrides):
    """A tampered count record that still hashes to its own (new) contents."""
    from fpbench.core.metric_models import EvaluationCountRecord, count_record_hash

    fields = {
        "ordinal": record.ordinal,
        "count_family": record.count_family,
        "scope": record.scope,
        "total_count": record.total_count,
        "counts": dict(record.counts),
        "source_fingerprint": record.source_fingerprint,
    }
    fields.update(overrides)
    probe = _Probe(fields)
    return EvaluationCountRecord(
        count_record_hash=count_record_hash(probe), **fields
    )


def rewrite_observations(store, run_id: str, metric_set_id: str, observations) -> None:
    """Overwrite the stored observations, bypassing the store's guards."""
    import pyarrow.parquet as pq

    from fpbench.storage import metric_schemas

    pq.write_table(
        metric_schemas.observations_to_table(observations),
        store.observations_path(run_id, metric_set_id),
    )


def rewrite_counts(store, run_id: str, metric_set_id: str, counts) -> None:
    """Overwrite the stored count records, bypassing the store's guards."""
    import pyarrow.parquet as pq

    from fpbench.storage import metric_schemas

    pq.write_table(
        metric_schemas.counts_to_table(counts),
        store.counts_path(run_id, metric_set_id),
    )


class _Probe:
    """Attribute access over a field dict, for the ``*_hash`` helpers."""

    def __init__(self, fields: Mapping[str, Any]) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


class _FakeRun:
    """The four run fields the summary builder reads, and nothing else."""

    def __init__(self, world: MetricWorld) -> None:
        self.run_id = world.run_id
        self.algorithm = _Probe(
            {"algorithm_id": "scripted_matcher", "implementation_version": "test-1"}
        )
        self.execution_profile = _Probe({"profile_id": "test_profile_v1"})


class _FakeProfile:
    """The two decision-profile fields the summary builder reads."""

    def __init__(self, world: MetricWorld) -> None:
        self.profile_id = world.decision_profile_id
        self.threshold = world.threshold
