"""
Unit tests for GenJob, GenerationMode, GenerationResult, BatchGenerationResult.
Coverage target: models.py — validation, serialization, output_key, edge cases.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.services.generation.models import (
    BatchGenerationResult,
    GenJob,
    GenerationMode,
    GenerationResult,
)


# ---------------------------------------------------------------------------
# GenerationMode
# ---------------------------------------------------------------------------

class TestGenerationMode:

    def test_universal_value(self) -> None:
        assert GenerationMode.UNIVERSAL.value == "universal"

    def test_image2video_value(self) -> None:
        assert GenerationMode.IMAGE2VIDEO.value == "image2video"

    def test_is_str_enum(self) -> None:
        assert isinstance(GenerationMode.UNIVERSAL, str)


# ---------------------------------------------------------------------------
# GenJob — creation
# ---------------------------------------------------------------------------

class TestGenJobCreation:

    def test_minimal_t2v_job(self) -> None:
        job = GenJob(prompts=["anime rain"])
        assert job.id is not None
        assert len(job.id) > 0
        assert job.mode == GenerationMode.UNIVERSAL
        assert job.prompts == ["anime rain"]

    def test_default_params(self) -> None:
        job = GenJob(prompts=["test"])
        assert job.guidance_scale == 6.0
        assert job.num_inference_steps == 50
        assert job.num_frames == 49
        assert job.fps == 8

    def test_unique_ids(self) -> None:
        a = GenJob(prompts=["p1"])
        b = GenJob(prompts=["p2"])
        assert a.id != b.id

    def test_output_prefix_normalized(self) -> None:
        job = GenJob(prompts=["test"], output_prefix="generated")
        assert job.output_prefix.endswith("/")

    def test_output_prefix_with_slash(self) -> None:
        job = GenJob(prompts=["test"], output_prefix="generated/")
        assert job.output_prefix == "generated/"


# ---------------------------------------------------------------------------
# GenJob — validation errors
# ---------------------------------------------------------------------------

class TestGenJobValidation:

    def test_empty_prompts_list_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=[])

    def test_blank_prompt_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=["  "])

    def test_prompt_too_long_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=["x" * 1001])

    def test_guidance_scale_too_low_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=["test"], guidance_scale=0.5)

    def test_guidance_scale_too_high_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=["test"], guidance_scale=25.0)

    def test_i2v_mode_without_images_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(prompts=["test"], mode=GenerationMode.IMAGE2VIDEO)

    def test_i2v_mode_images_count_mismatch_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(
                prompts=["p1", "p2"],
                mode=GenerationMode.IMAGE2VIDEO,
                input_images=["https://example.com/img.png"],
            )

    def test_universal_mode_with_images_raises(self) -> None:
        with pytest.raises(ValidationError):
            GenJob(
                prompts=["test"],
                mode=GenerationMode.UNIVERSAL,
                input_images=["https://example.com/img.png"],
            )


# ---------------------------------------------------------------------------
# GenJob — I2V valid creation
# ---------------------------------------------------------------------------

class TestGenJobI2V:

    def test_i2v_job_valid(self) -> None:
        job = GenJob(
            prompts=["animate this"],
            mode=GenerationMode.IMAGE2VIDEO,
            input_images=["https://example.com/ref.jpg"],
        )
        assert job.mode == GenerationMode.IMAGE2VIDEO
        assert job.input_images == ["https://example.com/ref.jpg"]

    def test_i2v_batch_valid(self) -> None:
        job = GenJob(
            prompts=["p1", "p2"],
            mode=GenerationMode.IMAGE2VIDEO,
            input_images=["https://a.com/1.jpg", "https://a.com/2.jpg"],
        )
        assert len(job.input_images) == 2


# ---------------------------------------------------------------------------
# GenJob — output_key
# ---------------------------------------------------------------------------

class TestGenJobOutputKey:

    def test_output_key_contains_job_id(self) -> None:
        job = GenJob(prompts=["test"], output_prefix="gen/")
        key = job.get_output_key(0)
        assert job.id in key

    def test_output_key_ends_with_mp4(self) -> None:
        job = GenJob(prompts=["test"])
        assert job.get_output_key(0).endswith(".mp4")

    def test_output_key_custom_extension(self) -> None:
        job = GenJob(prompts=["test"])
        assert job.get_output_key(0, extension="webm").endswith(".webm")

    def test_output_key_contains_index(self) -> None:
        job = GenJob(prompts=["a", "b"])
        key0 = job.get_output_key(0)
        key1 = job.get_output_key(1)
        assert key0 != key1

    def test_output_key_invalid_index_raises(self) -> None:
        job = GenJob(prompts=["test"])
        with pytest.raises(ValueError):
            job.get_output_key(5)

    def test_output_key_negative_index_raises(self) -> None:
        job = GenJob(prompts=["test"])
        with pytest.raises(ValueError):
            job.get_output_key(-1)

    def test_output_key_i2v_prefix(self) -> None:
        job = GenJob(
            prompts=["test"],
            mode=GenerationMode.IMAGE2VIDEO,
            input_images=["https://example.com/img.jpg"],
            output_prefix="out/",
        )
        key = job.get_output_key(0)
        assert key.startswith("out/i2v_")


# ---------------------------------------------------------------------------
# GenJob — JSON serialization
# ---------------------------------------------------------------------------

class TestGenJobSerialization:

    def test_round_trip_t2v(self) -> None:
        job = GenJob(prompts=["test prompt"])
        restored = GenJob.from_json(job.to_json())
        assert restored.id == job.id
        assert restored.prompts == job.prompts
        assert restored.mode == job.mode

    def test_round_trip_i2v(self) -> None:
        job = GenJob(
            prompts=["animate"],
            mode=GenerationMode.IMAGE2VIDEO,
            input_images=["https://example.com/img.jpg"],
            seed=42,
        )
        restored = GenJob.from_json(job.to_json())
        assert restored.seed == 42
        assert restored.input_images == job.input_images

    def test_from_json_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            GenJob.from_json("{not valid json")

    def test_to_json_is_valid_json(self) -> None:
        job = GenJob(prompts=["test"])
        data = json.loads(job.to_json())
        assert "id" in data
        assert "prompts" in data


# ---------------------------------------------------------------------------
# GenerationResult
# ---------------------------------------------------------------------------

class TestGenerationResult:

    def test_default_success_true(self) -> None:
        r = GenerationResult(
            job_id="j1",
            prompt_index=0,
            prompt="test",
            mode=GenerationMode.UNIVERSAL,
            output_key="gen/test.mp4",
        )
        assert r.success is True
        assert r.error is None

    def test_failure_result(self) -> None:
        r = GenerationResult(
            job_id="j1",
            prompt_index=0,
            prompt="test",
            mode=GenerationMode.UNIVERSAL,
            output_key="gen/test.mp4",
            success=False,
            error="OOM",
        )
        assert r.success is False
        assert r.error == "OOM"

    def test_generated_at_is_utc(self) -> None:
        r = GenerationResult(
            job_id="j1",
            prompt_index=0,
            prompt="test",
            mode=GenerationMode.UNIVERSAL,
            output_key="gen/test.mp4",
        )
        assert r.generated_at.tzinfo is not None


# ---------------------------------------------------------------------------
# BatchGenerationResult
# ---------------------------------------------------------------------------

class TestBatchGenerationResult:

    def test_duration_none_when_not_completed(self) -> None:
        b = BatchGenerationResult(
            job_id="j1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=2,
        )
        assert b.duration_seconds is None

    def test_duration_calculated_when_completed(self) -> None:
        from datetime import timedelta

        b = BatchGenerationResult(
            job_id="j1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=1,
        )
        b.completed_at = b.started_at + timedelta(seconds=5)
        assert b.duration_seconds == pytest.approx(5.0, abs=0.1)

    def test_success_failure_tracking(self) -> None:
        b = BatchGenerationResult(
            job_id="j1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=3,
            successful=2,
            failed=1,
        )
        assert b.successful + b.failed == 3
