"""Which checkpoint goes into which model, and whether it fits.

Six checkpoints, five model classes and four different ways of getting bytes
into parameters. That variety is upstream's, not this project's, and the whole
job here is to record it faithfully rather than to normalise it away.

**The bindings are declared, then checked.** :data:`CHECKPOINT_BINDINGS` states,
for each checkpoint, the model class the official script constructs, the exact
constructor arguments it passes, whether it wraps the model in ``DataParallel``,
which loader it calls, where in the checkpoint the parameters live, and what
that loader does to the keys on the way in. Every field is copied from a pinned
official file and names it. :func:`inspect_checkpoint` then opens the actual
bytes and says whether the declaration holds.

**Upstream's loader semantics are preserved, and audited separately.** Both
repositories ship a ``load_model`` that unwraps a ``"model"`` key and strips a
``module.`` prefix before calling ``load_state_dict``. That is legitimate
upstream behaviour and this stage records it. What this stage may not do is add
``strict=False``, filter keys, or substitute a loader of its own and pretend
there was no mapping — so the audit is *independent* of the loader: it counts
what the loader would leave unaccounted for, whatever the loader believes
(docs/adr/0087, spec section 20).

**Nothing here publishes a tensor.** Parameter *names*, counts, shape summaries
and compatibility totals reach the evidence. Parameter values, sample tensors,
state dicts and checkpoint bytes never do (spec section 51).

**Absence is a state, not a failure.** ``torch`` is not a dependency of this
repository and the six checkpoints live outside it, so on most machines — and on
every CI runner by design — the inspection cannot run. That is reported as
``INSPECTION_NOT_PERFORMED`` and is not the same claim as "inspected and found
compatible". A READY outcome requires the second.
"""

from __future__ import annotations

import hashlib
import importlib.util
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from fpbench.core.flare_errors import (
    FlareCheckpointError,
    FlareQualificationError,
    Stage9AFinalizationError,
)
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage9a_flare_artifacts as artifacts
from fpbench.experiments import stage9a_flare_identity as frozen
from fpbench.experiments import stage9a_flare_route as route

__all__ = [
    "ConstructorArgument",
    "KeyTransformation",
    "CheckpointBinding",
    "CHECKPOINT_BINDINGS",
    "REQUIRED_CHECKPOINT_ARTIFACTS",
    "CheckpointInspection",
    "CheckpointCompatibility",
    "CompatibilityReport",
    "binding_for",
    "torch_is_available",
    "inspect_checkpoint",
    "build_compatibility_report",
    "checkpoint_compatibility_document",
    "DENOMINATOR_CLIP",
    "SYNTHETIC_IMAGE_NAMES",
    "reference_branch_score",
    "reference_route_score",
    "write_synthetic_images",
    "RouteModelCase",
    "RouteModelQualification",
    "run_route_model_qualification",
    "FlareByteFinding",
    "FlareByteAudit",
    "flare_artifact_digests",
    "audit_tracked_bytes_against_flare_artifacts",
    "require_no_flare_bytes_in_git",
    "QualificationOutcome",
    "build_qualification_report",
    "qualification_report_document",
]

#: Neither loader in either repository passes ``strict``. ``load_state_dict``
#: defaults to ``strict=True``, so upstream's own contract is that the
#: checkpoint and the model agree exactly — which is why this stage never needs
#: to relax it and never may (spec section 20).
_UPSTREAM_STRICTNESS = "load_state_dict(strict=True), the PyTorch default"


@dataclass(frozen=True, slots=True)
class ConstructorArgument:
    """One argument the official script passes when it builds the model.

    ``source`` is where the value comes from, and it is the interesting field: a
    literal in the script is a different kind of authority from a key in a
    pinned configuration file, and a reader deciding whether fpbench invented
    something needs to see which one this is.
    """

    name: str
    value: str
    source: str


@dataclass(frozen=True, slots=True)
class KeyTransformation:
    """One thing a loader does to checkpoint keys before they reach the model."""

    transformation: str
    condition: str
    upstream_location: str


@dataclass(frozen=True, slots=True)
class CheckpointBinding:
    """One checkpoint, bound to the model class one official script builds.

    Copied field by field from the pinned sources named in
    :attr:`construction_locator` and :attr:`loader_locator`. Nothing is inferred
    and nothing is chosen: where two official scripts do the same thing
    differently — and two of them do — both are recorded as they are.
    """

    artifact_id: str
    model_class: str
    model_module: str
    construction_locator: str
    constructor_arguments: tuple[ConstructorArgument, ...]
    wrapped_in_data_parallel: bool
    loader_function: str
    loader_locator: str
    top_level_structure: str
    state_dict_path: str
    key_transformations: tuple[KeyTransformation, ...]
    strictness: str = _UPSTREAM_STRICTNESS
    inference_role: str = ""
    notes: tuple[str, ...] = ()


_FLARE_MISC_LOADER = (
    "Yu-Yy/FLARE@7d13ca72:utils/misc.py::load_model"
)
_FLARE_ENH_MISC_LOADER = (
    "Yu-Yy/FLARE_ENH@ee735b03:utils/misc.py::load_model"
)

_MODULE_PREFIX_STRIP = KeyTransformation(
    transformation=(
        "every key's second dotted component is removed, so 'module.layer0.0."
        "weight' becomes 'layer0.0.weight'"
    ),
    condition=(
        "the substring 'module' appears anywhere in the first key of the state "
        "dict; the test is on one key and the transformation is then applied to "
        "all of them"
    ),
    upstream_location="load_model::remove_module_string",
)

_MODEL_KEY_OPTIONAL = KeyTransformation(
    transformation="the state dict is taken from checkpoint['model']",
    condition="'model' is a top-level key; otherwise the checkpoint itself is used",
    upstream_location=f"{_FLARE_MISC_LOADER}",
)

_MODEL_KEY_REQUIRED = KeyTransformation(
    transformation="the state dict is taken from checkpoint['model']",
    condition=(
        "unconditional in this repository's loader — there is no fallback to "
        "the checkpoint root, so a checkpoint without that key raises"
    ),
    upstream_location=f"{_FLARE_ENH_MISC_LOADER}",
)

