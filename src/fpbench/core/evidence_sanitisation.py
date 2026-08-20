"""Keeping one machine's directory layout out of published evidence.

``evidence/README.md`` states the rule: a receipt carries "no personal or
biometric data: ... and no absolute path to anything". Several stage markers
assert it about themselves, as ``"absolute_paths_in_evidence": false``.

Both were true of the *shape* of the documents and false of one of their
values. ``evidence/stage11a-verifinger-2025_2-preflight/runtime-identity.json``
published seven module paths beginning ``C:\\Users\\<name>\\.cache\\...`` — the
author's home directory, in a file whose own marker declared there were none.
Nothing checked, because the existing sanitiser
(:func:`fpbench.core.research_models.require_sanitised`) is scoped to research
receipts and never ran over stage evidence.

Two functions, and the split matters:

:func:`redact_absolute_paths` is what a *producer* calls. It replaces the
machine-specific prefix of a known root with a stable placeholder, so the part
of the path that carries information — which artifact, which subdirectory,
which file — survives. Deleting the whole string would have been safer and
useless: "the engine loaded a DLL" is not evidence of which DLL.

:func:`find_absolute_paths` is what a *checker* calls. It walks a rendered
document and reports every remaining absolute path, so the claim in a marker is
tested rather than asserted.
"""

from __future__ import annotations

import re
from typing import Any, Iterator, Mapping, Sequence

__all__ = [
    "ARTIFACT_STORE_PLACEHOLDER",
    "HOME_PLACEHOLDER",
    "ROOT_PLACEHOLDER",
    "WORKSPACE_PLACEHOLDER",
    "find_absolute_paths",
    "redact_absolute_paths",
]

#: What replaces the machine-specific prefix of the third-party artifact cache.
ARTIFACT_STORE_PLACEHOLDER = "<third_party_artifact_store>"
#: What replaces a user's home directory when nothing more specific applies.
HOME_PLACEHOLDER = "<home>"
#: What replaces the run workspace root.
WORKSPACE_PLACEHOLDER = "<workspace>"
#: What replaces a volume or mount marker no more specific rule claimed.
ROOT_PLACEHOLDER = "<root>"

#: A Windows drive path, a UNC path, or a POSIX path under a real root. A bare
#: ``/`` prefix is deliberately *not* matched: too many legitimate strings in
#: this repository start with one (``/``-separated relative locators, licence
#: prose), and the roots below are what an absolute path actually begins with.
#:
#: The lookbehind is what keeps ``https://example.org`` out of it. Without it
#: the ``s:/`` inside every URL in ``evidence/`` reads as a drive letter, and a
#: check that fires on forty published locators is a check somebody turns off.
_ABSOLUTE = re.compile(
    r"""(?xi)
    (?:
        (?<![A-Z])[A-Z]:[\\/]       # C:\ or C:/, not the tail of a URL scheme
      | \\\\[^\\/\s"]+[\\/]         # \\server\share
      | /(?:home|Users|root|mnt|opt|var|tmp|usr)/   # POSIX, under a real root
    )
    [^"'\s]*
    """
)

#: Prefixes replaced in order, longest-first: the artifact store lives *inside*
#: the home directory, and redacting the home first would throw away the part
#: that says which artifact.
_ORDERED_ROOTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"(?i)(?:[A-Z]:[\\/]|/)"
            r"(?:[^\\/\s\"']+[\\/]){0,8}?"
            r"\.cache[\\/]fpbench[\\/]third_party[\\/]"
        ),
        ARTIFACT_STORE_PLACEHOLDER + "/",
    ),
    (
        # The leading separator is consumed too, so a POSIX home becomes
        # ``<home>/...`` rather than ``/<home>/...`` — which would still read as
        # an absolute path and be re-flagged on the next check.
        re.compile(r"(?i)(?:[A-Z]:)?[\\/]?(?:Users|home)[\\/][^\\/\s\"']+[\\/]"),
        HOME_PLACEHOLDER + "/",
    ),
    (
        # The catch-all, and the reason redaction and detection cannot drift
        # apart: anything :data:`_ABSOLUTE` still recognises as rooted loses its
        # root here. Only the volume marker goes — ``D:\``, ``\\host\share\``,
        # ``/mnt/c/`` — because the tail is the part that says *what* the file
        # was, and a placeholder with nothing after it is not evidence.
        re.compile(
            r"""(?xi)
            (?:
                (?<![A-Z])[A-Z]:[\\/]
              | \\\\[^\\/\s"']+[\\/](?:[^\\/\s"']+[\\/])?
              | /(?:mnt|media)/[^/\s"']+/
              | /(?:root|opt|var|tmp|usr)/
            )
            """
        ),
        ROOT_PLACEHOLDER + "/",
    ),
)


def _normalise_separators(value: str) -> str:
    """Backslashes become forward slashes once a path has been redacted.

    A redacted path is no longer a path anybody opens; it is a description. A
    description that still says ``\\`` would be re-flagged by
    :func:`find_absolute_paths` on the next run and would read differently
    depending on the machine that produced it, which is the whole problem.
    """
    return value.replace("\\", "/")


def redact_absolute_paths(value: Any, *, extra_roots: Mapping[str, str] = {}) -> Any:
    """Return ``value`` with every machine-specific path prefix replaced.

    Recurses through mappings and sequences, so a caller hands over a whole
    document rather than remembering which fields hold paths — the failure this
    exists for was a field nobody thought of as a path field.

    ``extra_roots`` maps a literal prefix (a workspace root, a dataset root) to
    its placeholder, and is applied before the built-in roots.
    """
    if isinstance(value, Mapping):
        return {
            key: redact_absolute_paths(item, extra_roots=extra_roots)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        redacted = [
            redact_absolute_paths(item, extra_roots=extra_roots) for item in value
        ]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    if not isinstance(value, str):
        return value

    text = value
    for root, placeholder in extra_roots.items():
        for spelling in {root, root.replace("\\", "/"), root.replace("/", "\\")}:
            if spelling and spelling in text:
                text = text.replace(spelling, placeholder)
    for pattern, placeholder in _ORDERED_ROOTS:
        text = pattern.sub(placeholder, text)
    if text != value:
        text = _normalise_separators(text)
    return text


def find_absolute_paths(
    value: Any, *, path: str = "document"
) -> tuple[tuple[str, str], ...]:
    """Every ``(location, text)`` in ``value`` that still looks absolute.

    Keys are walked as well as values: a mapping keyed by filename is just as
    much a leak as one that stores the filename beside it.
    """
    return tuple(_walk(value, path))


def _walk(value: Any, path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _walk(str(key), f"{path}.<key>")
            yield from _walk(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")
        return
    if isinstance(value, str):
        match = _ABSOLUTE.search(value)
        if match is not None:
            yield path, match.group(0)
