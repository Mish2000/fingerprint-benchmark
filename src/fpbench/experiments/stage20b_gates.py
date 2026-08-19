"""The two gates that stand between Stage 20B and the canonical 6,000.

Section 16 asks for exactly two, and deliberately not for a third:

.. code-block:: text

    Gate A   the production bridge reproduces Stage 20A's official-sample scores
    Gate B   this route's MINDTCT is Algorithm 2's MINDTCT, byte for byte

Stage 20A already did the research. These two check the *plumbing* that was built
on top of it, and nothing else. Neither of them opens an SD300 image for a score,
and neither can change a route: their only outputs are PASS and a stop.

**Gate A is exact.** Not a tolerance of 0.01, not "about right". The production
bridge loads the same assembly, calls the same API and uses the same defaults as
the Stage 20A probe, so there is no biometric reason for the doubles to move —
and if they move anyway, something is wrong that a tolerance would hide.

It also goes through the *production* path rather than a special one: the
official ``SampleMinutiae`` files are, by Appendix A of the SDK manual, exactly
``width / height / resolution / count / x y direction`` — which is precisely what
``CreateMccTemplate(int, int, int, Minutia[])`` takes and precisely what the
bridge payload carries. So Gate A exercises the payload format, the bridge, the
template API and the matcher together, and the only thing it does *not* exercise
is MINDTCT. That is Gate B's job.

**Gate B reads no score at all.** It compares XYT bytes. A parity check that
looked at similarities would be selecting on SD300, and there is nothing to
select: the question is only whether two routes ran the same binary the same way.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from fpbench.adapters.mcc.identity import (
    ALGORITHM_ID,
    BRIDGE_PROTOCOL,
    STAGE_20A_SMOKE_SCORES,
)
from fpbench.adapters.mcc.interop import windows_path
from fpbench.adapters.support.workspace import AdapterJobWorkspace

__all__ = [
    "Stage20BGateError",
    "GATE_A_PASS",
    "GATE_A_FAIL",
    "GATE_B_PASS",
    "GATE_B_FAIL",
    "SampleTemplate",
    "read_official_sample",
    "render_sample_payload",
    "run_gate_a",
    "run_gate_b",
]

GATE_A_PASS = "MCC_PRODUCTION_BRIDGE_REPRODUCTION_PASS"
GATE_A_FAIL = "MCC_PRODUCTION_BRIDGE_REPRODUCTION_FAIL"
GATE_B_PASS = "MINDTCT_ROUTE_PARITY_PASS"
GATE_B_FAIL = "MINDTCT_ROUTE_PARITY_FAIL"

#: The five comparisons Stage 20A's smoke made, and which sample plays which side.
_GATE_A_COMPARISONS: tuple[tuple[str, int, int], ...] = (
    ("self", 0, 0),
    ("related_forward", 0, 1),
    ("related_reverse", 1, 0),
    ("unrelated_forward", 0, 2),
    ("unrelated_reverse", 2, 0),
)


class Stage20BGateError(RuntimeError):
    """A gate could not be run at all — which is not the same as failing it."""


@dataclass(frozen=True, slots=True)
class SampleTemplate:
    """One official minutiae file, in the SDK's own documented text format."""

    width: int
    height: int
    resolution: int
    minutiae: tuple[tuple[int, int, float], ...]


def read_official_sample(path: Path) -> SampleTemplate:
    """Parse one ``SampleMinutiae`` file per Appendix A of the SDK manual.

    These are already MCC-convention minutiae — upper-left origin, radians — so
    nothing is translated here. Gate A is about the bridge, not about MINDTCT.
    """
    fields = Path(path).read_text(encoding="ascii").split()
    if len(fields) < 4:
        raise Stage20BGateError(f"{Path(path).name} is not a minutiae template")
    width, height, resolution, count = (int(fields[index]) for index in range(4))
    rest = fields[4:]
    if len(rest) != count * 3:
        raise Stage20BGateError(f"{Path(path).name} declares {count} minutiae and carries a different number")
    minutiae = tuple(
        (int(rest[3 * index]), int(rest[3 * index + 1]), float(rest[3 * index + 2]))
        for index in range(count)
    )
    return SampleTemplate(
        width=width, height=height, resolution=resolution, minutiae=minutiae
    )


