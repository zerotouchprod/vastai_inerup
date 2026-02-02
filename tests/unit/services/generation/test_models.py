"""
Unit tests for generation data models.
"""

import pytest
import json
from src.services.generation.models import GenJob, GenerationResult, BatchGenerationResult, GenerationMode


def test_genjob_text2video_defaults():
    """Test GenJob creation with T2V defaults."""
    job = GenJob(prompts=["A test prompt"])

    assert job.id is not None
    assert job.mode == GenerationMode.TEXT2VIDEO
    assert len(job.prompts) == 1
    assert job.prompts[0] == "A test prompt"
    assert job.guidance_scale == 6.0
    assert job.num_inference_steps == 50
    assert job.num_frames == 49
    assert job.fps == 8
    assert job.output_prefix == "generated/"


def test_genjob_with_custom_params():
    """Test GenJob with custom parameters."""
    job = GenJob(
        prompts=["Prompt 1", "Prompt 2"],
        negative_prompt="bad quality",
        seed=42,
        guidance_scale=7.5,
        num_inference_steps=30,
        num_frames=25,
        fps=10,
        output_prefix="custom/"
    )

    assert len(job.prompts) == 2
    assert job.negative_prompt == "bad quality"
    assert job.seed == 42
    assert job.guidance_scale == 7.5
    assert job.num_inference_steps == 30
    assert job.num_frames == 25
    assert job.fps == 10
    assert job.output_prefix == "custom/"


def test_genjob_json_serialization():
    """Test JSON serialization and deserialization."""
    original = GenJob(
        prompts=["Test"],
        guidance_scale=7.0
    )

    json_str = original.to_json()
    assert isinstance(json_str, str)

    loaded = GenJob.from_json(json_str)
    assert loaded.id == original.id
    assert loaded.prompts == original.prompts
    assert loaded.guidance_scale == original.guidance_scale


def test_genjob_validation_empty_prompt():
    """Test validation of empty prompts."""
    with pytest.raises(ValueError, match="empty"):
        GenJob(prompts=[""])


def test_genjob_validation_long_prompt():
    """Test validation of too long prompts."""
    long_prompt = "A" * 1001
    with pytest.raises(ValueError, match="too long"):
        GenJob(prompts=[long_prompt])


def test_genjob_validation_guidance_scale():
    """Test validation of guidance_scale."""
    with pytest.raises(ValueError):
        GenJob(prompts=["test"], guidance_scale=0.5)

    with pytest.raises(ValueError):
        GenJob(prompts=["test"], guidance_scale=25.0)


def test_genjob_validation_inference_steps():
    """Test validation of num_inference_steps."""
    with pytest.raises(ValueError):
        GenJob(prompts=["test"], num_inference_steps=5)

    with pytest.raises(ValueError):
        GenJob(prompts=["test"], num_inference_steps=250)


def test_genjob_output_key_generation():
    """Test output key generation."""
    job = GenJob(prompts=["Test prompt"], output_prefix="videos/")

    key = job.get_output_key(0)
    assert key.startswith("videos/t2v_")
    assert key.endswith(".mp4")
    assert job.id in key


def test_genjob_i2v_mode_validation():
    """Test I2V mode validation."""
    # I2V without input_images should fail
    with pytest.raises(ValueError, match="input_images required"):
        GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["Animate this"]
        )

    # I2V with mismatched counts should fail
    with pytest.raises(ValueError, match="must match"):
        GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["Prompt 1", "Prompt 2"],
            input_images=["image1.jpg"]  # Only 1 image for 2 prompts
        )


def test_genjob_t2v_mode_with_images():
    """Test that T2V mode rejects input_images."""
    with pytest.raises(ValueError, match="not allowed"):
        GenJob(
            mode=GenerationMode.TEXT2VIDEO,
            prompts=["Test"],
            input_images=["image.jpg"]
        )


def test_generation_result():
    """Test GenerationResult model."""
    result = GenerationResult(
        job_id="test-job",
        prompt_index=0,
        prompt="Test prompt",
        mode=GenerationMode.TEXT2VIDEO,
        output_key="videos/test.mp4"
    )

    assert result.job_id == "test-job"
    assert result.success is True
    assert result.error is None
    assert result.mode == GenerationMode.TEXT2VIDEO


def test_batch_generation_result():
    """Test BatchGenerationResult model."""
    result = BatchGenerationResult(
        job_id="batch-job",
        mode=GenerationMode.TEXT2VIDEO,
        total_prompts=3
    )

    assert result.job_id == "batch-job"
    assert result.mode == GenerationMode.TEXT2VIDEO
    assert result.total_prompts == 3
    assert result.successful == 0
    assert result.failed == 0
    assert result.duration_seconds is None  # Not completed yet


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
