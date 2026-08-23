"""Rebuild the Stage 19A, 19B and 20B markers from the evidence beside them.

A marker that was re-fingerprinted but not rebuilt is a document its own builder
could not have produced: the source fingerprint says "this is the tree that
verified the run", and the condition map beside it is the one an older builder
computed. That middle state is worse than either end — a reader checking the
marker against the code finds a fingerprint that matches and a body that does
not.

So the markers are *rebuilt*, from the published documents that were their
inputs:

.. code-block:: text

    gate documents + canonical-run-binding + result-integrity + diagnostics
        -> build_stage..._finalization(created_utc=<now>)
        -> marker

Nothing about any run changes. The run's own measurements are in the binding and
the integrity document, and those are untouched — this only re-derives the
document that *concludes* from them, with the conditions the current builder
checks. ``created_utc`` is the moment of re-issue, because that is when the
document was written; the run's own timestamps live in the evidence it reads.

``tests/contract/test_markers_are_rebuildable.py`` then holds the property this
script establishes: every committed marker equals its builder's output from the
published evidence, byte for byte, with the marker's own ``created_utc`` fed
back in as the clock.

Usage::

    python scripts/reissue_stage19_20_markers.py [--at 2026-08-23T12:00:00Z]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _read(directory: Path, name: str) -> dict[str, Any]:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _hashes(directory: Path, names: tuple[str, ...]) -> dict[str, str]:
    import hashlib

    return {
        name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
        for name in names
    }


def _rebuild_19a(directory: Path, created_utc: str) -> dict[str, Any]:
    from fpbench.experiments import stage19a_identity as frozen
    from fpbench.experiments.stage19a_finalization import build_stage19a_finalization

    return build_stage19a_finalization(
        repository_root=REPOSITORY_ROOT,
        binding=_read(directory, "canonical-run-binding.json"),
        diagnostics={},
        evidence_hashes=_hashes(directory, tuple(frozen.EVIDENCE_DOCUMENTS)),
        created_utc=created_utc,
    )


def _rebuild_19b(directory: Path, created_utc: str) -> dict[str, Any]:
    from fpbench.experiments.stage19b_finalization import (
        EVIDENCE_DOCUMENTS,
        build_stage19b_finalization,
    )

    return build_stage19b_finalization(
        repository_root=REPOSITORY_ROOT,
        gate_a=_read(directory, "gate-a-inertness.json"),
        binding=_read(directory, "canonical-run-binding.json"),
        translator_inertness=_read(directory, "gate-a-inertness.json").get(
            "translator_inertness", {}
        ),
        evidence_hashes=_hashes(directory, tuple(EVIDENCE_DOCUMENTS)),
        created_utc=created_utc,
    )


def _rebuild_20b(directory: Path, created_utc: str) -> dict[str, Any]:
    from fpbench.experiments import stage20b_identity as frozen
    from fpbench.experiments.stage20b_finalization import build_stage20b_finalization

    return build_stage20b_finalization(
        repository_root=REPOSITORY_ROOT,
        gate_a=_read(directory, "gate-a-bridge-reproduction.json"),
        gate_b=_read(directory, "gate-b-mindtct-parity.json"),
        binding=_read(directory, "canonical-run-binding.json"),
        integrity=_read(directory, "result-integrity.json"),
        diagnostics=_read(directory, "diagnostic-report.json"),
        evidence_hashes=_hashes(directory, tuple(frozen.EVIDENCE_DOCUMENTS)),
        created_utc=created_utc,
    )


#: ``label -> (evidence directory, marker file, rebuild)``. In order, because
#: 19B binds 19A's fingerprint and 20B binds 19B's.
STAGES: tuple[tuple[str, str, str, Callable[[Path, str], Mapping[str, Any]]], ...] = (
    (
        "19A",
        "evidence/stage19a-mindtct-openafis",
        "stage-19a-finalization.json",
        _rebuild_19a,
    ),
    (
        "19B",
        "evidence/stage19b-openafis-capacity-extended",
        "stage-19b-finalization.json",
        _rebuild_19b,
    ),
    (
        "20B",
        "evidence/stage20b-mindtct-mcc-canonical500-raw",
        "stage-20b-finalization.json",
        _rebuild_20b,
    ),
)


def render(marker: Mapping[str, Any]) -> bytes:
    """The bytes a marker is stored as, LF on every platform."""
    return (
        json.dumps(dict(marker), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--at",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        help="the created_utc to stamp on the rebuilt markers",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild and report, without writing anything",
    )
    args = parser.parse_args(argv)

    for label, relative, name, rebuild in STAGES:
        directory = REPOSITORY_ROOT / relative
        path = directory / name
        before = json.loads(path.read_text(encoding="utf-8"))
        created = before["created_utc"] if args.check else args.at
        marker = dict(rebuild(directory, created))

        changed = sorted(
            key
            for key in set(before) | set(marker)
            if before.get(key) != marker.get(key)
        )
        print(f"Stage {label}")
        print(f"   fields that differ: {changed or 'none'}")
        if args.check:
            continue
        path.write_bytes(render(marker))
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
    raise SystemExit(main())
