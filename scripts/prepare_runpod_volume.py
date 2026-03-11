#!/usr/bin/env python3
"""
Prepare RunPod Network Volume with ML models.

Usage:
    HF_HUB_OFFLINE=0 python3 scripts/prepare_runpod_volume.py

Models:
    HunyuanVideo — T2V  (~30 GB safetensors, fp16/bf16 only)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import HfHubHTTPError
except ImportError:
    print("ERROR: pip install huggingface_hub")
    sys.exit(1)

try:
    from src.shared.logging import get_logger
    logger = get_logger(__name__)
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logger = logging.getLogger(__name__)

# ── Volume detection ──────────────────────────────────────────────────────────
_CANDIDATES = ["/workspace", "/runpod-volume", "/volume"]
VOLUME_BASE = next((p for p in _CANDIDATES if os.path.exists(p)), None)

if VOLUME_BASE is None:
    logger.error("❌ Network Volume not found!")
    sys.exit(1)

logger.info(f"✅ Found Network Volume at: {VOLUME_BASE}")
MODELS_DIR = Path(VOLUME_BASE) / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# ── Model specs ───────────────────────────────────────────────────────────────
MODELS = [
    {
        "name": "HunyuanVideo",
        # hunyuanvideo-community — diffusers-совместимый форм с model_index.json
        # tencent/HunyuanVideo — оригинал БЕЗ model_index.json, не работает с from_pretrained
        "repo_id": "hunyuanvideo-community/HunyuanVideo",
        "ignore_patterns": ["*.bin", "*.onnx", "fp32/*"],
        "description": "HunyuanVideo T2V diffusers format (~30 GB safetensors, fp16/bf16 only)",
    },
]


def check_disk_space() -> None:
    import shutil
    total, used, free = shutil.disk_usage(VOLUME_BASE)
    free_gb = free / 1024 ** 3
    logger.info(f"💾 Disk: {total/1024**3:.0f} GB total / {free_gb:.1f} GB free")
    if free_gb < 35:
        logger.warning(f"⚠️  Only {free_gb:.1f} GB free — need ~35 GB for HunyuanVideo")


def download_model(name: str, repo_id: str, ignore_patterns: list[str], description: str) -> bool:
    model_dir = MODELS_DIR / name

    if model_dir.exists() and any(model_dir.iterdir()):
        size_gb = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file()) / 1024 ** 3
        logger.info(f"⏭  {description} — already exists ({size_gb:.1f} GB), skipping")
        return True

    logger.info(f"⬇  Downloading {description}")
    logger.info(f"   repo  : {repo_id}")
    logger.info(f"   target: {model_dir}")






    model_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(model_dir),
            local_dir_use_symlinks=False,
            ignore_patterns=ignore_patterns,
            resume_download=True,
        )
    except HfHubHTTPError as e:
        logger.error(f"❌ HTTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return False

    files = [f for f in model_dir.rglob("*") if f.is_file()]
    size_gb = sum(f.stat().st_size for f in files) / 1024 ** 3
    elapsed = (time.time() - t0) / 60
    logger.info(f"✅ {name}: {len(files)} files, {size_gb:.1f} GB  ({elapsed:.1f} min)")
    return True


def main() -> None:
    if os.getenv("HF_HUB_OFFLINE", "0") == "1":
        logger.error("⚠️  HF_HUB_OFFLINE=1 — set to 0 before running")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("RunPod Network Volume — HunyuanVideo T2V")
    logger.info("=" * 60)

    check_disk_space()

    ok = 0
    for spec in MODELS:
        logger.info("")
        if download_model(**spec):
            ok += 1

    logger.info("")
    logger.info("=" * 60)
    if ok == len(MODELS):
        logger.info(f"✅ All {ok} models ready at {MODELS_DIR}")
    else:
        logger.error(f"❌ {len(MODELS) - ok} model(s) failed")
        sys.exit(1)


if __name__ == "__main__":
    main()

