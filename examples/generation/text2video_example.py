"""
Example: Text-to-Video generation with single prompt.

This example demonstrates basic text-to-video generation
without B2 upload (local file output).
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.services.generation.models import GenJob, GenerationMode
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig


def main():
    """Run simple T2V generation example."""

    print("=" * 60)
    print("Text-to-Video Generation Example")
    print("=" * 60)

    # Create job
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["A cat dancing in the moonlight, cinematic lighting"],
        guidance_scale=6.0,
        num_inference_steps=50,
        num_frames=49,  # ~6 seconds at 8fps
        output_prefix="examples/output/"
    )

    print(f"\nJob ID: {job.id}")
    print(f"Mode: {job.mode.value}")
    print(f"Prompt: {job.prompts[0]}")
    print(f"Parameters:")
    print(f"  - Guidance: {job.guidance_scale}")
    print(f"  - Steps: {job.num_inference_steps}")
    print(f"  - Frames: {job.num_frames}")

    # Create orchestrator (no B2 upload)
    config = GenerationConfig()
    orchestrator = GenerationOrchestrator(config=config, b2_client=None)

    print("\n" + "=" * 60)
    print("Starting generation...")
    print("=" * 60)
    print("⚠️  This requires a GPU with 24GB VRAM")
    print("⚠️  First run will download ~13GB model")
    print("=" * 60)

    try:
        # Process job
        result = orchestrator.process_job(job)

        # Show results
        print("\n" + "=" * 60)
        print("Generation Results")
        print("=" * 60)
        print(f"Total prompts: {result.total_prompts}")
        print(f"Successful: {result.successful}")
        print(f"Failed: {result.failed}")
        print(f"Duration: {result.duration_seconds:.1f}s")

        for i, gen_result in enumerate(result.results):
            print(f"\n[{i+1}] {gen_result.prompt[:50]}...")
            print(f"    Success: {gen_result.success}")
            if gen_result.success:
                print(f"    Output: {gen_result.url}")
                print(f"    Size: {gen_result.size_bytes / 1024 / 1024:.2f} MB")
            else:
                print(f"    Error: {gen_result.error}")

        print("\n✅ Example completed!")

    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        raise


if __name__ == "__main__":
    main()
