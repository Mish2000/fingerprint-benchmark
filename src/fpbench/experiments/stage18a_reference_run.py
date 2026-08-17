"""The Stage 18A private reference runner: 3,000 templates, then 6,000 raw scores.

This is deliberately *not* a production integration. It registers no adapter,
builds no environment descriptor, writes no ResultSet and never touches the
workspace. Section 9 of the requirements is explicit: forcing Stage 18A through
``BaseAdapter`` would spend the stage's time on conformance instead of on
numbers, and Stage 19A is where the production integration belongs.

TWO PHASES, SEPARATED ON PURPOSE

.. code-block:: text

    phase 1   3,000 canonical images  ->  3,000 SecuGen ISO templates   (cached)
    phase 2   6,000 manifest pairs    ->  6,000 OpenAFIS raw outcomes

Splitting them is what makes the run readable. Extraction coverage becomes a
property of SecuGen alone, matching behaviour a property of OpenAFIS alone, and
neither can hide inside the other. It also means phase 2 re-runs in minutes.

WHAT STOPS THE RUN

Almost nothing. Every one of the 6,000 pairs must end with a stored row, so a
per-pair problem is a recorded status and the loop continues. Only a condition
that makes *all* remaining rows meaningless — the matcher process dying and
refusing to restart, or the results file becoming unwritable — ends the run, and
it ends it with the rows so far intact on disk.

A ``score`` of 0 is always ``OK``. It is what OpenAFIS returns when too little
structure pairs up, and conflating it with a failure would put "these fingers do
not match" and "the extractor produced nothing" in the same column.

WHERE THE BYTES GO

Nothing here is written into the repository. Templates, results, failures,
timings and the receipt all live under ``$FPBENCH_PRIVATE_ROOT``, outside git,
and the repository carries only identifiers that point at them.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from fpbench.core.errors import ConfigurationError
from fpbench.experiments import stage18a_identity as frozen
from fpbench.experiments.stage18a_inputs import (
    REPOSITORY_ROOT,
    ComparisonPair,
    PreparedImage,
    Stage18AInputs,
    load_stage18a_inputs,
)

__all__ = [
    "Stage18AConfig",
    "TemplateRecord",
    "PairOutcome",
    "ExtractionSummary",
    "MatchingSummary",
    "load_stage18a_config",
    "run_extraction_phase",
    "run_matching_phase",
    "read_template_index",
    "read_pair_outcomes",
    "write_run_receipt",
    "main",
]


# --------------------------------------------------------------------- configuration


def _env_path(name: str, default: Path | None) -> Path | None:
    raw = os.environ.get(name, "").strip()
    if raw:
        return Path(raw).expanduser()
    return default


@dataclass(frozen=True, slots=True)
class Stage18AConfig:
    """Where the pieces are. Every field is overridable by environment variable."""

    private_root: Path
    extract_python: Path
    extract_script: Path
    secugen_sdk_dir: Path | None
    matcher_command: tuple[str, ...]
    matcher_is_wsl: bool
    wsl_distro: str

    def require_sdk(self) -> Path:
        """The SDK directory, or a refusal naming the variable that would supply it.

        Only extraction needs it. ``status``, ``match`` and ``receipt`` all work
        without one, which is what lets the matching half be exercised before the
        vendor half exists.
        """
        if self.secugen_sdk_dir is None:
            raise ConfigurationError(
                "FPBENCH_SECUGEN_SDK_DIR is not set. Point it at the directory holding sgfplib.dll "
                "and its per-device driver modules from the official FDx SDK Pro package"
            )
        return self.secugen_sdk_dir

    @property
    def stage_root(self) -> Path:
        return self.private_root / "stage18a-secugen-openafis"

    @property
    def templates_dir(self) -> Path:
        return self.stage_root / "templates"

    @property
    def results_dir(self) -> Path:
        return self.stage_root / "results"

    @property
    def failures_dir(self) -> Path:
        return self.stage_root / "failures"

    @property
    def timings_dir(self) -> Path:
        return self.stage_root / "timings"

    def ensure_layout(self) -> None:
        for name in frozen.PRIVATE_SUBDIRECTORIES:
            (self.stage_root / name).mkdir(parents=True, exist_ok=True)


def load_stage18a_config() -> Stage18AConfig:
    """Resolve the run's external pieces from the environment.

    Nothing here is discovered by searching the machine. Each path is either given
    explicitly or defaults to the location this stage created, so a run can always
    say where its SDK and its matcher came from.
    """
    private_root = _env_path(frozen.PRIVATE_ROOT_ENV_VAR, Path.home() / ".cache" / "fpbench" / "private")
    assert private_root is not None

    cache = Path.home() / ".cache" / "fpbench" / "third_party"
    extract_python = _env_path(
        "FPBENCH_STAGE18A_EXTRACT_PYTHON", cache / "stage18a-extract-venv" / "Scripts" / "python.exe"
    )
    assert extract_python is not None
    extract_script = _env_path(
        "FPBENCH_STAGE18A_EXTRACT_SCRIPT", REPOSITORY_ROOT / "integrations" / "secugen" / "extract_batch.py"
    )
    assert extract_script is not None
    # Absent is legal here and refused later, by require_sdk(), so that the
    # matching half can be driven before the vendor half exists.
    sdk_dir = _env_path("FPBENCH_SECUGEN_SDK_DIR", None)

    # The matcher is a Linux binary in the fallback runtime split (section 14), so
    # it is reached through wsl.exe and every path it is handed is translated.
    raw_matcher = os.environ.get("FPBENCH_STAGE18A_MATCHER", "").strip()
    distro = os.environ.get("FPBENCH_STAGE18A_WSL_DISTRO", "NBIS-BUILD-V1").strip()
    if raw_matcher:
        matcher_command = tuple(raw_matcher.split())
        is_wsl = False
    else:
        matcher_command = (
            "wsl.exe",
            "-d",
            distro,
            "--",
            "/home/nbisbuild/stage18a-openafis/bridge/build/fpbench_openafis_bridge",
        )
        is_wsl = True

    return Stage18AConfig(
        private_root=private_root,
        extract_python=extract_python,
        extract_script=extract_script,
        secugen_sdk_dir=sdk_dir,
        matcher_command=matcher_command,
        matcher_is_wsl=is_wsl,
        wsl_distro=distro,
    )


def _to_matcher_path(path: Path, config: Stage18AConfig) -> str:
    """Windows path -> the path the matcher process will see.

    Only needed in the fallback split, where extraction runs on Windows and
    matching in WSL. ISO 19794-2 is an interchange format, which is exactly why
    the two halves are allowed to live on different operating systems.
    """
    resolved = path.resolve()
    if not config.matcher_is_wsl:
        return str(resolved)
    text = str(resolved)
    if len(text) > 2 and text[1] == ":":
        drive = text[0].lower()
        return "/mnt/" + drive + text[2:].replace("\\", "/")
    return text.replace("\\", "/")


# ------------------------------------------------------------------------- records


@dataclass(frozen=True, slots=True)
class TemplateRecord:
    """One image's extraction outcome. ``status`` is OK or a SecuGen failure."""

    image_id: str
    status: str
    template_bytes: int
    extract_ms: float
    detail: str
    path: Path | None

    @property
    def ok(self) -> bool:
        return self.status == "OK"


