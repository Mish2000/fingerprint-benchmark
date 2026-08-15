"""G1 — the artifact and the runtime it will actually execute on.

The closure itself lives in
:mod:`fpbench.adapters.fingerprints_matching.runtime`, because the adapter has
to verify it before reporting itself ready and an adapter may import
``fpbench.core`` and itself and nothing else of fpbench. This module is the
stage's view of it: the same functions, under the name the Stage 15A evidence and
the experiment wrappers refer to.

Two questions, and the second one is the one with teeth.

The first is easy: are the bytes on this machine the bytes PyPI published for
``fingerprints-matching==0.1.0``? Both digests were written into
:mod:`fpbench.adapters.fingerprints_matching.identity` before anything was
fetched, so the download is checked against the record rather than the record
written from the download.

The second is that this candidate has no vendored runtime at all. It is 4,492
bytes of pure Python that calls OpenCV for every pixel operation it performs, and
it declares ``opencv-python`` with no version bound whatsoever. Whatever
``pip install fingerprints-matching`` resolves to on the day it is run *is* the
feature extractor, because the contours ``cv2.findContours`` returns are the
direct and only input to feature construction. A benchmark that let that float
could not reproduce its own results (docs/adr/0125).

So the runtime is frozen the way a vendor SDK would be: an exact interpreter, an
exact platform, an exact wheel for every installed distribution, each with a
SHA-256, in a wheelhouse this project holds, installed with ``--no-index`` into
an environment that never reaches the network again.

Nothing here downloads anything. Acquisition is a deliberate act with its own
command in :mod:`fpbench.experiments.stage15a_acquire`; this is the part that
says whether what arrived is what was expected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from fpbench.adapters.fingerprints_matching.runtime import (
    RUNTIME_SCHEMA,
    STORE_RELATIVE,
    ComponentCheck,
    RuntimeClosure,
    artifacts_directory,
    build_runtime_closure,
    check_artifacts,
    check_wheelhouse,
    file_sha256,
    inspect_installed_runtime,
    require_ready,
    resolve_store_root,
    runtime_directory,
    runtime_manifest_fingerprint,
    runtime_python,
    store_root,
    wheelhouse_directory,
)

__all__ = [
    "RUNTIME_SCHEMA",
    "STORE_RELATIVE",
    "ComponentCheck",
    "RuntimeClosure",
    "artifacts_directory",
    "build_runtime_closure",
    "check_artifacts",
    "check_wheelhouse",
    "file_sha256",
    "inspect_installed_runtime",
    "require_ready",
    "resolve_store_root",
    "runtime_directory",
    "runtime_manifest_fingerprint",
    "runtime_python",
    "store_root",
    "wheelhouse_directory",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "verify"
    closure = build_runtime_closure(repository_root=Path("."))
    if command == "verify":
        document = closure.as_document()
        document["runtime_manifest_fingerprint"] = runtime_manifest_fingerprint(closure)
        print(json.dumps(document, indent=2, sort_keys=True))
        return 0 if closure.gate_state == "PASS" else 1
    if command == "fingerprint":
        print(runtime_manifest_fingerprint(closure))
        return 0
    print(f"unknown command {command!r}; expected verify or fingerprint", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
