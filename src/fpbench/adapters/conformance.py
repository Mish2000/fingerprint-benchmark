"""One suite every adapter must pass, runnable without pytest.

``tests/contract/test_adapter_contract.py`` has held this project's adapters to
the contract since stage 2. It is parametrised over the registry, which is
exactly right for adapters that are registered and can be built from nothing —
and no use at all for an adapter that needs two executables materialised into a
bundle first, or for one deliberately kept out of the public registry.

So the checks live here, as a function over a case, and the pytest file is one
caller among several. A new algorithm's author runs this against their adapter
before wiring anything else up, gets a list of findings rather than a stack
trace, and knows what is left to do (spec sections 51 to 53).

Nothing here imports pytest, and nothing here knows what any particular
algorithm is. A finding is data: a check name, whether it held, and one sentence
about why not.
"""

from __future__ import annotations

import hashlib
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

from fpbench.adapters.base import (
    ADAPTER_CONTRACT_VERSION,
    SUPPORTED_ADAPTER_CONTRACT_VERSIONS,
    FingerprintAlgorithmAdapter,
)
from fpbench.core.enums import (
    EnvironmentStatus,
    ExecutionStatus,
    ScoreDirection,
)
from fpbench.core.execution_models import (
    ComparisonContext,
    PreparedImage,
    RawMatchResult,
    descriptor_fingerprint,
)
from fpbench.core.identifiers import InvalidIdentifierError, validate_id

__all__ = [
    "AdapterConformanceCase",
    "ConformanceFinding",
    "ConformanceReport",
    "ConformanceFailure",
    "run_adapter_conformance",
    "FORBIDDEN_RESULT_METADATA_KEYS",
]

AdapterFactory = Callable[[Mapping[str, object]], FingerprintAlgorithmAdapter]
DirectionalGolden = Callable[[RawMatchResult, RawMatchResult], bool]

#: Keys that would mean the adapter had been told something it must not know, or
#: had answered a question that is not its to answer (docs/adr/0003,
#: docs/adr/0010). The runner's own validator holds the authoritative list; this
#: one exists so an adapter author finds out before a run rather than after one.
FORBIDDEN_RESULT_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "threshold",
        "decision",
        "is_match",
        "matched",
        "ground_truth",
        "protocol_stage",
        "subject_id",
        "finger",
        "finger_position",
        "pair_id",
    }
)


class ConformanceFailure(AssertionError):
    """Raised by :meth:`ConformanceReport.require_clean`."""


@dataclass(frozen=True, slots=True)
class ConformanceFinding:
    """One check, and whether it held."""

    check: str
    passed: bool
    detail: str = ""

    def __str__(self) -> str:  # pragma: no cover - display only
        mark = "ok" if self.passed else "FAILED"
        return f"[{mark}] {self.check}{f': {self.detail}' if self.detail else ''}"


@dataclass(frozen=True, slots=True)
class ConformanceReport:
    """What the suite found, in the order it looked."""

    adapter_id: str
    findings: tuple[ConformanceFinding, ...]

    @property
    def is_clean(self) -> bool:
        return all(finding.passed for finding in self.findings)

    @property
    def failures(self) -> tuple[ConformanceFinding, ...]:
        return tuple(finding for finding in self.findings if not finding.passed)

    def finding(self, check: str) -> ConformanceFinding | None:
        for item in self.findings:
            if item.check == check:
                return item
        return None

    def require_clean(self) -> None:
        if self.is_clean:
            return
        detail = "; ".join(f"{f.check}: {f.detail}" for f in self.failures)
        raise ConformanceFailure(f"{self.adapter_id} is not conformant — {detail}")


