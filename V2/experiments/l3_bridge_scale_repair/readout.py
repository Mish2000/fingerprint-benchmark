"""Private comparison tables, deterministic examples and a Hebrew repair report."""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
from collections import Counter
from pathlib import Path

from analysis import descriptive_points, scale_policy, validate_pairs
from support import copy_new, digest, inspect_v1, read_json, write_csv, write_json


def verify_results(out):
    complete = read_json(out / "execution_complete.json")
    if digest(out / "prepared.json") != complete["prepared_sha256"]:
        raise ValueError("Execution/preparation binding changed")
    for name, sha in complete["files"].items():
        if digest(out / name) != sha:
            raise ValueError(f"Execution output changed: {name}")
    plan = read_json(out / "plan.json")
    validate_pairs(plan["pairs"])
    manifest = read_json(out / "preprocessing_manifest.json")
    prior = Path(read_json(out / "prepared.json")["prior_directory"])
    old_plan, old_routes = inspect_v1(prior)
    if old_plan != plan:
        raise ValueError("Comparison population differs from v1")
    comparison = []
    for route in ("P1", "P2", "R", "P2R", "P2R-wide"):
        directory = prior / route if route in old_routes else out / route
        identity_path = directory / "identity.json"
        identity_copy = out / "identities" / f"{route}.json"
        if (out / "scores_comparison.csv").exists() and (
            not identity_copy.exists() or digest(identity_copy) != digest(identity_path)
        ):
            raise ValueError("Portable run identity copy differs from its source")
        pair_files = {
            p.stem
            for p in (directory / "pairs").glob("*.json")
            if not p.stem.endswith("-correspondences")
        }
        if pair_files != {p["pair_id"] for p in plan["pairs"]}:
            raise ValueError("Unexpected or missing raw pair records")
        if route not in old_routes:
            identity = read_json(identity_path)
            if (
                identity["prepared_sha256"] != digest(out / "prepared.json")
                or identity["preprocessing_manifest_sha256"]
                != digest(out / "preprocessing_manifest.json")
                or identity["policy"] != manifest["policies"][route]
            ):
                raise ValueError("Repaired route identity mismatch")
            for item in plan["images"]:
                alias = item["alias"]
                audit = read_json(out / "scale-estimates" / f"{alias}.json")
                declared = manifest["policies"][route]
                policy = scale_policy(
                    audit["corrected"], declared["target"], declared["band"]
                )
                if policy != audit["policies"][route]:
                    raise ValueError(
                        "Saved scale eligibility disagrees with declared policy"
                    )
                detection = read_json(directory / "detections" / f"{alias}.json")
                if detection["ridge_scale"] != policy or (
                    policy["status"] != "OK"
                    and (
                        detection["status"] != "failure"
                        or detection["reason"] != policy["reason"]
                    )
                ):
                    raise ValueError("A wide success filled a main-policy failure")
        old_rows = (
            {r["pair_id"]: r for r in old_routes[route][1]}
            if route in old_routes
            else {}
        )
        for pair in plan["pairs"]:
            path = directory / "pairs" / f"{pair['pair_id']}.json"
            result = read_json(path)
            if any(result[k] != pair[k] for k in ("pair_id", "left", "right")):
                raise ValueError("Raw result is attached to a different pair")
            if result["status"] == "success":
                if not isinstance(result["score"], (int, float)) or not math.isfinite(
                    result["score"]
                ):
                    raise ValueError("A successful result has no finite score")
            elif result.get("score") is not None:
                raise ValueError("Failure was replaced by a score")
            if old_rows:
                old = old_rows[pair["pair_id"]]
                if (
                    result["status"] != old["status"]
                    or str(result["score"] if result["score"] is not None else "")
                    != old["score"]
                ):
                    raise ValueError("Original score CSV/raw binding mismatch")
            if route == "P2R":
                failures = {
                    s: read_json(directory / "templates" / f"{pair[s]}.json")
                    for s in ("left", "right")
                }
                failed = {
                    s: m["reason"]
                    for s, m in failures.items()
                    if m["status"] != "success"
                }
                if failed:
                    if (
                        result["status"] != "failure"
                        or result.get("extraction_failures") != failed
                        or result.get("shared_result")
                    ):
                        raise ValueError("Primary pair failure was not preserved")
                else:
                    shared = result["shared_result"]
                    shared_path = out / shared["path"]
                    if digest(shared_path) != shared["sha256"]:
                        raise ValueError("Shared pair receipt changed")
                    wide = read_json(shared_path)
                    if any(result[k] != wide[k] for k in ("status", "score", "reason")):
                        raise ValueError("Shared score is not identical")
                    for side in ("left", "right"):
                        name = f"templates/{pair[side]}.npz"
                        if digest(directory / name) != digest(out / "P2R-wide" / name):
                            raise ValueError("Shared pair has different descriptors")
            comparison.append(
                {
                    "pair_id": pair["pair_id"],
                    "left_image_alias": pair["left"],
                    "right_image_alias": pair["right"],
                    "kind": pair["kind"],
                    "route": route,
                    "score": result["score"],
                    "status": result["status"],
                    "reason": result["reason"],
                    "run_identity_sha256": digest(identity_path),
                    "run_identity_path": f"identities/{route}.json",
                    "raw_pair_sha256": digest(path),
                    "shared_result": json.dumps(
                        result.get("shared_result"), sort_keys=True
                    )
                    if result.get("shared_result")
                    else "",
                }
            )
    if len(comparison) != 1250:
        raise ValueError("Each of five routes must retain all 250 pairs")
    exported = out / "scores_comparison.csv"
    if exported.exists():
        with exported.open(encoding="utf-8", newline="") as stream:
            stored = list(csv.DictReader(stream))
        expected = [
            {k: "" if v is None else str(v) for k, v in row.items()}
            for row in comparison
        ]
        if stored != expected:
            raise ValueError("Comparison CSV differs from raw source rows")
    return comparison


