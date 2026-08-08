"""One route from the canonical bytes to a score, or a statement of why there is not.

This is Stage 9A's hard gate. Not the checkpoints — the pinned FLARE source
loads the FDD weights, and that question is closed. What is open is whether the
paper's route and the public code denote the same sequence of operations
(docs/adr/0088).

Four artifacts are produced here and each answers a different question:

:func:`paper_route_contract`
    what the paper says, quoted, in the order it says it.

:func:`public_code_route_audit`
    one row per operation, with the paper's statement beside the official code
    location, and a resolution. ``AMBIGUOUS`` or ``CONTRADICTORY`` on a
    score-affecting row is a blocker.

:func:`transform_graph`
    every operation from the canonical input bytes to the FDRN tensor, with its
    dtypes, geometry, interpolation, padding, normalisation, coordinate
    convention, angle units and rounding — and, for each, the authority it comes
    from.

:func:`score_contract`
    the exact masked cosine the official continuous path computes, the mask
    tiling and the clipping that go with it, and what happens when two
    fingerprints barely overlap.

The rule they are all measured against is one sentence: an operation that can
change a score must come from the paper, from the pinned code, or from a pinned
inference default. Where two of those disagree, or where none of them speaks,
this stage says so and stops (docs/adr/0087).

Nothing here executes FLARE, imports torch, opens a checkpoint or reads a
fingerprint. It is a reading of two pinned source trees and one published paper,
expressed as data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fpbench.core.flare_errors import FlareRouteError
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.experiments.stage9a_flare_identity import (
    BlockerCode,
    OperationAuthority,
    RouteResolution,
)

__all__ = [
    "FLARE_SOURCE",
    "FLARE_ENH_SOURCE",
    "TransformOperation",
    "TRANSFORM_OPERATIONS",
    "RouteAuditRow",
    "ROUTE_AUDIT_ROWS",
    "ParameterProvenance",
    "PARAMETER_PROVENANCE",
    "TransformGraphResolution",
    "RouteAuditResult",
    "transform_graph",
    "resolve_transform_graph",
    "paper_route_contract",
    "public_code_route_audit",
    "score_contract",
    "training_provenance",
    "route_blockers",
]

#: Pinned source locators, assembled once so that every row below cites the
#: commit rather than a branch.
FLARE_SOURCE = f"Yu-Yy/FLARE@{frozen.FLARE_REPOSITORY.commit[:8]}"
FLARE_ENH_SOURCE = f"Yu-Yy/FLARE_ENH@{frozen.FLARE_ENH_REPOSITORY.commit[:8]}"

_PAPER = frozen.PAPER_ARXIV_LOCATOR


# ------------------------------------------------------------ the transform graph


@dataclass(frozen=True, slots=True)
class TransformOperation:
    """One operation between the canonical input bytes and the FDRN tensor.

    Every field is something two implementations could differ on. That is why
    they are fields: a graph that recorded only "resize to 256" would be a graph
    two people could implement differently and both believe they had followed.
    """

    operation_id: str
    stage: str
    description: str
    authority: OperationAuthority
    authority_locator: str
    score_affecting: bool

    input_dtype: str = ""
    output_dtype: str = ""
    geometry: str = ""
    interpolation: str = ""
    padding_mode: str = ""
    padding_value: str = ""
    normalization: str = ""
    coordinate_convention: str = ""
    rotation_direction: str = ""
    angle_units: str = ""
    rounding_behaviour: str = ""
    branches: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.authority, OperationAuthority):
            raise FlareRouteError("authority must be an OperationAuthority")
        if self.authority.is_authoritative and not self.authority_locator.strip():
            raise FlareRouteError(
                f"{self.operation_id}: an authoritative operation names where "
                "the authority is. A citation nobody can follow is a claim"
            )

    @property
    def blocks(self) -> bool:
        """Whether this operation on its own prevents a READY outcome."""
        return self.score_affecting and not self.authority.is_authoritative


_ALL_BRANCHES = tuple(branch.branch_id for branch in frozen.BRANCHES)
_UNETENH_BRANCHES = ("voting_unetenh", "regression_unetenh")
_PRIORENH_BRANCHES = ("voting_priorenh", "regression_priorenh")

TRANSFORM_OPERATIONS: tuple[TransformOperation, ...] = (
    TransformOperation(
        operation_id="decode_canonical500",
        stage="decoder",
        description=(
            "read the canonical_500 PNG as a single-channel array of 0..255"
        ),
        authority=OperationAuthority.INTEGRATION_NEUTRAL,
        authority_locator=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::Descdataset.__getitem__ uses "
            "cv2.imread(IMREAD_GRAYSCALE); FingerPoseEvalDataset.load_img uses "
            "PIL Image.open().convert('L')"
        ),
        score_affecting=True,
        input_dtype="uint8 PNG bytes, gray8, 500 ppi",
        output_dtype="float32",
        geometry="unchanged from the stored image",
        normalization="none at this step",
        branches=_ALL_BRANCHES,
        notes=(
            "The two upstream entry points decode with different libraries. On "
            "a single-channel 8-bit PNG both produce the same array, so the "
            "difference cannot move a score here; on a colour or 16-bit input "
            "it could, and the canonical profile emits neither "
            "(docs/adr/0031).",
        ),
    ),
    TransformOperation(
        operation_id="pose_input_center_512",
        stage="pose preprocessing",
        description=(
            "translate the image so its centre lands at the centre of a 512x512 "
            "canvas; no rotation and no scale"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::"
            "FingerPoseEvalDataset.process_img"
        ),
        score_affecting=True,
        input_dtype="float32 in 0..255",
        output_dtype="float32 in 0..255, shape (1, 512, 512)",
        geometry=(
            "tar_shape is derived as rint(max(1, (512*1.0 + 32)//64) * 64) = 512 "
            "for a 500 ppi input"
        ),
        interpolation="cv2.INTER_LINEAR",
        padding_mode="cv2.BORDER_CONSTANT",
        padding_value="255, white",
        normalization="none; the raw 0..255 values are passed to the estimator",
        coordinate_convention="(x, y) with y increasing downwards",
        rotation_direction="none at this step",
        angle_units="not applicable",
        rounding_behaviour="none; the affine is a pure translation of image centres",
        branches=_ALL_BRANCHES,
        notes=(
            "The scale branch that would low-pass and zoom applies only below "
            "500 ppi; at 500 ppi self.scale is 1.0 and it is skipped.",
        ),
    ),
    TransformOperation(
        operation_id="pose_forward",
        stage="pose coordinates",
        description=(
            "run VotingPose (GRIDNET4) or RegressionPose (FingerPose_2D_Single) "
            "over the centred 512x512 image"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:extract_VotingPose.py::valid_pose and "
            f"{FLARE_SOURCE}:extract_RegressionPose.py::valid_pose"
        ),
        score_affecting=True,
        input_dtype="float32 (1, 512, 512)",
        output_dtype="float32 (x, y, theta)",
        geometry="the 512x512 centred frame",
        angle_units="degrees",
        branches=_ALL_BRANCHES,
        notes=(
            "RegressionPose decodes its two classification heads through "
            "classify2vector_trans and classify2vector_rot and then adds 256 to "
            "x and y, which places them in the 512x512 frame.",
        ),
    ),
    TransformOperation(
        operation_id="pose_back_projection",
        stage="pose coordinates",
        description=(
            "map the predicted centre back into original image coordinates with "
            "the inverse of the centring transform, and wrap the angle"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:extract_VotingPose.py::valid_pose, "
            "pose_2d[:2] = T_inv[:2,:2] @ pose_2d[:2] + T_inv[:2,2]"
        ),
        score_affecting=True,
        input_dtype="float32 (x, y, theta) in the 512x512 frame",
        output_dtype="float32 (x, y, theta) in original image coordinates",
        coordinate_convention="(x, y) with y increasing downwards",
        angle_units="degrees",
        rounding_behaviour=(
            "theta is wrapped by (theta + 180) % 360 - 180, giving [-180, 180)"
        ),
        branches=_ALL_BRANCHES,
        notes=(
            "Both estimators apply the identical back-projection and the "
            "identical wrap, so the pose file format is one format.",
        ),
    ),
    TransformOperation(
        operation_id="alignment_affine_matrix",
        stage="affine matrix",
        description=(
            "build the similarity transform that carries the pose centre to the "
            "output centre, rotating by theta and scaling by "
            "tar_shape[0] / middle_shape[0]"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::affine_matrix and "
            "Descdataset.process_img"
        ),
        score_affecting=True,
        input_dtype="float32 (x, y, theta)",
        output_dtype="float32 3x3 homogeneous matrix, of which the top two rows are used",
        geometry=(
            "R = [[cos, -sin], [sin, cos]] * scale; t = R @ (-pose_centre) + "
            "output_centre"
        ),
        coordinate_convention=(
            "(x, y) with y increasing downwards; the output centre is "
            "tar_shape[::-1] / 2.0"
        ),
        rotation_direction=(
            "positive theta rotates from +x toward +y, which is clockwise on "
            "screen because y points down"
        ),
        angle_units="degrees, converted by numpy.deg2rad",
        branches=_ALL_BRANCHES,
        notes=(
            "Under the official configuration scale is 256/512 = 0.5, which is "
            "what fuses alignment and the downsample into a single warp. "
            "Producing the paper's 512x512 aligned image means calling this "
            "with tar_shape = middle_shape and therefore scale 1.0.",
        ),
    ),
    TransformOperation(
        operation_id="aligned_crop_512",
        stage="512x512 aligned image",
        description=(
            "warp the original image by the alignment matrix into a 512x512 "
            "canvas, as the image the enhancers are to receive"
        ),
        authority=OperationAuthority.CHOSEN_BY_FPBENCH,
        authority_locator=(
            "no upstream code path produces this image: Descdataset.process_img "
            "always warps to tar_shape, which the official configuration sets "
            "to 256x256, and no other caller of affine_matrix exists"
        ),
        score_affecting=True,
        input_dtype="float32",
        output_dtype="float32 (512, 512)",
        geometry="512x512 at 500 ppi, the paper's stated intermediate",
        interpolation=(
            "cv2.INTER_LINEAR if Descdataset.process_img is reused; nothing "
            "upstream states what it should be for this image"
        ),
        padding_mode="cv2.BORDER_CONSTANT",
        padding_value=(
            "unresolved: Descdataset.process_img passes no borderValue and so "
            "fills with 0 *after* normalising, which is mid-grey once "
            "denormalised, while FingerPoseEvalDataset fills with 255. The "
            "paper says nothing about what surrounds the aligned crop"
        ),
        normalization=(
            "unresolved: Descdataset normalises with (x - 127.5) / 127.5 before "
            "warping, and the enhancer entry points expect 0..255 and normalise "
            "again themselves"
        ),
        branches=_ALL_BRANCHES,
        notes=(
            "This is the first of the two operations that block. Reusing the "
            "upstream affine with tar_shape = middle_shape = 512 is legitimate "
            "under spec section 25, but the fill value that surrounds the "
            "fingerprint in the enhancer's input is not settled by any "
            "authority, and a mid-grey frame and a white frame are different "
            "inputs to a network trained on fingerprints.",
        ),
    ),
    TransformOperation(
        operation_id="unetenh_preprocessing",
        stage="enhancer preprocessing",
        description=(
            "resize to the next multiple of 16 in each dimension, then "
            "normalise with (x - 127.5) / 127.5"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=f"{FLARE_ENH_SOURCE}:deploy_unetenh.py::image_read",
        score_affecting=True,
        input_dtype="uint8",
        output_dtype="float32 (1, H, W)",
        geometry=(
            "h = ceil(h/16)*16 and w = ceil(w/16)*16; on a 512x512 input both "
            "are 512 and cv2.resize to the same size is the identity"
        ),
        interpolation="cv2.resize with its default, cv2.INTER_LINEAR",
        normalization="(x - 127.5) / 127.5",
        branches=_UNETENH_BRANCHES,
        notes=(
            "Only an identity because the paper's aligned crop is already a "
            "multiple of 16 on both axes. On an arbitrary original image it "
            "resamples, which is what the deploy script was written for.",
        ),
    ),
    TransformOperation(
        operation_id="priorenh_preprocessing",
        stage="enhancer preprocessing",
        description=(
            "pad to a square with white, resize to 512x512, then normalise with "
            "(x - 127.5) / 127.5"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=f"{FLARE_ENH_SOURCE}:deploy_priorenh.py::image_read",
        score_affecting=True,
        input_dtype="uint8",
        output_dtype="float32 (1, 512, 512)",
        geometry=(
            "cv2.copyMakeBorder to max(h, w) on the shorter axis, then resize to "
            "512x512; on a 512x512 input the border is zero-width and the resize "
            "is the identity"
        ),
        interpolation="cv2.resize with its default, cv2.INTER_LINEAR",
        padding_mode="cv2.BORDER_CONSTANT",
        padding_value="255, white",
        normalization="(x - 127.5) / 127.5",
        branches=_PRIORENH_BRANCHES,
        notes=(
            "The paper's Table XI gives PriorEnh an input of 512x512, and the "
            "training description applies its geometric augmentation to "
            "fingerprints of size 512x512 at 500 ppi. Both agree with an "
            "aligned crop and not with an arbitrary original image rescaled to "
            "512, which is what this script does when run as documented.",
        ),
    ),
    TransformOperation(
        operation_id="unetenh_forward",
        stage="enhancement",
        description=(
            "SqueezeUNet forward; the two output channels are split [1, 1] and "
            "the first is the enhanced image"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=f"{FLARE_ENH_SOURCE}:deploy_unetenh.py::deploy_enh",
        score_affecting=True,
        input_dtype="float32 (1, 1, H, W)",
        output_dtype="float32 in (0, 1) after the network's sigmoid",
        branches=_UNETENH_BRANCHES,
    ),
    TransformOperation(
        operation_id="priorenh_forward",
        stage="enhancement",
        description=(
            "VQFPEnhancer_PCNN.enhance(x, w), with the CFT weight w passed "
            "explicitly by the official CLI"
        ),
        authority=OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
        authority_locator=(
            f"{FLARE_ENH_SOURCE}:deploy_priorenh.py, --w default 0.5, passed to "
            "enhance()"
        ),
        score_affecting=True,
        input_dtype="float32 (1, 1, 512, 512)",
        output_dtype="float32, clamped to [-1, 1] by the caller",
        branches=_PRIORENH_BRANCHES,
        notes=(
            "The paper defines w in [0, 1] as the weight controlling how much "
            "the encoder features modulate the decoder, and gives no value for "
            "inference. The method's own signature defaults to 0 and the CLI "
            "overrides it to 0.5, so the pinned inference default is 0.5.",
        ),
    ),
    TransformOperation(
        operation_id="unetenh_postprocessing",
        stage="enhancer postprocessing",
        description="scale (0, 1) to 0..255 as uint8, then resize to the input size",
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=f"{FLARE_ENH_SOURCE}:deploy_unetenh.py::deploy_enh",
        score_affecting=True,
        input_dtype="float32 in (0, 1)",
        output_dtype="uint8",
        geometry="cv2.resize back to (w_org, h_org); the identity at 512x512",
        interpolation="cv2.resize with its default, cv2.INTER_LINEAR",
        rounding_behaviour="(enh * 255).astype(uint8), which truncates rather than rounds",
        branches=_UNETENH_BRANCHES,
    ),
    TransformOperation(
        operation_id="priorenh_postprocessing",
        stage="enhancer postprocessing",
        description=(
            "map [-1, 1] to 0..255 as uint8, resize back to the padded square, "
            "and remove the padding"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_ENH_SOURCE}:deploy_priorenh.py::inverse_image"
        ),
        score_affecting=True,
        input_dtype="float32 in [-1, 1]",
        output_dtype="uint8",
        geometry=(
            "resize to max(w_org, h_org) then crop off the padding; both are "
            "the identity when the input was already square and 512x512"
        ),
        interpolation="cv2.resize with its default, cv2.INTER_LINEAR",
        rounding_behaviour=(
            "((enh + 1) * 127.5).astype(uint8), which truncates rather than "
            "rounds"
        ),
        branches=_PRIORENH_BRANCHES,
    ),
    TransformOperation(
        operation_id="downsample_512_to_256",
        stage="256x256 FDRN input",
        description="downsample the enhanced 512x512 image to 256x256",
        authority=OperationAuthority.CHOSEN_BY_FPBENCH,
        authority_locator=(
            "no implementation exists in either repository: the only 2:1 "
            "reduction upstream performs is the scale factor inside "
            "Descdataset.process_img's single warp, which is applied to the "
            "unenhanced original rather than to an enhanced 512x512 image"
        ),
        score_affecting=True,
        input_dtype="uint8 (512, 512)",
        output_dtype="float32 (256, 256)",
        geometry="512x512 to 256x256, a factor of two on each axis",
        interpolation=(
            "unresolved: the paper says only 'downsampled'. cv2.INTER_LINEAR, "
            "cv2.INTER_AREA, scipy.ndimage.zoom(order=1) and a second "
            "warpAffine with scale 0.5 all produce different pixels, and no "
            "authority chooses"
        ),
        branches=_ALL_BRANCHES,
        notes=(
            "This is the second of the two operations that block, and it is the "
            "cleaner of them: it is one function call with at least four "
            "reasonable spellings and no upstream implementation to copy.",
        ),
    ),
    TransformOperation(
        operation_id="fdrn_input_normalization",
        stage="FDRN normalization",
        description=(
            "normalise with (x - 127.5) / 127.5 and present the image as a "
            "single-channel float32 tensor"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::Descdataset.process_img, and "
            "MODEL.input_norm false in model_weights/desc_configs.yaml"
        ),
        score_affecting=True,
        input_dtype="uint8 or float32 in 0..255",
        output_dtype="float32 (1, 256, 256)",
        normalization=(
            "(x - 127.5) / 127.5 only; FDD.img_norm is not applied, because "
            "input_norm is false in the official configuration"
        ),
        branches=_ALL_BRANCHES,
        notes=(
            "Upstream applies this normalisation *before* the warp rather than "
            "after it. On a linear interpolation the two commute exactly except "
            "at the border, where the fill value differs — which is the "
            "unresolved parameter of aligned_crop_512.",
        ),
    ),
    TransformOperation(
        operation_id="fdrn_forward",
        stage="FDRN",
        description=(
            "FDD.get_embedding returns the concatenated texture and minutiae "
            "descriptors and the sigmoid foreground mask, both flattened"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=(
            f"{FLARE_SOURCE}:models/model_zoo.py::FDD.get_embedding"
        ),
        score_affecting=True,
        input_dtype="float32 (B, 1, 256, 256)",
        output_dtype=(
            "feature (B, 3072) and mask (B, 256); 2D x 16 x 16 and 1 x 16 x 16 "
            "with D = 6"
        ),
        geometry="16x16 spatial cells, one sixteenth of the 256x256 input",
        normalization="none after the network",
        branches=_ALL_BRANCHES,
        notes=(
            "feature is cat(feature_t, feature_m) over the channel axis and is "
            "then flattened in C order, so the descriptor is channel-major: 256 "
            "values per channel, twelve channels.",
        ),
    ),
    TransformOperation(
        operation_id="branch_similarity",
        stage="score",
        description=(
            "the overlap-masked cosine of one branch's two descriptors, with "
            "the mask tiled across the descriptor channels"
        ),
        authority=OperationAuthority.UPSTREAM_CODE_EXPLICIT,
        authority_locator=f"{FLARE_SOURCE}:extract_FDD.py::calculate_score",
        score_affecting=True,
        input_dtype="float32 descriptors (3072,) and masks (256,)",
        output_dtype="float32 scalar",
        branches=_ALL_BRANCHES,
    ),
    TransformOperation(
        operation_id="max_fusion",
        stage="fusion",
        description="the maximum of the four branch similarities",
        authority=OperationAuthority.PAPER_EXPLICIT,
        authority_locator=f"{_PAPER} Eq. 8",
        score_affecting=True,
        input_dtype="four float32 scalars",
        output_dtype="one float32 scalar",
        branches=_ALL_BRANCHES,
        notes=(
            "There is exactly one way to take a maximum of four numbers, so "
            "implementing this in fpbench adds nothing. What has no "
            "implementation upstream is the pipeline that produces the four.",
        ),
    ),
)


# ---------------------------------------------------- paper against public code


@dataclass(frozen=True, slots=True)
class RouteAuditRow:
    """One operation, with what the paper says beside what the code does."""

    operation: str
    paper_statement: str
    paper_source: str
    official_code_location: str
    artifact_dependencies: tuple[str, ...]
    parameter_sources: tuple[str, ...]
    resolution: RouteResolution
    score_affecting: bool
    fpbench_glue_required: bool
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, RouteResolution):
            raise FlareRouteError("resolution must be a RouteResolution")

    @property
    def blocks(self) -> bool:
        return self.score_affecting and not self.resolution.is_resolved


ROUTE_AUDIT_ROWS: tuple[RouteAuditRow, ...] = (
    RouteAuditRow(
        operation="input_resolution",
        paper_statement="Given a 500 ppi query image I_q and a gallery image I_g",
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            f"{FLARE_SOURCE}:model_weights/desc_configs.yaml DATASET.PPI 500; "
            "FingerPoseEvalDataset is constructed with img_ppi=500"
        ),
        artifact_dependencies=("flare_desc_configs",),
        parameter_sources=("paper §III-E", "desc_configs.yaml DATASET.PPI"),
        resolution=RouteResolution.EXACT_MATCH,
        score_affecting=True,
        fpbench_glue_required=False,
    ),
    RouteAuditRow(
        operation="two_pose_estimators",
        paper_statement=(
            "FLARE first estimates the 2D pose using two complementary "
            "estimators"
        ),
        paper_source=f"{_PAPER} §III, pipeline overview",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_VotingPose.py and extract_RegressionPose.py"
        ),
        artifact_dependencies=(
            "flare_voting_pose_checkpoint",
            "flare_regression_pose_checkpoint",
        ),
        parameter_sources=("literals in both scripts",),
        resolution=RouteResolution.EXACT_MATCH,
        score_affecting=True,
        fpbench_glue_required=False,
        detail=(
            "Both estimators exist and both write the same pose file format. "
            "The README presents them as alternatives, but that is an "
            "instruction about how to run one script, not a claim about the "
            "method."
        ),
    ),
    RouteAuditRow(
        operation="pose_preprocessing_geometry",
        paper_statement=(
            "random geometric transformations are applied to the fingerprints "
            "of size 512x512 at 500 ppi"
        ),
        paper_source=f"{_PAPER} §IV, training configuration",
        official_code_location=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::"
            "FingerPoseEvalDataset.process_img, middle_shape (512, 512)"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=(
            "middle_shape literal (512, 512)",
            "borderValue 255",
            "cv2.INTER_LINEAR",
        ),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
        detail=(
            "The paper gives the geometry; the implementation gives the "
            "centring rule, the fill value and the interpolation."
        ),
    ),
    RouteAuditRow(
        operation="pose_output_convention",
        paper_statement=(
            "aligns the image into standardized spatial configurations "
            "according to each estimator's interpretation"
        ),
        paper_source=f"{_PAPER} §III",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_RegressionPose.py::valid_pose, back "
            "projection through T_inv and the wrap to [-180, 180)"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("the wrap (theta + 180) % 360 - 180",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
    ),
    RouteAuditRow(
        operation="alignment_then_enhancement_ordering",
        paper_statement=(
            "we first apply pose estimation and alignment, followed by cropping "
            "to 512x512 pixels. The aligned images are then enhanced ... each "
            "enhanced image is downsampled to 256x256 pixels before being input "
            "to the FDRN"
        ),
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::Descdataset.process_img, "
            "which builds one affine with scale = tar_shape/middle_shape = "
            "256/512 and warps the original image straight to 256x256"
        ),
        artifact_dependencies=("flare_source_archive", "flare_desc_configs"),
        parameter_sources=(
            "paper §III-E for the order",
            "desc_configs.yaml middle_shape and tar_shape for the fused scale",
        ),
        resolution=RouteResolution.CONTRADICTORY,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "The paper puts enhancement between alignment and the downsample. "
            "The only upstream code that aligns performs the alignment and the "
            "downsample as a single interpolation of the unenhanced original, "
            "leaving no 512x512 image and no point of insertion. The code path "
            "corresponds to the earlier unenhanced FDD route rather than to "
            "this paper's inference route, and nothing upstream composes the "
            "two."
        ),
    ),
    RouteAuditRow(
        operation="aligned_crop_border_fill",
        paper_statement=(
            "cropping to 512x512 pixels — the paper does not say what surrounds "
            "the fingerprint in that crop"
        ),
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py: Descdataset.process_img "
            "passes no borderValue and fills with 0 after normalising, while "
            "FingerPoseEvalDataset.process_img fills with 255"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("two upstream warps that disagree",),
        resolution=RouteResolution.AMBIGUOUS,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "Whichever fill is chosen becomes part of the enhancer's input. A "
            "mid-grey frame and a white frame are different images to a network "
            "trained on fingerprints, and the descriptor that follows differs."
        ),
    ),
    RouteAuditRow(
        operation="enhancer_input_geometry",
        paper_statement=(
            "the aligned images are then enhanced; PriorEnh's input is 512x512"
        ),
        paper_source=f"{_PAPER} §III-E and Table XI",
        official_code_location=(
            f"{FLARE_ENH_SOURCE}:deploy_unetenh.py::image_read and "
            "deploy_priorenh.py::image_read, both of which take whole original "
            "images from a folder"
        ),
        artifact_dependencies=(
            "flare_enh_source_archive",
            "flare_unetenh_checkpoint",
            "flare_priorenh_checkpoint",
        ),
        parameter_sources=(
            "paper Table XI for 512x512",
            "the deploy scripts for their own resizing",
        ),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "On a 512x512 input both scripts' preprocessing and postprocessing "
            "reduce to exact identities: the multiple-of-16 resize is a no-op, "
            "the square padding is zero-width, and both inverse resizes return "
            "the same size. So the paper's aligned crop composes with the "
            "official enhancer entry points without any fpbench-chosen "
            "resampling at this boundary — which is what makes this row "
            "resolvable while the two around it are not."
        ),
    ),
    RouteAuditRow(
        operation="priorenh_cft_weight",
        paper_statement=(
            "w in [0, 1] is a weighting factor that controls the degree of "
            "influence — the paper gives no inference value"
        ),
        paper_source=f"{_PAPER} §III-B, Eq. 1",
        official_code_location=(
            f"{FLARE_ENH_SOURCE}:deploy_priorenh.py, --w default 0.5, passed "
            "explicitly into enhance()"
        ),
        artifact_dependencies=("flare_priorenh_checkpoint",),
        parameter_sources=("the official CLI default",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
        detail=(
            "The paper is silent on the value and the pinned inference entry "
            "point sets one unambiguously, which is the case the authority "
            "hierarchy allows the implementation to fill."
        ),
    ),
    RouteAuditRow(
        operation="enhancer_contrast_pre_enhancement",
        paper_statement="the paper does not mention a CLAHE pre-enhancement step",
        paper_source=f"{_PAPER} §III-B",
        official_code_location=(
            f"{FLARE_ENH_SOURCE}: both deploy scripts default pre_enh to false; "
            "-e turns it on"
        ),
        artifact_dependencies=("flare_enh_source_archive",),
        parameter_sources=("the official CLI default, false",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
    ),
    RouteAuditRow(
        operation="downsample_to_fdrn_input",
        paper_statement=(
            "each enhanced image is downsampled to 256x256 pixels before being "
            "input to the FDRN"
        ),
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            "none. Neither repository contains a 512-to-256 reduction of an "
            "enhanced image; the only 2:1 factor upstream is the scale inside "
            "Descdataset's single warp of the unenhanced original"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=(),
        resolution=RouteResolution.AMBIGUOUS,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "One function call, at least four reasonable spellings — "
            "cv2.INTER_LINEAR, cv2.INTER_AREA, scipy.ndimage.zoom(order=1), a "
            "second warpAffine at scale 0.5 — and different pixels from each. "
            "The paper states the target size and not the kernel."
        ),
    ),
    RouteAuditRow(
        operation="fdrn_input_presentation",
        paper_statement="before being input to the FDRN",
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            f"{FLARE_SOURCE}:datasets/FPdataset.py::Descdataset.process_img "
            "normalises with (x - 127.5)/127.5; input_norm is false in "
            "desc_configs.yaml so FDD.img_norm is not applied"
        ),
        artifact_dependencies=("flare_desc_configs",),
        parameter_sources=("desc_configs.yaml MODEL.input_norm",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "Descdataset has no path that accepts an already-aligned image: "
            "with a pose file it warps by the pose, and without one it warps by "
            "coarse_center with theta 0. Presenting a pre-aligned 256x256 image "
            "to FDD therefore needs fpbench code, though the normalisation it "
            "would apply is fully specified."
        ),
    ),
    RouteAuditRow(
        operation="descriptor_and_mask_shape",
        paper_statement=(
            "dense descriptors f in R^{2D x 16 x 16} and foreground masks S in "
            "R^{1 x 16 x 16}, with D set to 6"
        ),
        paper_source=f"{_PAPER} §III-E and §IV",
        official_code_location=(
            f"{FLARE_SOURCE}:models/model_zoo.py::FDD.get_embedding with "
            "ndim_feat 6 from desc_configs.yaml"
        ),
        artifact_dependencies=("flare_fdd_checkpoint", "flare_desc_configs"),
        parameter_sources=("paper §IV", "desc_configs.yaml MODEL.ndim_feat"),
        resolution=RouteResolution.EXACT_MATCH,
        score_affecting=True,
        fpbench_glue_required=False,
    ),
    RouteAuditRow(
        operation="mask_semantics",
        paper_statement=(
            "matching is performed only within the overlapping foreground "
            "regions"
        ),
        paper_source=f"{_PAPER} §III-E, Eq. 7",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_FDD.py::calculate_score, continuous branch: "
            "the mask values enter the numerator and both denominator terms "
            "without being thresholded"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("the continuous branch of calculate_score",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
        detail=(
            "The paper's Eq. 7 reads as written under binary masks. The mask is "
            "a sigmoid output, and the implementation generalises the same "
            "formula to continuous values by keeping it linear in each mask. "
            "Thresholding appears only in the binary branch, which this "
            "identity excludes."
        ),
    ),
    RouteAuditRow(
        operation="branch_score_formula",
        paper_statement=(
            "the cosine similarity between the flattened dense representations, "
            "where only the overlapping foreground regions are considered"
        ),
        paper_source=f"{_PAPER} §III-E, Eq. 7",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_FDD.py::calculate_score, including the "
            "np.tile of the mask across 2D channels and the clip(1e-3, None) on "
            "the product of the two denominator terms"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("calculate_score",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
    ),
    RouteAuditRow(
        operation="four_branch_orchestration",
        paper_statement=(
            "producing four augmented versions of each image ... the four sets "
            "of descriptors are independently compared, yielding four "
            "similarity scores"
        ),
        paper_source=f"{_PAPER} §III-E",
        official_code_location=(
            "none. extract_FDD.py takes one -p pose and no enhancement, and "
            "neither repository contains a script that builds four branches"
        ),
        artifact_dependencies=(
            "flare_source_archive",
            "flare_enh_source_archive",
        ),
        parameter_sources=("paper §III-E",),
        resolution=RouteResolution.AMBIGUOUS,
        score_affecting=True,
        fpbench_glue_required=True,
        detail=(
            "The branch construction is unresolved only because the transform "
            "graph it repeats is unresolved. Given a settled graph, applying it "
            "for each of the two poses and each of the two enhancers is "
            "arithmetic."
        ),
    ),
    RouteAuditRow(
        operation="max_fusion",
        paper_statement=(
            "the final matching score is obtained by taking the maximum over "
            "the four matching scores"
        ),
        paper_source=f"{_PAPER} §III-E, Eq. 8",
        official_code_location=(
            "none, and none is needed: there is one way to take a maximum"
        ),
        artifact_dependencies=(),
        parameter_sources=("paper Eq. 8",),
        resolution=RouteResolution.INTEGRATION_NEUTRAL_GLUE,
        score_affecting=True,
        fpbench_glue_required=True,
    ),
    RouteAuditRow(
        operation="binary_route",
        paper_statement=(
            "the paper's Eq. 7 is continuous; no binary representation is part "
            "of the reported method"
        ),
        paper_source=f"{_PAPER} §III-E, Eq. 7",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_FDD.py, the -b flag and the binary branch "
            "of calculate_score with its 0.5 and 0.2 mask thresholds"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("the README, which presents -b as optional",),
        resolution=RouteResolution.EXACT_MATCH,
        score_affecting=True,
        fpbench_glue_required=False,
        detail="Excluded from the identity, so the disagreement never arises.",
    ),
    RouteAuditRow(
        operation="degenerate_overlap",
        paper_statement=(
            "the paper does not state what the score is when two foregrounds "
            "barely overlap"
        ),
        paper_source=f"{_PAPER} §III-E, Eq. 7",
        official_code_location=(
            f"{FLARE_SOURCE}:extract_FDD.py::calculate_score, "
            "x12 / (x1 * x2).clip(1e-3, None)"
        ),
        artifact_dependencies=("flare_source_archive",),
        parameter_sources=("the clip literal 1e-3",),
        resolution=RouteResolution.IMPLEMENTATION_SUPPLIES_DETAIL,
        score_affecting=True,
        fpbench_glue_required=False,
        detail=(
            "As the overlap vanishes the numerator goes to zero and the clipped "
            "denominator stays at 1e-3, so the score goes to zero and stays "
            "finite. The behaviour is defined by the pinned source and needs no "
            "new policy here."
        ),
    ),
)


# -------------------------------------------------------- parameter provenance


@dataclass(frozen=True, slots=True)
class ParameterProvenance:
    """One score-affecting parameter, its value, and where the value came from."""

    parameter: str
    value: str
    source_type: str
    source_locator: str
    authority: OperationAuthority

    def __post_init__(self) -> None:
        if not isinstance(self.authority, OperationAuthority):
            raise FlareRouteError("authority must be an OperationAuthority")

    @property
    def blocks(self) -> bool:
        return not self.authority.is_authoritative


_DESC_CONFIG = f"{FLARE_SOURCE}:model_weights/desc_configs.yaml"
_VQ_CONFIG = f"{FLARE_ENH_SOURCE}:pretrained_model/priorenh/vq.yaml"
_FPDATASET = f"{FLARE_SOURCE}:datasets/FPdataset.py"

PARAMETER_PROVENANCE: tuple[ParameterProvenance, ...] = (
    ParameterProvenance(
        "input.ppi", "500", "official inference configuration",
        f"{_DESC_CONFIG} DATASET.PPI", OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "descriptor.ndim_feat", "6", "official inference configuration",
        f"{_DESC_CONFIG} MODEL.ndim_feat",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "descriptor.input_norm", "False", "official inference configuration",
        f"{_DESC_CONFIG} MODEL.input_norm",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "alignment.middle_shape", "512 x 512", "official inference configuration",
        f"{_DESC_CONFIG} MODEL.middle_shape",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "fdrn.tar_shape", "256 x 256", "official inference configuration",
        f"{_DESC_CONFIG} MODEL.tar_shape",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.middle_shape", "512 x 512", "pinned source literal",
        f"{FLARE_SOURCE}:extract_VotingPose.py", OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.img_ppi", "500", "pinned source literal",
        f"{FLARE_SOURCE}:extract_VotingPose.py", OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.warp_border_value", "255", "pinned source literal",
        f"{_FPDATASET}::FingerPoseEvalDataset.process_img",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.warp_interpolation", "cv2.INTER_LINEAR", "pinned source literal",
        f"{_FPDATASET}::FingerPoseEvalDataset.process_img",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.angle_units", "degrees", "pinned source",
        f"{_FPDATASET}::Descdataset.process_img uses numpy.deg2rad",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "pose.angle_wrap", "[-180, 180)", "pinned source literal",
        f"{FLARE_SOURCE}:extract_RegressionPose.py::valid_pose",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "alignment.rotation_matrix",
        "[[cos, -sin], [sin, cos]] * scale, applied to (x, y) with y downwards",
        "pinned source", f"{_FPDATASET}::affine_matrix",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "alignment.output_centre", "tar_shape[::-1] / 2.0", "pinned source",
        f"{_FPDATASET}::Descdataset.process_img",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "alignment.warp_interpolation", "cv2.INTER_LINEAR", "pinned source literal",
        f"{_FPDATASET}::Descdataset.process_img",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "aligned_crop_512.border_fill",
        "unresolved: 0 after normalisation in one upstream warp, 255 in the other",
        "no authority", "the two warps in datasets/FPdataset.py disagree",
        OperationAuthority.CHOSEN_BY_FPBENCH,
    ),
    ParameterProvenance(
        "downsample_512_to_256.interpolation",
        "unresolved: the paper names the size and no upstream code performs it",
        "no authority",
        f"{_PAPER} §III-E states only 'downsampled to 256x256'",
        OperationAuthority.CHOSEN_BY_FPBENCH,
    ),
    ParameterProvenance(
        "unetenh.pre_enh", "False", "official inference default",
        f"{FLARE_ENH_SOURCE}:deploy_unetenh.py --pre_enh",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "priorenh.pre_enh", "False", "official inference default",
        f"{FLARE_ENH_SOURCE}:deploy_priorenh.py --pre_enh",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "priorenh.w", "0.5", "official inference default",
        f"{FLARE_ENH_SOURCE}:deploy_priorenh.py --w",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "priorenh.input_size", "512", "official inference default and paper table",
        f"{FLARE_ENH_SOURCE}:deploy_priorenh.py::image_read size=512; "
        f"{_PAPER} Table XI",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "priorenh.n_codebook", "4096", "official configuration and paper",
        f"{_VQ_CONFIG} n_codebook; {_PAPER} §IV",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "priorenh.embed_dim", "3", "official configuration and paper",
        f"{_VQ_CONFIG} embed_dim; {_PAPER} §IV",
        OperationAuthority.UPSTREAM_DEFAULT_EXPLICIT,
    ),
    ParameterProvenance(
        "fdrn.input_normalization", "(x - 127.5) / 127.5", "pinned source",
        f"{_FPDATASET}::Descdataset.process_img",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "matching.mask_tiling", "numpy.tile(mask, (1, 2D)) with 2D = 12",
        "pinned source", f"{FLARE_SOURCE}:extract_FDD.py::calculate_score",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "matching.mask_threshold", "none in the continuous route", "pinned source",
        f"{FLARE_SOURCE}:extract_FDD.py::calculate_score",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "matching.denominator_clip", "clip(1e-3, None) on the product x1 * x2",
        "pinned source literal", f"{FLARE_SOURCE}:extract_FDD.py::calculate_score",
        OperationAuthority.UPSTREAM_CODE_EXPLICIT,
    ),
    ParameterProvenance(
        "matching.binary", "False", "paper and identity",
        f"{_PAPER} §III-E Eq. 7", OperationAuthority.PAPER_EXPLICIT,
    ),
    ParameterProvenance(
        "fusion.reduction", "max over the four branches", "paper",
        f"{_PAPER} §III-E Eq. 8", OperationAuthority.PAPER_EXPLICIT,
    ),
)


# ------------------------------------------------------------------- resolution


@dataclass(frozen=True, slots=True)
class TransformGraphResolution:
    """Whether every operation from the input bytes to the tensor has an authority."""

    operation_count: int
    score_affecting_count: int
    authoritative_count: int
    unresolved_operations: tuple[str, ...]
    unresolved_parameters: tuple[str, ...]
    graph_fingerprint: str

    @property
    def resolved(self) -> bool:
        return not self.unresolved_operations and not self.unresolved_parameters


@dataclass(frozen=True, slots=True)
class RouteAuditResult:
    """The paper-against-code audit, reduced to the counts that gate."""

    row_count: int
    score_affecting_ambiguous: tuple[str, ...]
    score_affecting_contradictory: tuple[str, ...]
    glue_required_operations: tuple[str, ...]
    audit_fingerprint: str

    @property
    def resolved(self) -> bool:
        return not self.score_affecting_ambiguous and not (
            self.score_affecting_contradictory
        )


def transform_graph() -> tuple[TransformOperation, ...]:
    """Every operation, in the order the paper's route performs them."""
    return TRANSFORM_OPERATIONS


