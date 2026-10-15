#!/usr/bin/env python3
"""Read an image manifest from a local registry:2 and report per-layer compressed sizes.

Usage: registry_layer_report.py --registry localhost:5000 --repo slim --tag build1 [--tag build2] --output out.json
Sizes are the compressed blob sizes from the (OCI/Docker v2) manifest, i.e. exactly what a host pulls.
"""
import argparse, json, urllib.request

ACCEPT = ",".join([
    "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v2+json"])

def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": ACCEPT}))
    return r.headers.get("Docker-Content-Digest"), json.load(r)

def manifest(reg, repo, ref):
    digest, m = get(f"http://{reg}/v2/{repo}/manifests/{ref}")
    index_digest = None
    if "manifests" in m:
        index_digest = digest
        amd = [x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64"][0]
        digest, m = get(f"http://{reg}/v2/{repo}/manifests/{amd['digest']}")
    cfg = json.load(urllib.request.urlopen(f"http://{reg}/v2/{repo}/blobs/{m['config']['digest']}"))
    diff_ids = cfg.get("rootfs", {}).get("diff_ids", [])
    layers = [{"index": i + 1, "digest": l["digest"], "diff_id": diff_ids[i] if i < len(diff_ids) else None,
               "size": l["size"], "mediaType": l["mediaType"]} for i, l in enumerate(m["layers"])]
    return {"ref": ref, "index_digest": index_digest, "manifest_digest": digest, "config_digest": m["config"]["digest"], "layer_count": len(layers),
            "total_compressed_bytes": sum(l["size"] for l in layers), "layers": layers}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default="localhost:5000"); ap.add_argument("--repo", required=True)
    ap.add_argument("--tag", action="append", required=True); ap.add_argument("--output", required=True)
    a = ap.parse_args()
    builds = [manifest(a.registry, a.repo, t) for t in a.tag]
    report = {"method": "registry:2 manifest blob sizes (compressed, as pulled)", "builds": builds}
    if len(builds) == 2:
        d2 = {l["digest"] for l in builds[1]["layers"]}
        shared = [l for l in builds[0]["layers"] if l["digest"] in d2]
        report["reuse"] = {"identical_layers": len(shared), "identical_bytes": sum(l["size"] for l in shared),
                           "changed_bytes_build2": sum(l["size"] for l in builds[1]["layers"] if l["digest"] not in {x["digest"] for x in shared}),
                           "identical_layers_ge_10MB": [l for l in shared if l["size"] >= 10_000_000]}
    json.dump(report, open(a.output, "w"), indent=2)
    for b in builds:
        print(f"{b['ref']}: {b['manifest_digest']} layers={b['layer_count']} total={b['total_compressed_bytes']:,}")
        for l in b["layers"]:
            print(f"  {l['index']:>2} {l['size']:>14,} {l['digest']}")
    if "reuse" in report:
        r = report["reuse"]
        print(f"reuse: {r['identical_layers']} identical layers, {r['identical_bytes']:,} bytes; build2 new bytes {r['changed_bytes_build2']:,}")

if __name__ == "__main__":
    main()
