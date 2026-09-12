"""Verify and render local pilot results; never reads the frozen benchmark scores."""

from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path

from common import digest, read_json


def inspect(out):
    plan = read_json(out / "plan.json")
    prepared = read_json(out / "prepared.json")
    if digest(out / "plan.json") != prepared["plan_sha256"]:
        raise ValueError("Plan changed")
    pairs = {p["pair_id"]: p for p in plan["pairs"]}
    routes = {}
    for route in ("P1", "P2", "R"):
        directory = out / route
        if not (directory / "summary.json").exists():
            continue
        summary = read_json(directory / "summary.json")
        identity = read_json(directory / "identity.json")
        if identity["plan_sha256"] != prepared["plan_sha256"]:
            raise ValueError("Route used a different population")
        if digest(directory / "scores.csv") != summary["scores_sha256"]:
            raise ValueError("Scores changed")
        with (directory / "scores.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 250 or [r["pair_id"] for r in rows] != list(pairs):
            raise ValueError("Missing, duplicated, reordered or extra planned pair")
        for row in rows:
            if row["kind"] != pairs[row["pair_id"]]["kind"] or row["route"] != route:
                raise ValueError("Pair truth/route mismatch")
            if row["identity_sha256"] != digest(directory / "identity.json"):
                raise ValueError("Execution identity changed")
            if (row["score"] != "") != (row["status"] == "success"):
                raise ValueError("Failure was converted to a score")
            raw = directory / "pairs" / (row["pair_id"] + ".json")
            if raw.exists():
                result = read_json(raw)
                if (
                    result["status"] != row["status"]
                    or str(
                        result.get("score") if result.get("score") is not None else ""
                    )
                    != row["score"]
                ):
                    raise ValueError("CSV and raw pair result disagree")
            elif row["status"] != "blocked":
                raise ValueError("Executed row has no raw result")
        counts = {
            status: sum(r["status"] == status for r in rows)
            for status in ("success", "failure", "blocked")
        }
        if [summary[k] for k in ("scored", "failures", "blocked")] != [
            counts[k] for k in ("success", "failure", "blocked")
        ]:
            raise ValueError("Summary counts disagree with scores")
        if (
            summary["executed"] != counts["success"] + counts["failure"]
            or sum(counts.values()) != summary["planned"]
        ):
            raise ValueError("Attempt counts disagree")
        routes[route] = (summary, rows)
    return plan, routes


def render(out):
    plan, routes = inspect(out)
    text = [
        "# L3 bridge v1 — development pilot",
        "",
        "Native SD300B delivery, 1000 PPI. Five development subjects, ten fingers each; 100 original gray8 images; 50 genuine and 200 directed cross-subject impostor pairs per route.",
        "",
        "## Population",
        "",
        'Selection: SHA256(UTF8("l3-bridge-v1-dev\\0" + subject_id)), then subject_id. Select 20, execute only the first five. No score or quality selection.',
        "",
        "Selected (in order): " + ", ".join(plan["selected_subjects"]),
        "",
        "Executed subjects: " + ", ".join(plan["active_subjects"]),
        "",
        "832 local eligible candidates; 782 outside the protected 50. Protected overlap: zero, at subject level across all fingers and A/B/C derivatives.",
        "",
        "Known Experiment 001 exposure: "
        + json.dumps(plan["known_exposure"], ensure_ascii=False),
        "",
        "The delivery's local 50-subject CSV was compared with the actual cohort: "
        + json.dumps(plan.get("reference_subject_manifest", {})),
        "",
        "The two separately mentioned pasted Markdown reports, four supplied workbook copies and arithmetic-audit JSON were not attached here or found by their specified names. Their cell/arithmetic claims were not independently re-audited; selection used the actual local cohort and image manifests.",
        "",
        "## Execution",
        "",
        "Executed counts logical pair attempts, including failures inherited from attempted image extraction. Matcher invocations are shown separately. A blocked route contributes no scored biometric rejection.",
        "",
        "| Route | Planned | Executed | Scored | Failures | Blocked | Matcher calls |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for route, (summary, rows) in routes.items():
        text.append(
            "| "
            + " | ".join(
                [route]
                + [
                    str(summary[k])
                    for k in (
                        "planned",
                        "executed",
                        "scored",
                        "failures",
                        "blocked",
                        "matcher_invocations",
                    )
                ]
            )
            + " |"
        )
    text += ["", "## Scores and failures", ""]
    for route, (summary, rows) in routes.items():
        text += [
            f"**{route}** — scored-only raw distributions: `{json.dumps(summary['score_distributions_scored_only'])}`.",
            "",
            f"Pair reasons: `{json.dumps(summary['reasons'])}`. Image extraction reasons: `{json.dumps(summary['extraction_reasons'])}`.",
            "",
        ]
    text += [
        "## Processing and examples",
        "",
        "P1: original pixels /255, Survey f40 valid convolutions, stitched 256-pixel output tiles with 16-pixel input overlap, one global upstream NMS. The upstream output is zero-based row,column +8; convert to x,y without subtracting one. No resize or padding.",
        "",
        "P2: original Experiment 004 seed40401, threshold 0.72, NMS radius 2. Ridge target 34 px and frozen factor band [0.2,1.5]; original estimator and dispersion/tile guards. Percentile 1/99 normalization, CLAHE 2.0/(8,8), /255. Inference tiles 512, overlap 64, cosine ramp 32; reflect padding only at bottom/right when needed, removed after blending. Map normalized points back by (p+0.5)/factor-0.5. Scale failures are retained; the exploratory widened band is not used.",
        "",
        "Both configurations describe points on the same original native image using upstream Dahia median3/CLAHE3/SIFT4 under the same OpenCV 3.4.18 runtime. Pass row,column to its SIFT helper, which internally swaps into OpenCV x,y. Spatial matching uses its original squared-distance ratio 0.7, without registration or pair selection. Zero is upstream's valid result for fewer than two correspondences, including empty descriptors.",
        "",
        "R: the existing SourceAFIS Java 3.18.1 stateless bridge at explicit 1000 PPI. It internally normalizes to 500 PPI and is not a pore route. Its integration mandates two fresh extractions per pair. Pore extraction and SIFT run once per image and are cached locally. Loading, image extraction and comparison timings remain separate; these conditions are not comparable to Stage 21C timings.",
        "",
        "`demo.html` shows the first genuine and first impostor in manifest order for each completed route, plus its first failure if different. Pore marks and descriptor correspondences are model outputs, not anatomical ground truth. No examples were selected for attractive scores.",
        "",
        "## Changes and limits",
        "",
        "Technical adaptations: coordinate basis/order correction; exact receptive-field tiling; isolated existing environments; native-coordinate conversion after P2 scaling; per-image caching; failure-preserving records; tie-atomic scored-only sweeps. Focused numerical checks use synthetic non-square images.",
        "",
        "Research configuration: P2 is a new composition of the frozen detector and P1's descriptor/matcher. P1's corrected coordinate route has its own identity. No scale estimator, detection threshold, matching parameter, fusion, training or operating threshold was tuned. No original experiment 001–004 or Stage 21A–21C artifact was changed.",
        "",
        "This is an operational development pilot. 200 impostors give a 0.5% empirical FAR step, insufficient for a convincing FAR=0.1% claim. Pair dependence and historical exposure remain. No superiority, final FAR attainment, anatomical correctness or held-out benchmark performance is established. P1/P2 are two configurations of a composite chain, not two independently published complete systems.",
        "",
        "Review these results before expanding. The first scaling failures, if present, require a separately declared variant or remediation with technical proof; do not loosen the frozen guard silently. The remaining 15 development subjects, SD300C, fusion, screening and reserved-test evaluation were not run.",
        "",
    ]
    with (out / "report.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(text))
    all_rows = [row for _, rows in routes.values() for row in rows]
    if all_rows:
        with (out / "scores.csv").open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    demo(out, plan, routes)
    print(
        {
            "verified_routes": list(routes),
            "rows": len(all_rows),
            "report": str(out / "report.md"),
        }
    )


def demo(out, plan, routes):
    # SVG is an overlay on byte-identical originals; the page has no external resources.
    import numpy as np

    images = {r["alias"]: r for r in read_json(out / "worker-inputs.json")}
    sections = []
    for route, (summary, rows) in routes.items():
        chosen = list(
            dict.fromkeys(
                plan["examples"]
                + ([summary["first_failure"]] if summary["first_failure"] else [])
            )
        )
        for pair_id in chosen:
            row = next(r for r in rows if r["pair_id"] == pair_id)
            pair = next(p for p in plan["pairs"] if p["pair_id"] == pair_id)
            left, right = (images[pair[s]] for s in ("left", "right"))
            offset = left["width"] + 40
            width, height = (
                offset + right["width"],
                max(left["height"], right["height"]),
            )
            svg = [
                f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
            ]
            points = {}
            for side, item, dx in (("left", left, 0), ("right", right, offset)):
                svg.append(
                    f'<image x="{dx}" width="{item["width"]}" height="{item["height"]}" href="inputs/{item["alias"]}.png"/>'
                )
                cache = out / route / "detections" / (item["alias"] + ".npz")
                if cache.exists():
                    with np.load(cache, allow_pickle=False) as data:
                        points[side] = data["points_xy"]
                    svg += [
                        f'<circle class="pore" cx="{float(x) + dx:.3f}" cy="{float(y):.3f}" r="3"/>'
                        for x, y in points[side]
                    ]
            correspondence_path = (
                out / route / "pairs" / (pair_id + "-correspondences.json")
            )
            if correspondence_path.exists() and len(points) == 2:
                matches = read_json(correspondence_path)
                for a, b, distance in matches:
                    x1, y1 = points["left"][int(a)]
                    x2, y2 = points["right"][int(b)]
                    svg.append(
                        f'<line class="match" x1="{x1}" y1="{y1}" x2="{x2 + offset}" y2="{y2}"/>'
                    )
            svg.append("</svg>")
            reason = row["reason"]
            details = json.loads(row["details_json"])
            if details.get("extraction_failures"):
                reason += ": " + json.dumps(details["extraction_failures"])
            sections.append(
                f"<section><h2>{route} · {row['kind']} · {pair_id}</h2><p>Status: {row['status']}; raw score: {row['score'] or 'unavailable'}; {html.escape(reason)}</p><p>PLAIN left → ROLL right. Native pixels; browser fits the view.</p>{''.join(svg)}</section>"
            )
    page = (
        "<!doctype html><meta charset=\"utf-8\"><title>L3 bridge — development examples</title><style>body{font:16px system-ui;margin:2rem;background:#f3f4f6;color:#172336}section{background:white;padding:1rem;margin:1rem 0}svg{width:100%;max-height:900px}.pore{fill:none;stroke:#e5336a;stroke-width:1.5}.match{stroke:#00aa8c;stroke-width:1.2;opacity:.6}h1{font-size:1.6rem}</style><h1>Development examples — L3 bridge v1</h1><p>Deterministic first genuine, first impostor, and first failure per route. Model outputs are not anatomical ground truth or proof of superiority.</p><label><input type=\"checkbox\" checked onchange=\"document.querySelectorAll('.pore').forEach(x=>x.style.display=this.checked?'':'none')\">Pore marks</label> <label><input type=\"checkbox\" checked onchange=\"document.querySelectorAll('.match').forEach(x=>x.style.display=this.checked?'':'none')\">Descriptor correspondences</label>"
        + "".join(sections)
    )
    with (out / "demo.html").open("x", encoding="utf-8") as stream:
        stream.write(page)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        _, result = inspect(args.out)
        print({"verified_routes": list(result)})
    else:
        render(args.out)