def resolve_transform_graph() -> TransformGraphResolution:
    """Reduce the graph and the parameter table to the gate's counts."""
    operations = transform_graph()
    unresolved_operations = tuple(
        operation.operation_id for operation in operations if operation.blocks
    )
    unresolved_parameters = tuple(
        parameter.parameter for parameter in PARAMETER_PROVENANCE if parameter.blocks
    )
    return TransformGraphResolution(
        operation_count=len(operations),
        score_affecting_count=sum(1 for item in operations if item.score_affecting),
        authoritative_count=sum(
            1 for item in operations if item.authority.is_authoritative
        ),
        unresolved_operations=unresolved_operations,
        unresolved_parameters=unresolved_parameters,
        graph_fingerprint=stable_hash(
            {
                "schema": "stage_9a_flare_transform_graph_v1",
                "operations": [
                    {
                        "operation_id": item.operation_id,
                        "stage": item.stage,
                        "authority": item.authority.value,
                        "score_affecting": item.score_affecting,
                    }
                    for item in operations
                ],
                "parameters": [
                    {
                        "parameter": item.parameter,
                        "value": item.value,
                        "authority": item.authority.value,
                    }
                    for item in PARAMETER_PROVENANCE
                ],
            },
            length=64,
        ),
    )


def public_code_route_audit() -> RouteAuditResult:
    """One row per operation, reduced to what READY needs to be zero."""
    rows = ROUTE_AUDIT_ROWS
    return RouteAuditResult(
        row_count=len(rows),
        score_affecting_ambiguous=tuple(
            row.operation
            for row in rows
            if row.score_affecting and row.resolution is RouteResolution.AMBIGUOUS
        ),
        score_affecting_contradictory=tuple(
            row.operation
            for row in rows
            if row.score_affecting and row.resolution is RouteResolution.CONTRADICTORY
        ),
        glue_required_operations=tuple(
            row.operation for row in rows if row.fpbench_glue_required
        ),
        audit_fingerprint=stable_hash(
            {
                "schema": "stage_9a_public_code_route_audit_v1",
                "rows": [
                    {
                        "operation": row.operation,
                        "resolution": row.resolution.value,
                        "score_affecting": row.score_affecting,
                        "fpbench_glue_required": row.fpbench_glue_required,
                    }
                    for row in rows
                ],
            },
            length=64,
        ),
    )