CHECKPOINT_BINDINGS: tuple[CheckpointBinding, ...] = (
    CheckpointBinding(
        artifact_id="flare_fdd_checkpoint",
        model_class="FDD",
        model_module="models.model_zoo",
        construction_locator="Yu-Yy/FLARE@7d13ca72:extract_FDD.py::extracting",
        constructor_arguments=(
            ConstructorArgument(
                "ndim_feat", "6", "model_weights/desc_configs.yaml MODEL.ndim_feat"
            ),
            ConstructorArgument(
                "input_norm",
                "False",
                "model_weights/desc_configs.yaml MODEL.input_norm",
            ),
            ConstructorArgument(
                "tar_shape",
                "(256, 256)",
                "model_weights/desc_configs.yaml MODEL.tar_shape",
            ),
        ),
        wrapped_in_data_parallel=True,
        loader_function="load_model",
        loader_locator=_FLARE_MISC_LOADER,
        top_level_structure="a mapping, either a state dict or a training checkpoint",
        state_dict_path='checkpoint["model"] if present, else the checkpoint itself',
        key_transformations=(_MODEL_KEY_OPTIONAL, _MODULE_PREFIX_STRIP),
        inference_role="descriptor and foreground mask, via FDD.get_embedding",
        notes=(
            "The load is present and active at the pinned commit: the model is "
            "built, moved to CUDA, wrapped in DataParallel, and load_model is "
            "called on model_weights/desc_model.pth.tar.",
            "get_embedding returns feature.flatten(1) and mask.flatten(1); with "
            "ndim_feat 6 and tar_shape 256 that is 3072 and 256 scalars.",
        ),
    ),
    CheckpointBinding(
        artifact_id="flare_voting_pose_checkpoint",
        model_class="GRIDNET4",
        model_module="models.model_zoo",
        construction_locator="Yu-Yy/FLARE@7d13ca72:extract_VotingPose.py::main",
        constructor_arguments=(
            ConstructorArgument("num_pose_2d", "(33, 33, 1)", "a literal in the script"),
            ConstructorArgument(
                "num_layers", "(64, 128, 256, 512)", "a literal in the script"
            ),
            ConstructorArgument("img_ppi", "500", "a literal in the script"),
            ConstructorArgument(
                "middle_shape", "numpy.array([512, 512])", "a literal in the script"
            ),
            ConstructorArgument("activate", "'sigmoid'", "a literal in the script"),
            ConstructorArgument("bin_type", "'invprop'", "a literal in the script"),
            ConstructorArgument("with_tv", "True", "a literal in the script"),
        ),
        wrapped_in_data_parallel=True,
        loader_function="load_model",
        loader_locator=_FLARE_MISC_LOADER,
        top_level_structure="a mapping, either a state dict or a training checkpoint",
        state_dict_path='checkpoint["model"] if present, else the checkpoint itself',
        key_transformations=(_MODEL_KEY_OPTIONAL, _MODULE_PREFIX_STRIP),
        inference_role="pose_2d = (x, y, theta) in the 512x512 aligned frame",
    ),
    CheckpointBinding(
        artifact_id="flare_regression_pose_checkpoint",
        model_class="FingerPose_2D_Single",
        model_module="models.model_zoo",
        construction_locator=(
            "Yu-Yy/FLARE@7d13ca72:extract_RegressionPose.py::main"
        ),
        constructor_arguments=(
            ConstructorArgument("inp_mode", "'fp'", "a literal in the script"),
            ConstructorArgument(
                "trans_out_form", "'claSum'", "a literal in the script"
            ),
            ConstructorArgument("trans_num_classes", "512", "a literal in the script"),
            ConstructorArgument("rot_out_form", "'claSum'", "a literal in the script"),
            ConstructorArgument("rot_num_classes", "180", "a literal in the script"),
        ),
        wrapped_in_data_parallel=True,
        loader_function="load_model",
        loader_locator=(
            "Yu-Yy/FLARE@7d13ca72:extract_RegressionPose.py::load_model"
        ),
        top_level_structure="a mapping, either a state dict or a training checkpoint",
        state_dict_path='checkpoint["model"] if present, else the checkpoint itself',
        key_transformations=(_MODEL_KEY_OPTIONAL, _MODULE_PREFIX_STRIP),
        inference_role=(
            "classify2vector_trans and classify2vector_rot produce (x, y) and "
            "theta; x and y are offset by +256 into the 512x512 frame"
        ),
        notes=(
            "This script does not import utils.misc.load_model; it defines its "
            "own with an identical body plus a by_name shape filter that its "
            "call does not use. The duplication is upstream's and is recorded "
            "rather than unified.",
        ),
    ),
    CheckpointBinding(
        artifact_id="flare_unetenh_checkpoint",
        model_class="SqueezeUNet",
        model_module="model.network",
        construction_locator=(
            "Yu-Yy/FLARE_ENH@ee735b03:deploy_unetenh.py::deploy_enh"
        ),
        constructor_arguments=(
            ConstructorArgument("input_channels", "1", "a literal in the script"),
            ConstructorArgument("num_classes", "2", "a literal in the script"),
            ConstructorArgument(
                "pre_enh",
                "False",
                "the -e command-line flag, which defaults to false",
            ),
        ),
        wrapped_in_data_parallel=False,
        loader_function="load_model",
        loader_locator=_FLARE_ENH_MISC_LOADER,
        top_level_structure='a mapping with a "model" key',
        state_dict_path='checkpoint["model"]',
        key_transformations=(_MODEL_KEY_REQUIRED, _MODULE_PREFIX_STRIP),
        inference_role=(
            "two output channels, split [1, 1]; the first is the enhanced image "
            "in (0, 1) after the network's sigmoid"
        ),
        notes=(
            "No DataParallel wrapper here, unlike the three FLARE models. This "
            "repository's loader also has no fallback when 'model' is absent.",
        ),
    ),
    CheckpointBinding(
        artifact_id="flare_priorenh_checkpoint",
        model_class="VQFPEnhancer_PCNN",
        model_module="model.network",
        construction_locator=(
            "Yu-Yy/FLARE_ENH@ee735b03:deploy_priorenh.py::deploy_enh"
        ),
        constructor_arguments=(
            ConstructorArgument(
                "hdconfig",
                "the hdconfig mapping",
                "pretrained_model/priorenh/vq.yaml",
            ),
            ConstructorArgument(
                "ldconfig",
                "the ldconfig mapping",
                "pretrained_model/priorenh/vq.yaml",
            ),
            ConstructorArgument(
                "n_embed", "4096", "pretrained_model/priorenh/vq.yaml n_codebook"
            ),
            ConstructorArgument(
                "embed_dim", "3", "pretrained_model/priorenh/vq.yaml embed_dim"
            ),
            ConstructorArgument(
                "pcn_embed", "64", "pretrained_model/priorenh/vq.yaml pcn_embed"
            ),
            ConstructorArgument(
                "ckpt_path",
                "pretrained_model/priorenh/Prior.ckpt",
                "pretrained_model/priorenh/vq.yaml ckpt_path",
            ),
            ConstructorArgument(
                "pre_enh",
                "False",
                "the -e command-line flag, which defaults to false",
            ),
        ),
        wrapped_in_data_parallel=False,
        loader_function="load_model",
        loader_locator=_FLARE_ENH_MISC_LOADER,
        top_level_structure='a mapping with a "model" key',
        state_dict_path='checkpoint["model"]',
        key_transformations=(_MODEL_KEY_REQUIRED, _MODULE_PREFIX_STRIP),
        inference_role=(
            "enhance(x, w) returns the decoded image, clamped to [-1, 1] by the "
            "caller"
        ),
        notes=(
            "The constructor asserts ckpt_path is not None and loads the Prior "
            "artifact before this checkpoint is applied, so PriorEnh needs two "
            "sets of weights and the second is named only by vq.yaml.",
        ),
    ),
    CheckpointBinding(
        artifact_id="flare_prior_codebook_checkpoint",
        model_class="VQFPEnhancer_PCNN.save_dict_to_prior",
        model_module="model.network",
        construction_locator=(
            "Yu-Yy/FLARE_ENH@ee735b03:model/network.py::VQFPEnhancer_PCNN.__init__"
        ),
        constructor_arguments=(
            ConstructorArgument(
                "map_location", "'cpu'", "a literal in the constructor"
            ),
        ),
        wrapped_in_data_parallel=False,
        loader_function="save_dict_to_prior",
        loader_locator=(
            "Yu-Yy/FLARE_ENH@ee735b03:model/network.py::"
            "VQFPEnhancer_PCNN.save_dict_to_prior"
        ),
        top_level_structure='a mapping with a "state_dict" key',
        state_dict_path='checkpoint["state_dict"]',
        key_transformations=(
            KeyTransformation(
                transformation=(
                    "keys are routed into five sub-modules by prefix — encoder., "
                    "decoder., quantize., quant_conv., post_quant_conv. — and "
                    "the prefix is stripped from each"
                ),
                condition="the key starts with one of those five prefixes",
                upstream_location="save_dict_to_prior",
            ),
            KeyTransformation(
                transformation=(
                    "a key matching none of the five prefixes is dropped, "
                    "silently: the routing has no else branch"
                ),
                condition="always",
                upstream_location="save_dict_to_prior",
            ),
        ),
        inference_role=(
            "the frozen VQ-VAE codebook and high-resolution decoder that guide "
            "PriorEnh; every parameter has requires_grad set to False after "
            "loading"
        ),
        notes=(
            "A different top-level structure from the other five, and a "
            "different loader. The silent drop is why this stage counts skipped "
            "keys independently of what the loader reports (spec section 21).",
        ),
    ),
)

#: The artifacts a checkpoint binding exists for, in the binding order.
REQUIRED_CHECKPOINT_ARTIFACTS: tuple[str, ...] = tuple(
    binding.artifact_id for binding in CHECKPOINT_BINDINGS
)


