"""
Integration tests — full Text-to-Video pipeline with mock engine.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.mocks.mock_engines import MockText2VideoEngine
from src.services.generation.models import GenJob, GenerationMode, BatchGenerationResult
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(
    config: GenerationConfig,
    b2_client: MagicMock | None = None,
    delay: float = 0.0,
) -> GenerationOrchestrator:
    """Build orchestrator with mock T2V engine injected."""
    orch = GenerationOrchestrator(config=config, b2_client=b2_client)
    engine = MockText2VideoEngine(delay=delay, config=config)
    engine.initialize()
    # Inject mock engine for UNIVERSAL mode
    orch._t2v_engine = engine
    return orch


# ---------------------------------------------------------------------------
# Single-prompt tests
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestT2VSinglePrompt:

    def test_process_job_returns_batch_result(
        self, gen_config: GenerationConfig, t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(t2v_job)

        assert isinstance(result, BatchGenerationResult)
        assert result.job_id == t2v_job.id
        assert result.total_prompts == 1

    def test_single_prompt_success(
        self, gen_config: GenerationConfig, t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(t2v_job)

        assert result.successful == 1
        assert result.failed == 0
        assert result.results[0].success is True

    def test_output_key_format(
        self, gen_config: GenerationConfig, t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(t2v_job)

        key = result.results[0].output_key
        assert key.startswith("test/")
        assert key.endswith(".mp4")

    def test_duration_is_set_after_completion(
        self, gen_config: GenerationConfig, t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(t2v_job)

        assert result.completed_at is not None
        assert result.duration_seconds is not None
        assert result.duration_seconds >= 0.0

    def test_local_path_is_set_without_b2(
        self, gen_config: GenerationConfig, t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=None)
        result = orch.process_job(t2v_job)

        r = result.results[0]
        assert r.local_path is not None
        assert r.url is not None and r.url.startswith("file://")


# ---------------------------------------------------------------------------
# B2 upload integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestT2VWithB2Upload:

    def test_upload_called_once_per_prompt(
        self, gen_config: GenerationConfig, t2v_job: GenJob, mock_b2_client: MagicMock
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        orch.process_job(t2v_job)

        mock_b2_client.upload_file.assert_called_once()

    def test_presigned_url_set_after_upload(
        self, gen_config: GenerationConfig, t2v_job: GenJob, mock_b2_client: MagicMock
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        result = orch.process_job(t2v_job)

        r = result.results[0]
        assert r.url == "https://b2.example.com/test/video.mp4"

    def test_b2_failure_marks_result_failed(
        self,
        gen_config: GenerationConfig,
        t2v_job: GenJob,
        mock_b2_client_failing: MagicMock,
    ) -> None:
        orch = _make_orchestrator(gen_config, b2_client=mock_b2_client_failing)
        result = orch.process_job(t2v_job)

        assert result.failed == 1
        assert result.results[0].success is False
        assert "B2 connection refused" in result.results[0].error


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestT2VBatchProcessing:

    def test_batch_three_prompts(
        self, gen_config: GenerationConfig, batch_t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(batch_t2v_job)

        assert result.total_prompts == 3
        assert result.successful == 3
        assert result.failed == 0

    def test_batch_results_count_matches_prompts(
        self, gen_config: GenerationConfig, batch_t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(batch_t2v_job)

        assert len(result.results) == 3

    def test_batch_unique_output_keys(
        self, gen_config: GenerationConfig, batch_t2v_job: GenJob
    ) -> None:
        orch = _make_orchestrator(gen_config)
        result = orch.process_job(batch_t2v_job)

        keys = [r.output_key for r in result.results]
        assert len(set(keys)) == 3


# ---------------------------------------------------------------------------
# Delay parametrize — timing tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delay", [0.0, 0.1])
def test_t2v_pipeline_with_delay(
    delay: float, gen_config: GenerationConfig
) -> None:
    import time

    job = GenJob(prompts=["test"], mode=GenerationMode.UNIVERSAL, num_frames=5)
    orch = _make_orchestrator(gen_config, delay=delay)

    start = time.monotonic()
    result = orch.process_job(job)
    elapsed = time.monotonic() - start

    assert result.successful == 1
    assert elapsed >= delay


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_orchestrator_context_manager(gen_config: GenerationConfig) -> None:
    job = GenJob(prompts=["test"], mode=GenerationMode.UNIVERSAL, num_frames=5)
    with GenerationOrchestrator(config=gen_config) as orch:
        engine = MockText2VideoEngine(delay=0.0, config=gen_config)
        engine.initialize()
        orch._t2v_engine = engine
        result = orch.process_job(job)

    assert result.successful == 1
