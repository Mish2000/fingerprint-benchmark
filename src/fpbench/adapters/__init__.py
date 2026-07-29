"""Algorithm-specific code, and the only place it is allowed to live.

Dependency rule: ``adapters`` may import ``core``. It must not import
``protocols``, ``storage`` or ``evaluation`` — an adapter that can see the
protocol can see the ground truth (docs/adr/0001, docs/adr/0010).
"""

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.errors import AdapterContractViolation, AdapterError
from fpbench.adapters.registry import (
    AdapterFactory,
    create_adapter,
    register_adapter,
    registered_adapters,
)

__all__ = [
    "ADAPTER_CONTRACT_VERSION",
    "AdapterContractViolation",
    "AdapterError",
    "AdapterFactory",
    "FingerprintAlgorithmAdapter",
    "create_adapter",
    "register_adapter",
    "registered_adapters",
]