@dataclass(frozen=True, slots=True)
class AdapterConformanceCase:
    """One adapter, and enough context to exercise it honestly."""

    adapter_id: str
    factory: AdapterFactory

    #: Configuration under which the adapter should report READY.
    ready_config: Mapping[str, object]
    #: Configuration under which a dependency is missing. The adapter must report
    #: UNAVAILABLE and must not raise: a missing dependency is one fault of the
    #: run, not one failure per pair.
    unavailable_config: Mapping[str, object]

    left_image: PreparedImage
    right_image: PreparedImage

    expected_score_direction: ScoreDirection
    expected_contract_version: str = ADAPTER_CONTRACT_VERSION

    #: Whether a successful comparison is expected over these two images. An
    #: adapter whose fixture inputs are meant to fail sets this to ``False`` and
    #: the score checks become failure checks.
    expect_success: bool = True

    #: Whether ``adapter_id`` should resolve through the public registry. A
    #: fixture adapter that is deliberately unregistered sets this to ``False``.
    registered: bool = True

    #: Extra metadata keys this adapter must never emit.
    additional_forbidden_metadata: tuple[str, ...] = ()

    #: Optional algorithm-specific proof that reversing probe and reference was
    #: not silently normalised back into the same call. Generic score equality
    #: cannot prove this because a conformant matcher may be symmetric.
    directional_golden: DirectionalGolden | None = None

    context_overrides: Mapping[str, object] = field(default_factory=dict)


def run_adapter_conformance(
    case: AdapterConformanceCase,
    *,
    working_directory: Path,
    artifact_directory: Path,
    sandbox_root: Path,
) -> ConformanceReport:
    """Run every mandatory check and return what happened.

    Args:
        working_directory: The job's scratch directory, already created.
        artifact_directory: The job's artefact directory, already created.
        sandbox_root: A directory containing both of the above *and* the input
            images. Everything created underneath it during ``compare`` must be
            inside one of the two job directories; anything else is a stray
            write.

    Never raises for a non-conformant adapter — the findings are the answer. It
    raises only if the adapter cannot be constructed at all, because then there
    is nothing to report on.
    """
    findings: list[ConformanceFinding] = []
    add = findings.append

    adapter = case.factory(dict(case.ready_config))
    adapter_finding = _check_is_adapter(adapter)
    add(adapter_finding)
    if not adapter_finding.passed:
        return ConformanceReport(adapter_id=case.adapter_id, findings=tuple(findings))
    descriptor = adapter.descriptor

    add(_check_identifiers(descriptor))
    add(_check_versions(descriptor))
    add(_check_contract_version(descriptor, case))
    add(_check_descriptor_stability(adapter))
    add(_check_registry(case, descriptor))
    add(_check_score_direction_declared(descriptor, case))
    add(_check_probe_side(descriptor))

    add(_check_ready_environment(adapter))
    findings.extend(_check_unavailable_environment(case))

    invocation_specs = (
        ("forward-1", case.left_image, case.right_image),
        ("forward-2", case.left_image, case.right_image),
        ("reverse-1", case.right_image, case.left_image),
    )
    invocation_directories: dict[str, tuple[Path, Path]] = {}
    for label, _, _ in invocation_specs:
        invocation_work = Path(working_directory) / label
        invocation_artifacts = Path(artifact_directory) / label
        invocation_work.mkdir(parents=True, exist_ok=False)
        invocation_artifacts.mkdir(parents=True, exist_ok=False)
        invocation_directories[label] = (invocation_work, invocation_artifacts)

    invocations: list[_Invocation] = []
    for label, left, right in invocation_specs:
        invocation_work, invocation_artifacts = invocation_directories[label]
        invocations.append(
            _invoke_compare(
                label=label,
                adapter=adapter,
                case=case,
                left=left,
                right=right,
                working_directory=invocation_work,
                artifact_directory=invocation_artifacts,
                sandbox_root=Path(sandbox_root),
            )
        )

    raised = [
        f"{item.label}: {type(item.exception).__name__}: {item.exception}"
        for item in invocations
        if item.exception is not None
    ]
    add(ConformanceFinding("compare_does_not_raise", not raised, "; ".join(raised)))
    add(
        _merge_findings(
            "compare_returns_a_raw_match_result",
            [
                _label_finding(item, _check_result_type(item.result))
                for item in invocations
            ],
        )
    )

    result_checks: tuple[
        tuple[str, Callable[[RawMatchResult], ConformanceFinding]], ...
    ] = (
        (
            "result_score_direction_matches_the_descriptor",
            lambda result: _check_score_direction_matches(result, descriptor),
        ),
        ("outcome_shape_is_valid", lambda result: _check_outcome_shape(result, case)),
        ("result_metadata_is_string_to_string", _check_metadata_types),
        (
            "result_metadata_carries_no_answer",
            lambda result: _check_forbidden_metadata(result, case),
        ),
        (
            "result_metadata_holds_no_absolute_path",
            lambda result: _check_no_absolute_paths(result, Path(sandbox_root)),
        ),
    )
    for check_name, check in result_checks:
        per_call: list[ConformanceFinding] = []
        for item in invocations:
            if isinstance(item.result, RawMatchResult):
                per_call.append(_label_finding(item, check(item.result)))
            else:
                per_call.append(
                    ConformanceFinding(check_name, False, f"{item.label}: no result")
                )
        add(_merge_findings(check_name, per_call))

    add(
        _merge_findings(
            "artifacts_are_verifiable", [item.artifacts for item in invocations]
        )
    )
    add(
        _merge_findings(
            "compare_does_not_modify_its_inputs",
            [item.inputs for item in invocations],
        )
    )
    add(
        _merge_findings(
            "compare_writes_only_inside_its_directories",
            [item.containment for item in invocations],
        )
    )
    add(_check_determinism(descriptor, invocations[0].result, invocations[1].result))
    add(
        _check_direction_is_not_reordered(
            case, invocations[0].result, invocations[2].result
        )
    )

    return ConformanceReport(adapter_id=case.adapter_id, findings=tuple(findings))


