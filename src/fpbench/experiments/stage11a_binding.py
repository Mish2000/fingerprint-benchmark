"""Prove Stage 11B is running the algorithm Stage 11A actually qualified.

The experiment configuration restates Stage 11A's fingerprint and outcome so a
reviewer sees them in a diff. Restated values catch a typo and nothing else: if
the qualification were republished with different findings under the same
numbers, the configuration would still load.

So preparation reads the **published Stage 11A evidence** itself, recomputes the
finalization fingerprint from the committed documents, and compares. Three
agreements have to hold and the stage stops unless all three do:

1. the committed evidence hashes to the fingerprint this stage names;
2. Stage 11A concluded ``VERIFINGER_PREFLIGHT_PASS`` and says it opens 11B;
3. every claim Stage 11B depends on — the score route, the pair semantics, the
   SELF rule, restart determinism, the platform lock — is one Stage 11A actually
   established rather than one this stage assumed.

Nothing here needs an SDK, a licence or a JVM. It reads committed JSON, which is
what lets CI check the binding on a machine that is not allowed to download
VeriFinger (spec sections 1 and 37).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.serialization import read_json
from fpbench.core.verifinger_errors import Stage11BBindingError
from fpbench.adapters.verifinger_java import identity

__all__ = [
    "STAGE_11A_EVIDENCE_DIRECTORY",
    "STAGE_11A_FINALIZATION_NAME",
    "Stage11APublication",
    "read_stage11a_publication",
    "require_stage11a_binding",
]

STAGE_11A_EVIDENCE_DIRECTORY = Path("evidence/stage11a-verifinger-2025_2-preflight")
STAGE_11A_FINALIZATION_NAME = "stage-11a-finalization.json"

#: The claims Stage 11B rests on, as ``(field, required value)``. Each one is
#: something this stage would otherwise have had to establish for itself, and
#: each is a real key of the published marker (spec section 1).
_REQUIRED_CLAIMS: tuple[tuple[str, Any], ...] = (
    ("outcome", identity.STAGE_11A_OUTCOME),
    ("candidate_verdict", identity.STAGE_11A_OUTCOME),
    ("selected_candidate", identity.STAGE_11A_SELECTED_CANDIDATE),
    ("algorithm_slot", identity.ALGORITHM_SLOT),
    ("opens_stage_11b", True),
    ("gate_count_defined", 17),
    ("gates_reached", 17),
    ("gates_passed", 17),
    ("gates_awaiting_action", 0),
    ("artifact_obtained", True),
    ("artifact_identity_pinned", True),
    ("runtime_identity_established", True),
    ("runtime_platform_locked", True),
    ("runtime_platform", "windows/x86_64"),
    ("runtime_dependency_closure_complete", True),
    ("research_use_opens_execution", True),
    ("research_use_blocked", False),
    ("canonical500_input_route_resolved", True),
    ("fpbench_preprocessing_required", False),
    ("raw_score_route_resolved", True),
    ("score_numeric_type", "integer"),
    ("score_direction", "HIGHER_IS_MORE_SIMILAR"),
    ("threshold_applied_inside_the_score", False),
    ("self_independent_extraction_required", True),
    ("self_semantics_demonstrated", True),
    ("pair_order_semantics_resolved", True),
    ("restart_determinism_verified", True),
    ("failure_semantics_resolved", True),
    ("runtime_feasibility_measured", True),
    ("license_workload_capacity_sufficient", True),
    ("sd300_training_overlap_found", False),
    # Stage 11A produced no benchmark score, no threshold and no metric, and
    # Stage 11B inherits a clean slate rather than a partially-decided one.
    ("benchmark_run_performed", False),
    ("threshold_produced", False),
    ("calibration_performed", False),
    ("metrics_produced", False),
    ("prior_algorithm_scores_read", False),
    ("sd300_scores_produced", 0),
)


@dataclass(frozen=True, slots=True)
class Stage11APublication:
    """What the committed Stage 11A evidence says, read once."""

    outcome: str
    finalization_fingerprint: str
    selected_candidate: str
    algorithm_slot: str
    opens_stage_11b: bool
    gates_passed: int
    source_commit: str
    verifier_source_commit: str
    marker: Mapping[str, Any]


def read_stage11a_publication(
    *, repository_root: Path = Path(".")
) -> Stage11APublication:
    """Read the published Stage 11A chain and re-verify it against itself.

    The marker carries a content hash of every other document it was derived
    from. Those are recomputed here, so a stage whose evidence was edited after
    publication cannot be used to authorise this one.

    Raises:
        Stage11BBindingError: the publication is missing, unreadable, or does not
            verify.
    """
    directory = Path(repository_root) / STAGE_11A_EVIDENCE_DIRECTORY
    marker_path = directory / STAGE_11A_FINALIZATION_NAME
    if not marker_path.is_file():
        raise Stage11BBindingError(
            "the committed Stage 11A finalization is missing; Stage 11B may not "
            "run without the qualification it rests on"
        )
    try:
        marker = read_json(marker_path)
    except (OSError, ValueError) as exc:
        raise Stage11BBindingError(
            f"the Stage 11A finalization cannot be read: {type(exc).__name__}: {exc}"
        ) from exc

    hashes = marker.get("evidence_content_hashes")
    if not isinstance(hashes, Mapping) or not hashes:
        raise Stage11BBindingError(
            "the Stage 11A finalization carries no evidence content hashes, so "
            "nothing binds its verdict to the documents it was derived from"
        )
    drifted: list[str] = []
    for name, expected in sorted(hashes.items()):
        target = directory / str(name)
        if not target.is_file():
            drifted.append(f"{name} is missing")
            continue
        found = _content_hash(target)
        if found != str(expected):
            drifted.append(f"{name} hashes to {found[:12]}..., not {str(expected)[:12]}...")
    if drifted:
        raise Stage11BBindingError(
            "the published Stage 11A evidence is not what its own marker was "
            "derived from: " + "; ".join(drifted)
        )

    return Stage11APublication(
        outcome=str(marker.get("outcome")),
        finalization_fingerprint=str(marker.get("stage_11a_finalization_fingerprint")),
        selected_candidate=str(marker.get("selected_candidate")),
        algorithm_slot=str(marker.get("algorithm_slot")),
        opens_stage_11b=bool(marker.get("opens_stage_11b")),
        gates_passed=int(marker.get("gates_passed") or 0),
        source_commit=str(marker.get("source_commit")),
        verifier_source_commit=str(marker.get("verifier_source_commit")),
        marker=dict(marker),
    )


def require_stage11a_binding(
    *,
    declared_fingerprint: str,
    declared_outcome: str,
    repository_root: Path = Path("."),
) -> Stage11APublication:
    """Bind this stage to that one, or refuse to proceed.

    Args:
        declared_fingerprint: what the experiment configuration says Stage 11A
            finalised to.
        declared_outcome: what it says Stage 11A concluded.

    Raises:
        Stage11BBindingError: the declaration, the publication and this source do
            not all agree. A changed fingerprint is not something to work around
            — it means 11B must not run until somebody has looked at why
            (spec section 1).
    """
    published = read_stage11a_publication(repository_root=repository_root)

    differences: list[str] = []
    if declared_fingerprint != identity.STAGE_11A_FINALIZATION_FINGERPRINT:
        differences.append(
            f"the experiment names {declared_fingerprint[:12]}... and this source "
            f"is frozen at {identity.STAGE_11A_FINALIZATION_FINGERPRINT[:12]}..."
        )
    if published.finalization_fingerprint != identity.STAGE_11A_FINALIZATION_FINGERPRINT:
        differences.append(
            f"the publication carries {published.finalization_fingerprint[:12]}... "
            f"and this source is frozen at "
            f"{identity.STAGE_11A_FINALIZATION_FINGERPRINT[:12]}..."
        )
    if declared_outcome != identity.STAGE_11A_OUTCOME:
        differences.append(
            f"the experiment names outcome {declared_outcome!r}, and only "
            f"{identity.STAGE_11A_OUTCOME!r} opens Stage 11B"
        )
    if differences:
        raise Stage11BBindingError(
            "Stage 11B is not bound to the published Stage 11A qualification: "
            + "; ".join(differences)
        )

    unmet = [
        f"{field}={published.marker.get(field)!r} (needs {expected!r})"
        for field, expected in _REQUIRED_CLAIMS
        if published.marker.get(field) != expected
    ]
    if unmet:
        raise Stage11BBindingError(
            "the published Stage 11A qualification does not establish what "
            "Stage 11B depends on: " + "; ".join(unmet)
        )
    return published


def _content_hash(path: Path) -> str:
    """A digest over one evidence document, with newlines normalised.

    ``core.autocrlf`` is on for this repository, so the same committed blob is
    LF in one checkout and CRLF in another. A raw digest would therefore move on
    a fresh checkout with no change at all — which is how a check that should be
    trusted becomes one somebody switches off. The same normalisation Stage 11A
    itself applies.
    """
    content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()