def route_blockers() -> tuple[BlockerCode, ...]:
    """The blockers the route alone contributes, derived rather than listed."""
    resolution = resolve_transform_graph()
    audit = public_code_route_audit()
    blockers: list[BlockerCode] = []
    if resolution.unresolved_operations:
        blockers.append(BlockerCode.TRANSFORM_ORDER_AMBIGUOUS)
    if resolution.unresolved_parameters:
        blockers.append(BlockerCode.SCORE_AFFECTING_PARAMETER_UNRESOLVED)
    if audit.score_affecting_contradictory:
        blockers.append(BlockerCode.PAPER_CODE_CONTRADICTION)
    if any(
        row.operation == "four_branch_orchestration" and row.blocks
        for row in ROUTE_AUDIT_ROWS
    ):
        blockers.append(BlockerCode.FULL_FOUR_BRANCH_ROUTE_UNRESOLVED)
    return tuple(blockers)


# ------------------------------------------------------------ published documents


def paper_route_contract() -> Mapping[str, Any]:
    """What the paper says, quoted, with the identity it implies."""
    return {
        "schema": "stage_9a_paper_route_contract_v1",
        "paper": frozen.PAPER_LOCATOR,
        "preprint": frozen.PAPER_ARXIV_LOCATOR,
        "algorithm_candidate": frozen.ALGORITHM_CANDIDATE_ID,
        "display_name": frozen.ALGORITHM_DISPLAY_NAME,
        "input_profile": frozen.INPUT_PROFILE,
        "input_ppi": frozen.INPUT_PPI,
        "input_pixel_format": frozen.INPUT_PIXEL_FORMAT,
        "aligned_geometry": list(frozen.ALIGNED_GEOMETRY),
        "fdrn_geometry": list(frozen.FDRN_GEOMETRY),
        "descriptor_feature_dimension": frozen.DESCRIPTOR_FEATURE_DIMENSION,
        "descriptor_shape": list(frozen.DESCRIPTOR_SHAPE),
        "descriptor_scalar_count": frozen.DESCRIPTOR_SCALAR_COUNT,
        "mask_shape": list(frozen.MASK_SHAPE),
        "mask_scalar_count": frozen.MASK_SCALAR_COUNT,
        "required_pose_estimators": frozen.REQUIRED_POSE_ESTIMATORS,
        "required_enhancers": frozen.REQUIRED_ENHANCERS,
        "branch_count": frozen.BRANCH_COUNT,
        "binary_representation": frozen.BINARY_REPRESENTATION_ENABLED,
        "score_direction": frozen.SCORE_DIRECTION,
        "branches": [
            {
                "branch_id": branch.branch_id,
                "pose_estimator": branch.pose_estimator,
                "enhancer": branch.enhancer,
            }
            for branch in frozen.BRANCHES
        ],
        "route": [
            {
                "order": stage.order,
                "stage_id": stage.stage_id,
                "statement": stage.statement,
                "paper_source": stage.paper_locator,
            }
            for stage in frozen.PAPER_ROUTE
        ],
        "notes": [
            "The branch order is not part of the algorithm, because a maximum "
            "does not depend on the order of its arguments. The branch count "
            "is.",
            "One fingerprint carries four descriptors of 3072 scalars and four "
            "masks of 256, not a single representation of 3072.",
        ],
    }