# ------------------------------------------------------------------- checks


def _check_is_adapter(adapter: object) -> ConformanceFinding:
    ok = isinstance(adapter, FingerprintAlgorithmAdapter)
    return ConformanceFinding(
        "factory_returns_an_adapter",
        ok,
        "" if ok else f"got {type(adapter).__name__}",
    )


def _check_identifiers(descriptor) -> ConformanceFinding:
    """Ids have to be usable as directory names and dictionary keys."""
    try:
        validate_id(descriptor.algorithm_id)
        validate_id(descriptor.adapter_id)
    except InvalidIdentifierError as exc:
        return ConformanceFinding("descriptor_identifiers_are_usable", False, str(exc))
    return ConformanceFinding("descriptor_identifiers_are_usable", True)


def _check_versions(descriptor) -> ConformanceFinding:
    missing = [
        name
        for name in ("adapter_version", "implementation_version", "display_name")
        if not str(getattr(descriptor, name, "")).strip()
    ]
    return ConformanceFinding(
        "descriptor_declares_versions",
        not missing,
        f"blank: {missing}" if missing else "",
    )


def _check_contract_version(descriptor, case) -> ConformanceFinding:
    declared = descriptor.adapter_contract_version
    ok = (
        declared == case.expected_contract_version
        and declared in SUPPORTED_ADAPTER_CONTRACT_VERSIONS
    )
    return ConformanceFinding(
        "contract_version_is_supported",
        ok,
        "" if ok else f"declares {declared!r}",
    )


def _check_descriptor_stability(adapter) -> ConformanceFinding:
    first, second = adapter.descriptor, adapter.descriptor
    ok = first == second and descriptor_fingerprint(first) == descriptor_fingerprint(
        second
    )
    return ConformanceFinding(
        "descriptor_is_stable",
        ok,
        "" if ok else "two reads produced different descriptors",
    )


def _check_registry(case, descriptor) -> ConformanceFinding:
    if not case.registered:
        return ConformanceFinding(
            "registry_id_matches_descriptor", True, "not registered by design"
        )
    from fpbench.adapters.registry import registered_adapters

    listed = registered_adapters()
    ok = case.adapter_id in listed and descriptor.adapter_id == case.adapter_id
    return ConformanceFinding(
        "registry_id_matches_descriptor",
        ok,
        "" if ok else f"{case.adapter_id!r} vs descriptor {descriptor.adapter_id!r}",
    )


def _check_score_direction_declared(descriptor, case) -> ConformanceFinding:
    ok = descriptor.score_direction is case.expected_score_direction
    return ConformanceFinding(
        "descriptor_declares_expected_score_direction",
        ok,
        "" if ok else f"declares {descriptor.score_direction.value!r}",
    )


