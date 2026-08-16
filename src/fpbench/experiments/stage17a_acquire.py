"""Fetching the two published distributions, and nothing else.

Only PyPI, only 1.0.6, and both digests checked against the record written down
before the fetch. The repository is not acquired: it is not this stage's
authority, and downloading it would invite reading it as one.

Nothing here decides anything. Whether the bytes are sufficient is G1, and what
the module does with them is G2 — both in
:mod:`fpbench.experiments.stage17a_score_contract`.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

from fpbench.core.stage17a_errors import Stage17AArtifactIdentityError
from fpbench.experiments import stage17a_identity as frozen
from fpbench.experiments import stage17a_score_contract as gate

__all__ = ["PYPI_FILES", "acquire", "main"]

PYPI_FILES: dict[str, tuple[str, str]] = {
    frozen.SOURCE_ARTIFACT_NAME: (
        frozen.SOURCE_ARTIFACT_SHA256,
        "https://files.pythonhosted.org/packages/2d/d4/"
        "271c7b5a71889f6f6dbc963bfdef0dd57b82eff06223f8966f6b6dc7e672/"
        "fingerprintMatcher-1.0.6.tar.gz",
    ),
    frozen.RUNTIME_ARTIFACT_NAME: (
        frozen.RUNTIME_ARTIFACT_SHA256,
        "https://files.pythonhosted.org/packages/26/f1/"
        "b110df17e1b51adafb18e214c43301885cf16cd4ed68aee47cb4cbe20efc/"
        "fingerprintMatcher-1.0.6-py3-none-any.whl",
    ),
}


def acquire(
    *, repository_root: Path | None = None, force: bool = False, strict: bool = True
) -> dict[str, Any]:
    """Fetch both distributions into the store, refusing anything unexpected."""
    directory = gate.store_root(repository_root=repository_root) / "artifacts"
    directory.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for name, (expected, url) in PYPI_FILES.items():
        target = directory / name
        if target.is_file() and not force:
            payload = target.read_bytes()
            cached = True
        else:
            request = urllib.request.Request(
                url, headers={"User-Agent": "fpbench-research"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = response.read()
            target.write_bytes(payload)
            cached = False
        observed = hashlib.sha256(payload).hexdigest()
        records.append(
            {
                "name": name,
                "source": "pypi",
                "size_bytes": len(payload),
                "sha256": observed,
                "matches": observed == expected,
                "already_present": cached,
            }
        )

    wrong = [record["name"] for record in records if not record["matches"]]
    if wrong and strict:
        raise Stage17AArtifactIdentityError(
            "these downloads are not the recorded bytes: " + ", ".join(wrong)
        )
    return {
        "candidate_id": frozen.CANDIDATE_ID,
        "package": frozen.PACKAGE_REQUIREMENT,
        "repository_acquired": False,
        "why_repository_not_acquired": frozen.WHY_NOT_THE_REPOSITORY,
        "distributions": records,
        "mismatches": wrong,
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    argv = list(sys.argv[1:] if argv is None else argv)
    report = acquire(
        repository_root=Path("."), force="--force" in argv, strict=False
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["mismatches"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
