"""Fetching what Stage 16A reads, from the locators upstream itself publishes.

Three kinds of bytes, all of them self-service and none of them entering Git:

.. code-block:: text

    artifacts/    the two PyPI distributions for fingerflow 3.0.1
    checkpoints/  the nine published weights, from Dropbox and Google Drive
    sources/      the upstream files this stage parses, at the pinned commit

Every one of them is checked against a digest written down *before* the fetch, so
a download is measured against the record rather than the record written from
the download. That ordering is the whole point: the opposite way round, a
corrupted or substituted file simply redefines what the artifact is.

Two of the README's Google Drive links are dead. ``CoarseNet`` and ``FineNet``
answer HTTP 404 on ``/uc``, on ``/file/d/`` and on ``drive.usercontent`` alike,
and the Dropbox mirrors published beside them in the same README serve both. The
locator recorded for each checkpoint is therefore the one that actually served
it, not the one listed first (docs/adr/0129).

Google Drive serves anything large behind an HTML confirmation form rather than
as a download, so :func:`_drive_url` resolves that form once and posts its own
fields back. That is not a bypass of anything — the form is what a browser would
submit, and the small VerifyNet weights come straight down without it.

This module downloads. It does not decide anything: whether the bytes are
sufficient is G1's question, in :mod:`fpbench.experiments.stage16a_artifacts`.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from fpbench.core.stage16a_errors import Stage16AArtifactIdentityError
from fpbench.experiments import stage16a_artifacts as artifacts
from fpbench.experiments import stage16a_identity as frozen

__all__ = [
    "USER_AGENT",
    "PYPI_FILES",
    "FetchOutcome",
    "acquire_distributions",
    "acquire_checkpoints",
    "acquire_sources",
    "acquire_all",
    "main",
]

#: Drive's confirmation form is served to browsers and withheld from clients that
#: do not look like one. Nothing here depends on being mistaken for a person; the
#: header is what makes the *documented* download path work at all.
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

#: The two distribution URLs PyPI publishes for 3.0.1.
PYPI_FILES: dict[str, str] = {
    frozen.SOURCE_ARTIFACT_NAME: (
        "https://files.pythonhosted.org/packages/a0/c9/"
        "594918a5cf620efd5c6dff19d7426e33fa402d43168a1ef90974e626788f/"
        "fingerflow-3.0.1.tar.gz"
    ),
    frozen.RUNTIME_ARTIFACT_NAME: (
        "https://files.pythonhosted.org/packages/ac/05/"
        "45d2e06846977483c73a95e9efd52b3878adf83fb57b36fbdecc42a90f5f/"
        "fingerflow-3.0.1-py3-none-any.whl"
    ),
}

_RAW_GITHUB = "https://raw.githubusercontent.com/jakubarendac/fingerflow"


@dataclass(frozen=True, slots=True)
class FetchOutcome:
    """What one fetch produced, measured against what was expected."""

    name: str
    target: Path
    expected_sha256: str
    observed_sha256: str
    size_bytes: int
    source: str
    skipped: bool

    @property
    def matches(self) -> bool:
        return self.observed_sha256 == self.expected_sha256

    def as_document(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "size_bytes": self.size_bytes,
            "sha256": self.observed_sha256,
            "matches": self.matches,
            "already_present": self.skipped,
        }


def _open(url: str):
    return urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=300
    )


def _drive_url(file_id: str) -> str:
    """Resolve Drive's interstitial confirm form, which large files always serve."""
    direct = (
        f"https://drive.usercontent.google.com/download?id={file_id}&export=download"
    )
    with _open(direct) as response:
        if "text/html" not in response.headers.get("Content-Type", ""):
            return direct
        page = response.read().decode("utf-8", "replace")
    action = re.search(r'<form[^>]+action="([^"]+)"', page)
    fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', page))
    base = (action.group(1) if action else direct).replace("&amp;", "&")
    joiner = "&" if "?" in base else "?"
    return base + joiner + urllib.parse.urlencode(fields)