def _check_probe_side(descriptor) -> ConformanceFinding:
    """When the route names a probe side, it has to be the left one.

    ``compare(left, right)`` fixes left as the probe. A route that declared
    ``probe_side: right`` would be running a different experiment from the one
    the pair manifest describes (spec section 67).
    """
    declared = dict(descriptor.metadata).get("probe_side")
    if declared is None:
        return ConformanceFinding("probe_side_is_left", True, "not declared")
    return ConformanceFinding(
        "probe_side_is_left",
        declared == "left",
        "" if declared == "left" else f"declares {declared!r}",
    )


def _check_ready_environment(adapter) -> ConformanceFinding:
    report = adapter.validate_environment()
    ok = report.status is EnvironmentStatus.READY and bool(
        str(report.implementation_version).strip()
    )
    return ConformanceFinding(
        "environment_is_ready_when_dependencies_are_present",
        ok,
        "" if ok else f"{report.status.value}: {report.message}",
    )


def _check_unavailable_environment(case) -> tuple[ConformanceFinding, ...]:
    """A missing dependency is a report, never an exception."""
    try:
        adapter = case.factory(dict(case.unavailable_config))
        report = adapter.validate_environment()
    except Exception as exc:  # noqa: BLE001 - that is precisely the failure
        finding = ConformanceFinding(
            "missing_dependency_is_not_an_exception",
            False,
            f"{type(exc).__name__}: {exc}",
        )
        return (finding,)

    ok = report.status is EnvironmentStatus.UNAVAILABLE
    return (
        ConformanceFinding("missing_dependency_is_not_an_exception", True),
        ConformanceFinding(
            "environment_is_unavailable_when_a_dependency_is_missing",
            ok,
            "" if ok else f"reported {report.status.value}",
        ),
    )


def _check_result_type(result: object) -> ConformanceFinding:
    ok = isinstance(result, RawMatchResult)
    return ConformanceFinding(
        "compare_returns_a_raw_match_result",
        ok,
        "" if ok else f"returned {type(result).__name__}",
    )


def _check_score_direction_matches(result, descriptor) -> ConformanceFinding:
    ok = result.score_direction is descriptor.score_direction
    return ConformanceFinding(
        "result_score_direction_matches_the_descriptor",
        ok,
        "" if ok else f"result says {result.score_direction.value!r}",
    )


def _check_outcome_shape(result, case) -> ConformanceFinding:
    """A success has a finite score and no failure; a failure has neither."""
    import math

    if result.status is ExecutionStatus.SUCCESS:
        if not case.expect_success:
            return ConformanceFinding(
                "outcome_shape_is_valid", False, "expected a failure, got a score"
            )
        score = result.raw_score
        ok = (
            score is not None
            and math.isfinite(float(score))
            and result.failure is None
        )
        return ConformanceFinding(
            "outcome_shape_is_valid",
            ok,
            "" if ok else "a success must carry a finite score and no failure",
        )

    ok = result.raw_score is None and result.failure is not None
    detail = ""
    if not ok:
        detail = "a failure must carry no score and must explain itself"
    elif case.expect_success:
        return ConformanceFinding(
            "outcome_shape_is_valid",
            False,
            f"expected a score, got {result.failure.code.value}",
        )
    return ConformanceFinding("outcome_shape_is_valid", ok, detail)


def _check_metadata_types(result) -> ConformanceFinding:
    offenders = [
        f"{key!r}={type(value).__name__}"
        for key, value in dict(result.metadata).items()
        if not isinstance(key, str) or not isinstance(value, str)
    ]
    return ConformanceFinding(
        "result_metadata_is_string_to_string",
        not offenders,
        ", ".join(offenders),
    )


def _check_forbidden_metadata(result, case) -> ConformanceFinding:
    forbidden = FORBIDDEN_RESULT_METADATA_KEYS | set(
        case.additional_forbidden_metadata
    )
    present = sorted(forbidden & set(result.metadata))
    return ConformanceFinding(
        "result_metadata_carries_no_answer",
        not present,
        f"carries {present}" if present else "",
    )