def binding_for(artifact_id: str) -> CheckpointBinding:
    for binding in CHECKPOINT_BINDINGS:
        if binding.artifact_id == artifact_id:
            return binding
    raise FlareCheckpointError(
        f"{artifact_id} has no declared checkpoint binding; a checkpoint whose "
        "intended model class is unstated cannot be qualified"
    )


# ---------------------------------------------------------------- inspection


def torch_is_available() -> bool:
    """Whether the runtime that could open a checkpoint is installed here.

    ``torch`` is not a dependency of this repository and Stage 9A does not make
    it one: the runtime question belongs to Stage 9B (spec section 36).
    """
    return importlib.util.find_spec("torch") is not None


@dataclass(frozen=True, slots=True)
class CheckpointInspection:
    """What was actually found inside one checkpoint's bytes.

    ``performed`` is the first thing to read. Everything below it describes an
    inspection that happened; when it is ``False`` the fields are empty and
    ``reason`` says why, which is a different claim from "inspected and found
    nothing wrong".
    """

    artifact_id: str
    performed: bool
    reason: str = ""
    top_level_keys: tuple[str, ...] = ()
    state_dict_path_taken: str = ""
    parameter_key_count: int = 0
    module_prefixed_key_count: int = 0
    key_prefix_histogram: Mapping[str, int] = field(default_factory=dict)
    non_tensor_top_level_keys: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()


def inspect_checkpoint(
    artifact_id: str, *, root: Path | None = None, repository_root: Path | None = None
) -> CheckpointInspection:
    """Open one checkpoint and describe its structure. No value is read out.

    Loads with ``map_location="cpu"`` and ``weights_only=True`` where the
    installed torch supports it, because this function's whole purpose is to
    look at somebody else's file and it should not be able to execute it. Keys
    and shapes are read; tensor contents are not touched.

    Absence of ``torch`` or of the artifact is reported, not raised: on every CI
    runner both are absent by design.
    """
    binding = binding_for(artifact_id)
    artifact = next(
        (item for item in frozen.REQUIRED_ARTIFACTS if item.artifact_id == artifact_id),
        None,
    )
    if artifact is None:  # pragma: no cover - bindings and artifacts are paired
        raise FlareCheckpointError(f"{artifact_id} is not a required artifact")

    if not torch_is_available():
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=False,
            reason="torch is not installed here; the runtime question is Stage 9B's",
        )
    if not artifact.identity_established:
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=False,
            reason=(
                "no identity has been established for this artifact, so there "
                "are no expected bytes to inspect"
            ),
        )
    verification = artifacts.verify_artifact(
        artifact, root=root, repository_root=repository_root
    )
    if not verification.verified:
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=False,
            reason=(
                "the artifact is absent from this machine's store"
                if not verification.present
                else "the bytes on this machine are not the bytes expected"
            ),
        )

    import torch  # noqa: PLC0415 - deliberately deferred; not a dependency

    store = artifacts.resolve_third_party_root(repository_root=repository_root)
    path = artifacts.resolve_store_path(
        artifact, root=Path(root) if root is not None else store
    )
    try:
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except TypeError:  # pragma: no cover - torch < 1.13
            payload = torch.load(path, map_location="cpu")
    except Exception as exc:  # pragma: no cover - a corrupt checkpoint
        raise FlareCheckpointError(
            f"{artifact_id}: the checkpoint could not be opened: {exc}"
        ) from exc

    findings: list[str] = []
    if not isinstance(payload, Mapping):
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=True,
            reason="",
            findings=(
                f"the checkpoint deserialises to {type(payload).__name__} and "
                f"the binding expects {binding.top_level_structure}",
            ),
        )

    top_level = tuple(sorted(str(key) for key in payload))
    if binding.state_dict_path.startswith('checkpoint["state_dict"]'):
        wanted = "state_dict"
    else:
        wanted = "model"
    if wanted in payload:
        state = payload[wanted]
        taken = f'checkpoint["{wanted}"]'
    elif binding.state_dict_path.endswith("else the checkpoint itself"):
        state = payload
        taken = "the checkpoint itself"
    else:
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=True,
            top_level_keys=top_level,
            findings=(
                f'the binding takes parameters from checkpoint["{wanted}"] and '
                "the checkpoint has no such key",
            ),
        )
    if not isinstance(state, Mapping):
        return CheckpointInspection(
            artifact_id=artifact_id,
            performed=True,
            top_level_keys=top_level,
            state_dict_path_taken=taken,
            findings=(f"{taken} is not a mapping of parameter names to tensors",),
        )

    names = [str(key) for key in state]
    prefixes: dict[str, int] = {}
    for name in names:
        head = name.split(".", 1)[0]
        prefixes[head] = prefixes.get(head, 0) + 1
    module_prefixed = sum(1 for name in names if name.split(".", 1)[0] == "module")
    non_tensor = tuple(
        sorted(
            str(key)
            for key, value in payload.items()
            if key != wanted and not hasattr(value, "shape")
        )
    )
    if names and ("module" in names[0]) != (module_prefixed == len(names)):
        findings.append(
            "the loader decides whether to strip a prefix from one key and "
            "applies the result to all of them; here those two answers differ"
        )

    return CheckpointInspection(
        artifact_id=artifact_id,
        performed=True,
        top_level_keys=top_level,
        state_dict_path_taken=taken,
        parameter_key_count=len(names),
        module_prefixed_key_count=module_prefixed,
        key_prefix_histogram={key: prefixes[key] for key in sorted(prefixes)},
        non_tensor_top_level_keys=non_tensor,
        findings=tuple(findings),
    )


# ------------------------------------------------------------- compatibility


@dataclass(frozen=True, slots=True)
class CheckpointCompatibility:
    """One checkpoint's fit to its model, in the four counts that gate.

    ``unexplained`` is the word that matters in every one of them. A missing
    parameter that upstream's own loader accounts for is explained; an optimizer
    state at the top level of a training checkpoint is explained; anything left
    over is not, and any of it blocks (spec section 21).
    """

    artifact_id: str
    model_class: str
    established: bool
    inspection_performed: bool
    reason: str = ""
    inference_required_parameters: int = 0
    loaded_parameters: int = 0
    unexplained_missing_parameters: int = 0
    unexplained_shape_mismatches: int = 0
    unexplained_skipped_inference_affecting_keys: int = 0
    explained_non_model_keys: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    @property
    def compatible(self) -> bool:
        return (
            self.established
            and self.inspection_performed
            and self.unexplained_missing_parameters == 0
            and self.unexplained_shape_mismatches == 0
            and self.unexplained_skipped_inference_affecting_keys == 0
            and not self.findings
        )