@dataclass(frozen=True, slots=True)
class PairOutcome:
    """One of the 6,000 rows. Section 15's field list, in storage order."""

    ordinal: int
    pair_id: str
    left_image_id: str
    right_image_id: str
    stage: str
    release: str
    ground_truth: str
    left_template_status: str
    right_template_status: str
    openafis_score: int | None
    status: str
    extract_left_ms: float | None
    extract_right_ms: float | None
    match_ms: float | None
    detail: str = ""

    def to_row(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "pair_id": self.pair_id,
            "left_image_id": self.left_image_id,
            "right_image_id": self.right_image_id,
            "stage": self.stage,
            "release": self.release,
            "ground_truth": self.ground_truth,
            "left_template_status": self.left_template_status,
            "right_template_status": self.right_template_status,
            "openafis_score": self.openafis_score,
            "status": self.status,
            "extract_left_ms": self.extract_left_ms,
            "extract_right_ms": self.extract_right_ms,
            "match_ms": self.match_ms,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ExtractionSummary:
    attempted: int
    succeeded: int
    failed: int
    reused: int
    # None when the summary was rebuilt from what is on disk rather than measured.
    # A rebuilt receipt must not publish a wall time it never observed, and 0.0
    # would read as "instant" rather than as "not measured".
    wall_seconds: float | None

    def describe(self) -> dict[str, object]:
        return {
            "images_attempted": self.attempted,
            "templates_produced": self.succeeded,
            "extraction_failures": self.failed,
            "templates_reused_from_cache": self.reused,
            "wall_seconds": round(self.wall_seconds, 3) if self.wall_seconds is not None else None,
        }


@dataclass(frozen=True, slots=True)
class MatchingSummary:
    expected: int
    stored: int
    missing: int
    status_counts: Mapping[str, int]
    wall_seconds: float | None

    @property
    def complete(self) -> bool:
        """Section 12's entire completion criterion. There is nothing else."""
        return self.expected == frozen.EXPECTED_PAIR_OUTCOMES and self.stored == self.expected and self.missing == 0

    def describe(self) -> dict[str, object]:
        return {
            "expected_pair_outcomes": self.expected,
            "stored_pair_outcomes": self.stored,
            "missing": self.missing,
            "status_counts": dict(sorted(self.status_counts.items())),
            "wall_seconds": round(self.wall_seconds, 3) if self.wall_seconds is not None else None,
        }


# ------------------------------------------------------------------ phase 1: extract


def _template_path(config: Stage18AConfig, image_id: str) -> Path:
    return config.templates_dir / f"{image_id}.iso"


def _template_index_path(config: Stage18AConfig) -> Path:
    return config.templates_dir / "index.jsonl"


def read_template_index(config: Stage18AConfig) -> dict[str, TemplateRecord]:
    """Every extraction outcome recorded so far, keyed by image id."""
    path = _template_index_path(config)
    if not path.is_file():
        return {}
    records: dict[str, TemplateRecord] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            template_path = Path(row["path"]) if row.get("path") else None
            records[row["image_id"]] = TemplateRecord(
                image_id=row["image_id"],
                status=row["status"],
                template_bytes=int(row["template_bytes"]),
                extract_ms=float(row["extract_ms"]),
                detail=row.get("detail", ""),
                path=template_path,
            )
    return records


def run_extraction_phase(
    inputs: Stage18AInputs,
    config: Stage18AConfig,
    *,
    images: Sequence[PreparedImage] | None = None,
    repeat_probe: bool = False,
    resume: bool = True,
) -> ExtractionSummary:
    """3,000 canonical images -> 3,000 SecuGen ISO templates.

    Resumable: an image whose template already exists on disk and whose outcome is
    already in the index is skipped, so a run interrupted at image 2,700 does not
    redo 2,700 extractions. ``repeat_probe`` extracts each image twice and records
    whether the two templates are byte-identical — section 10's determinism check,
    which is an observation and never a blocker.
    """
    config.ensure_layout()
    selected = tuple(images) if images is not None else inputs.images

    known = read_template_index(config) if resume else {}
    pending = [
        image
        for image in selected
        if not (
            resume
            and image.image_id in known
            and (known[image.image_id].status != "OK" or _template_path(config, image.image_id).is_file())
        )
    ]
    reused = len(selected) - len(pending)

    started = time.perf_counter()
    if not pending:
        cached_ok = sum(1 for image in selected if image.image_id in known and known[image.image_id].ok)
        return ExtractionSummary(len(selected), cached_ok, 0, reused, 0.0)

    sdk_dir = config.require_sdk()
    command = [
        str(config.extract_python),
        str(config.extract_script),
        "--sdk-dir",
        str(sdk_dir),
    ]
    if repeat_probe:
        command.append("--repeat")

    jobs = "".join(
        f"{image.image_id}\t{image.path.resolve()}\t{_template_path(config, image.image_id).resolve()}\n"
        for image in pending
    )

    completed = subprocess.run(
        command,
        input=jobs,
        text=True,
        capture_output=True,
        # Upstream's instruction is "copy the DLLs into the current directory":
        # sgfplib loads its per-device driver modules by plain name, which
        # searches the working directory. Running from the SDK directory is the
        # documented arrangement rather than a workaround.
        cwd=str(sdk_dir),
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        raise ConfigurationError(
            f"the SecuGen extractor produced nothing and exited {completed.returncode}: {completed.stderr.strip()[:800]}"
        )

    succeeded = 0
    failed = 0
    index_path = _template_index_path(config)
    failure_log = config.failures_dir / "extraction-failures.jsonl"
    with index_path.open("a", encoding="utf-8") as index, failure_log.open("a", encoding="utf-8") as failures:
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            fields = line.split("\t")
            if len(fields) < 4:
                continue
            image_id, status, size, micros = fields[0], fields[1], fields[2], fields[3]
            detail = fields[4] if len(fields) > 4 else ""
            record = {
                "image_id": image_id,
                "status": status,
                "template_bytes": int(size),
                "extract_ms": int(micros) / 1000.0,
                "detail": detail,
                "path": str(_template_path(config, image_id)) if status == "OK" else None,
            }
            index.write(json.dumps(record, sort_keys=True) + "\n")
            if status == "OK":
                succeeded += 1
            else:
                failed += 1
                failures.write(json.dumps(record, sort_keys=True) + "\n")

    return ExtractionSummary(len(selected), succeeded, failed, reused, time.perf_counter() - started)


# -------------------------------------------------------------------- phase 2: match

# The bridge's own vocabulary, mapped onto section 11's closed list. A load
# problem on either side is one OpenAFIS status, because the requirement's list
# does not distinguish the sides for loads the way it does for extractions.
_BRIDGE_TO_STATUS = {
    "OK": "OK",
    "LOAD_FAILED_LEFT": "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "LOAD_FAILED_RIGHT": "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "LOAD_FAILED_BOTH": "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "NO_FINGERPRINT_LEFT": "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "NO_FINGERPRINT_RIGHT": "OPENAFIS_TEMPLATE_LOAD_FAILED",
    "MATCH_EXCEPTION": "OPENAFIS_MATCH_PROCESS_FAILED",
}


def _extraction_status(left_ok: bool, right_ok: bool) -> str | None:
    """The SecuGen half of section 11, decided before the matcher is asked."""
    if left_ok and right_ok:
        return None
    if not left_ok and not right_ok:
        return "SECU_GEN_EXTRACTION_FAILED_BOTH"
    return "SECU_GEN_EXTRACTION_FAILED_LEFT" if not left_ok else "SECU_GEN_EXTRACTION_FAILED_RIGHT"


def _results_path(config: Stage18AConfig) -> Path:
    return config.results_dir / "pair-outcomes.jsonl"


def read_pair_outcomes(config: Stage18AConfig) -> list[PairOutcome]:
    """Read back every stored row, in storage order."""
    path = _results_path(config)
    if not path.is_file():
        return []
    outcomes: list[PairOutcome] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            outcomes.append(
                PairOutcome(
                    ordinal=int(row["ordinal"]),
                    pair_id=row["pair_id"],
                    left_image_id=row["left_image_id"],
                    right_image_id=row["right_image_id"],
                    stage=row["stage"],
                    release=row["release"],
                    ground_truth=row["ground_truth"],
                    left_template_status=row["left_template_status"],
                    right_template_status=row["right_template_status"],
                    openafis_score=row["openafis_score"],
                    status=row["status"],
                    extract_left_ms=row["extract_left_ms"],
                    extract_right_ms=row["extract_right_ms"],
                    match_ms=row["match_ms"],
                    detail=row.get("detail", ""),
                )
            )
    return outcomes


def run_matching_phase(
    inputs: Stage18AInputs,
    config: Stage18AConfig,
    *,
    pairs: Sequence[ComparisonPair] | None = None,
    resume: bool = True,
) -> MatchingSummary:
    """6,000 manifest pairs -> 6,000 stored raw outcomes.

    Pairs whose templates are both present go to the matcher in one batch over a
    single held-open process; pairs missing a template never reach it and are
    written straight out with the SecuGen status that explains them. Rows are
    appended as they are produced, so an interruption keeps everything already
    decided.
    """
    config.ensure_layout()
    selected = tuple(pairs) if pairs is not None else inputs.pairs

    already = {outcome.pair_id for outcome in read_pair_outcomes(config)} if resume else set()
    pending = [pair for pair in selected if pair.pair_id not in already]

    templates = read_template_index(config)
    started = time.perf_counter()

    # Split before spawning anything: a pair with no template is not the matcher's
    # business, and asking it about one would only produce a load error that hides
    # the real cause.
    matchable: list[ComparisonPair] = []
    unmatchable: list[tuple[ComparisonPair, str]] = []
    for pair in pending:
        left = templates.get(pair.left_image_id)
        right = templates.get(pair.right_image_id)
        left_ok = bool(left and left.ok and _template_path(config, pair.left_image_id).is_file())
        right_ok = bool(right and right.ok and _template_path(config, pair.right_image_id).is_file())
        status = _extraction_status(left_ok, right_ok)
        if status is None:
            matchable.append(pair)
        else:
            unmatchable.append((pair, status))

    results_path = _results_path(config)
    failure_log = config.failures_dir / "matching-failures.jsonl"
    status_counts: dict[str, int] = {}

    def _record(handle, failures, outcome: PairOutcome) -> None:
        handle.write(json.dumps(outcome.to_row(), sort_keys=True) + "\n")
        handle.flush()
        status_counts[outcome.status] = status_counts.get(outcome.status, 0) + 1
        if outcome.status != frozen.OK_STATUS:
            failures.write(json.dumps(outcome.to_row(), sort_keys=True) + "\n")

    def _template_ms(image_id: str) -> float | None:
        record = templates.get(image_id)
        return record.extract_ms if record else None

    def _template_status(image_id: str) -> str:
        record = templates.get(image_id)
        return record.status if record else "NOT_EXTRACTED"

    with results_path.open("a", encoding="utf-8") as handle, failure_log.open("a", encoding="utf-8") as failures:
        for pair, status in unmatchable:
            _record(
                handle,
                failures,
                PairOutcome(
                    ordinal=pair.ordinal,
                    pair_id=pair.pair_id,
                    left_image_id=pair.left_image_id,
                    right_image_id=pair.right_image_id,
                    stage=pair.protocol_stage,
                    release=pair.release,
                    ground_truth=pair.ground_truth,
                    left_template_status=_template_status(pair.left_image_id),
                    right_template_status=_template_status(pair.right_image_id),
                    openafis_score=None,
                    status=status,
                    extract_left_ms=_template_ms(pair.left_image_id),
                    extract_right_ms=_template_ms(pair.right_image_id),
                    match_ms=None,
                ),
            )

        if matchable:
            jobs = "".join(
                f"{pair.pair_id}\t{_to_matcher_path(_template_path(config, pair.left_image_id), config)}"
                f"\t{_to_matcher_path(_template_path(config, pair.right_image_id), config)}\n"
                for pair in matchable
            )
            completed = subprocess.run(
                [*config.matcher_command, "batch"],
                input=jobs,
                text=True,
                capture_output=True,
            )
            by_id = {pair.pair_id: pair for pair in matchable}
            seen: set[str] = set()
            for line in completed.stdout.splitlines():
                if not line.strip():
                    continue
                fields = line.split("\t")
                if len(fields) < 6:
                    continue
                pair_id, bridge_status, score, _load_left, _load_right, match_us = fields[:6]
                pair = by_id.get(pair_id)
                if pair is None:
                    continue
                seen.add(pair_id)
                status = _BRIDGE_TO_STATUS.get(bridge_status, "OPENAFIS_MATCH_PROCESS_FAILED")
                _record(
                    handle,
                    failures,
                    PairOutcome(
                        ordinal=pair.ordinal,
                        pair_id=pair.pair_id,
                        left_image_id=pair.left_image_id,
                        right_image_id=pair.right_image_id,
                        stage=pair.protocol_stage,
                        release=pair.release,
                        ground_truth=pair.ground_truth,
                        left_template_status=_template_status(pair.left_image_id),
                        right_template_status=_template_status(pair.right_image_id),
                        openafis_score=int(score) if status == frozen.OK_STATUS else None,
                        status=status,
                        extract_left_ms=_template_ms(pair.left_image_id),
                        extract_right_ms=_template_ms(pair.right_image_id),
                        match_ms=int(match_us) / 1000.0,
                        detail="" if status == frozen.OK_STATUS else bridge_status,
                    ),
                )

            # A pair the matcher never answered for still needs a row. This is the
            # one place INFRASTRUCTURE_FAILURE is legitimate: the process ended
            # before it reached this comparison.
            detail = f"matcher exit {completed.returncode}: {completed.stderr.strip()[:200]}"
            for pair in matchable:
                if pair.pair_id in seen:
                    continue
                _record(
                    handle,
                    failures,
                    PairOutcome(
                        ordinal=pair.ordinal,
                        pair_id=pair.pair_id,
                        left_image_id=pair.left_image_id,
                        right_image_id=pair.right_image_id,
                        stage=pair.protocol_stage,
                        release=pair.release,
                        ground_truth=pair.ground_truth,
                        left_template_status=_template_status(pair.left_image_id),
                        right_template_status=_template_status(pair.right_image_id),
                        openafis_score=None,
                        status="INFRASTRUCTURE_FAILURE",
                        extract_left_ms=_template_ms(pair.left_image_id),
                        extract_right_ms=_template_ms(pair.right_image_id),
                        match_ms=None,
                        detail=detail,
                    ),
                )

    stored = read_pair_outcomes(config)
    stored_ids = {outcome.pair_id for outcome in stored}
    missing = sum(1 for pair in inputs.pairs if pair.pair_id not in stored_ids)
    counts: dict[str, int] = {}
    for outcome in stored:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1

    return MatchingSummary(
        expected=len(inputs.pairs),
        stored=len(stored),
        missing=missing,
        status_counts=counts,
        wall_seconds=time.perf_counter() - started,
    )


# ------------------------------------------------------------------------- receipt


def write_run_receipt(
    inputs: Stage18AInputs,
    config: Stage18AConfig,
    extraction: ExtractionSummary,
    matching: MatchingSummary,
) -> Path:
    """The private receipt. Holds identifiers, counts and timings — never a score."""
    receipt = {
        "kind": "stage_18a_private_run_receipt",
        "stage": frozen.STAGE,
        "purpose": frozen.PURPOSE,
        "experiment_id": frozen.EXPERIMENT_ID,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "algorithm_5_established": frozen.ALGORITHM_5_ESTABLISHED,
        "opens_common_calibration": frozen.OPENS_COMMON_CALIBRATION,
        "publication_eligible": frozen.PUBLICATION_ELIGIBLE,
        "inputs": inputs.describe(),
        "openafis": {
            "repository": frozen.OPENAFIS_REPOSITORY,
            "commit": frozen.OPENAFIS_COMMIT,
            "tree": frozen.OPENAFIS_TREE,
            "license": frozen.OPENAFIS_LICENSE,
        },
        "route": {
            "extraction": list(frozen.EXTRACTION_ROUTE),
            "resize": f"{frozen.SENSOR_WIDTH}x{frozen.SENSOR_HEIGHT}",
            "resample": frozen.RESAMPLING_FILTER,
            "aspect_ratio_preserved": frozen.ASPECT_RATIO_PRESERVED,
            "device": frozen.SECUGEN_DEVICE,
            "template_format": frozen.SECUGEN_TEMPLATE_FORMAT,
        },
        "score_contract": {
            "native_type": frozen.SCORE_NATIVE_TYPE,
            "direction": frozen.SCORE_DIRECTION,
            "transform": frozen.SCORE_TRANSFORM,
            "threshold": frozen.SCORE_THRESHOLD,
            "formula": frozen.SCORE_FORMULA,
            "zero_is_a_valid_score": frozen.ZERO_IS_A_VALID_SCORE,
            "pair_orientation": dict(frozen.PAIR_ORIENTATION),
        },
        "extraction": extraction.describe(),
        "matching": matching.describe(),
        "complete": matching.complete,
        "outcome": frozen.OUTCOME_COMPLETE if matching.complete else "INCOMPLETE",
        "host": {"platform": platform.platform(), "python": platform.python_version()},
    }
    path = config.stage_root / "run-receipt.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- cli


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Stage 18A private reference runner")
    parser.add_argument(
        "command", choices=("status", "extract", "match", "run", "receipt"), help="which phase to run"
    )
    parser.add_argument("--limit", type=int, default=None, help="only the first N images/pairs (smoke runs)")
    parser.add_argument("--repeat-probe", action="store_true", help="extract twice and report byte equality")
    parser.add_argument("--no-resume", action="store_true", help="ignore what is already on disk")
    args = parser.parse_args(argv)

    inputs = load_stage18a_inputs()
    config = load_stage18a_config()
    config.ensure_layout()
    resume = not args.no_resume

    if args.command == "status":
        templates = read_template_index(config)
        outcomes = read_pair_outcomes(config)
        print(json.dumps(
            {
                "stage_root": str(config.stage_root),
                "inputs": inputs.describe(),
                "templates_recorded": len(templates),
                "templates_ok": sum(1 for record in templates.values() if record.ok),
                "pair_outcomes_stored": len(outcomes),
                "expected_pair_outcomes": frozen.EXPECTED_PAIR_OUTCOMES,
            },
            indent=2,
        ))
        return 0

    extraction = ExtractionSummary(0, 0, 0, 0, 0.0)
    if args.command in ("extract", "run"):
        images = inputs.images[: args.limit] if args.limit else None
        extraction = run_extraction_phase(
            inputs, config, images=images, repeat_probe=args.repeat_probe, resume=resume
        )
        print(json.dumps(extraction.describe(), indent=2))

    matching = MatchingSummary(len(inputs.pairs), 0, len(inputs.pairs), {}, 0.0)
    if args.command in ("match", "run"):
        pairs = inputs.pairs[: args.limit] if args.limit else None
        matching = run_matching_phase(inputs, config, pairs=pairs, resume=resume)
        print(json.dumps(matching.describe(), indent=2))

    if args.command in ("run", "receipt"):
        if args.command == "receipt":
            outcomes = read_pair_outcomes(config)
            counts: dict[str, int] = {}
            for outcome in outcomes:
                counts[outcome.status] = counts.get(outcome.status, 0) + 1
            stored_ids = {outcome.pair_id for outcome in outcomes}
            # Rebuilt from disk: the counts are real, the wall times were not
            # observed by this process and are published as null rather than 0.
            matching = MatchingSummary(
                expected=len(inputs.pairs),
                stored=len(outcomes),
                missing=sum(1 for pair in inputs.pairs if pair.pair_id not in stored_ids),
                status_counts=counts,
                wall_seconds=None,
            )
            templates = read_template_index(config)
            extraction = ExtractionSummary(
                attempted=len(templates),
                succeeded=sum(1 for record in templates.values() if record.ok),
                failed=sum(1 for record in templates.values() if not record.ok),
                reused=0,
                wall_seconds=None,
            )
        path = write_run_receipt(inputs, config, extraction, matching)
        print(f"receipt {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
