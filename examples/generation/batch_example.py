"""
Example: Batch Text-to-Video generation with B2 upload.

This example demonstrates:
- Multiple prompts in single job
- B2/S3 storage upload
- Custom generation parameters
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.generation.models import GenJob, GenerationMode
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig


def main():
    """Run batch T2V generation with B2 upload."""

    print("=" * 60)
    print("Batch Text-to-Video Generation with B2 Upload")
    print("=" * 60)

    # Check B2 credentials
    if not all([
        os.getenv('B2_KEY'),
        os.getenv('B2_SECRET'),
        os.getenv('B2_BUCKET')
    ]):
        print("\n⚠️  B2 credentials not set!")
        print("Export these environment variables:")
        print("  - B2_KEY")
        print("  - B2_SECRET")
        print("  - B2_BUCKET")
        print("  - B2_ENDPOINT (optional)")
        return 1

    # Create batch job
    prompts = [
        "A sunset over the ocean, waves crashing, cinematic",
        "A futuristic city at night, neon lights, cyberpunk style",
        "A cat playing with yarn, cute and playful, 4K quality"
    ]

    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=prompts,
        negative_prompt="blurry, low quality, distorted",
        guidance_scale=7.0,
        num_inference_steps=40,  # Faster than default
        num_frames=49,
        output_prefix="generated/batch_demo/"
    )

    print(f"\nJob ID: {job.id}")
    print(f"Mode: {job.mode.value}")
    print(f"Prompts: {len(job.prompts)}")
    for i, prompt in enumerate(job.prompts):
        print(f"  [{i+1}] {prompt}")

    print(f"\nParameters:")
    print(f"  - Guidance: {job.guidance_scale}")
    print(f"  - Steps: {job.num_inference_steps}")
    print(f"  - Frames: {job.num_frames}")
    print(f"  - Negative: {job.negative_prompt}")

    # Create orchestrator with B2
    config = GenerationConfig()
    orchestrator = GenerationOrchestrator(config=config)  # Will auto-init B2

    print("\n" + "=" * 60)
    print("Starting batch generation...")
    print("=" * 60)
    print(f"⚠️  This will generate {len(prompts)} videos")
    print(f"⚠️  Estimated time: ~{len(prompts) * 2} minutes")
    print("=" * 60)

    try:
        # Process job
        result = orchestrator.process_job(job)

        # Show results
        print("\n" + "=" * 60)
        print("Batch Generation Results")
        print("=" * 60)
        print(f"Total prompts: {result.total_prompts}")
        print(f"Successful: {result.successful}")
        print(f"Failed: {result.failed}")
        print(f"Success rate: {result.successful/result.total_prompts*100:.1f}%")
        print(f"Total duration: {result.duration_seconds:.1f}s")
        print(f"Avg per video: {result.duration_seconds/result.total_prompts:.1f}s")

        print("\n📹 Generated videos:")
        for i, gen_result in enumerate(result.results):
            print(f"\n[{i+1}] {gen_result.prompt[:60]}...")
            if gen_result.success:
                print(f"    ✅ Success")
                print(f"    🔗 URL: {gen_result.url}")
                print(f"    📦 Size: {gen_result.size_bytes / 1024 / 1024:.2f} MB")
                print(f"    🔑 Key: {gen_result.output_key}")
            else:
                print(f"    ❌ Failed: {gen_result.error}")

        print("\n✅ Batch generation completed!")
        return 0

    except Exception as e:
        print(f"\n❌ Batch generation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
