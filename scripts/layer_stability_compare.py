#!/usr/bin/env python3
"""Compare layer digests across builds from several registry_layer_report.py JSON files.

Usage: layer_stability_compare.py --reference a1 --output out.md file1.json [file2.json ...]
Each build is keyed by its ref (tag). Heavy = layer >= 10 MB in the reference build.
"""
import argparse, json

ap = argparse.ArgumentParser()
ap.add_argument("--reference", required=True)
ap.add_argument("--pair", action="append", default=[], help="extra comparison A:B (e.g. r1:r2)")
ap.add_argument("--output", required=True)
ap.add_argument("files", nargs="+")
a = ap.parse_args()
builds = {}
for f in a.files:
    for b in json.load(open(f))["builds"]:
        builds[b["ref"]] = b

def compare(ref, other):
    rl, ol = builds[ref]["layers"], builds[other]["layers"]
    od = {l["digest"] for l in ol}
    heavy = [l for l in rl if l["size"] >= 10_000_000]
    torch = max(rl, key=lambda l: l["size"])
    same_all = [l for l in rl if l["digest"] in od]
    new_bytes = sum(l["size"] for l in ol if l["digest"] not in {x["digest"] for x in rl})
    ot = ol[torch["index"] - 1] if torch["index"] <= len(ol) else {}
    did = "n/a" if not torch.get("diff_id") or not ot.get("diff_id") else ("SAME" if torch["diff_id"] == ot["diff_id"] else "DIFFERENT")
    return (f"| {ref} vs {other} | {len(same_all)}/{len(rl)} | {sum(l['digest'] in od for l in heavy)}/{len(heavy)} | "
            f"{'SAME' if torch['digest'] == ot.get('digest') else 'DIFFERENT'} ({torch['size']:,} B) | {did} | {new_bytes:,} |")

lines = ["| comparison | identical layers | identical heavy (>=10MB) layers | torch layer compressed digest | torch layer diff_id | new bytes in 2nd |", "|---|---|---|---|---|---|"]
pairs = [(a.reference, k) for k in builds if k != a.reference and not k.startswith(("r", "rc"))] + [tuple(p.split(":")) for p in a.pair]
for x, y in pairs:
    if x in builds and y in builds:
        lines.append(compare(x, y))
lines += ["", "| build | manifest digest | layers | total compressed | largest layer digest |", "|---|---|---|---|---|"]
for k, b in builds.items():
    t = max(b["layers"], key=lambda l: l["size"])
    lines.append(f"| {k} | `{b['manifest_digest']}` | {b['layer_count']} | {b['total_compressed_bytes']:,} | `{t['digest']}` |")
lines += ["", "Heavy layer digests per build:", "", "| idx | size(ref) | " + " | ".join(builds) + " |", "|---|---|" + "---|" * len(builds)]
for l in builds[a.reference]["layers"]:
    if l["size"] >= 10_000_000:
        i = l["index"] - 1
        cells = [b["layers"][i]["digest"][7:19] if i < len(b["layers"]) else "-" for b in builds.values()]
        lines.append(f"| {l['index']} | {l['size']:,} | " + " | ".join(cells) + " |")
lines += ["", "Torch layer blob digest / diff_id per build:", ""]
ti = max(builds[a.reference]["layers"], key=lambda l: l["size"])["index"] - 1
for k, b in builds.items():
    lines.append(f"- {k}: blob `{b['layers'][ti]['digest']}` diff_id `{b['layers'][ti].get('diff_id')}`")
open(a.output, "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