def summarize(out, rows):
    audits = [read_json(p) for p in sorted((out / "scale-estimates").glob("*.json"))]
    coverage = {}
    for route in ("P1", "P2", "R", "P2R", "P2R-wide"):
        selected = [r for r in rows if r["route"] == route]
        coverage[route] = {
            "planned": 250,
            "counts": dict(Counter(r["status"] for r in selected)),
            "genuine": dict(
                Counter(r["status"] for r in selected if r["kind"] == "genuine")
            ),
            "impostor": dict(
                Counter(r["status"] for r in selected if r["kind"] == "impostor")
            ),
            "zero_scores": sum(
                r["status"] == "success" and r["score"] == 0 for r in selected
            ),
            "reasons": dict(Counter(r["reason"] for r in selected if r["reason"])),
        }
    policies = {
        "original-P2": dict(Counter(a["original_reason"] or "OK" for a in audits)),
        "corrected-estimator": dict(Counter(a["corrected"]["status"] for a in audits)),
    }
    for name in ("rotation-only", "P2R", "P2R-wide"):
        policies[name] = dict(
            Counter(a["policies"][name]["reason"] or "OK" for a in audits)
        )
    return {
        "schema": "l3_scale_repair_private_readout_v1",
        "image_scale_counts": policies,
        "pair_coverage": coverage,
        "descriptive_points": {
            r: descriptive_points([p for p in rows if p["route"] == r])
            for r in ("P1", "R", "P2R", "P2R-wide")
        },
        "original_P2": "Reported by coverage and failures; four scores are not a useful stand-alone accuracy comparison",
    }


