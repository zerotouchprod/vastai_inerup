#!/usr/bin/env python3
"""Compare a pulled baseline image with a locally built experimental image."""
from __future__ import annotations

import argparse
import json
import subprocess
import zlib
from pathlib import Path
from typing import Any


def inspect(image: str) -> dict[str, Any]:
    raw = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{json .}}"],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(raw.stdout)


def saved_gzip_bytes(image: str) -> int:
    proc = subprocess.Popen(["docker", "save", image], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    total = 0
    compressor = zlib.compressobj(level=1, wbits=31)
    while chunk := proc.stdout.read(1024 * 1024):
        total += len(compressor.compress(chunk))
    total += len(compressor.flush())
    if proc.wait() != 0:
        raise RuntimeError(f"docker save failed for {image}")
    return total


def oci_layer_report(image: str) -> dict[str, Any]:
    """Read compressed OCI layer sizes from the registry manifest."""
    raw = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", image, "--raw"],
        check=True,
        text=True,
        capture_output=True,
    )
    document = json.loads(raw.stdout)
    selected = document
    manifest_digest = image.split("@", 1)[1] if "@" in image else None
    if "manifests" in document:
        candidates = [
            item for item in document["manifests"]
            if item.get("platform", {}).get("os") == "linux"
            and item.get("platform", {}).get("architecture") == "amd64"
        ]
        if len(candidates) != 1:
            raise RuntimeError(f"expected one linux/amd64 manifest for {image}, got {len(candidates)}")
        manifest_digest = candidates[0]["digest"]
        platform_ref = f"{image.split('@', 1)[0]}@{manifest_digest}"
        platform_raw = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", platform_ref, "--raw"],
            check=True,
            text=True,
            capture_output=True,
        )
        selected = json.loads(platform_raw.stdout)
    layers = selected.get("layers", [])
    sizes = [int(layer["size"]) for layer in layers]
    return {
        "platform": "linux/amd64",
        "manifest_digest": manifest_digest,
        "layer_count": len(sizes),
        "layer_sizes_bytes": sizes,
        "compressed_oci_layer_bytes": sum(sizes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", default="evidence/worker-image-variant-comparison.json")
    args = parser.parse_args()

    rows = []
    for name, image in (("current-published", args.baseline), ("python-base-experiment", args.candidate)):
        data = inspect(image)
        rows.append(
            {
                "name": name,
                "image": image,
                "uncompressed_bytes": data.get("Size"),
                "compressed_docker_save_gzip_bytes": saved_gzip_bytes(image),
                "oci": oci_layer_report(image),
                "entrypoint": data.get("Config", {}).get("Entrypoint"),
                "cmd": data.get("Config", {}).get("Cmd"),
                "rootfs_layers": len(data.get("RootFS", {}).get("Layers", [])),
                "revision": data.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision"),
            }
        )

    report = {"baseline": args.baseline, "candidate": args.candidate, "images": rows}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
