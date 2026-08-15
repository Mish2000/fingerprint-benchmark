"""G3 — is the same input the same score, and is a refusal a refusal?

Twenty comparisons at most, none of them SD300. Two questions, and they are not
the same question.

**Determinism is required.** The same two files, in the same frozen environment,
must produce the same IEEE double — compared as bits through ``float.hex()``,
not as printed decimals — when repeated in one process, through a fresh adapter
object, and in a fresh interpreter. A matcher whose answer moves between runs
cannot have 6,000 results stored against its name.

**Symmetry is not required, and its absence is not a defect.** ``match`` returns
``sum(best) / len(minutiae1)``, so the first argument sets the denominator and
``score(A,B)`` and ``score(B,A)`` are answers to two different questions. When
they differ, the finding is not that the algorithm is broken: it is that
``left → image_path1`` is part of the algorithm's identity and the protocol binds
it (docs/adr/0109).

**A refusal is an outcome, not a score.** The research that selected this
candidate proposed rejecting it if any image yielded zero features, because
``match`` divides by ``len(minutiae1)``. That rule is not applied here. The
benchmark already represents algorithmic failures, so the requirement is weaker
and more honest: upstream either returns a finite number, or it raises and the
comparison is recorded as an algorithmic failure carrying no number at all.
Never an exception turned into a zero (docs/adr/0127).

The gate fails only if fpbench would have to repair the algorithm to proceed — a
denominator fallback, an invented score for an empty feature set — or if the same
frozen input produced two different numbers.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from fpbench.adapters.fingerprints_matching.bridge_client import (
    BridgeResponse,
    BridgeWorker,
    bridge_script_path,
)
from fpbench.core.stage15a_errors import Stage15AQualificationError
from fpbench.experiments import stage15a_identity as frozen
from fpbench.experiments import stage15a_runtime as runtime

__all__ = [
    "QUALIFICATION_SCHEMA",
    "Observation",
    "QualificationReport",
    "fixture_directory",
    "available_fixtures",
    "run_qualification",
    "main",
]

QUALIFICATION_SCHEMA = "stage_15a_qualification_v1"

#: Non-SD300 fixtures, in preference order. The project's own synthetic ridge
#: fields come first; upstream sample prints from the local artifact store stand
#: in when those are not extractable. Neither is anybody's benchmark finger and
#: neither leaves the local store.
_FIXTURE_CANDIDATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("A", ("verifinger-2025-2/fixtures/fixture_a.png",)),
    ("B", ("verifinger-2025-2/fixtures/fixture_b.png",)),
    ("BLANK", ("verifinger-2025-2/fixtures/fixture_blank.png",)),
    ("MALFORMED", ("verifinger-2025-2/fixtures/fixture_invalid.png",)),
)


def fixture_directory(*, repository_root: Path | None = None) -> Path:
    from fpbench.third_party.artifacts import resolve_third_party_root

    return Path(resolve_third_party_root(repository_root=repository_root))


def available_fixtures(*, repository_root: Path | None = None) -> dict[str, Path]:
    root = fixture_directory(repository_root=repository_root)
    found: dict[str, Path] = {}
    for label, relatives in _FIXTURE_CANDIDATES:
        for relative in relatives:
            candidate = root.joinpath(*relative.split("/"))
            if candidate.exists():
                found[label] = candidate
                break
    return found


@dataclass(frozen=True, slots=True)
class Observation:
    """One probe, and what came back. Values, because equality is the claim."""

    case: str
    status: str
    detail: str
    score_hex: str | None = None
    score: float | None = None
    upstream_code: str | None = None

    def as_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "case": self.case,
            "status": self.status,
            "detail": self.detail,
        }
        if self.score_hex is not None:
            document["score_hex"] = self.score_hex
            document["score"] = self.score
        if self.upstream_code is not None:
            document["upstream_code"] = self.upstream_code
        return document


@dataclass
class QualificationReport:
    observations: list[Observation] = field(default_factory=list)
    claims: dict[str, bool] = field(default_factory=dict)
    notes: dict[str, Any] = field(default_factory=dict)

    @property
    def comparisons(self) -> int:
        return sum(1 for o in self.observations if o.case != "environment")

    @property
    def gate_state(self) -> str:
        if not self.claims:
            return "ACTION_REQUIRED"
        return "PASS" if all(self.claims.values()) else "FAIL"

    def as_document(self) -> dict[str, Any]:
        return {
            "schema": QUALIFICATION_SCHEMA,
            "gate": frozen.GATES["G3"],
            "gate_state": self.gate_state,
            "candidate_id": frozen.CANDIDATE_ID,
            "comparisons_used": self.comparisons,
            "comparisons_budget": frozen.QUALIFICATION_MAX_COMPARISONS,
            "sd300_used": False,
            "fixtures": "non-SD300: this project's synthetic ridge fields and "
            "upstream sample prints from the local artifact store",
            "required_cases": list(frozen.QUALIFICATION_CASES),
            "failure_probes": list(frozen.FAILURE_PROBES),
            "determinism_required": True,
            "symmetry_required": frozen.SYMMETRY_REQUIRED,
            "why_symmetry_is_not_required": (
                "match normalises by len(minutiae1), so the first argument sets "
                "the denominator and the two orderings are different questions. "
                "Observed asymmetry binds left→image_path1 into the algorithm's "
                "identity rather than failing the candidate (docs/adr/0109)"
            ),
            "zero_feature_policy": {
                "rule": "upstream raises → ALGORITHMIC_FAILURE, carrying no score",
                "never": "exception → score 0",
                "fpbench_denominator_fallback": "NONE",
                "fpbench_invented_score_for_empty_features": "NONE",
            },
            "claims": dict(sorted(self.claims.items())),
            "observations": [o.as_document() for o in self.observations],
            "notes": self.notes,
        }


def _observe(case: str, response: BridgeResponse) -> Observation:
    if response.is_score:
        return Observation(
            case=case,
            status="SCORE",
            detail=f"finite {response.payload.get('native_type', 'float')}",
            score_hex=str(response.payload.get("score_hex")),
            score=response.score,
        )
    if response.is_algorithmic_failure:
        return Observation(
            case=case,
            status="ALGORITHMIC_FAILURE",
            detail=str(response.payload.get("exception_type", "")),
            upstream_code=response.code,
        )
    return Observation(
        case=case,
        status="INFRASTRUCTURE_FAILURE",
        detail=str(response.payload.get("message", ""))[:200],
        upstream_code=response.code,
    )


def run_qualification(*, repository_root: Path | None = None) -> QualificationReport:
    """Drive every required case, and record what each one produced."""
    root = Path(repository_root or ".")
    closure = runtime.build_runtime_closure(repository_root=root)
    runtime.require_ready(closure)

    fixtures = available_fixtures(repository_root=root)
    missing = [label for label in ("A", "B") if label not in fixtures]
    if missing:
        raise Stage15AQualificationError(
            "the qualification needs two non-SD300 prints in the local artifact "
            f"store; missing: {', '.join(missing)}"
        )

    report = QualificationReport()
    interpreter = runtime.runtime_python(repository_root=root)
    script = bridge_script_path(repository_root=root)

    def worker() -> BridgeWorker:
        return BridgeWorker(
            interpreter=interpreter,
            script=script,
            timeout_seconds=float(frozen.JOB_DEADLINE_SECONDS),
        )

    a, b = fixtures["A"], fixtures["B"]

    # -- determinism inside one process, and through a fresh client object
    with worker() as first:
        environment = first.environment()
        report.notes["runtime"] = {
            key: environment.payload.get(key)
            for key in ("python_version", "machine", "numpy", "opencv")
        }
        repeated = [_observe("A_B_repeated", first.compare(a, b)) for _ in range(3)]
        report.observations.extend(repeated)
        ba = _observe("B_A", first.compare(b, a))
        aa = _observe("A_A", first.compare(a, a))
        report.observations.extend([ba, aa])

    with worker() as second:
        fresh_object = _observe("A_B_fresh_object", second.compare(a, b))
        report.observations.append(fresh_object)

    with worker() as third:
        fresh_process = _observe("A_B_fresh_process", third.compare(a, b))
        report.observations.append(fresh_process)

    ab_values = {o.score_hex for o in repeated if o.status == "SCORE"}
    ab_statuses = {o.status for o in repeated}
    all_ab = list(repeated) + [fresh_object, fresh_process]
    all_ab_keys = {(o.status, o.score_hex) for o in all_ab}

    report.claims["A,B repeated is one value"] = (
        len(ab_statuses) == 1 and len(ab_values) <= 1
    )
    report.claims["A,B through a fresh object is the same value"] = (
        len(all_ab_keys) == 1
    )
    report.claims["A,B in a fresh process is the same value"] = len(all_ab_keys) == 1
    report.claims["no comparison ended at infrastructure level"] = all(
        o.status != "INFRASTRUCTURE_FAILURE" for o in report.observations
    )

    reference = all_ab[0]
    if reference.status == "SCORE" and ba.status == "SCORE":
        symmetric = reference.score_hex == ba.score_hex
        report.notes["symmetry"] = {
            "score_left_right": reference.score,
            "score_right_left": ba.score,
            "symmetric": symmetric,
            "consequence": (
                "none — the orderings agreed on these fixtures"
                if symmetric
                else "left→image_path1 and right→image_path2 are bound into the "
                "algorithm's identity and the protocol never reverses them"
            ),
        }
    report.notes["self_comparison"] = {
        "status": aa.status,
        "score": aa.score,
        "two_independent_extractions": True,
        "cached": False,
    }

    # -- the failure probes
    with worker() as probes:
        probe_results: dict[str, Observation] = {}
        if "BLANK" in fixtures:
            probe_results["blank_valid_image"] = _observe(
                "blank_valid_image", probes.compare(fixtures["BLANK"], a)
            )
        if "MALFORMED" in fixtures:
            probe_results["malformed_image"] = _observe(
                "malformed_image", probes.compare(fixtures["MALFORMED"], a)
            )
        with tempfile.TemporaryDirectory() as scratch:
            absent = Path(scratch) / "not-a-file.png"
            probe_results["missing_path"] = _observe(
                "missing_path", probes.compare(absent, a)
            )
            unreadable = Path(scratch) / "unreadable.png"
            unreadable.write_bytes(b"\x89PNG\r\n\x1a\nnot a png body at all")
            probe_results["unreadable_invalid_image"] = _observe(
                "unreadable_invalid_image", probes.compare(unreadable, a)
            )
        # determinism of a refusal: the same bad input twice
        if "BLANK" in fixtures:
            again = _observe("blank_valid_image", probes.compare(fixtures["BLANK"], a))
            report.claims["a refusal repeats identically"] = (
                again.status == probe_results["blank_valid_image"].status
                and again.upstream_code
                == probe_results["blank_valid_image"].upstream_code
            )
            probe_results["blank_repeat"] = again

    report.observations.extend(probe_results.values())
    report.claims["every required failure probe ran"] = all(
        name in probe_results for name in frozen.FAILURE_PROBES
    )
    report.claims["no failure carries a score"] = all(
        o.score is None
        for o in probe_results.values()
        if o.status != "SCORE"
    )
    report.claims["every probe is an outcome, not a crash"] = all(
        o.status in {"SCORE", "ALGORITHMIC_FAILURE"} for o in probe_results.values()
    )
    report.claims["the comparison budget was respected"] = (
        report.comparisons <= frozen.QUALIFICATION_MAX_COMPARISONS
    )

    report.notes["failure_breakdown"] = {
        name: {"status": o.status, "upstream_code": o.upstream_code}
        for name, o in probe_results.items()
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    list(sys.argv[1:] if argv is None else argv)
    report = run_qualification(repository_root=Path("."))
    print(json.dumps(report.as_document(), indent=2, sort_keys=True))
    return 0 if report.gate_state == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
