"""Fingerprint only code/configuration that can affect Stage 21B execution."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from fpbench.core.serialization import stable_hash
from fpbench.stage21b.errors import Stage21BPreflightError

__all__ = [
    "ExecutionSourceGuard",
    "ExecutionSourceSnapshot",
    "build_execution_source_snapshot",
    "execution_source_file_sha256s",
    "source_file_sha256",
    "verify_execution_source_snapshot",
]

_SOURCE_DIRECTORIES = (
    "src/fpbench/adapters",
    "src/fpbench/core",
    "src/fpbench/storage",
    "src/fpbench/imaging",
)
_SOURCE_FILES = (
    # The execution and integrity closure is explicit so changing the evidence
    # prose/publisher/status UI after all matcher calls cannot silently create a
    # new experimental identity.  Those files are content-hashed separately in
    # the final Git evidence.
    "src/fpbench/stage21b/constants.py",
    "src/fpbench/stage21b/errors.py",
    "src/fpbench/stage21b/models.py",
    "src/fpbench/stage21b/policy.py",
    "src/fpbench/stage21b/bindings.py",
    "src/fpbench/stage21b/prepared.py",
    "src/fpbench/stage21b/source_freeze.py",
    "src/fpbench/stage21b/adapters.py",
    "src/fpbench/stage21b/runner.py",
    "src/fpbench/stage21b/store.py",
    "src/fpbench/stage21b/preflight.py",
    "src/fpbench/stage21b/integrity.py",
    "src/fpbench/execution/blinding.py",
    "src/fpbench/execution/adapter_result_validation.py",
    "src/fpbench/protocols/cross_subject.py",
    "src/fpbench/experiments/flx_adapter.py",
    "src/fpbench/experiments/flx_failure_mapping.py",
    "configs/protocols/sd300_cross_subject_non_mated_v1.yaml",
    "configs/comparisons/final_baseline_roster_v1.yaml",
    "configs/imaging/canonical_gray8_500ppi_lanczos3_v1.yaml",
    "configs/stage21b/frozen_execution_v1.yaml",
)
_FLX_DIRECTORIES = ("src/fpbench/flx", "integrations/flx/worker")


@dataclass(frozen=True, slots=True)
class ExecutionSourceSnapshot:
    fingerprint: str
    revision: str
    file_sha256s: Mapping[str, str]

    def __post_init__(self) -> None:
        files = {
            str(path): str(digest).strip().lower()
            for path, digest in sorted(self.file_sha256s.items())
        }
        if not files or any(
            len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            for digest in files.values()
        ):
            raise ValueError("execution source snapshot contains an invalid digest")
        object.__setattr__(self, "file_sha256s", MappingProxyType(files))


@dataclass(slots=True)
class ExecutionSourceGuard:
    """Detect a mid-run patch without hashing the whole tree 73,500 times."""

    repository_root: Path
    snapshot: ExecutionSourceSnapshot
    private_adapter_config: Path
    private_adapter_config_sha256: str
    pair_manifest_hash: str
    pair_count: int = 73_500
    _stats: dict[str, tuple[int, int]] = field(init=False, repr=False)
    _private_stat: tuple[int, int] = field(init=False, repr=False)
    _invocations: int = field(init=False, default=0, repr=False)

    def __post_init__(self) -> None:
        self.repository_root = Path(self.repository_root).resolve()
        self.private_adapter_config = Path(self.private_adapter_config).resolve()
        verify_execution_source_snapshot(self.repository_root, self.snapshot)
        if _raw_sha256(self.private_adapter_config) != self.private_adapter_config_sha256:
            raise Stage21BPreflightError("private adapter config changed after preflight")
        self._stats = {
            relative: _stat_identity(self.repository_root / relative)
            for relative in self.snapshot.file_sha256s
        }
        self._private_stat = _stat_identity(self.private_adapter_config)

    def before_invocation(self, *, pair: Any, spec: Any) -> None:
        # Gate 21B-P1 is deliberately tested for every invocation.  This is a
        # binding check, not a re-generation or a method-specific subset.
        if spec.pair_count != self.pair_count or spec.expected_attempts != self.pair_count:
            raise Stage21BPreflightError("Stage 21B pair count changed before invocation")
        if spec.pair_manifest_hash != self.pair_manifest_hash:
            raise Stage21BPreflightError("Stage 21B pair-manifest binding changed")
        if pair.ordinal < 0 or pair.ordinal >= spec.pair_count:
            raise Stage21BPreflightError("pair ordinal is outside the frozen manifest")
        # Python source already imported by this process cannot silently change
        # its semantics.  A bounded stat scan still catches an operator editing
        # the closure during a long batch; a full content re-hash occurs at both
        # boundaries and every resume.
        self._invocations += 1
        if self._invocations == 1 or self._invocations % 256 == 0:
            for relative, expected in self._stats.items():
                if _stat_identity(self.repository_root / relative) != expected:
                    raise Stage21BPreflightError(
                        f"execution source changed during the run: {relative}"
                    )
            if _stat_identity(self.private_adapter_config) != self._private_stat:
                raise Stage21BPreflightError("private adapter config changed during the run")

    def after_batch(self, *, spec: Any) -> None:
        verify_execution_source_snapshot(self.repository_root, self.snapshot)
        if _raw_sha256(self.private_adapter_config) != self.private_adapter_config_sha256:
            raise Stage21BPreflightError("private adapter config changed during the run")


def build_execution_source_snapshot(
    *,
    repository_root: Path,
    algorithm_config: Path,
    private_adapter_config_sha256: str,
    runtime_identity_fingerprint: str,
    include_flx: bool,
    require_clean: bool,
) -> ExecutionSourceSnapshot:
    root = Path(repository_root).resolve()
    relative_hashes = execution_source_file_sha256s(
        repository_root=root,
        algorithm_config=algorithm_config,
        include_flx=include_flx,
    )
    revision = _git(root, "rev-parse", "HEAD").strip()
    if len(revision) != 40:
        raise Stage21BPreflightError("execution source is not on an identifiable git revision")
    if require_clean:
        changed = _changed_execution_paths(root, set(relative_hashes))
        if changed:
            raise Stage21BPreflightError(
                "execution-affecting source is not clean/frozen: " + ", ".join(changed[:8])
            )
    fingerprint = stable_hash(
        {
            "schema": "stage21b_execution_source_v1",
            "files": relative_hashes,
            "private_adapter_config_sha256": private_adapter_config_sha256,
            "runtime_identity_fingerprint": runtime_identity_fingerprint,
        },
        length=64,
    )
    return ExecutionSourceSnapshot(
        fingerprint=fingerprint,
        revision=revision,
        file_sha256s=relative_hashes,
    )


def execution_source_file_sha256s(
    *, repository_root: Path, algorithm_config: Path, include_flx: bool
) -> dict[str, str]:
    """Re-derive the complete route-specific execution-source closure.

    This is shared by preflight and the offline evidence verifier so a receipt
    cannot validate a self-consistent but truncated file map.
    """
    root = Path(repository_root).resolve()
    paths: set[Path] = set()
    for relative in _SOURCE_DIRECTORIES + (_FLX_DIRECTORIES if include_flx else ()):
        directory = root / relative
        if not directory.is_dir():
            raise Stage21BPreflightError(f"execution source directory is missing: {relative}")
        paths.update(path for path in directory.rglob("*.py") if path.is_file())
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise Stage21BPreflightError(f"execution source file is missing: {relative}")
        paths.add(path)
    config = Path(algorithm_config)
    config = config if config.is_absolute() else root / config
    if not config.is_file():
        raise Stage21BPreflightError(f"algorithm execution config is missing: {config}")
    paths.add(config.resolve())

    relative_hashes = {
        path.resolve().relative_to(root).as_posix(): source_file_sha256(path)
        for path in sorted(paths)
    }
    return dict(sorted(relative_hashes.items()))


def verify_execution_source_snapshot(
    repository_root: Path, snapshot: ExecutionSourceSnapshot
) -> None:
    root = Path(repository_root).resolve()
    changed = [
        relative
        for relative, expected in snapshot.file_sha256s.items()
        if not (root / relative).is_file()
        or source_file_sha256(root / relative) != expected
    ]
    if changed:
        raise Stage21BPreflightError(
            "execution-affecting source differs from the frozen run: "
            + ", ".join(changed[:8])
        )


def _changed_execution_paths(root: Path, execution_paths: set[str]) -> list[str]:
    output = _git(root, "status", "--porcelain", "--untracked-files=all")
    changed: list[str] = []
    for line in output.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].strip().strip('"').replace("\\", "/")
        if " -> " in name:
            name = name.split(" -> ", 1)[1]
        if name in execution_paths:
            changed.append(name)
    return sorted(changed)


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage21BPreflightError(f"cannot inspect git execution source: {exc}") from exc
    if completed.returncode:
        raise Stage21BPreflightError(
            f"git {' '.join(args)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout


def source_file_sha256(path: Path) -> str:
    """SHA-256 of one execution-source file, with CRLF normalised to LF.

    The alternative — hashing the checkout's raw bytes — makes the question
    "is this the code that produced the run?" depend on which platform checked
    the tree out.  ``core.autocrlf=true`` is set on the machine that runs these
    benchmarks and 95 of the 188 files in this closure are CRLF in its working
    copy while the index holds LF, so a raw digest would bind the six sealed
    result sets to one laptop: ``stage21b-verify`` would fail on CI, on Linux,
    and on any fresh checkout — the failure Stage 18A already paid for.

    Normalising is the same answer Stage 11A reached
    (``stage11a_finalization.source_file_sha256``) and it loses nothing worth
    keeping: a file whose only difference is its line endings is the same
    Python, the same YAML and the same execution semantics.
    """
    try:
        content = Path(path).read_bytes().replace(b"\r\n", b"\n")
    except OSError as exc:
        raise Stage21BPreflightError(
            f"cannot hash execution source {path}: {exc}"
        ) from exc
    return hashlib.sha256(content).hexdigest()


def _raw_sha256(path: Path) -> str:
    """Byte-exact digest, for the private local configuration only.

    That file is never committed and never verified from another checkout, so
    it is compared against itself on one machine and the raw bytes are the
    stricter check.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat_identity(path: Path) -> tuple[int, int]:
    try:
        value = Path(path).stat()
    except OSError as exc:
        raise Stage21BPreflightError(f"execution input is unavailable: {path}") from exc
    return value.st_size, value.st_mtime_ns