def render_sample_payload(left: SampleTemplate, right: SampleTemplate) -> str:
    """Two official samples as an ordinary bridge payload.

    Written here rather than through the adapter's renderer because the input is
    already in MCC's coordinate system: passing it through
    ``translate_xyt_to_mcc_input`` would apply the origin change a second time
    and Gate A would be testing a route nothing runs.
    """
    lines = [BRIDGE_PROTOCOL]
    for label, side in (("LEFT", left), ("RIGHT", right)):
        lines.append(
            f"{label} {side.width} {side.height} {side.resolution} {len(side.minutiae)}"
        )
        lines.extend(f"{x} {y} {direction!r}" for x, y, direction in side.minutiae)
    return "\n".join(lines) + "\n"


def run_gate_a(
    *, bridge: Path, samples: Path, sample_files: Sequence[str], workspace: Path
) -> dict[str, Any]:
    """Drive the production bridge over Stage 20A's own official samples.

    Returns the gate record. ``outcome`` is :data:`GATE_A_PASS` only when every
    one of the five doubles is *bit-identical* to Stage 20A's and both symmetry
    pairs still agree exactly.
    """
    workspace.mkdir(parents=True, exist_ok=True)
    templates = [read_official_sample(Path(samples) / name) for name in sample_files]

    observed: dict[str, float | None] = {}
    statuses: dict[str, str] = {}
    for label, left_index, right_index in _GATE_A_COMPARISONS:
        payload = workspace / f"gate-a-{label.replace('_', '-')}.txt"
        payload.write_text(
            render_sample_payload(templates[left_index], templates[right_index]),
            encoding="ascii",
        )
        run = subprocess.run(
            [str(bridge), "match", windows_path(payload)],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
        )
        answers = [line for line in run.stdout.splitlines() if line.strip()]
        if run.returncode != 0 or not answers:
            raise Stage20BGateError(
                f"the production bridge did not answer for {label}: {run.stderr.strip()[:200]}"
            )
        # Never stripped: the success line ends in an empty detail field.
        fields = answers[-1].split("\t")
        statuses[label] = fields[0]
        observed[label] = float(fields[1]) if fields[0] == "OK" and fields[1] else None

    comparisons = []
    for label, expected in STAGE_20A_SMOKE_SCORES.items():
        actual = observed.get(label)
        comparisons.append(
            {
                "comparison": label,
                "stage20a_score": expected,
                "production_score": actual,
                "status": statuses.get(label),
                # Bit-identical, via Python's float equality on two IEEE-754
                # doubles. No tolerance is applied anywhere in this comparison.
                "exact": actual is not None and actual == expected,
            }
        )

    symmetry = {
        "related": observed.get("related_forward") == observed.get("related_reverse"),
        "unrelated": observed.get("unrelated_forward") == observed.get("unrelated_reverse"),
    }
    exact_matches = sum(1 for row in comparisons if row["exact"])
    passed = exact_matches == len(comparisons) and all(symmetry.values())

    return {
        "kind": "stage_20b_gate_a_bridge_reproduction",
        "stage": "20B",
        "gate": "A",
        "algorithm_id": ALGORITHM_ID,
        "outcome": GATE_A_PASS if passed else GATE_A_FAIL,
        "authority": "Stage 20A runtime smoke, evidence/stage20a-mcc-sdk-preflight/runtime-smoke.json",
        "sample_authority": "SDK_PROVIDED_SAMPLE_MINUTIAE",
        "sample_files": list(sample_files),
        "template_api_used": "production_CreateMccTemplate_int_int_int_Minutia_array",
        "stage20a_template_api": "CreateMccTemplateFromTextTemplate",
        "why_the_apis_may_be_compared": (
            "Appendix A of the SDK manual defines the sample text format as image width, "
            "height, resolution and one x/y/direction row per minutia — the exact arguments "
            "the production template API takes, so the two routes carry identical input"
        ),
        "tolerance": None,
        "comparisons": comparisons,
        "expected_comparisons": len(comparisons),
        "exact_matches": exact_matches,
        "mismatches": len(comparisons) - exact_matches,
        "symmetry_preserved": symmetry,
        "sd300_images_used": 0,
        "parameter_setters_called": False,
        "what_this_does_not_prove": (
            "nothing about MINDTCT: these minutiae are the vendor's own and never passed "
            "through an extractor here. Gate B is what proves the extractor route"
        ),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _extract_through_route(
    *, adapter, module, image, directory: Path, output_root: str
) -> bytes:
    """One image through one adapter's own extraction path, returning its XYT.

    Deliberately the adapter's ``_stage`` and ``_extract`` rather than a
    subprocess this module builds itself. Running ``mindtct`` twice from here
    would prove only that MINDTCT is deterministic; what Gate B has to answer is
    whether the *two routes* — two stagings, two argv constructions, two run
    wrappers, two XYT readers — produce the same bytes.
    """
    directory.mkdir(parents=True, exist_ok=True)
    workspace = AdapterJobWorkspace(
        working_directory=directory, artifact_directory=directory
    )
    budget = module._Budget(120.0)
    timings: dict[str, float] = {}
    counts: dict[str, str] = {}

    source, raster = adapter._stage(image, workspace, "input.png", "left")
    adapter._extract(
        side="left",
        source=source,
        output_root=output_root,
        raster=raster,
        workspace=workspace,
        budget=budget,
        timings=timings,
        counts=counts,
    )
    return workspace.work_path(f"{output_root}.xyt").read_bytes()


def run_gate_b(
    *,
    algorithm2,
    stage20b,
    images: Sequence[Mapping[str, Any]],
    workspace: Path,
) -> dict[str, Any]:
    """Extract each frozen image through both routes and compare the XYT bytes.

    ``algorithm2`` is the ``nbis_mindtct_bozorth3`` adapter and ``stage20b`` the
    ``nbis_mindtct_mcc_sdk_v2`` one, each driven through its own code. The output
    *file names* differ and are not compared; the XYT content must be identical
    for every image.

    No score is read anywhere. This is a plumbing test, so there is no selection
    on SD300 here and nothing in the record it returns can influence the route.

    Raises:
        Stage20BGateError: the two adapters are not configured against the same
            MINDTCT. A parity result between two different binaries would answer
            a question nobody asked.
    """
    from fpbench.adapters.mcc import adapter as mcc_module
    from fpbench.adapters.nbis import adapter as nbis_module

    left_binary = Path(algorithm2.config.mindtct_executable).resolve()
    right_binary = Path(stage20b.config.mindtct_executable).resolve()
    if left_binary != right_binary:
        raise Stage20BGateError(
            "the two routes are configured against different mindtct executables; "
            "Stage 20B must run Algorithm 2's certified build and no other"
        )

    rows: list[dict[str, Any]] = []
    for index, image in enumerate(images, start=1):
        left_bytes = _extract_through_route(
            adapter=algorithm2,
            module=nbis_module,
            image=image["prepared"],
            directory=workspace / "algorithm2" / f"{index:02d}",
            output_root="left-nbis",
        )
        right_bytes = _extract_through_route(
            adapter=stage20b,
            module=mcc_module,
            image=image["prepared"],
            directory=workspace / "stage20b" / f"{index:02d}",
            output_root="left-nbis",
        )
        rows.append(
            {
                "image_id": image["image_id"],
                "release": image.get("release"),
                "impression_type": image.get("impression_type"),
                "algorithm2_xyt_sha256": hashlib.sha256(left_bytes).hexdigest(),
                "stage20b_xyt_sha256": hashlib.sha256(right_bytes).hexdigest(),
                "identical": left_bytes == right_bytes,
                "minutiae_count": len(
                    [line for line in left_bytes.decode("ascii").splitlines() if line.strip()]
                ),
            }
        )

    identical = sum(1 for row in rows if row["identical"])
    return {
        "kind": "stage_20b_gate_b_mindtct_parity",
        "stage": "20B",
        "gate": "B",
        "algorithm_id": ALGORITHM_ID,
        "outcome": GATE_B_PASS if identical == len(rows) else GATE_B_FAIL,
        "compared": "each adapter's own staging and extraction path, not two runs of one script",
        "algorithm2_adapter_id": algorithm2.descriptor.adapter_id,
        "stage20b_adapter_id": stage20b.descriptor.adapter_id,
        "same_mindtct_executable": True,
        "mindtct_sha256": _sha256(left_binary),
        "flags": [],
        "subset_frozen_before_extraction": True,
        "expected_images": len(rows),
        "identical_xyt": identical,
        "mismatches": len(rows) - identical,
        "filenames_compared": False,
        "scores_read": 0,
        "sd300_used_for_selection": False,
        "images": rows,
    }
