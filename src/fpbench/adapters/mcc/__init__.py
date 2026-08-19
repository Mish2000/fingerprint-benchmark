"""The MINDTCT + official MCC SDK v2.0 route (Stage 20B).

Importing this package costs nothing and needs neither NBIS, nor .NET, nor the
vendor assembly: the adapter reports its own environment as ``UNAVAILABLE`` when
any of them is absent, so listing the registry stays cheap on a machine that has
none of them — which is every CI runner, by design.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