#: Top-level entries a training checkpoint legitimately carries beside its
#: parameters. Present here means "explained", never "ignored" (spec section 21).
_EXPLAINED_NON_MODEL_KEYS: frozenset[str] = frozenset(
    {"epoch", "optimizer", "optim", "lr_scheduler", "schedule", "global_step",
     "best", "args", "config", "hyper_parameters", "pytorch-lightning_version"}
)


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Every checkpoint, and whether its binding to a model was established."""

    entries: tuple[CheckpointCompatibility, ...]
    torch_available: bool
    report_fingerprint: str

    @property
    def all_established(self) -> bool:
        return bool(self.entries) and all(item.compatible for item in self.entries)

    @property
    def unestablished(self) -> tuple[str, ...]:
        return tuple(item.artifact_id for item in self.entries if not item.compatible)


def build_compatibility_report(
    *, root: Path | None = None, repository_root: Path | None = None
) -> CompatibilityReport:
    """Inspect what can be inspected, and say plainly what could not.

    Constructing the model classes themselves is deliberately *not* attempted
    here: that would mean importing upstream source into this process, which is
    a runtime question and belongs to Stage 9B. What this does is establish the
    half that does not need a runtime — the declared binding, the checkpoint's
    real structure, and whether the two agree — and report the other half as
    not performed.
    """
    entries: list[CheckpointCompatibility] = []
    available = torch_is_available()
    for binding in CHECKPOINT_BINDINGS:
        inspection = inspect_checkpoint(
            binding.artifact_id, root=root, repository_root=repository_root
        )
        if not inspection.performed:
            entries.append(
                CheckpointCompatibility(
                    artifact_id=binding.artifact_id,
                    model_class=binding.model_class,
                    established=False,
                    inspection_performed=False,
                    reason=inspection.reason,
                )
            )
            continue
        explained = tuple(
            key
            for key in inspection.non_tensor_top_level_keys
            if key.lower() in _EXPLAINED_NON_MODEL_KEYS
        )
        unexplained_top_level = tuple(
            key
            for key in inspection.non_tensor_top_level_keys
            if key.lower() not in _EXPLAINED_NON_MODEL_KEYS
        )
        findings = list(inspection.findings)
        findings.extend(
            f"top-level key {key!r} is neither a parameter nor recognised "
            "training metadata"
            for key in unexplained_top_level
        )
        entries.append(
            CheckpointCompatibility(
                artifact_id=binding.artifact_id,
                model_class=binding.model_class,
                # The full establishment needs the model class constructed, and
                # that needs a runtime. Structure alone is not the claim.
                established=False,
                inspection_performed=True,
                reason=(
                    "the checkpoint's structure was read; binding it to a "
                    "constructed model needs the upstream runtime, which is "
                    "Stage 9B's subject"
                ),
                loaded_parameters=inspection.parameter_key_count,
                explained_non_model_keys=explained,
                findings=tuple(findings),
            )
        )
    ordered = tuple(sorted(entries, key=lambda item: item.artifact_id))
    return CompatibilityReport(
        entries=ordered,
        torch_available=available,
        report_fingerprint=stable_hash(
            {
                "schema": "stage_9a_checkpoint_compatibility_v1",
                "entries": [
                    {
                        "artifact_id": item.artifact_id,
                        "model_class": item.model_class,
                        "established": item.established,
                        "inspection_performed": item.inspection_performed,
                        "unexplained_missing_parameters": (
                            item.unexplained_missing_parameters
                        ),
                        "unexplained_shape_mismatches": (
                            item.unexplained_shape_mismatches
                        ),
                        "unexplained_skipped_inference_affecting_keys": (
                            item.unexplained_skipped_inference_affecting_keys
                        ),
                    }
                    for item in ordered
                ],
            },
            length=64,
        ),
    )


def checkpoint_compatibility_document(
    report: CompatibilityReport,
) -> Mapping[str, Any]:
    """The published form: bindings, counts and reasons. No tensor, ever."""
    return {
        "schema": "stage_9a_checkpoint_compatibility_v1",
        "upstream_strictness": _UPSTREAM_STRICTNESS,
        "fpbench_relaxes_strictness": False,
        "fpbench_filters_keys": False,
        "fpbench_substitutes_its_own_loader": False,
        "torch_available_on_this_machine": report.torch_available,
        "all_bindings_established": report.all_established,
        "unestablished": list(report.unestablished),
        "report_fingerprint": report.report_fingerprint,
        "bindings": [
            {
                "artifact_id": binding.artifact_id,
                "intended_model_class": binding.model_class,
                "model_module": binding.model_module,
                "construction_locator": binding.construction_locator,
                "constructor_arguments": [
                    {
                        "name": argument.name,
                        "value": argument.value,
                        "source": argument.source,
                    }
                    for argument in binding.constructor_arguments
                ],
                "wrapped_in_data_parallel": binding.wrapped_in_data_parallel,
                "loader_function": binding.loader_function,
                "loader_locator": binding.loader_locator,
                "top_level_structure": binding.top_level_structure,
                "state_dict_path": binding.state_dict_path,
                "key_transformation_behaviour": [
                    {
                        "transformation": item.transformation,
                        "condition": item.condition,
                        "upstream_location": item.upstream_location,
                    }
                    for item in binding.key_transformations
                ],
                "strictness": binding.strictness,
                "inference_role": binding.inference_role,
                "notes": list(binding.notes),
            }
            for binding in CHECKPOINT_BINDINGS
        ],
        "compatibility": [
            {
                "artifact_id": item.artifact_id,
                "model_class": item.model_class,
                "established": item.established,
                "inspection_performed": item.inspection_performed,
                "reason": item.reason,
                "loaded_parameters": item.loaded_parameters,
                "unexplained_missing_parameters": (
                    item.unexplained_missing_parameters
                ),
                "unexplained_shape_mismatches": item.unexplained_shape_mismatches,
                "unexplained_skipped_inference_affecting_keys": (
                    item.unexplained_skipped_inference_affecting_keys
                ),
                "explained_non_model_keys": list(item.explained_non_model_keys),
                "findings": list(item.findings),
            }
            for item in report.entries
        ],
        "notes": [
            "Upstream's loader semantics are preserved rather than replaced. "
            "Both repositories unwrap a 'model' key and strip a 'module.' "
            "prefix before load_state_dict, and neither passes strict=False.",
            "The Prior artifact is loaded by a different path from the other "
            "five — checkpoint['state_dict'], routed into five sub-modules by "
            "prefix — and a key matching none of those prefixes is dropped "
            "without comment. That is why skipped keys are counted here rather "
            "than taken from the loader.",
        ],
    }


# ------------------------------------------------------------ the route model
#
# A *model* of the score contract, not an adapter. It exists so the arithmetic
# frozen in stage9a_flare_route.score_contract() can be exercised — is it
# symmetric, does it reach one for identical inputs, does it stay finite when
# two foregrounds barely overlap, does the continuous mask actually matter — and
# it computes over lists of floats that no fingerprint produced. Stage 9B builds
# the adapter; this cannot become one, because it never sees an image, a
# checkpoint or a network (spec sections 38 and 43).

#: The clip upstream applies to the product of the two denominator terms.
DENOMINATOR_CLIP = 1e-3

#: The synthetic images a local smoke run needs. Generated into a temporary
#: directory at test time and never committed: the repository guard allows ten
#: historical imaging fixtures by name and nothing else (spec section 39).
SYNTHETIC_IMAGE_NAMES: tuple[str, ...] = (
    "synthetic_white_512.png",
    "synthetic_black_512.png",
    "synthetic_gradient_512.png",
    "synthetic_ridges_512.png",
    "synthetic_rectangle_640x480.png",
    "synthetic_odd_513x407.png",
)


def _tiled(mask: Sequence[float], channels: int) -> list[float]:
    """``numpy.tile(mask, (1, channels))`` for one row, in plain Python.

    The whole 256-value block is repeated, so block ``c`` lines up with channel
    ``c`` of a descriptor that was flattened channel-major. Getting this wrong
    would silently compare a mask cell against the wrong channel and still
    produce a plausible number.
    """
    return list(mask) * channels


def reference_branch_score(
    descriptor_a: Sequence[float],
    descriptor_b: Sequence[float],
    mask_a: Sequence[float],
    mask_b: Sequence[float],
    *,
    channels: int = 2 * frozen.DESCRIPTOR_FEATURE_DIMENSION,
) -> float:
    """One branch's overlap-masked cosine, exactly as upstream computes it.

    Transcribed from the continuous branch of ``calculate_score``: both masks
    multiply the numerator and both denominator terms, each linearly, and the
    clip is applied to the *product* of the terms rather than to either of them.

    Raises:
        FlareQualificationError: the lengths do not agree with the frozen
            descriptor and mask shapes. A score over mismatched vectors is a
            number nobody can interpret.
    """
    if len(descriptor_a) != len(descriptor_b):
        raise FlareQualificationError("the two descriptors have different lengths")
    if len(mask_a) != len(mask_b):
        raise FlareQualificationError("the two masks have different lengths")
    if len(descriptor_a) != len(mask_a) * channels:
        raise FlareQualificationError(
            f"a descriptor of {len(descriptor_a)} values does not tile a mask of "
            f"{len(mask_a)} values across {channels} channels"
        )
    tiled_a = _tiled(mask_a, channels)
    tiled_b = _tiled(mask_b, channels)
    numerator = 0.0
    term_1 = 0.0
    term_2 = 0.0
    for index, (value_a, value_b) in enumerate(zip(descriptor_a, descriptor_b)):
        weight_a = tiled_a[index]
        weight_b = tiled_b[index]
        numerator += (weight_a * value_a) * (weight_b * value_b)
        term_1 += weight_a * value_a * value_a * weight_b
        term_2 += weight_a * value_b * value_b * weight_b
    denominator = math.sqrt(term_1) * math.sqrt(term_2)
    return numerator / max(denominator, DENOMINATOR_CLIP)


def reference_route_score(
    branch_scores: Mapping[str, float],
) -> tuple[float, str]:
    """The maximum of the four branch scores, and which branch won.

    Raises:
        FlareQualificationError: fewer or more than the four frozen branches.
            A maximum over three is a different function from a maximum over
            four, and it is not this algorithm (docs/adr/0085).
    """
    expected = {branch.branch_id for branch in frozen.BRANCHES}
    present = set(branch_scores)
    if present != expected:
        raise FlareQualificationError(
            f"the route fuses exactly {sorted(expected)} and was given "
            f"{sorted(present)}"
        )
    winner = max(expected, key=lambda name: (branch_scores[name], name))
    return branch_scores[winner], winner


def write_synthetic_images(directory: Path) -> tuple[Path, ...]:
    """Generate the smoke images into a caller-supplied directory.

    White, black, a gradient, a ridge-like pattern, a rectangle and an
    odd-sized image — enough to exercise geometry handling without any
    fingerprint existing anywhere near the process. Nothing real is used for
    artifact qualification (spec section 40).

    Raises:
        FlareQualificationError: the directory is inside this repository. These
            are generated at test time precisely so that they are never
            committed, and a helper that could write into the tree would make
            that an accident away from being untrue.
    """
    from PIL import Image  # noqa: PLC0415 - only needed when images are wanted

    directory = Path(directory)
    repository = Path(__file__).resolve().parents[3]
    try:
        resolved = directory.resolve()
    except OSError as exc:  # pragma: no cover - unreadable path
        raise FlareQualificationError(f"cannot resolve {directory}: {exc}") from exc
    if resolved == repository or repository in resolved.parents:
        raise FlareQualificationError(
            f"{resolved} is inside the repository. Stage 9A adds no image to "
            "this tree; the synthetic fixtures are generated into a temporary "
            "directory at test time (spec section 39)"
        )
    directory.mkdir(parents=True, exist_ok=True)

    def _save(name: str, width: int, height: int, pixel) -> Path:
        image = Image.new("L", (width, height))
        image.putdata([pixel(x, y) for y in range(height) for x in range(width)])
        path = directory / name
        image.save(path, format="PNG")
        return path

    written = (
        _save("synthetic_white_512.png", 512, 512, lambda x, y: 255),
        _save("synthetic_black_512.png", 512, 512, lambda x, y: 0),
        _save("synthetic_gradient_512.png", 512, 512, lambda x, y: (x * 255) // 511),
        _save(
            "synthetic_ridges_512.png",
            512,
            512,
            lambda x, y: 255 if ((x + y) // 6) % 2 else 0,
        ),
        _save(
            "synthetic_rectangle_640x480.png",
            640,
            480,
            lambda x, y: 255 if 100 < x < 540 and 80 < y < 400 else 0,
        ),
        _save(
            "synthetic_odd_513x407.png",
            513,
            407,
            lambda x, y: (x * 7 + y * 5) % 256,
        ),
    )
    return written


@dataclass(frozen=True, slots=True)
class RouteModelCase:
    """One property of the frozen score contract, exercised and recorded."""

    case_id: str
    claim: str
    holds: bool
    observed: str


@dataclass(frozen=True, slots=True)
class RouteModelQualification:
    """Every property, and whether the contract as written actually has it."""

    cases: tuple[RouteModelCase, ...]
    qualification_fingerprint: str

    @property
    def all_hold(self) -> bool:
        return bool(self.cases) and all(case.holds for case in self.cases)

    @property
    def failing(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.cases if not case.holds)


def _constant(value: float, length: int) -> list[float]:
    return [value] * length


def run_route_model_qualification() -> RouteModelQualification:
    """Exercise the score contract over vectors no fingerprint produced.

    Structural qualification, not accuracy. None of these cases says FLARE
    recognises anything; they say the arithmetic this stage froze is the
    arithmetic it claims to be.
    """
    scalars = frozen.DESCRIPTOR_SCALAR_COUNT
    cells = frozen.MASK_SCALAR_COUNT
    channels = 2 * frozen.DESCRIPTOR_FEATURE_DIMENSION
    cases: list[RouteModelCase] = []

    descriptor = [((index % 17) - 8) / 8.0 for index in range(scalars)]
    other = [((index % 11) - 5) / 5.0 for index in range(scalars)]
    full = _constant(1.0, cells)
    empty = _constant(0.0, cells)
    half = _constant(0.5, cells)

    identical = reference_branch_score(descriptor, descriptor, full, full)
    cases.append(
        RouteModelCase(
            case_id="identical_descriptors_under_full_masks_score_one",
            claim=(
                "the masked cosine of a descriptor with itself, under masks of "
                "one, is one"
            ),
            holds=abs(identical - 1.0) < 1e-9,
            observed=f"{identical:.12f}",
        )
    )

    forward = reference_branch_score(descriptor, other, full, half)
    backward = reference_branch_score(other, descriptor, half, full)
    cases.append(
        RouteModelCase(
            case_id="score_is_symmetric_in_its_two_arguments",
            claim=(
                "swapping the two fingerprints swaps the two denominator terms "
                "and leaves their product, so the score is unchanged"
            ),
            holds=abs(forward - backward) < 1e-12,
            observed=f"{forward:.12f} and {backward:.12f}",
        )
    )

    disjoint = reference_branch_score(descriptor, other, full, empty)
    cases.append(
        RouteModelCase(
            case_id="empty_overlap_gives_a_finite_zero",
            claim=(
                "with no overlapping foreground the numerator vanishes and the "
                "clipped denominator holds at 1e-3, so the score is zero and "
                "finite"
            ),
            holds=disjoint == 0.0 and math.isfinite(disjoint),
            observed=f"{disjoint!r}",
        )
    )

    tiny = _constant(1e-9, cells)
    degenerate = reference_branch_score(descriptor, other, tiny, tiny)
    cases.append(
        RouteModelCase(
            case_id="vanishing_overlap_stays_finite",
            claim=(
                "as the mask goes to zero the clip keeps the denominator away "
                "from zero, so no division by zero can occur"
            ),
            holds=math.isfinite(degenerate) and abs(degenerate) < 1.0,
            observed=f"{degenerate:.3e}",
        )
    )

    uniform_half = reference_branch_score(descriptor, other, half, full)
    uniform_full = reference_branch_score(descriptor, other, full, full)
    cases.append(
        RouteModelCase(
            case_id="a_uniform_mask_rescaling_does_not_change_the_score",
            claim=(
                "scaling a whole mask by a constant multiplies the numerator and "
                "both denominator terms' product by the same constant, so the "
                "score is unchanged while the clip does not bind. The mask's "
                "absolute magnitude carries no information; only its spatial "
                "profile does"
            ),
            holds=abs(uniform_half - uniform_full) < 1e-12,
            observed=f"{uniform_half:.12f} against {uniform_full:.12f}",
        )
    )

    profiled = [1.0 if index % 3 else 0.05 for index in range(cells)]
    varying = reference_branch_score(descriptor, other, profiled, full)
    cases.append(
        RouteModelCase(
            case_id="a_spatially_varying_mask_changes_the_score",
            claim=(
                "a mask that weights some cells more than others gives a "
                "different score, which is why rounding the sigmoid mask to a "
                "boolean would not be a harmless simplification"
            ),
            holds=abs(varying - uniform_full) > 1e-12,
            observed=f"{varying:.12f} against {uniform_full:.12f}",
        )
    )

    shifted = list(descriptor[cells:]) + list(descriptor[:cells])
    rotated_mask = _constant(1.0, cells)
    misaligned = reference_branch_score(descriptor, shifted, rotated_mask, rotated_mask)
    cases.append(
        RouteModelCase(
            case_id="mask_tiling_aligns_block_c_with_channel_c",
            claim=(
                "rotating the descriptor by one whole channel block changes the "
                "score, which is what shows the tiling is channel-aligned"
            ),
            holds=abs(misaligned - identical) > 1e-9,
            observed=f"{misaligned:.12f} against {identical:.12f}",
        )
    )

    branch_scores = {
        "voting_unetenh": 0.11,
        "voting_priorenh": 0.42,
        "regression_unetenh": 0.37,
        "regression_priorenh": 0.05,
    }
    fused, winner = reference_route_score(branch_scores)
    cases.append(
        RouteModelCase(
            case_id="fusion_takes_the_maximum_of_exactly_four_branches",
            claim="the route score is the maximum over the four frozen branches",
            holds=fused == 0.42 and winner == "voting_priorenh",
            observed=f"{fused} from {winner}",
        )
    )

    reordered = dict(reversed(list(branch_scores.items())))
    reordered_score, _ = reference_route_score(reordered)
    cases.append(
        RouteModelCase(
            case_id="fusion_does_not_depend_on_branch_order",
            claim=(
                "a maximum does not depend on the order of its arguments, which "
                "is why the branch order is not part of the algorithm"
            ),
            holds=reordered_score == fused,
            observed=f"{reordered_score} and {fused}",
        )
    )

    incomplete = dict(list(branch_scores.items())[:3])
    try:
        reference_route_score(incomplete)
    except FlareQualificationError:
        refused = True
    else:  # pragma: no cover - the refusal is the point
        refused = False
    cases.append(
        RouteModelCase(
            case_id="fusion_refuses_fewer_than_four_branches",
            claim=(
                "a maximum over three branches is a different function and is "
                "not this algorithm"
            ),
            holds=refused,
            observed="refused" if refused else "accepted three branches",
        )
    )

    try:
        reference_branch_score(descriptor[:-1], other[:-1], full, full)
    except FlareQualificationError:
        shape_refused = True
    else:  # pragma: no cover - the refusal is the point
        shape_refused = False
    cases.append(
        RouteModelCase(
            case_id="score_refuses_a_descriptor_that_does_not_tile_its_mask",
            claim=(
                "a descriptor whose length is not the mask length times twelve "
                "cannot be scored"
            ),
            holds=shape_refused,
            observed="refused" if shape_refused else "accepted a mismatched pair",
        )
    )

    cases.append(
        RouteModelCase(
            case_id="descriptor_and_mask_shapes_match_the_frozen_identity",
            claim=(
                "one branch produces 3072 descriptor scalars and 256 mask "
                "scalars, and one fingerprint carries four of each"
            ),
            holds=(
                scalars == 3072
                and cells == 256
                and channels == 12
                and len(frozen.BRANCHES) == frozen.BRANCH_COUNT == 4
            ),
            observed=(
                f"{scalars} descriptor scalars, {cells} mask scalars, "
                f"{channels} channels, {len(frozen.BRANCHES)} branches"
            ),
        )
    )

    ordered = tuple(sorted(cases, key=lambda case: case.case_id))
    return RouteModelQualification(
        cases=ordered,
        qualification_fingerprint=stable_hash(
            {
                "schema": "stage_9a_route_model_qualification_v1",
                "cases": [
                    {"case_id": case.case_id, "holds": case.holds}
                    for case in ordered
                ],
            },
            length=64,
        ),
    )


# --------------------------------------------------- the FLARE-exact byte guard
#
# Stage 8E's guard is generic and its digest registry is hard-coded, and Stage
# 8E is closed: adding a FLARE digest to it is exactly the edit spec section 3
# forbids. So Stage 9A carries its own exact-digest guard beside it. Together
# they give full coverage — the generic rules catch a checkpoint by extension,
# by name, by size and by path, and this catches these particular bytes however
# they were renamed (spec section 52).


@dataclass(frozen=True, slots=True)
class FlareByteFinding:
    """One tracked path whose bytes are a FLARE artifact."""

    path: str
    artifact_id: str
    component_role: str


@dataclass(frozen=True, slots=True)
class FlareByteAudit:
    """What the FLARE-exact guard found across every file Git tracks."""

    tracked_file_count: int
    hashed_file_count: int
    known_digest_count: int
    findings: tuple[FlareByteFinding, ...]

    @property
    def clean(self) -> bool:
        return not self.findings


def flare_artifact_digests() -> Mapping[str, tuple[str, str]]:
    """Every FLARE digest this repository pins, keyed by digest.

    Grows by itself as identities are enrolled: an artifact that gains an
    expected digest gains guard coverage in the same edit, rather than in a
    second one somebody has to remember.
    """
    return {
        artifact.expected_sha256: (artifact.artifact_id, artifact.component_role)
        for artifact in frozen.REQUIRED_ARTIFACTS
        if artifact.expected_sha256 is not None
    }


def _tracked_files(repository_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ("git", "-C", str(repository_root), "ls-files", "-z"),
            check=False,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Stage9AFinalizationError(
            f"cannot read the tracked file list with Git: {exc}"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise Stage9AFinalizationError(
            "cannot read the tracked file list with Git"
            + (f": {detail}" if detail else "")
        )
    names = completed.stdout.decode("utf-8", "surrogateescape").split("\0")
    return tuple(sorted(name for name in names if name))


def audit_tracked_bytes_against_flare_artifacts(
    repository_root: Path,
    *,
    digests: Mapping[str, tuple[str, str]] | None = None,
) -> FlareByteAudit:
    """Hash every tracked file and compare it with every FLARE digest.

    Returns a report rather than raising, because the caller publishing evidence
    needs to say what was scanned even when nothing was found — an audit that
    only spoke up on failure would be indistinguishable from one that never ran.

    ``digests`` is injectable so that a test can point the guard at a digest it
    is allowed to reproduce. A guard whose *catching* branch nobody had exercised
    would be a guard qualified only on the case where it does nothing.
    """
    repository_root = Path(repository_root)
    digests = flare_artifact_digests() if digests is None else dict(digests)
    paths = _tracked_files(repository_root)
    findings: list[FlareByteFinding] = []
    hashed = 0
    for relative in paths:
        absolute = repository_root / PurePosixPath(relative)
        try:
            payload = absolute.read_bytes()
        except OSError:
            # Tracked but absent from this checkout. Nothing to hash; Stage 8E's
            # name-based rules have already run over it.
            continue
        hashed += 1
        digest = hashlib.sha256(payload).hexdigest()
        if digest in digests:
            artifact_id, role = digests[digest]
            findings.append(
                FlareByteFinding(
                    path=relative, artifact_id=artifact_id, component_role=role
                )
            )
    return FlareByteAudit(
        tracked_file_count=len(paths),
        hashed_file_count=hashed,
        known_digest_count=len(digests),
        findings=tuple(sorted(findings, key=lambda item: item.path)),
    )


def require_no_flare_bytes_in_git(repository_root: Path) -> FlareByteAudit:
    """The raising form, for a gate.

    Raises:
        Stage9AFinalizationError: a tracked file is byte-for-byte a FLARE
            artifact.
    """
    audit = audit_tracked_bytes_against_flare_artifacts(repository_root)
    if not audit.clean:
        detail = "; ".join(
            f"{finding.path} is {finding.component_role}"
            for finding in audit.findings
        )
        raise Stage9AFinalizationError(
            f"FLARE bytes are tracked in this public repository: {detail}"
        )
    return audit


# ------------------------------------------------------------ the qualification


@dataclass(frozen=True, slots=True)
class QualificationOutcome:
    """Everything Stage 9A established, and the outcome that follows from it.

    The outcome is *derived*. There is no parameter through which a caller could
    supply one, for the reason Stage 8E's decision engine has none: a
    qualification that accepted a verdict and then checked it would be an
    elaborate way of writing the verdict down.
    """

    outcome: str
    blockers: tuple[BlockerDetail, ...]

    all_identities_established: bool
    all_locally_verified: bool
    research_use_opens_execution: bool
    checkpoint_compatibility_established: bool
    paper_route_resolved: bool
    public_code_route_resolved: bool
    transform_graph_resolved: bool
    parameter_provenance_complete: bool
    route_model_holds: bool
    training_overlap_found: bool
    flare_bytes_in_git: int

    qualification_fingerprint: str

    @property
    def ready(self) -> bool:
        return self.outcome == frozen.STAGE_9A_READY_OUTCOME


@dataclass(frozen=True, slots=True)
class BlockerDetail:
    """One blocker, with what it affects and why fidelity cannot be established."""

    blocker_code: str
    affected_component: str
    evidence: str
    why_score_fidelity_cannot_be_established: str


def build_qualification_report(
    *, repository_root: Path, root: Path | None = None
) -> QualificationOutcome:
    """Run every gate and let the outcome follow from what they found."""
    repository_root = Path(repository_root)
    artifacts.require_stage8e_is_the_policy_this_reuses(repository_root)

    inventory = artifacts.build_artifact_inventory(
        root=root, repository_root=repository_root
    )
    usage = artifacts.build_flare_usage_audit()
    compatibility = build_compatibility_report(
        root=root, repository_root=repository_root
    )
    graph = route.resolve_transform_graph()
    audit = route.public_code_route_audit()
    model = run_route_model_qualification()
    provenance = route.training_provenance()
    byte_audit = audit_tracked_bytes_against_flare_artifacts(repository_root)

    blockers: list[BlockerDetail] = []

    if not inventory.all_identities_established:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.ARTIFACT_IDENTITY_UNRESOLVED.value,
                affected_component=", ".join(
                    status.artifact_id
                    for status in inventory.statuses
                    if not status.identity_frozen
                ),
                evidence=(
                    "artifact-manifest.json: expected_sha256 is null for these "
                    "artifacts, whose only locator is a Google Drive file id"
                ),
                why_score_fidelity_cannot_be_established=(
                    "A Drive id names a place, not bytes. Two downloads from "
                    "the same link at different times cannot be shown to be the "
                    "same artifact, so a score could not be attributed to any "
                    "particular set of weights."
                ),
            )
        )
    if not inventory.all_locally_verified:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.REQUIRED_ARTIFACT_MISSING.value,
                affected_component=", ".join(inventory.missing),
                evidence=(
                    "artifact-manifest.json local_status: these artifacts do not "
                    "verify against the manifest on the machine that produced "
                    "this evidence"
                ),
                why_score_fidelity_cannot_be_established=(
                    "An artifact nobody has verified is an artifact whose "
                    "contribution to a score nobody can reproduce."
                ),
            )
        )
    if not usage.opens_execution:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.RESEARCH_USE_BLOCKED.value,
                affected_component=", ".join(
                    mapping.artifact_id for mapping in usage.blocked
                ),
                evidence=(
                    "third-party-usage-manifest.json: Stage 8E's engine returns "
                    "BLOCKED for these components"
                ),
                why_score_fidelity_cannot_be_established=(
                    "A component this project may not execute cannot contribute "
                    "to a score this project produces."
                ),
            )
        )
    if not compatibility.all_established:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.CHECKPOINT_MODEL_MISMATCH.value,
                affected_component=", ".join(compatibility.unestablished),
                evidence=(
                    "checkpoint-compatibility.json: the binding between these "
                    "checkpoints and their model classes has not been "
                    "established"
                ),
                why_score_fidelity_cannot_be_established=(
                    "Until a checkpoint is shown to fill exactly the parameters "
                    "its model needs, an inference-affecting parameter could be "
                    "silently missing and the network would still run."
                ),
            )
        )
    if graph.unresolved_operations:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.TRANSFORM_ORDER_AMBIGUOUS.value,
                affected_component=", ".join(graph.unresolved_operations),
                evidence=(
                    "transform-graph-resolution.json: these operations carry no "
                    "authority from the paper, the pinned code or a pinned "
                    "inference default"
                ),
                why_score_fidelity_cannot_be_established=(
                    "Every implementation of these operations produces "
                    "different pixels and therefore different descriptors. A "
                    "score computed through one of them would be attributable "
                    "to fpbench's choice rather than to FLARE."
                ),
            )
        )
    if graph.unresolved_parameters:
        blockers.append(
            BlockerDetail(
                blocker_code=(
                    frozen.BlockerCode.SCORE_AFFECTING_PARAMETER_UNRESOLVED.value
                ),
                affected_component=", ".join(graph.unresolved_parameters),
                evidence=(
                    "transform-graph-resolution.json parameter provenance: no "
                    "source establishes a value for these"
                ),
                why_score_fidelity_cannot_be_established=(
                    "A border fill and a resampling kernel are not free "
                    "parameters. Choosing them would put fpbench's judgement "
                    "inside a number published under somebody else's method "
                    "name (docs/adr/0087)."
                ),
            )
        )
    if audit.score_affecting_contradictory:
        blockers.append(
            BlockerDetail(
                blocker_code=frozen.BlockerCode.PAPER_CODE_CONTRADICTION.value,
                affected_component=", ".join(audit.score_affecting_contradictory),
                evidence=(
                    "public-code-route-audit.json: the paper's statement and the "
                    "pinned code give different answers for these operations"
                ),
                why_score_fidelity_cannot_be_established=(
                    "The paper places enhancement between alignment and the "
                    "downsample; the only upstream code that aligns fuses "
                    "alignment and the downsample into one interpolation of the "
                    "unenhanced image, leaving no point of insertion. Following "
                    "either would mean overruling the other."
                ),
            )
        )
    if any(
        row.operation == "four_branch_orchestration" and row.blocks
        for row in route.ROUTE_AUDIT_ROWS
    ):
        blockers.append(
            BlockerDetail(
                blocker_code=(
                    frozen.BlockerCode.FULL_FOUR_BRANCH_ROUTE_UNRESOLVED.value
                ),
                affected_component="four_branch_orchestration",
                evidence=(
                    "public-code-route-audit.json: neither repository contains a "
                    "script that builds four branches; extract_FDD.py takes one "
                    "pose and no enhancement"
                ),
                why_score_fidelity_cannot_be_established=(
                    "The four branches repeat the transform graph, and the "
                    "graph is unresolved. Given a settled graph the "
                    "orchestration is arithmetic; without one there is nothing "
                    "to repeat."
                ),
            )
        )
    if provenance["sd300_training_overlap_found"] is True:  # pragma: no cover
        blockers.append(
            BlockerDetail(
                blocker_code=(
                    frozen.BlockerCode.SD300_TRAINING_OR_TUNING_OVERLAP_FOUND.value
                ),
                affected_component="the released FLARE artifacts",
                evidence="training-provenance.json",
                why_score_fidelity_cannot_be_established=(
                    "An artifact tuned on this project's evaluation cohort "
                    "would produce a number about itself."
                ),
            )
        )

    ordered = tuple(sorted(blockers, key=lambda item: item.blocker_code))
    outcome = (
        frozen.STAGE_9A_BLOCKED_OUTCOME
        if ordered or not model.all_hold or byte_audit.findings
        else frozen.STAGE_9A_READY_OUTCOME
    )
    return QualificationOutcome(
        outcome=outcome,
        blockers=ordered,
        all_identities_established=inventory.all_identities_established,
        all_locally_verified=inventory.all_locally_verified,
        research_use_opens_execution=usage.opens_execution,
        checkpoint_compatibility_established=compatibility.all_established,
        paper_route_resolved=True,
        public_code_route_resolved=audit.resolved,
        transform_graph_resolved=graph.resolved,
        parameter_provenance_complete=not graph.unresolved_parameters,
        route_model_holds=model.all_hold,
        training_overlap_found=bool(provenance["sd300_training_overlap_found"]),
        flare_bytes_in_git=len(byte_audit.findings),
        qualification_fingerprint=stable_hash(
            {
                "schema": "stage_9a_qualification_v1",
                "outcome": outcome,
                "blockers": [
                    {
                        "blocker_code": item.blocker_code,
                        "affected_component": item.affected_component,
                    }
                    for item in ordered
                ],
                "graph_fingerprint": graph.graph_fingerprint,
                "audit_fingerprint": audit.audit_fingerprint,
                "usage_audit_fingerprint": usage.audit_fingerprint,
                "compatibility_fingerprint": compatibility.report_fingerprint,
                "route_model_fingerprint": model.qualification_fingerprint,
            },
            length=64,
        ),
    )


def qualification_report_document(
    outcome: QualificationOutcome,
    *,
    graph: route.TransformGraphResolution,
    audit: route.RouteAuditResult,
    model: RouteModelQualification,
    byte_audit: FlareByteAudit,
) -> Mapping[str, Any]:
    """The published qualification: what was established, and what blocks."""
    return {
        "schema": "stage_9a_qualification_report_v1",
        "algorithm_candidate": frozen.ALGORITHM_CANDIDATE_ID,
        "outcome": outcome.outcome,
        "qualification_fingerprint": outcome.qualification_fingerprint,
        "gates": {
            "all_required_artifacts_identity_established": (
                outcome.all_identities_established
            ),
            "all_required_artifacts_locally_verified": outcome.all_locally_verified,
            "all_required_research_use_decisions_open_execution": (
                outcome.research_use_opens_execution
            ),
            "checkpoint_compatibility_resolved": (
                outcome.checkpoint_compatibility_established
            ),
            "paper_route_resolved": outcome.paper_route_resolved,
            "public_code_route_resolved": outcome.public_code_route_resolved,
            "transform_graph_resolved": outcome.transform_graph_resolved,
            "material_parameter_provenance_complete": (
                outcome.parameter_provenance_complete
            ),
            "route_model_qualification_holds": outcome.route_model_holds,
            "training_overlap_with_sd300_found": outcome.training_overlap_found,
            "flare_bytes_tracked_in_git": outcome.flare_bytes_in_git,
        },
        "blockers": [
            {
                "blocker_code": item.blocker_code,
                "affected_component": item.affected_component,
                "evidence": item.evidence,
                "why_score_fidelity_cannot_be_established": (
                    item.why_score_fidelity_cannot_be_established
                ),
            }
            for item in outcome.blockers
        ],
        "transform_graph": {
            "operation_count": graph.operation_count,
            "score_affecting_count": graph.score_affecting_count,
            "authoritative_count": graph.authoritative_count,
            "unresolved_operations": list(graph.unresolved_operations),
            "unresolved_parameters": list(graph.unresolved_parameters),
            "graph_fingerprint": graph.graph_fingerprint,
        },
        "public_code_route_audit": {
            "row_count": audit.row_count,
            "score_affecting_ambiguous": list(audit.score_affecting_ambiguous),
            "score_affecting_contradictory": list(
                audit.score_affecting_contradictory
            ),
            "glue_required_operations": list(audit.glue_required_operations),
            "audit_fingerprint": audit.audit_fingerprint,
        },
        "route_model_qualification": {
            "case_count": len(model.cases),
            "all_hold": model.all_hold,
            "failing": list(model.failing),
            "qualification_fingerprint": model.qualification_fingerprint,
            "cases": [
                {
                    "case_id": case.case_id,
                    "claim": case.claim,
                    "holds": case.holds,
                    "observed": case.observed,
                }
                for case in model.cases
            ],
        },
        "flare_exact_byte_guard": {
            # The population is deliberately absent. It is a fact about a
            # moment — it grows with every commit, including the commit that
            # publishes this document — so a published count could never be
            # re-derived from a later tree. The conclusion is stable, and the
            # conclusion is the evidence. Stage 8E's repository audit excludes
            # its population from its fingerprint for the same reason.
            "every_tracked_file_was_hashed": (
                byte_audit.hashed_file_count == byte_audit.tracked_file_count
            ),
            "known_digest_count": byte_audit.known_digest_count,
            "finding_count": len(byte_audit.findings),
            "clean": byte_audit.clean,
            "findings": [
                {
                    "path": finding.path,
                    "artifact_id": finding.artifact_id,
                    "component_role": finding.component_role,
                }
                for finding in byte_audit.findings
            ],
            "note": (
                "Runs beside Stage 8E's generic guard rather than inside it. "
                "Stage 8E is closed, so its hard-coded digest registry is not "
                "extended from here (spec sections 3 and 52)."
            ),
        },
        "fdd_checkpoint_load": {
            # Recorded because the previous reading of this repository, against
            # an earlier upstream state, had it the other way round. It is no
            # longer a blocker and it is still a fact worth pinning
            # (spec section 45).
            "present": True,
            "active": True,
            "official": True,
            "locator": (
                f"Yu-Yy/FLARE@{frozen.FLARE_REPOSITORY.commit[:8]}:extract_FDD.py"
                "::extracting"
            ),
            "detail": (
                "FDD is constructed, moved to CUDA, wrapped in DataParallel, and "
                "load_model(desc_model, 'model_weights/desc_model.pth.tar') is "
                "called. The pinned source is the authority; an earlier upstream "
                "state recorded this load as commented out, which is why a "
                "commit is pinned rather than a branch."
            ),
        },
        "deferred_to_stage_9b": {
            "note": (
                "Recorded here and decided there. Stage 9A is about which "
                "operations run; the runtime is about how they run "
                "(spec sections 36 and 37)."
            ),
            "runtime_determinism_observed": {
                "cudnn_benchmark": True,
                "cudnn_deterministic": False,
                "cudnn_enabled": True,
                "locator": (
                    f"Yu-Yy/FLARE@{frozen.FLARE_REPOSITORY.commit[:8]}: "
                    "extract_FDD.py, extract_VotingPose.py and "
                    "extract_RegressionPose.py all set these before running"
                ),
                "changed_by_this_stage": False,
                "detail": (
                    "Non-deterministic cuDNN algorithm selection is upstream's "
                    "own inference setting. Stage 9A documents it and does not "
                    "correct it: CUDA, the torch version, cuDNN, repeatability, "
                    "DataParallel removal and the GPU model are all Stage 9B's."
                ),
            },
            "upstream_declared_dependency_surface": {
                "flare": [
                    "torch >= 1.10",
                    "numpy",
                    "opencv-python",
                    "scipy",
                    "Pillow",
                    "tqdm",
                    "PyYAML",
                    "easydict",
                    "pandas",
                ],
                "flare_enh": [
                    "torch==2.0.0+cu118",
                    "numpy==1.24.4",
                    "einops==0.8.0",
                    "kornia==0.7.3",
                    "scipy==1.10.1",
                    "easydict==1.13",
                    "opencv-python==4.8.0.76",
                ],
                "locators": [
                    f"Yu-Yy/FLARE@{frozen.FLARE_REPOSITORY.commit[:8]}:README.md",
                    (
                        "Yu-Yy/FLARE_ENH@"
                        f"{frozen.FLARE_ENH_REPOSITORY.commit[:8]}:requirements.txt"
                    ),
                ],
                "closure_frozen_by_this_stage": False,
                "detail": (
                    "Declared surfaces, not a resolved closure. The two "
                    "repositories declare different torch requirements and only "
                    "one of them pins versions at all. A wheel-level lock — the "
                    "equivalent of the flx bundle pinned by bytes "
                    "(docs/adr/0072) — is Stage 9B's to build."
                ),
            },
        },
        "what_this_stage_did_not_do": {
            "sd300_image_bytes_read": False,
            "sd300_score_rows_read": False,
            "prior_algorithm_scores_read": False,
            "calibration_performed": False,
            "threshold_produced": False,
            "decision_profile_produced": False,
            "production_adapter_created": False,
            "runtime_qualified": False,
            "benchmark_run_performed": False,
            "third_party_bytes_added_to_git": False,
            "stage8e_evidence_changed": False,
            "upstream_behaviour_modified": False,
        },
    }
