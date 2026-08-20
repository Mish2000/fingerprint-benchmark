"""Hashing repository source so the answer does not depend on the checkout.

A stage's source fingerprint answers "is the code in this tree the code that
produced the published run?". Hashing the checkout's raw bytes answers a
different question — "is the code in this tree, *materialised the way this
machine materialises text*, the code that produced the run?" — and the two
diverge the moment a Windows checkout with ``core.autocrlf=true`` meets a Linux
one. The same commit then has two fingerprints, and a gate that was green on the
machine that published it goes red everywhere else.

``.gitattributes`` pins some paths to LF, which fixes it for those paths and
leaves every path nobody remembered exposed. This normalises at the point of
hashing instead, so the property holds whether or not a path was remembered.

**Why this module re-exports rather than defines.**
:func:`fpbench.experiments.stage19_result_integrity.canonical_source_sha256` is
the original implementation, and that file is inside Stage 19A's and Stage 19B's
own ``_SOURCE_FILES``: editing it — even to move a function out — changes both
published markers. Two copies of one hash function would be worse than an
awkward import, because the day they drift is the day two stages disagree about
what the same file hashes to.
"""

from __future__ import annotations

from fpbench.experiments.stage19_result_integrity import canonical_source_sha256

__all__ = ["canonical_source_sha256"]
