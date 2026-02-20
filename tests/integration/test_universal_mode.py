"""
Integration tests — UNIVERSAL mode (T2I → I2V two-stage pipeline).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.mocks.mock_engines import MockUniversalEngine
from src.services.generation.config import GenerationConfig
from src.services.generation.models import GenJob, GenerationMode
from src.services.generation.orchestrator import GenerationOrchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_orchestrator(
    config: GenerationConfig,
    b2_client: MagicMock | None = None,
    delay: float = 0.0,
) -> tuple[GenerationOrchestrator, MockUniversalEngine]:
    orch = GenerationOrchestrator(config=config, b2_client=b2_client)
    engine = MockUniversalEngine(delay=delay, config=config)
    engine.initialize()
    orch._t2v_engine = engine
    return orch, engine


def _universal_job(n: int = 1) -> GenJob:
    return GenJob(
        prompts=[f"anime rain scene {i}" for i in range(n)],
        mode=GenerationMode.UNIVERSAL,
        num_frames=5,
        fps=8,
        output_prefix="test/universal/",
    )


# ---------------------------------------------------------------------------
# Two-stage ordering
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUniversalTwoStage:

    def test_both_stages_called_for_single_prompt(
        self, gen_config: GenerationConfig
    ) -> None:
        orch, engine = _make_orchestrator(gen_config)
        orch.process_job(_universal_job(n=1))

        assert engine.t2i_call_count == 1, "T2I stage must be called exactly once"
        assert engine.i2v_call_count == 1, "I2V stage must be called exactly once"

    def test_both_stages_called_per_prompt_in_batch(
        self, gen_config: GenerationConfig
    ) -> None:
        orch, engine = _make_orchestrator(gen_config)
        orch.process_job(_universal_job(n=3))

        assert engine.t2i_call_count == 3
        assert engine.i2v_call_count == 3

    def test_t2i_before_i2v(self, gen_config: GenerationConfig) -> None:
        """
        Verify ordering by tracking a call log inside the engine.
        T2I must always increment before I2V within one generate() call.
        """
        call_log: list[str] = []

        class OrderTrackingEngine(MockUniversalEngine):
            def generate(self, prompt, **kwargs):
                call_log.append("t2i_start")
                result = super().generate(prompt, **kwargs)
                call_log.append("i2v_done")
                return result

        orch = GenerationOrchestrator(config=gen_config)
        engine = OrderTrackingEngine(config=gen_config)
        engine.initialize()
        orch._t2v_engine = engine

        orch.process_job(_universal_job(n=1))

        assert call_log == ["t2i_start", "i2v_done"]


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUniversalOutput:

    def test_result_is_successful(self, gen_config: GenerationConfig) -> None:
        orch, _ = _make_orchestrator(gen_config)
        result = orch.process_job(_universal_job())

        assert result.successful == 1
        assert result.failed == 0

    def test_output_mp4_exists_without_b2(self, gen_config: GenerationConfig) -> None:
        orch, _ = _make_orchestrator(gen_config)
        result = orch.process_job(_universal_job())

        r = result.results[0]
        assert r.local_path is not None
        assert r.local_path.exists()
        assert r.local_path.stat().st_size > 0

    def test_output_key_contains_universal(self, gen_config: GenerationConfig) -> None:
        orch, _ = _make_orchestrator(gen_config)
        result = orch.process_job(_universal_job())

        key = result.results[0].output_key
        assert "universal" in key

    def test_mode_in_result(self, gen_config: GenerationConfig) -> None:
        orch, _ = _make_orchestrator(gen_config)
        result = orch.process_job(_universal_job())

        assert result.results[0].mode == GenerationMode.UNIVERSAL


# ---------------------------------------------------------------------------
# B2 upload
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestUniversalWithB2:

    def test_upload_called_per_prompt(
        self, gen_config: GenerationConfig, mock_b2_client: MagicMock
    ) -> None:
        orch, _ = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        orch.process_job(_universal_job(n=2))

        assert mock_b2_client.upload_file.call_count == 2

    def test_presigned_url_in_result(
        self, gen_config: GenerationConfig, mock_b2_client: MagicMock
    ) -> None:
        orch, _ = _make_orchestrator(gen_config, b2_client=mock_b2_client)
        result = orch.process_job(_universal_job())

        assert result.results[0].url == "https://b2.example.com/test/video.mp4"


# ---------------------------------------------------------------------------
# Delay parametrize
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("delay", [0.0, 0.1])
def test_universal_pipeline_with_delay(
    delay: float, gen_config: GenerationConfig
) -> None:
    import time

    orch, _ = _make_orchestrator(gen_config, delay=delay)
    start = time.monotonic()
    result = orch.process_job(_universal_job())
    elapsed = time.monotonic() - start

    assert result.successful == 1
    assert elapsed >= delay


# ---------------------------------------------------------------------------
# Engine cleanup
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_universal_engine_cleanup(gen_config: GenerationConfig) -> None:
    engine = MockUniversalEngine(delay=0.0, config=gen_config)
    engine.initialize()
    assert engine._initialized is True

    engine.cleanup()

    assert engine._initialized is False
    assert engine.pipe is None


@pytest.mark.unit
def test_universal_engine_context_manager(gen_config: GenerationConfig) -> None:
    with MockUniversalEngine(config=gen_config) as engine:
        assert engine._initialized is True

    assert engine._initialized is False
