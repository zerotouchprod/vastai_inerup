#!/usr/bin/env python3
"""Gate: every layer inherited from gpu-base must be byte-identical (compressed digest AND diff_id) in both workers.

Usage: gpu_base_gate.py --base base.json --workers workers.json --output gate.md
Inputs are registry_layer_report.py outputs (base has 1 build, workers has 2). Exit 1 if the gate fails.
"""
import argparse, json, sys

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True); ap.add_argument("--workers", required=True); ap.add_argument("--output", required=True)
a = ap.parse_args()
base = json.load(open(a.base))["builds"][0]
w1, w2 = json.load(open(a.workers))["builds"][:2]
bl = base["layers"]; n = len(bl)
rows, ok = [], True
for i, l in enumerate(bl):
    cells = []
    for w in (w1, w2):
        wl = w["layers"][i] if i < len(w["layers"]) else {}
        d, f = wl.get("digest") == l["digest"], wl.get("diff_id") == l["diff_id"]
        ok &= d and f
        cells += ["same" if d else "DIFFERENT", "same" if f else "DIFFERENT"]
    rows.append(f"| {i+1} | {l['size']:,} | `{l['digest'][7:19]}` | " + " | ".join(cells) + " |")
def own(w): return w["layers"][n:]
lines = [f"Gate: {'PASS' if ok else 'FAIL'} — {n} inherited gpu-base layers checked in {w1['ref']} and {w2['ref']}", "",
         f"- gpu-base manifest `{base['manifest_digest']}` (index `{base['index_digest']}`), config `{base.get('config_digest')}`, "
         f"{n} layers, {base['total_compressed_bytes']:,} bytes compressed",
         "", f"| layer | size | base blob | {w1['ref']} blob | {w1['ref']} diff_id | {w2['ref']} blob | {w2['ref']} diff_id |", "|---|---|---|---|---|---|---|"] + rows
lines += ["", "| worker | manifest digest | layers | total compressed | worker-own layers | worker-own bytes |", "|---|---|---|---|---|---|"]
for w in (w1, w2):
    lines.append(f"| {w['ref']} | `{w['manifest_digest']}` | {w['layer_count']} | {w['total_compressed_bytes']:,} | {len(own(w))} | {sum(l['size'] for l in own(w)):,} |")
d1 = {l["digest"] for l in w1["layers"]}
new = [l for l in w2["layers"] if l["digest"] not in d1]
lines += ["", f"New bytes {w2['ref']} vs {w1['ref']}: {sum(l['size'] for l in new):,} in {len(new)} layers "
          f"(identical worker-own layers: {sum(l['digest'] in d1 for l in own(w2))}/{len(own(w2))})"]
open(a.output, "w").write("\n".join(lines) + "\n"); print("\n".join(lines))
sys.exit(0 if ok else 1)
