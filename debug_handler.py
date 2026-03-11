"""
debug_handler.py — локальный запуск handler для отладки на Pod.

    cd /app && python3 debug_handler.py           # полный прогон
    cd /app && python3 debug_handler.py --check   # только проверка окружения
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def check_env() -> None:
    print("=" * 60)
    print("🔍 Checking environment...")
    print()
    for var in ["HF_HUB_OFFLINE", "HF_HOME", "R2_BUCKET", "R2_ENDPOINT"]:
        print(f"  {var:<25}: {os.getenv(var, '<not set>')}")
    print()

    import torch
    cuda_ok = torch.cuda.is_available()
    print(f"  CUDA available : {cuda_ok}")
    if cuda_ok:
        print(f"  GPU            : {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
        print(f"  VRAM           : {vram:.1f} GB")
    print()


def check_models() -> None:
    print("📦 Checking models...")
    volume = next((p for p in ["/workspace", "/runpod-volume", "/volume"] if os.path.exists(p)), None)

    if volume is None:
        print("  ❌ No Network Volume found!")
        sys.exit(1)

    model_path = Path(volume) / "models" / "HunyuanVideo"
    if model_path.exists() and any(model_path.iterdir()):
        size_gb = sum(f.stat().st_size for f in model_path.rglob("*") if f.is_file()) / 1024 ** 3
        print(f"  ✅ HunyuanVideo: {model_path}  ({size_gb:.1f} GB)")
    else:
        print(f"  ❌ HunyuanVideo: NOT FOUND at {model_path}")
        print("     Run: HF_HUB_OFFLINE=0 python3 scripts/prepare_runpod_volume.py")
        sys.exit(1)

    print()
    print("✅ All checks passed.")
    print()


def run_job() -> None:
    test_input_path = Path(__file__).parent / "test_input.json"
    if not test_input_path.exists():
        print(f"❌ test_input.json not found at {test_input_path}")
        sys.exit(1)

    with open(test_input_path) as f:
        test_data = json.load(f)

    job = {
        "id": f"debug-{int(time.time())}",
        "input": test_data.get("input", test_data),
    }

    print(f"📥 Job input:\n{json.dumps(job['input'], indent=2, ensure_ascii=False)}")
    print("=" * 60)

    sys.path.insert(0, str(Path(__file__).parent))
    from src.entrypoints.runpod_handler import process_job

    t0 = time.time()
    result = process_job(job)
    elapsed = time.time() - t0

    print("=" * 60)
    print(f"✅ Done in {elapsed:.1f}s")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 60)

    if result.get("status") == "error":
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Only check environment")
    args = parser.parse_args()

    check_env()
    check_models()

    if not args.check:
        run_job()


if __name__ == "__main__":
    main()