def score_contract() -> Mapping[str, Any]:
    """The exact arithmetic of one branch score, and of the fusion above it."""
    return {
        "schema": "stage_9a_score_contract_v1",
        "authority": f"{FLARE_SOURCE}:extract_FDD.py::calculate_score, "
        "continuous branch",
        "paper_source": f"{frozen.PAPER_ARXIV_LOCATOR} §III-E, Eq. 7 and Eq. 8",
        "descriptor_shape": list(frozen.DESCRIPTOR_SHAPE),
        "descriptor_scalar_count": frozen.DESCRIPTOR_SCALAR_COUNT,
        "mask_shape": list(frozen.MASK_SHAPE),
        "mask_scalar_count": frozen.MASK_SCALAR_COUNT,
        "flattening_order": (
            "channel-major: torch flatten(1) over an (N, C, H, W) tensor gives "
            "256 values for channel 0, then channel 1, and so on for twelve "
            "channels"
        ),
        "descriptor_composition": (
            "cat(feature_t, feature_m) over the channel axis, texture branch "
            "first"
        ),
        "mask_tiling": (
            "numpy.tile(mask, (1, 12)) repeats the whole 256-value mask block "
            "twelve times, so block c aligns with channel c"
        ),
        "mask_semantics": "continuous, the sigmoid output; no threshold is applied",
        "numerator": "x12 = (m_a * f_a) @ (m_b * f_b).T",
        "denominator_term_1": "x1 = sqrt((m_a * f_a**2) @ m_b.T)",
        "denominator_term_2": "x2 = sqrt(m_a @ (f_b**2 * m_b).T)",
        "denominator_clip": "(x1 * x2).clip(1e-3, None), applied to the product",
        "branch_score": "score = x12 / (x1 * x2).clip(1e-3, None)",
        "fusion": "score = max(branch_scores) over the four branches",
        "dtype": "float32 descriptors and masks; numpy float arithmetic",
        "score_direction": frozen.SCORE_DIRECTION,
        "degenerate_overlap": {
            "behaviour": (
                "as the overlap vanishes the numerator goes to zero while the "
                "clipped denominator stays at 1e-3, so the branch score goes to "
                "zero"
            ),
            "finite": True,
            "new_policy_required": False,
            "authority": (
                f"{FLARE_SOURCE}:extract_FDD.py::calculate_score, the clip "
                "literal"
            ),
        },
        "library_cosine_substitution_permitted": False,
        "notes": [
            "A library cosine over the two flattened descriptors is not this "
            "function. The masks weight the numerator and both denominator "
            "terms, each linearly, and the clip is on the product rather than "
            "on either factor.",
            "The paper's Eq. 7 reads as written under binary masks; the "
            "implementation generalises it to the sigmoid mask by staying "
            "linear in each. Thresholding belongs to the binary branch, which "
            "this identity excludes.",
            "The branch scores are diagnostics of one matcher, not four "
            "algorithms. A future adapter returns the maximum and may report "
            "the winning branch beside it.",
        ],
        "diagnostic_branch_scores": [
            branch.branch_id for branch in frozen.BRANCHES
        ],
    }


