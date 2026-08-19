"""What ``nbis_mindtct_mcc_sdk_v2`` is, stated once and checked against Stage 20A.

Everything here was settled by Stage 20A and is repeated rather than imported:
an adapter may import :mod:`fpbench.core` and itself, and nothing else of
fpbench, so it cannot reach into :mod:`fpbench.experiments` where the
qualification contract lives. ``tests/test_stage20b_contract.py`` closes the loop
by asserting that every constant below equals the published Stage 20A evidence —
which makes a drift between the two a failing test rather than a run attributed
to the wrong SDK.

**The identity is the whole route, not the matcher.** The official MCC SDK has no
image extractor: it accepts minutiae. MINDTCT is therefore half of what makes a
score here, and calling the algorithm ``mcc`` would claim an extractor Bologna
never shipped. Hence ``nbis_mindtct_mcc_sdk_v2``, and hence
``shares_extractor_with = nbis_mindtct_bozorth3``.

**The defaults are the SDK's own.** Not one parameter setter is called anywhere
in this route. :data:`SDK_OPTIMAL_ENROLL_PARAMETERS` and
:data:`SDK_OPTIMAL_MATCH_PARAMETERS` are what the assembly reports for baseline
MCC, recorded so that ``validate_environment`` can prove the loaded SDK still
answers with them — a check, never a configuration.
"""

from __future__ import annotations

from typing import Mapping

__all__ = [
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "DISPLAY_NAME",
    "IMPLEMENTATION_VERSION",
    "EXTRACTOR",
    "MATCHER",
    "MCC_VARIANT",
    "MCC_SDK_VERSION",
    "MCC_SDK_DLL_SHA256",
    "MCC_SDK_ASSEMBLY_FULL_NAME",
    "MCC_INPUT_RESOLUTION",
    "TEMPLATE_API",
    "MATCH_API",
    "BRIDGE_PROTOCOL",
    "SHARES_EXTRACTOR_WITH",
    "UPSTREAM_MODIFIED",
    "SCORE_MINIMUM",
    "SCORE_MAXIMUM",
    "SDK_OPTIMAL_ENROLL_PARAMETERS",
    "SDK_OPTIMAL_MATCH_PARAMETERS",
    "SDK_OPTIMAL_PARAMETERS",
    "STAGE_20A_SMOKE_SCORES",
    "FORBIDDEN_ROUTE_OPERATIONS",
]

ALGORITHM_ID = "nbis_mindtct_mcc_sdk_v2"
ADAPTER_ID = "nbis_mindtct_mcc_sdk_v2_subprocess"
ADAPTER_VERSION = "1.0.0"

#: Named for both halves. "MCC" alone would describe a matcher that cannot see
#: an image and would hide which extractor produced the minutiae it scored.
DISPLAY_NAME = "NBIS MINDTCT + MCC SDK v2.0"

IMPLEMENTATION_VERSION = "nbis-5.0.0+mcc-sdk-2.0.0.0"

EXTRACTOR = "NBIS_MINDTCT_5_0_0"
MATCHER = "MCC_SDK_V2_BASELINE"
MCC_VARIANT = "baseline_mcc"
MCC_SDK_VERSION = "2.0.0.0"

#: ``Sdk/MccSdk.dll`` from the official archive. ``Executables/MccSdk.dll`` is
#: byte-identical; both were hashed in Stage 20A.
MCC_SDK_DLL_SHA256 = (
    "7267ea9f2ea4c32bdeef30a49e648a516381941b531c59960517a87e5cd2eb01"
)
MCC_SDK_ASSEMBLY_FULL_NAME = (
    "MccSdk, Version=2.0.0.0, Culture=neutral, PublicKeyToken=494f31afeacaf3f4"
)

#: Canonical 500 ppi is part of this route's identity, so the resolution handed
#: to the SDK is a constant rather than something read off an image.
MCC_INPUT_RESOLUTION = 500

TEMPLATE_API = (
    "System.Object BioLab.Biometrics.Mcc.Sdk.MccSdk.CreateMccTemplate("
    "System.Int32,System.Int32,System.Int32,BioLab.Biometrics.Mcc.Sdk.Minutia[])"
)
MATCH_API = (
    "System.Double BioLab.Biometrics.Mcc.Sdk.MccSdk.MatchMccTemplates("
    "System.Object,System.Object)"
)

#: The payload dialect the adapter writes and the bridge reads. Bumping it is a
#: different bridge, and the identity probe refuses a mismatch.
BRIDGE_PROTOCOL = "FPBENCH-MCC-BRIDGE-1"

SHARES_EXTRACTOR_WITH = "nbis_mindtct_bozorth3"

#: Nothing of Bologna's was patched, recompiled or rebuilt. The vendor assembly
#: is loaded exactly as it was downloaded — which is the whole methodological
#: point of this route beside the capacity-extended OpenAFIS one.
UPSTREAM_MODIFIED = False

SCORE_MINIMUM = 0.0
SCORE_MAXIMUM = 1.0

SDK_OPTIMAL_ENROLL_PARAMETERS: Mapping[str, object] = {
    "CompressionFunction": None,
    "CylinderBaseCellCount": 208,
    "CylinderType": "Bit",
    "MinM": 1,
    "MinVC": 0.3,
    "MuPsi": 0.002,
    "ND": 5,
    "NS": 16,
    "Omega": 15,
    "R": 70,
    "SigmaD": 0.5235987755982988,
    "SigmaS": 7,
    "TauPsi": 400,
}

SDK_OPTIMAL_MATCH_PARAMETERS: Mapping[str, object] = {
    "DeltaTheta": 2.356194490192345,
    "GlobalScoreMethod": "LGS_DTR",
    "MaxNP": 10,
    "MaxNR": 50,
    "MinME": 0.3,
    "MinNP": 4,
    "MuP": 32,
    "MuRho1": 0.041666666666666664,
    "MuRho2": 0.7853981633974483,
    "MuRho3": 0.20943951023931953,
    "NRel": 2,
    "NormalizeLocalSimilarityMatrix": True,
    "TauP": 0.25,
    "TauRho1": -50,
    "TauRho2": -15,
    "TauRho3": -28,
    "WR": 0.5,
}

#: Keyed by the prefix the bridge prints, so the comparison in
#: ``validate_environment`` is a lookup rather than a second table.
SDK_OPTIMAL_PARAMETERS: Mapping[str, Mapping[str, object]] = {
    "default_enroll": SDK_OPTIMAL_ENROLL_PARAMETERS,
    "default_match": SDK_OPTIMAL_MATCH_PARAMETERS,
}

#: Stage 20A's runtime smoke, to the last bit. Gate A drives the *production*
#: bridge over the same official sample minutiae and requires these exact
#: doubles back — no tolerance, because the same DLL called through the same API
#: with the same defaults has no biometric reason to answer differently.
STAGE_20A_SMOKE_SCORES: Mapping[str, float] = {
    "self": 0.6463866269440767,
    "related_forward": 0.18989714373119645,
    "related_reverse": 0.18989714373119645,
    "unrelated_forward": 0.10158917843359545,
    "unrelated_reverse": 0.10158917843359545,
}

#: Named so that adding one later is visibly a different algorithm rather than a
#: quiet improvement. Every one of these would be an fpbench choice standing
#: between MINDTCT's output and the SDK's input.
FORBIDDEN_ROUTE_OPERATIONS: tuple[str, ...] = (
    "best-N selection",
    "central-minutiae selection",
    "crop",
    "deduplication",
    "enhancement",
    "quality cutoff",
    "resize",
    "rotation optimization",
    "sorting",
)
