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

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.flare_errors import FlareCheckpointError
from fpbench.core.serialization import stable_hash
from fpbench.experiments import stage9a_flare_artifacts as artifacts
from fpbench.experiments import stage9a_flare_identity as frozen

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
