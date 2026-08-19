"""Looking up an adapter by identifier.

The point of the registry is that nothing else in the codebase needs to know
which algorithms exist. The runner asks for an adapter by id and gets one; it
contains no ``if algorithm_id == ...`` anywhere, and neither does anything else
outside this module (docs/adr/0007).

Deliberately a plain dict rather than pip entry points. Dynamic discovery buys
nothing while the answer is a handful of adapters in this repository, and it
can replace this lookup later without a single adapter changing.
"""

from __future__ import annotations

from typing import Callable, Mapping

from fpbench.adapters.base import (
    SUPPORTED_ADAPTER_CONTRACT_VERSIONS,
    FingerprintAlgorithmAdapter,
)
from fpbench.adapters.errors import AdapterContractViolation
from fpbench.core.errors import ConfigurationError
from fpbench.core.identifiers import validate_id

__all__ = [
    "AdapterFactory",
    "ADAPTERS",
    "register_adapter",
    "create_adapter",
    "registered_adapters",
]

AdapterFactory = Callable[[Mapping[str, object]], FingerprintAlgorithmAdapter]

ADAPTERS: dict[str, AdapterFactory] = {}


def register_adapter(adapter_id: str, factory: AdapterFactory) -> None:
    """Make ``adapter_id`` resolvable.

    Raises:
        ConfigurationError: if the id is already taken. Silently replacing a
            registration would let an import order decide which matcher a run
            actually used.
    """
    validate_id(adapter_id)
    if adapter_id in ADAPTERS:
        raise ConfigurationError(f"adapter {adapter_id!r} is already registered")
    ADAPTERS[adapter_id] = factory


def create_adapter(
    adapter_id: str, config: Mapping[str, object] | None = None
) -> FingerprintAlgorithmAdapter:
    """Build the adapter registered under ``adapter_id``, and check it is it.

    Three things are verified before the adapter is handed back, because each of
    them would otherwise surface as a puzzle much later:

    * the adapter's descriptor names the id it was looked up under. A factory
      registered under the wrong key would produce a run whose manifest says one
      algorithm and whose results say another;
    * the contract version it declares is one this harness drives;
    * the descriptor is the same object twice running. A descriptor rebuilt per
      access — with a timestamp in it, say — would change the algorithm
      fingerprint mid-run, and the failure would look like corrupt results.

    Raises:
        ConfigurationError: unknown id, or a factory that returned the wrong one.
        AdapterContractViolation: an unsupported contract version, an unstable
            descriptor, or something that is not an adapter at all.
    """
    _ensure_builtin_adapters()
    try:
        factory = ADAPTERS[adapter_id]
    except KeyError:
        raise ConfigurationError(
            f"unknown adapter {adapter_id!r}; available: {sorted(ADAPTERS)}"
        ) from None

    adapter = factory(dict(config or {}))
    if not isinstance(adapter, FingerprintAlgorithmAdapter):
        raise AdapterContractViolation(
            f"the factory for {adapter_id!r} returned "
            f"{type(adapter).__name__}, not a FingerprintAlgorithmAdapter"
        )

    descriptor = adapter.descriptor
    if descriptor.adapter_id != adapter_id:
        raise ConfigurationError(
            f"adapter {adapter_id!r} describes itself as "
            f"{descriptor.adapter_id!r}; a run built from this registry would "
            "record an algorithm it did not use"
        )
    if descriptor.adapter_contract_version not in SUPPORTED_ADAPTER_CONTRACT_VERSIONS:
        raise AdapterContractViolation(
            f"adapter {adapter_id!r} implements contract version "
            f"{descriptor.adapter_contract_version!r}; this harness drives "
            f"{sorted(SUPPORTED_ADAPTER_CONTRACT_VERSIONS)}"
        )
    if adapter.descriptor != descriptor:
        raise AdapterContractViolation(
            f"adapter {adapter_id!r} returns a different descriptor on each "
            "access; an algorithm's identity must be stable for the lifetime of "
            "the adapter"
        )
    return adapter


def registered_adapters() -> tuple[str, ...]:
    """Every adapter id currently resolvable, sorted."""
    _ensure_builtin_adapters()
    return tuple(sorted(ADAPTERS))


