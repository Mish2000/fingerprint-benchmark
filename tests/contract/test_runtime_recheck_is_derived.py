"""``rechecked_per_comparison`` is read off the adapter, not asked for.

The research content closure publishes whether the adapter re-verifies its
pinned runtime before every comparison. The value came from
``getattr(adapter, "rechecks_runtime_per_comparison", False)`` over an attribute
no adapter has ever defined, so every closure published ``false`` — while all
six adapters call ``check_runtime_integrity()`` inside ``compare``. A provenance
claim that understates is still a claim that is wrong.

:func:`fpbench.adapters.runtime_recheck.rechecks_runtime_per_comparison` derives
it from the adapter's own source. The derivation has one dangerous failure mode
— answering ``False`` for everything because the source would not parse, which
is what it did on the first attempt — so this file pins the answer for every
adapter rather than only checking the mechanism.
"""

from __future__ import annotations

import importlib

import pytest

from fpbench.adapters.runtime_recheck import (
    RUNTIME_INTEGRITY_CHECK,
    rechecks_runtime_per_comparison,
)

#: Every adapter that runs a comparison, and whether its own code re-verifies
#: the runtime while doing so. All six do; the list exists so that one of them
#: quietly stopping is a failure here rather than a quieter published claim.
_ADAPTERS = {
    "fpbench.adapters.mcc.adapter": ("MccSdkAdapter", True),
    "fpbench.adapters.nbis.adapter": ("NbisAdapter", True),
    "fpbench.adapters.openafis.adapter": ("OpenAfisAdapter", True),
    "fpbench.adapters.sourceafis_java.adapter": ("SourceAfisJavaAdapter", True),
    "fpbench.adapters.synthetic_two_stage.adapter": (
        "SyntheticTwoStageCliAdapter",
        True,
    ),
    "fpbench.adapters.verifinger_java.adapter": ("VeriFingerJavaAdapter", True),
}


def _adapter_class(module_name: str, class_name: str) -> type:
    return getattr(importlib.import_module(module_name), class_name)


@pytest.mark.parametrize("module_name, expected", sorted(_ADAPTERS.items()))
def test_the_derivation_matches_the_adapters_own_code(
    module_name: str, expected: tuple[str, bool]
) -> None:
    class_name, rechecks = expected
    cls = _adapter_class(module_name, class_name)
    # Constructed without __init__: the answer is about the class's source, and
    # a real adapter would want an SDK, a JVM or a native build to exist.
    assert rechecks_runtime_per_comparison(cls.__new__(cls)) is rechecks


@pytest.mark.parametrize("module_name, expected", sorted(_ADAPTERS.items()))
def test_an_adapter_that_claims_to_recheck_really_calls_it(
    module_name: str, expected: tuple[str, bool]
) -> None:
    """The claim is checked against the text, independently of the deriver.

    A second reading, deliberately cruder: does the class's source contain the
    call at all? If the derivation and this disagree, the derivation is the one
    that is wrong.
    """
    import inspect

    class_name, rechecks = expected
    source = inspect.getsource(_adapter_class(module_name, class_name))
    calls = f"{RUNTIME_INTEGRITY_CHECK}()" in source
    assert calls is rechecks


def test_a_class_that_does_not_recheck_answers_false() -> None:
    """The negative control, without which "True everywhere" proves nothing."""

    class _Passive:
        def compare(self, *args, **kwargs):
            return None

    assert rechecks_runtime_per_comparison(_Passive()) is False


def test_the_check_is_found_through_a_helper_the_entry_point_calls() -> None:
    """Five of the six call it in the method ``compare`` delegates to."""

    class _Delegating:
        def compare(self, *args, **kwargs):
            return self._match()

        def _match(self):
            self.check_runtime_integrity()

        def check_runtime_integrity(self):
            return None

    assert rechecks_runtime_per_comparison(_Delegating()) is True


def test_a_wrapper_answers_for_the_adapter_it_wraps() -> None:
    """The research wrapper holds the adapter; the adapter holds the answer."""

    class _Inner:
        def compare(self, *args, **kwargs):
            self.check_runtime_integrity()

        def check_runtime_integrity(self):
            return None

    class _Wrapper:
        def __init__(self, delegate):
            self._delegate = delegate

    assert rechecks_runtime_per_comparison(_Wrapper(_Inner())) is True


def test_the_published_closure_carries_the_derived_answer(tmp_path) -> None:
    """End to end: what a research run would actually publish."""
    from runworld import build_world

    world = build_world(tmp_path / "world", research=True)
    closure = world.adapter.content_closure(world.preparer)
    assert closure.runtime_assets.rechecked_per_comparison is (
        rechecks_runtime_per_comparison(world.adapter)
    )
    # The world's adapter is a scripted double that does not re-check, so the
    # published answer is False — and that is the point: it is *derived*, not a
    # constant. The six real adapters are covered by the parameters above.
    assert closure.runtime_assets.rechecked_per_comparison is False