def _check_no_absolute_paths(result, sandbox_root: Path) -> ConformanceFinding:
    """A stored result that embeds one machine's layout is not evidence."""
    root = str(Path(sandbox_root))
    offenders = [
        key
        for key, value in dict(result.metadata).items()
        if root in str(value) or str(value).startswith(("/", "\\"))
        or (len(str(value)) > 2 and str(value)[1:3] == ":\\")
    ]
    return ConformanceFinding(
        "result_metadata_holds_no_absolute_path",
        not offenders,
        f"paths under {offenders}" if offenders else "",
    )


def _check_artifacts(
    result, artifact_directory: Path, sandbox_root: Path
) -> ConformanceFinding:
    """Every artefact is relative, contained, and hashes to what it claims."""
    problems: list[str] = []
    for reference in result.artifacts:
        path = Path(reference.relative_path)
        if path.is_absolute() or ".." in path.parts:
            problems.append(f"{reference.artifact_id}: unsafe path")
            continue
        # The reference may be workspace-relative or artefact-relative; both are
        # resolvable from the artefact directory upwards.
        candidates = [artifact_directory / path, sandbox_root / path]
        found = next(
            (
                item
                for item in candidates
                if _is_exclusive_regular_file(item, sandbox_root)
            ),
            None,
        )
        if found is None:
            problems.append(f"{reference.artifact_id}: not found")
            continue
        try:
            payload = found.read_bytes()
        except OSError as exc:
            problems.append(
                f"{reference.artifact_id}: unreadable ({type(exc).__name__})"
            )
            continue
        if hashlib.sha256(payload).hexdigest() != reference.sha256:
            problems.append(f"{reference.artifact_id}: digest mismatch")
        elif len(payload) != reference.size_bytes:
            problems.append(f"{reference.artifact_id}: size mismatch")
    return ConformanceFinding(
        "artifacts_are_verifiable", not problems, "; ".join(problems)
    )


def _check_inputs_unmodified(case, before) -> ConformanceFinding:
    """The adapter read its inputs; it did not edit them.

    Digest and size, re-read after the comparison. A prepared artefact that an
    adapter rewrote would silently change what every later run compares against
    (docs/adr/0033).
    """
    try:
        now = {
            "left": _file_identity(case.left_image.local_path),
            "right": _file_identity(case.right_image.local_path),
        }
    except OSError as exc:
        return ConformanceFinding(
            "compare_does_not_modify_its_inputs",
            False,
            f"an input is missing or unreadable ({type(exc).__name__})",
        )
    changed = sorted(side for side in before if now[side] != before[side])
    return ConformanceFinding(
        "compare_does_not_modify_its_inputs",
        not changed,
        f"changed: {changed}" if changed else "",
    )


def _check_containment(
    sandbox_root: Path,
    before: set[Path],
    working_directory: Path,
    artifact_directory: Path,
) -> ConformanceFinding:
    created = _files_under(sandbox_root) - before
    stray = [
        str(path.name)
        for path in created
        if not path.is_relative_to(working_directory)
        and not path.is_relative_to(artifact_directory)
    ]
    return ConformanceFinding(
        "compare_writes_only_inside_its_directories",
        not stray,
        f"wrote {stray}" if stray else "",
    )


def _check_determinism(descriptor, first, second) -> ConformanceFinding:
    """A deterministic adapter repeats itself, or it is not deterministic."""
    if not descriptor.deterministic:
        return ConformanceFinding(
            "deterministic_adapter_repeats_itself", True, "not declared deterministic"
        )
    ok = isinstance(first, RawMatchResult) and isinstance(
        second, RawMatchResult
    ) and (
        second.status is first.status
        and second.raw_score == first.raw_score
    )
    return ConformanceFinding(
        "deterministic_adapter_repeats_itself",
        ok,
        "" if ok else "two identical comparisons produced different answers",
    )