def _ensure_builtin_adapters() -> None:
    """Register the adapters shipped with the project, on first use.

    Imported lazily so that an adapter with heavy or platform-specific
    dependencies never makes ``import fpbench.adapters`` expensive — or
    impossible — for someone running a different algorithm.
    """
    if "dummy_sha256" not in ADAPTERS:
        from fpbench.adapters.dummy.adapter import DummyShaAdapter

        register_adapter("dummy_sha256", DummyShaAdapter.from_config)

    if "sourceafis_java_subprocess" not in ADAPTERS:
        # Registering it does not require Java. The adapter reports its own
        # environment as UNAVAILABLE when the JVM or the bridge jar is missing, so
        # listing the registry stays cheap and never fails on a machine that has no
        # JDK installed.
        from fpbench.adapters.sourceafis_java.adapter import SourceAfisJavaAdapter

        register_adapter(
            "sourceafis_java_subprocess", SourceAfisJavaAdapter.from_config
        )

    if "nbis_mindtct_bozorth3_subprocess" not in ADAPTERS:
        # Registering it does not require NBIS, and importing the package costs
        # nothing. Unlike the two above, this adapter has no default paths at
        # all: it must be told where its two executables and its build manifest
        # are, because a bare ``mindtct`` would mean whatever this machine's PATH
        # happens to say (docs/adr/0048). Building it from an empty configuration
        # therefore raises, which is the correct answer to "run NBIS from
        # nowhere".
        from fpbench.adapters.nbis.adapter import NbisAdapter

        register_adapter("nbis_mindtct_bozorth3_subprocess", NbisAdapter.from_config)

    if "nbis_mindtct_openafis_subprocess" not in ADAPTERS:
        # Algorithm 5. Shares the NBIS route's extractor and its build manifest,
        # and differs from it only in the matcher — which is exactly why both are
        # registered separately rather than one growing a "matcher" setting: a
        # setting that changes which matcher produced a score would let two
        # different algorithms share one identity (docs/adr/0135).
        from fpbench.adapters.openafis.adapter import OpenAfisAdapter

        register_adapter("nbis_mindtct_openafis_subprocess", OpenAfisAdapter.from_config)

    if "nbis_mindtct_openafis_capacity_extended_subprocess" not in ADAPTERS:
        # Stage 19B. The same route against an OpenAFIS build whose upper
        # minutiae bound is disabled, and therefore a *different identity*: a
        # score from a modified build must not be attributed to upstream
        # (docs/adr/0136). Registered separately rather than as a setting of the
        # one above, for the same reason the two NBIS routes are separate.
        from fpbench.adapters.openafis.capacity_extended import (
            OpenAfisCapacityExtendedAdapter,
        )

        register_adapter(
            "nbis_mindtct_openafis_capacity_extended_subprocess",
            OpenAfisCapacityExtendedAdapter.from_config,
        )

    if "nbis_mindtct_mcc_sdk_v2_subprocess" not in ADAPTERS:
        # Stage 20B. The same certified extractor again, into the official
        # unmodified MCC SDK v2.0 rather than into BOZORTH3 or OpenAFIS.
        # Registered separately for the third time and for the third time for
        # the same reason: a setting that changed which matcher produced a score
        # would let several algorithms share one identity (docs/adr/0137).
        from fpbench.adapters.mcc.adapter import MccSdkAdapter

        register_adapter("nbis_mindtct_mcc_sdk_v2_subprocess", MccSdkAdapter.from_config)

    if "verifinger_java_subprocess" not in ADAPTERS:
        # Registering it requires neither Java, nor a licence, nor 4.7 GB of
        # vendor SDK. The adapter reports its own environment as UNAVAILABLE
        # when the installation, the licence or the bridge jar is missing, so
        # listing the registry stays cheap on a machine that has none of them —
        # which is every CI runner, by design (spec section 37).
        from fpbench.adapters.verifinger_java.adapter import VeriFingerJavaAdapter

        register_adapter("verifinger_java_subprocess", VeriFingerJavaAdapter.from_config)

    if "fingerprints_matching_subprocess" not in ADAPTERS:
        # Registering it needs neither OpenCV nor the frozen runtime. Unlike the
        # four above, this algorithm's dependencies are not the adapter's own:
        # the pinned numpy and OpenCV live in an environment outside the
        # repository, and importing fpbench must never require them.
        from fpbench.adapters.fingerprints_matching.adapter import (
            FingerprintsMatchingAdapter,
        )

        register_adapter(
            "fingerprints_matching_subprocess", FingerprintsMatchingAdapter.from_config
        )
