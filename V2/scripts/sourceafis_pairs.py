"""Score an existing pair list with the fpbench SourceAFIS bridge (1 JVM/pair).

Reads the pair list from a pore-run scores.csv (columns kind,left,right,...),
invokes the already-built bridge for each pair at the declared dpi, and writes
safis_scores.csv with the same key columns plus the SourceAFIS score.

Usage:
  python sourceafis_pairs.py --pairs <scores.csv> --images-dir <R1 dir>
      --jar <bridge jar> --dpi 1200 --out <safis_scores.csv>
"""
import argparse
import csv
import json
import os
import subprocess
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--images-dir", required=True)
    ap.add_argument("--jar", required=True)
    ap.add_argument("--dpi", type=int, default=1200)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    images_dir = os.path.abspath(args.images_dir).replace("\\", "/")
    jar = os.path.abspath(args.jar)

    with open(args.pairs) as f:
        pairs = list(csv.DictReader(f))

    rows, failures = [], 0
    t0 = time.time()
    for i, p in enumerate(pairs):
        req = {
            "schema_version": "1",
            "request_id": f"v2_safis_{i}",
            "left": {"path": f"{images_dir}/{p['left']}.png", "dpi": args.dpi},
            "right": {"path": f"{images_dir}/{p['right']}.png", "dpi": args.dpi},
        }
        r = subprocess.run(
            ["java", "-jar", jar, "compare"],
            input=json.dumps(req).encode(),
            capture_output=True, timeout=120)
        try:
            resp = json.loads(r.stdout.decode())
            assert resp["status"] == "success"
            score = resp["score"]
        except Exception:
            failures += 1
            score = ""
        rows.append(dict(kind=p["kind"], left=p["left"], right=p["right"],
                         safis=score))
        if (i + 1) % 50 == 0:
            el = time.time() - t0
            print(f"{i+1}/{len(pairs)} pairs, {el:.0f}s "
                  f"({el/(i+1):.2f}s/pair), failures={failures}", flush=True)

    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "left", "right", "safis"])
        w.writeheader()
        w.writerows(rows)
    print(f"done: {len(rows)} pairs, {failures} failures -> {args.out}")


if __name__ == "__main__":
    main()