def hebrew(out, summary):
    train = read_json(out / "preprocessing_manifest.json")
    source = read_json(out / "source_snapshot.json")
    comparison = read_json(out / "rotation_probe_source_comparison.json")
    lines = [
        "# תיקון קנה המידה של P2 — פיתוח מקומי",
        "",
        "ההרצה משתמשת באותם חמישה נבדקי פיתוח, 100 תמונות מקור ו־250 זוגות. ההרצה הראשונה נשמרה ללא שינוי.",
        "",
        "## אימות התיקון ויעד TRAIN",
        "",
        "בקוד המקומי המקורי: 10/60 אומדני פסים בתוך טולרנס של פיקסל אחד; לאחר תיקון סימן הסיבוב: 60/60. כל 66 בדיקות הנסיגה המספריות עברו, כולל רקע אחיד וניגודיות חלשה.",
        "הבדיקה המבנית מאשרת שהשינוי בפונקציית אומדן האריח הוא בדיוק `math.degrees(orientation) - 90.0`.",
        "",
        f"גיבוב AST מקומי: `{comparison['actual_ast_sha256']}`. בדוח שסופק: `{comparison['supplied_ast_sha256']}`. הגיבובים אינם זהים; שתי הפונקציות במקור המקומי ובטקסט הסקריפט שסופק זהות ברמת AST באותה סביבת Python. לא הונחה סיבת פער הגיבובים. גיבוב הקובץ המקומי תואם למקור המקובע.",
        "",
        f"נבדקו בדיוק {train['image_count']} תמונות TRAIN מקוריות ב־{train['group_count']} קבוצות. הזהויות, גיבובי התמונות, החלוקה וקישור המניפסט למודל אומתו. לא נקראו פיקסלים של validation/test ולא הוסק קשר ל־final_320.",
        f"תקינות/כשלים: `{json.dumps(train['counts'], sort_keys=True)}`. היעד החדש **T_train_fixed={train['target_period_px']} פיקסלים**, לעומת 34.0 במקור; זהו חציון האומדנים התקינים, ללא שימוש בציוני SD300 לבחירתו.",
        f"התפלגות האומדנים התקינים: `{json.dumps({k: v for k, v in train['accepted_distribution'].items() if k != 'histogram'})}`. היסטוגרמה מלאה ורשומות TRAIN במניפסט ובקובצי האבחון.",
        "",
        "## סיבות כשל בתמונות",
        "",
        "| תצורה | תקינות | פיזור | פחות מ־5 אריחים | מחוץ לטווח |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, counts in summary["image_scale_counts"].items():
        lines.append(
            f"| {name} | {counts.get('OK', 0)} | {counts.get('UNRELIABLE_DISPERSION', 0)} | {counts.get('UNRELIABLE_TOO_FEW_TILES', 0)} | {counts.get('SCALE_OUTSIDE_FROZEN_BAND', 0)} |"
        )
    lines += [
        "",
        "תיקון סיבוב בלבד שומר יעד 34 וטווח [0.2,1.5] ומופיע באבחון preprocessing בלבד. P2R משתמש ביעד TRAIN החדש ובאותו טווח; P2R-wide משתמש באותו יעד ובטווח [0.2,3.0] כבדיקת רגישות שהוגדרה מראש. למשל, יעד 34 ומרווח 20 דורשים גורם 1.7 ולכן נדחים בטווח הראשי. סף MAD/median=0.25, מינימום 5 אריחים וחלון lags 5–64 נשמרו.",
        "",
        "## כיסוי זוגות",
        "",
        "| מסלול | הצלחות / 250 | כשלים | חסימות | genuine עם ציון / 50 | impostor עם ציון / 200 | אפסים אמיתיים |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for route, c in summary["pair_coverage"].items():
        lines.append(
            f"| {route} | {c['counts'].get('success', 0)} | {c['counts'].get('failure', 0)} | {c['counts'].get('blocked', 0)} | {c['genuine'].get('success', 0)} | {c['impostor'].get('success', 0)} | {c['zero_scores']} |"
        )
    lines += [
        "",
        "P1 ו־R נצרכו מהרשומות המקוריות לאחר אימות. P2 המקורי מוצג דרך כיסוי וכשלים. כל כשל נשמר בנפרד; הוא אינו ציון אפס או דחייה שהמתאם ביצע.",
        "",
        "## נקודות דיווח תיאוריות",
        "",
        "| מסלול | יעד FAR | TA / 50 | FA / 200 | cut | TAR | FAR | FRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for route, result in summary["descriptive_points"].items():
        if not result["points"]:
            lines.append(
                f"| {route} | לא נתמך: אין ציון genuine או impostor | — | — | — | — | — | — |"
            )
        for point in result["points"]:
            cut = "מעל כל הציונים" if point["accept_none"] else str(point["cut"])
            lines.append(
                f"| {route} | {float(point['target_far']):.0%} | {point['TA']} / 50 | {point['FA']} / 200 | {cut} | {point['TAR']:.1%} | {point['FAR']:.1%} | {point['FRR']:.1%} |"
            )
    lines += [
        "",
        "כלל הקבלה הוא score >= cut וקבוצות שוויון אינן מפוצלות. לכל יעד נבחר TAR מרבי, בשוויון FAR קטן יותר ואז cut גבוה יותר. המכנים נשארים 50/200 גם בכשל: FRR=(50-TA)/50 במדיניות דחייה בכשל. פירוט הכשלים והדחיות שבוצעו על ציונים מופיע ב־summary.json.",
        "ה־cuts הם תיאור של קבוצת הפיתוח בלבד. אין כאן סף תפעולי, בדיקה חיצונית, מובהקות או טענת עליונות. ב־200 impostor כל FA נוסף הוא 0.5%; היעדים מאפשרים לכל היותר 2 או 10 FA. אין טענת FAR=0.1% ואין רווחי סמך בינומיים עצמאיים לזוגות שחולקים תמונות ונבדקים.",
        "",
        "## זהות ושינויים",
        "",
        "השינויים האלגוריתמיים היחידים: סימן הסיבוב; יעד מרווח מחודש מ־TRAIN; ובזרוע wide בלבד גבול עליון 3.0. נשמרו seed40401 והמשקולות, סף גילוי 0.72, NMS=2, הכנת הקלט אחרי התאמת קנה המידה, tiling, SIFT על התמונה המקורית והמתאם המרחבי. תוצאות זהות ששותפו מקושרות במפורש, וזכאות כל זרוע נבדקת בנפרד.",
        f"SHA-256 משקולות: `{train['weight']['sha256']}`.",
        f"בסיס Git: `{source['base_revision']}`. ההרצה משתמשת בתמונת מצב מקומית לא מקומטת, עם קוד בר־שחזור ב־source_snapshot.zip וגיבוב `{source['source_fingerprint']}`. הבדלים ב־implementation.patch. לא בוצעו קומיטים או דחיפה.",
        "הרצת v1, קוד וארטיפקטי experiment001–004, נתוני המקור ו־Stage 21A–21C נשמרו. ארבעת קובצי האקסל לא נפתחו ולא נערכו במסגרת המשימה. כל התוצרים פרטיים ב־workspace. אין אימון, חיפוש פרמטרים, הרחבת נבדקים, SD300C או fusion.",
        "",
        "הדגמה: demo.html משתמש באותם מזהי דוגמאות שנקבעו בהרצה הראשונה; אין בחירה מחדש לפי הצלחה. הסימונים הם פלטי מודל ואינם אמת אנטומית. הניסוי נעצר כאן לצורך הסקירה הבאה.",
        "",
    ]
    with (out / "readout_he.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))


def demo(out, rows):
    import numpy as np

    prior = Path(read_json(out / "prepared.json")["prior_directory"])
    examples = read_json(out / "examples.json")
    inputs = {i["alias"]: i for i in read_json(out / "worker-inputs.json")}
    sections = []
    for route, pair_ids in examples.items():
        directory = out / route if route in ("P2R", "P2R-wide") else prior / route
        for pair_id in pair_ids:
            row = next(
                r for r in rows if r["route"] == route and r["pair_id"] == pair_id
            )
            a, b = inputs[row["left_image_alias"]], inputs[row["right_image_alias"]]
            offset = a["width"] + 40
            svg = [
                f'<svg viewBox="0 0 {offset + b["width"]} {max(a["height"], b["height"])}" xmlns="http://www.w3.org/2000/svg">'
            ]
            points = {}
            for side, item, dx in (("left", a, 0), ("right", b, offset)):
                path = Path(item["path"]).resolve()
                href = html.escape(
                    os.path.relpath(path, out).replace("\\", "/"), quote=True
                )
                svg.append(
                    f'<image x="{dx}" width="{item["width"]}" height="{item["height"]}" href="{href}"/>'
                )
                cache = directory / "detections" / f"{item['alias']}.npz"
                if cache.exists():
                    with np.load(cache, allow_pickle=False) as data:
                        points[side] = data["points_xy"]
                    svg += [
                        f'<circle class="pore" cx="{float(x) + dx:.3f}" cy="{float(y):.3f}" r="3"/>'
                        for x, y in points[side]
                    ]
            match_dir = (
                out / "P2R-wide/pairs" if route == "P2R" else directory / "pairs"
            )
            matches = match_dir / f"{pair_id}-correspondences.json"
            if row["status"] == "success" and matches.exists() and len(points) == 2:
                for first, second, _ in read_json(matches):
                    x1, y1 = points["left"][int(first)]
                    x2, y2 = points["right"][int(second)]
                    svg.append(
                        f'<line class="match" x1="{x1}" y1="{y1}" x2="{x2 + offset}" y2="{y2}"/>'
                    )
            svg.append("</svg>")
            text = f"{row['status']}; score={row['score']}; reason={row['reason']}"
            sections.append(
                f'<section data-route="{route}" data-pair="{pair_id}"><h2>{route} · {row["kind"]} · {pair_id}</h2><p>{html.escape(text)}</p>{"".join(svg)}</section>'
            )
    page = (
        '<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>תיקון קנה המידה — דוגמאות פיתוח</title><style>body{font:16px system-ui;margin:2rem;background:#f3f4f6;color:#172336}section{background:white;padding:1rem;margin:1rem 0}svg{width:100%;max-height:900px;direction:ltr}.pore{fill:none;stroke:#e5336a;stroke-width:1.5}.match{stroke:#00aa8c;stroke-width:1.2;opacity:.6}h2{direction:ltr}</style><h1>תיקון P2 — אותן דוגמאות פיתוח</h1><p>PLAIN משמאל, ROLL מימין. הדוגמאות הועתקו מבחירת v1 לפני ההרצה החדשה. סימוני נקבוביות והתאמות הם פלט מודל ולא אמת אנטומית.</p><label><input type="checkbox" checked onchange="document.querySelectorAll(\'.pore\').forEach(x=>x.style.display=this.checked?\'\':\'none\')">סימוני נקבוביות</label> <label><input type="checkbox" checked onchange="document.querySelectorAll(\'.match\').forEach(x=>x.style.display=this.checked?\'\':\'none\')">התאמות descriptors</label>'
        + "".join(sections)
        + "</html>"
    )
    with (out / "demo.html").open("x", encoding="utf-8") as stream:
        stream.write(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    rows = verify_results(args.out)
    summary = summarize(args.out, rows)
    if args.verify:
        if read_json(args.out / "summary.json") != summary:
            raise ValueError("Summary differs from verified raw results")
        print("Verified 1250 comparison rows and descriptive attempt denominators")
        return
    identities = args.out / "identities"
    identities.mkdir()
    prior = Path(read_json(args.out / "prepared.json")["prior_directory"])
    for route in ("P1", "P2", "R", "P2R", "P2R-wide"):
        directory = args.out / route if route in ("P2R", "P2R-wide") else prior / route
        copy_new(directory / "identity.json", identities / f"{route}.json")
    write_csv(args.out / "scores_comparison.csv", rows)
    write_json(args.out / "summary.json", summary)
    hebrew(args.out, summary)
    demo(args.out, rows)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