def _check_direction_is_not_reordered(case, forward, reversed_result) -> ConformanceFinding:
    """Reversing the sides must be a *different call*, not the same one.

    A symmetric algorithm may legitimately return the same score both ways, so
    equality proves nothing and is not failed. The generic check proves only
    that the reversed call is answered in kind. Detecting silent input sorting
    requires the optional adapter-specific directional golden.
    """
    ok = isinstance(forward, RawMatchResult) and isinstance(
        reversed_result, RawMatchResult
    ) and (
        reversed_result.score_direction is forward.score_direction
    )
    detail = "" if ok else "the reversed comparison was not answered in kind"
    if ok and case.directional_golden is not None:
        try:
            ok = bool(case.directional_golden(forward, reversed_result))
        except Exception as exc:  # noqa: BLE001 - reported as conformance data
            ok = False
            detail = f"directional golden raised {type(exc).__name__}: {exc}"
        else:
            detail = "" if ok else "the adapter-specific directional golden failed"
    elif ok:
        detail = (
            "both orders were invoked; silent internal reordering requires an "
            "adapter-specific directional golden"
        )
    return ConformanceFinding("both_directions_are_separate_calls", ok, detail)


# ------------------------------------------------------------------ helpers


def _context(
    working_directory: Path, artifact_directory: Path, case
) -> ComparisonContext:
    settings: dict[str, object] = {
        "run_id": "run_abc123def456",
        "job_id": "job_0123456789abcdef",
        "attempt": 1,
        "working_directory": Path(working_directory),
        "artifact_directory": Path(artifact_directory),
        "timeout_seconds": 60.0,
        "deterministic_seed": 0,
    }
    settings.update(dict(case.context_overrides))
    return ComparisonContext(**settings)  # type: ignore[arg-type]


def _files_under(root: Path) -> set[Path]:
    found: set[Path] = set()
    for path in Path(root).rglob("*"):
        try:
            mode = path.lstat().st_mode
        except OSError:
            continue
        if stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            found.add(path)
    return found


def _file_identity(path: Path) -> tuple[str, int]:
    payload = Path(path).read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


@dataclass(frozen=True, slots=True)
class _Invocation:
    label: str
    result: object | None
    exception: Exception | None
    artifacts: ConformanceFinding
    inputs: ConformanceFinding
    containment: ConformanceFinding


def _invoke_compare(
    *,
    label: str,
    adapter: FingerprintAlgorithmAdapter,
    case: AdapterConformanceCase,
    left: PreparedImage,
    right: PreparedImage,
    working_directory: Path,
    artifact_directory: Path,
    sandbox_root: Path,
) -> _Invocation:
    before_files = _files_under(sandbox_root)
    before_inputs = {
        "left": _file_identity(case.left_image.local_path),
        "right": _file_identity(case.right_image.local_path),
    }
    result: object | None = None
    exception: Exception | None = None
    try:
        result = adapter.compare(
            left,
            right,
            _context(working_directory, artifact_directory, case),
        )
    except Exception as exc:  # noqa: BLE001 - findings, never a stack trace
        exception = exc
    artifacts = (
        _check_artifacts(result, artifact_directory, sandbox_root)
        if isinstance(result, RawMatchResult)
        else ConformanceFinding("artifacts_are_verifiable", False, f"{label}: no result")
    )
    return _Invocation(
        label=label,
        result=result,
        exception=exception,
        artifacts=_label_finding_raw(label, artifacts),
        inputs=_label_finding_raw(label, _check_inputs_unmodified(case, before_inputs)),
        containment=_label_finding_raw(
            label,
            _check_containment(
                sandbox_root,
                before_files,
                working_directory,
                artifact_directory,
            ),
        ),
    )


def _label_finding(
    invocation: _Invocation, finding: ConformanceFinding
) -> ConformanceFinding:
    return _label_finding_raw(invocation.label, finding)


def _label_finding_raw(label: str, finding: ConformanceFinding) -> ConformanceFinding:
    detail = f"{label}: {finding.detail}" if finding.detail else label
    return ConformanceFinding(finding.check, finding.passed, detail)


def _merge_findings(
    check: str, findings: list[ConformanceFinding]
) -> ConformanceFinding:
    failures = [item.detail for item in findings if not item.passed]
    return ConformanceFinding(check, not failures, "; ".join(failures))


def _is_exclusive_regular_file(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    current = root
    for component in relative.parts:
        current = current / component
        try:
            info = current.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode):
            return False
    return stat.S_ISREG(info.st_mode) and info.st_nlink == 1
