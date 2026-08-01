"""Tools every adapter may use, and no adapter has to reimplement.

Three of the four things a new external-tool adapter would otherwise have to get
right on its own live here: keeping scratch files inside the directories the
runner allotted, launching a subprocess without inheriting the developer's
environment or leaking a child process, and noticing that a pinned executable
was replaced mid-run.

Nothing in this package knows what a fingerprint is. It imports ``fpbench.core``
and the adapter contract, and nothing else — no protocol, no storage, no
decisions, no metrics — and there is a structural test that keeps it that way
(spec section 60).
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
