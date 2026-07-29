"""Errors raised about adapters, as opposed to by them.

An adapter reports *expected* trouble — a template it could not extract, an
image its matcher rejected — as a ``RawMatchResult.failed()``, never as an
exception. These exceptions cover the other case: the adapter itself is wrong.
"""

from __future__ import annotations

from fpbench.core.errors import FpbenchError

__all__ = ["AdapterError", "AdapterContractViolation"]


class AdapterError(FpbenchError):
    """Base class for adapter-level faults."""


class AdapterContractViolation(AdapterError):
    """An adapter returned something the contract forbids.

    A NaN score, a success that also carries a failure, a score running in the
    opposite direction to the one its descriptor declares. The runner records
    this as an ``INTERNAL_ERROR`` result with ``details.kind =
    adapter_contract_violation`` and carries on: one broken adapter response
    must not destroy the other 5,999 comparisons in a run (docs/adr/0006).
    """
