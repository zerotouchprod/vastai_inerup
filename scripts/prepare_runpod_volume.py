"""
prepare_runpod_volume.py — скачать модели на RunPod Network Volume.

Запускать ОДИН РАЗ с Pod у которого есть интернет (HF_HUB_OFFLINE=0):

    HF_HUB_OFFLINE=0 python3 scripts/prepare_runpod_volume.py

Модели сохраняются в /workspace/models/ и остаются на Network Volume.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
VOLUME_BASE = Path(os.getenv("VOLUME_BASE", "/workspace"))
MODELS_DIR = VOLUME_BASE / "models"

MODELS: list[dict] = [
    {
        "repo_id": "black-forest-labs/FLUX.1-schnell",
        "local_dir": MODELS_DIR / "FLUX.1-schnell",
        "ignore_patterns": ["*.bin", "*.onnx"],
        "description": "FLUX.1-schnell T2I (~24 GB safetensors)",
    },
    {
        "repo_id": "tencent/HunyuanVideo",
        "local_dir": MODELS_DIR / "HunyuanVideo",
        "ignore_patterns": ["*.bin", "*.onnx", "fp32/*"],
        "description": "HunyuanVideo I2V (~30 GB safetensors)",
    },
]

# ── Download ──────────────────────────────────────────────────────────────────

def download_model(repo_id: str, local_dir: Path, ignore_patterns: list[str], description: str) -> None:
    from huggingface_hub import snapshot_download  # noqa: PLC0415

    if local_dir.exists() and any(local_dir.iterdir()):
        print(f"⏭  {description} — already exists at {local_dir}, skipping")
        return

    local_dir.mkdir(parents=True, exist_ok=True)
    print(f"\n⬇  Downloading {description}")
    print(f"   repo  : {repo_id}")
    print(f"   target: {local_dir}")

    snapshot_download(
        repo_id=repo_id,
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
        ignore_patterns=ignore_patterns,
    )
    print(f"✅  {description} downloaded")


def main() -> None:
    if os.getenv("HF_HUB_OFFLINE", "0") == "1":
        print("⚠  HF_HUB_OFFLINE=1 — set it to 0 before running this script")
        sys.exit(1)

    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print("❌  huggingface_hub not installed. Run: pip install huggingface_hub")
        sys.exit(1)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Models directory: {MODELS_DIR}")

    for model in MODELS:
        download_model(**model)

    print("\n✅  All models ready.")
    print(f"   Location: {MODELS_DIR}")
    print("   You can now launch the Serverless endpoint.")


if __name__ == "__main__":
    main()

