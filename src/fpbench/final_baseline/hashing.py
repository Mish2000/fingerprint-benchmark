"""Line-ending-stable hashing for final-baseline text artifacts.

Stage 21B's source freeze already learned this lesson: hashing raw bytes binds
a fingerprint to one machine's checkout, because a ``core.autocrlf=true``
working tree materialises shared text files with CRLF. The reporting source
fingerprint and evidence content hashes must reproduce on every machine that
runs ``verify``, so text bytes are normalised to LF before hashing — and only
line endings; every other byte still counts.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["normalized_text_sha256"]


def normalized_text_sha256(path: Path) -> str:
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()
