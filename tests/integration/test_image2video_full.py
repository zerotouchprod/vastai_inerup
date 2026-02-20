"""
Integration tests — full Image-to-Video pipeline with mock engine.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.mocks.mock_engines import MockImage2VideoEngine
from src.services.generation.config import GenerationConfig
from src.services.generation.models import GenJob, GenerationMode, BatchGenerationResult
from src.services.generation.orchestrator import GenerationOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(
    config: GenerationConfig,
    b2_client: MagicMock | None = None,
    delay: float = 0.0,
) -> GenerationOrchestrator:
    orch = GenerationOrchestrator(config=config, b2_client=b2_client)
    engine = MockImage2VideoEngine(delay=delay, config=config)
    engine.initialize()
    orch._i2v_engine = engine
    return orch


def _i2v_job(n: int = 1, **kwargs) -> GenJob:
    prompts = [f"animate frame {i}" for i in range(n)]
    images = [f"https://example.com/img_{i}.jpg" for i in range(n)]
    return GenJob(
        prompts=prompts,
        mode=GenerationMode.IMAGE2VIDEO,
        input_images=images,
        num_frames=5,
        fps=8,
        output_prefix="test/i2v/",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Single prompt
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestI2VSinglePrompt:

    def test_returns_batch_result(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job())

        assert isinstance(result, BatchGenerationResult)
        assert result.total_prompts == 1

    def test_single_success(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job())

        assert result.successful == 1
        assert result.failed == 0
        assert result.results[0].success is True

    def test_mode_in_result(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job())

        assert result.results[0].mode == GenerationMode.IMAGE2VIDEO

    def test_output_key_has_i2v_prefix(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job())

        key = result.results[0].output_key
        assert "i2v" in key
        assert key.endswith(".mp4")

    def test_input_image_passed_to_engine(self, gen_config: GenerationConfig) -> None:
        """Engine must receive the correct input_image URL."""
        engine = MockImage2VideoEngine(delay=0.0, config=gen_config)
        engine.initialize()

        orch = GenerationOrchestrator(config=gen_config)
        orch._i2v_engine = engine

        orch.process_job(_i2v_job())

        assert engine._last_input_image == "https://example.com/img_0.jpg"

    def test_file_created_without_b2(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config, b2_client=None)
        result = orch.process_job(_i2v_job())

        r = result.results[0]
        assert r.local_path is not None
        assert r.local_path.exists()
        assert r.local_path.stat().st_size > 0


# ---------------------------------------------------------------------------
# B2 upload
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestI2VWithB2Upload:

    def test_upload_called_per_prompt(
        self, gen_config: GenerationConfig, mock_b2_client: MagicMock
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        orch.process_job(_i2v_job(n=2))

        assert mock_b2_client.upload_file.call_count == 2

    def test_presigned_urls_set(
        self, gen_config: GenerationConfig, mock_b2_client: MagicMock
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        result = orch.process_job(_i2v_job(n=2))

        for r in result.results:
            assert r.url is not None


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestI2VBatch:

    def test_batch_three(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job(n=3))

        assert result.successful == 3
        assert len(result.results) == 3

    def test_each_result_has_unique_key(self, gen_config: GenerationConfig) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(_i2v_job(n=3))

        keys = [r.output_key for r in result.results]
        assert len(set(keys)) == 3


# ---------------------------------------------------------------------------
# Missing input_image at runtime
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_missing_input_image_marks_result_failed(gen_config: GenerationConfig) -> None:
    """
    Orchestrator must mark result as failed if input_image is missing at runtime
    (edge case: correct job but engine receives wrong index).
    """
    job = _i2v_job(n=2)
    # Simulate engine receiving a job where second image is missing at runtime
    # by patching the job's input_images to be shorter after creation
    job_data = job.model_dump()
    job_data["input_images"] = ["https://example.com/img_0.jpg"]  # only 1 for 2 prompts
    # Bypass pydantic validation — set directly on the object
    job.__dict__["input_images"] = ["https://example.com/img_0.jpg"]

    orch = _make_orchestrator(gen_config)
    result = orch.process_job(job)

    # prompt[1] must fail — no image at index 1
    assert result.results[1].success is False


# ---------------------------------------------------------------------------
# Delay parametrize
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delay", [0.0, 0.1])
def test_i2v_pipeline_with_delay(delay: float, gen_config: GenerationConfig) -> None:
    import time

    orch = _make_orchestrator(gen_config, delay=delay)
    start = time.monotonic()
    result = orch.process_job(_i2v_job())
    elapsed = time.monotonic() - start

    assert result.successful == 1
    assert elapsed >= delay
