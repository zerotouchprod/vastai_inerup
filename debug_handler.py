#!/usr/bin/env python3
"""
debug_handler.py — локальный дебаг runpod_handler без запуска RunPod worker.

Запуск внутри контейнера:
    docker run --rm --gpus all \
        -v /workspace:/workspace \
        -e HF_HUB_OFFLINE=1 \
        -v $(pwd)/test_input.json:/app/test_input.json \
        -v $(pwd)/debug_output:/app/debug_output \
        registry.gitlab.com/gfever/vastai_interup:video-gen-serverless-ultra \
        python3 debug_handler.py

Или на RunPod Pod (не Serverless) с тем же Network Volume:
    python3 debug_handler.py
    python3 debug_handler.py --phase t2i          # только генерация картинки
    python3 debug_handler.py --phase i2v          # только картинка → видео (нужен --image)
    python3 debug_handler.py --phase i2v --image /tmp/ref.png
    python3 debug_handler.py --input '{"prompt": "A dog running", "num_frames": 8}'
"""

import os
import sys
import json
import argparse
import time
from pathlib import Path

# Убедимся что src в пути
sys.path.insert(0, str(Path(__file__).parent))

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HOME", "/workspace/huggingface_cache")

# Cloudflare R2 credentials (можно переопределить через env перед запуском)
os.environ.setdefault("R2_ACCESS_KEY_ID", "")
os.environ.setdefault("R2_SECRET_ACCESS_KEY", "")
os.environ.setdefault("R2_DEFAULT_REGION", "EEUR")
os.environ.setdefault("R2_BUCKET", "videos")
os.environ.setdefault("R2_ENDPOINT", "")


def run_full(job_input: dict) -> None:
    from src.entrypoints.runpod_handler import process_job

    job = {
        "id": f"debug-{int(time.time())}",
        "input": job_input,
    }

    print("\n" + "=" * 60)
    print("🚀 Running full pipeline: prompt → image → video")
    print(f"Input: {json.dumps(job_input, indent=2)}")
    print("=" * 60 + "\n")

    t0 = time.time()
    result = process_job(job)
    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print(f"✅ Done in {elapsed:.1f}s")
    print(json.dumps(result, indent=2))
    print("=" * 60)

    if result.get("status") == "success":
        video_path = result.get("video_path")
        video_url = result.get("video_url")
        if video_url:
            print(f"\n📥 Download video:\n  {video_url}")
        elif video_path and Path(video_path).exists():
            out_dir = Path("debug_output")
            out_dir.mkdir(exist_ok=True)
            dest = out_dir / Path(video_path).name
            Path(video_path).rename(dest)
            print(f"\n💾 Video saved to: {dest.resolve()}")


def run_t2i_only(job_input: dict) -> None:
    from src.entrypoints.runpod_handler import generate_image

    print("\n🖼  Phase 1 only: Text → Image")
    t0 = time.time()
    image_path = generate_image(
        prompt=job_input["prompt"],
        negative_prompt=job_input.get("negative_prompt"),
        num_inference_steps=job_input.get("t2i_steps", 4),
        guidance_scale=job_input.get("t2i_guidance_scale", 0.0),
        seed=job_input.get("seed"),
    )
    print(f"✅ Image generated in {time.time() - t0:.1f}s: {image_path}")

    out_dir = Path("debug_output")
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / image_path.name
    image_path.rename(dest)
    print(f"💾 Saved to: {dest.resolve()}")


def run_i2v_only(job_input: dict, image_path: Path) -> None:
    from src.entrypoints.runpod_handler import generate_video

    print(f"\n🎬 Phase 2 only: Image → Video  (image: {image_path})")
    t0 = time.time()
    video_path = generate_video(
        image_path=image_path,
        prompt=job_input["prompt"],
        negative_prompt=job_input.get("negative_prompt"),
        num_inference_steps=job_input.get("num_inference_steps", 10),
        guidance_scale=job_input.get("guidance_scale", 6.0),
        num_frames=job_input.get("num_frames", 16),
        fps=job_input.get("fps", 8),
        seed=job_input.get("seed"),
    )
    print(f"✅ Video generated in {time.time() - t0:.1f}s: {video_path}")

    out_dir = Path("debug_output")
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / video_path.name
    video_path.rename(dest)
    print(f"💾 Saved to: {dest.resolve()}")


def check_models() -> None:
    """Проверить что модели на месте перед запуском."""
    from src.entrypoints.runpod_handler import T2I_MODEL_PATH, I2V_MODEL_PATH

    ok = True
    for label, path in [("T2I (DreamShaper)", T2I_MODEL_PATH), ("I2V (CogVideoX)", I2V_MODEL_PATH)]:
        exists = Path(path).exists()
        status = "✅" if exists else "❌"
        print(f"  {status} {label}: {path}")
        if not exists:
            ok = False

    if not ok:
        print("\n⚠️  Загрузите модели:")
        print("  huggingface-cli download lykon/dreamshaper-xl-lightning \\")
        print("    --local-dir /workspace/models/dreamshaper-xl-lightning")
        print("  huggingface-cli download THUDM/CogVideoX-5b-I2V \\")
        print("    --local-dir /workspace/models/CogVideoX-5b-I2V")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local debug runner for runpod_handler")
    parser.add_argument(
        "--phase",
        choices=["full", "t2i", "i2v"],
        default="full",
        help="Which phase to run (default: full)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="JSON string with job input (overrides test_input.json)",
    )
    parser.add_argument(
        "--image",
        type=str,
        default=None,
        help="Path to reference image (required for --phase i2v)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check model paths, don't run generation",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("🔍 Checking environment...")
    print(f"  HF_HUB_OFFLINE : {os.getenv('HF_HUB_OFFLINE')}")
    print(f"  HF_HOME        : {os.getenv('HF_HOME')}")
    print(f"  R2_BUCKET      : {os.getenv('R2_BUCKET', '(not set)')}")
    print(f"  R2_ENDPOINT    : {os.getenv('R2_ENDPOINT', '(not set)')}")

    import torch
    print(f"  CUDA available : {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  GPU            : {torch.cuda.get_device_name(0)}")
        vram = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
        print(f"  VRAM           : {vram:.1f} GB")

    print("\n📦 Checking models...")
    check_models()

    if args.check:
        print("\n✅ All checks passed.")
        return

    # Load job input
    if args.input:
        job_input = json.loads(args.input)
    else:
        test_input_path = Path(__file__).parent / "test_input.json"
        if not test_input_path.exists():
            print(f"❌ test_input.json not found at {test_input_path}")
            sys.exit(1)
        job_input = json.loads(test_input_path.read_text())["input"]

    if args.phase == "full":
        run_full(job_input)
    elif args.phase == "t2i":
        run_t2i_only(job_input)
    elif args.phase == "i2v":
        if not args.image:
            print("❌ --image is required for --phase i2v")
            sys.exit(1)
        run_i2v_only(job_input, Path(args.image))


if __name__ == "__main__":
    main()