def _stream(url: str, target: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    with _open(url) as response, partial.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    partial.replace(target)
    return digest.hexdigest(), size


def _fetch(
    *, name: str, url: str, target: Path, expected: str, source: str, force: bool
) -> FetchOutcome:
    if target.is_file() and not force:
        observed = hashlib.sha256(target.read_bytes()).hexdigest()
        return FetchOutcome(
            name=name,
            target=target,
            expected_sha256=expected,
            observed_sha256=observed,
            size_bytes=target.stat().st_size,
            source=source,
            skipped=True,
        )
    observed, size = _stream(url, target)
    return FetchOutcome(
        name=name,
        target=target,
        expected_sha256=expected,
        observed_sha256=observed,
        size_bytes=size,
        source=source,
        skipped=False,
    )


def acquire_distributions(
    *, repository_root: Path | None = None, force: bool = False
) -> tuple[FetchOutcome, ...]:
    """The wheel and the sdist, checked against the digests PyPI publishes."""
    directory = artifacts.store_root(repository_root=repository_root) / "artifacts"
    expected = {
        frozen.SOURCE_ARTIFACT_NAME: frozen.SOURCE_ARTIFACT_SHA256,
        frozen.RUNTIME_ARTIFACT_NAME: frozen.RUNTIME_ARTIFACT_SHA256,
    }
    return tuple(
        _fetch(
            name=name,
            url=url,
            target=directory / name,
            expected=expected[name],
            source="pypi",
            force=force,
        )
        for name, url in PYPI_FILES.items()
    )


def acquire_checkpoints(
    *, repository_root: Path | None = None, force: bool = False
) -> tuple[FetchOutcome, ...]:
    """The nine published weights, each from the locator that serves it."""
    directory = artifacts.store_root(repository_root=repository_root) / "checkpoints"
    outcomes: list[FetchOutcome] = []
    for record in frozen.CHECKPOINTS:
        locator = str(record["locator"])
        source = str(record["source"])
        url = _drive_url(locator) if source == "google_drive" else locator
        outcomes.append(
            _fetch(
                name=str(record["stored_as"]),
                url=url,
                target=directory / str(record["stored_as"]),
                expected=str(record["sha256"]),
                source=source,
                force=force,
            )
        )
    return tuple(outcomes)


def acquire_sources(
    *, repository_root: Path | None = None, force: bool = False
) -> tuple[FetchOutcome, ...]:
    """The upstream files G2 parses, at :data:`stage16a_identity.UPSTREAM_COMMIT`."""
    directory = artifacts.store_root(repository_root=repository_root) / "sources"
    return tuple(
        _fetch(
            name=relative,
            url=f"{_RAW_GITHUB}/{frozen.UPSTREAM_COMMIT}/{relative}",
            target=directory / relative,
            expected=expected,
            source="github_raw",
            force=force,
        )
        for relative, expected in frozen.UPSTREAM_SOURCE_DIGESTS.items()
    )


def acquire_all(
    *, repository_root: Path | None = None, force: bool = False, strict: bool = True
) -> dict[str, Any]:
    """Everything, in one pass, refusing bytes that are not the recorded ones."""
    groups = {
        "distributions": acquire_distributions(
            repository_root=repository_root, force=force
        ),
        "sources": acquire_sources(repository_root=repository_root, force=force),
        "checkpoints": acquire_checkpoints(
            repository_root=repository_root, force=force
        ),
    }
    wrong = [
        outcome.name
        for outcomes in groups.values()
        for outcome in outcomes
        if not outcome.matches
    ]
    if wrong and strict:
        raise Stage16AArtifactIdentityError(
            "these downloads are not the recorded bytes: " + ", ".join(wrong)
        )
    return {
        "candidate_id": frozen.CANDIDATE_ID,
        "upstream_commit": frozen.UPSTREAM_COMMIT,
        "vendor_or_author_request_required": False,
        "groups": {
            group: [outcome.as_document() for outcome in outcomes]
            for group, outcomes in groups.items()
        },
        "mismatches": wrong,
        "total_bytes": sum(
            outcome.size_bytes for outcomes in groups.values() for outcome in outcomes
        ),
    }


def _selected(argv: Iterable[str]) -> set[str]:
    wanted = {a for a in argv if not a.startswith("-")}
    return wanted or {"all"}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator tool
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv
    wanted = _selected(argv)
    root = Path(".")

    if wanted == {"all"}:
        report = acquire_all(repository_root=root, force=force, strict=False)
    else:
        groups: dict[str, Any] = {}
        if "distributions" in wanted:
            groups["distributions"] = acquire_distributions(
                repository_root=root, force=force
            )
        if "sources" in wanted:
            groups["sources"] = acquire_sources(repository_root=root, force=force)
        if "checkpoints" in wanted:
            groups["checkpoints"] = acquire_checkpoints(
                repository_root=root, force=force
            )
        report = {
            "groups": {
                name: [o.as_document() for o in outcomes]
                for name, outcomes in groups.items()
            },
            "mismatches": [
                o.name for outcomes in groups.values() for o in outcomes if not o.matches
            ],
        }

    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report.get("mismatches") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