def training_provenance() -> Mapping[str, Any]:
    """What the released artifacts were trained on, and what was not found.

    The distinction this document exists to preserve: no mention of SD300 in the
    paper's text is ``NO_EVIDENCE_FOUND``, and it is not ``PROVEN_ABSENT``.
    Absence of evidence is reported as absence of evidence (spec section 18).
    """
    return {
        "schema": "stage_9a_training_provenance_v1",
        "paper": frozen.PAPER_LOCATOR,
        "preprint": frozen.PAPER_ARXIV_LOCATOR,
        "training_datasets": [
            {
                "module": "pose estimation",
                "datasets": [
                    "the Diverse Pose Fingerprint (DPF) dataset: 776 rolled and "
                    "40,112 plain fingerprints",
                    "the first 3,200 rolled fingerprints from the gallery "
                    "portion of NIST SD14",
                ],
                "paper_source": f"{frozen.PAPER_ARXIV_LOCATOR} §IV",
            },
            {
                "module": "enhancement (UNetEnh and PriorEnh)",
                "datasets": [
                    "the DPF dataset, which is also what the PriorEnh codebook "
                    "is constructed from",
                ],
                "paper_source": f"{frozen.PAPER_ARXIV_LOCATOR} §IV",
            },
            {
                "module": "fixed-length dense representation (FDRN)",
                "datasets": [
                    "the first 24,000 pairs of rolled fingerprints from NIST "
                    "SD14",
                    "32,676 plain fingerprints from 633 fingers",
                ],
                "paper_source": f"{frozen.PAPER_ARXIV_LOCATOR} §IV",
            },
        ],
        "datasets_named_anywhere_in_the_paper": [
            "NIST SD4",
            "NIST SD14",
            "NIST SD27",
            "NIST SD302",
            "DPF",
            "N2N Plain",
            "FVC2002 DB3A",
            "FVC2004 DB1A",
            "FVC2006 DB1A",
            "THU Latent10K",
            "PolyU CL2CB",
        ],
        "sd300_training_overlap_status": "NO_EVIDENCE_FOUND",
        "sd300_training_overlap_found": False,
        "search_performed": (
            "the full text of the pinned preprint was searched for SD300, "
            "'SD 300' and 'Special Database 300'; none appears. NIST SD302 does "
            "appear and is a different database"
        ),
        "why_not_proven_absent": (
            "The paper's dataset table is a statement about what the authors "
            "describe, not a guarantee about every checkpoint they released. "
            "Absence of a mention is absence of evidence, and this project does "
            "not upgrade one into the other (spec section 18)."
        ),
        "blocking_rule": (
            "Only positive evidence that the exact released artifacts were "
            "trained, validated, hyperparameter-selected, checkpoint-selected "
            "or threshold-selected on this project's SD300 evaluation cohort "
            "blocks a READY outcome. None was found."
        ),
        "sd300_data_read_by_this_stage": False,
    }
