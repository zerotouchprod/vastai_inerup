"""
Unit tests for src/domain/generation.py.
Coverage target: IVideoGenerator protocol, VideoGenerationRequest, GenerationMetadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.domain.generation import (
    GenerationMetadata,
    GenerationMode,
    IVideoGenerator,
    VideoGenerationRequest,
)


class TestDomainGenerationMode:

    def test_text2video_value(self) -> None:
        assert GenerationMode.TEXT2VIDEO.value == "text2video"

    def test_image2video_value(self) -> None:
        assert GenerationMode.IMAGE2VIDEO.value == "image2video"

    def test_is_str_enum(self) -> None:
        assert isinstance(GenerationMode.TEXT2VIDEO, str)


class TestVideoGenerationRequest:

    def test_defaults(self) -> None:
        req = VideoGenerationRequest(prompt="anime rain")
        assert req.mode == GenerationMode.TEXT2VIDEO
        assert req.guidance_scale == 6.0
        assert req.num_inference_steps == 50
        assert req.num_frames == 49
        assert req.fps == 8
        assert req.negative_prompt is None
        assert req.input_image is None
        assert req.seed is None

    def test_custom_values(self) -> None:
        req = VideoGenerationRequest(
            prompt="dragon",
            mode=GenerationMode.IMAGE2VIDEO,
            input_image="https://example.com/img.jpg",
            seed=42,
            guidance_scale=7.5,
            num_frames=25,
            fps=16,
        )
        assert req.mode == GenerationMode.IMAGE2VIDEO
        assert req.input_image == "https://example.com/img.jpg"
        assert req.seed == 42
        assert req.guidance_scale == 7.5
        assert req.num_frames == 25
        assert req.fps == 16

    def test_prompt_stored(self) -> None:
        req = VideoGenerationRequest(prompt="test prompt")
        assert req.prompt == "test prompt"

    def test_negative_prompt(self) -> None:
        req = VideoGenerationRequest(prompt="test", negative_prompt="blurry, bad quality")
        assert req.negative_prompt == "blurry, bad quality"


class TestGenerationMetadata:

    def _make_meta(self, path: Path) -> GenerationMetadata:
        return GenerationMetadata(
            job_id="job-123",
            prompt="anime rain scene",
            mode=GenerationMode.TEXT2VIDEO,
            output_path=path,
            size_bytes=1024 * 512,
            duration_seconds=6.125,
            num_frames=49,
            fps=8,
            generated_at=datetime.now(timezone.utc),
            inference_time_seconds=45.3,
        )

    def test_fields_stored(self, tmp_path: Path) -> None:
        vid = tmp_path / "out.mp4"
        vid.write_bytes(b"\x00" * 100)
        meta = self._make_meta(vid)

        assert meta.job_id == "job-123"
        assert meta.prompt == "anime rain scene"
        assert meta.mode == GenerationMode.TEXT2VIDEO
        assert meta.size_bytes == 1024 * 512
        assert meta.num_frames == 49
        assert meta.fps == 8
        assert meta.inference_time_seconds == pytest.approx(45.3, abs=0.01)

    def test_seed_used_default_none(self, tmp_path: Path) -> None:
        meta = self._make_meta(tmp_path / "out.mp4")
        assert meta.seed_used is None

    def test_seed_used_set(self, tmp_path: Path) -> None:
        meta = self._make_meta(tmp_path / "out.mp4")
        meta.seed_used = 42
        assert meta.seed_used == 42

    def test_generated_at_timezone_aware(self, tmp_path: Path) -> None:
        meta = self._make_meta(tmp_path / "out.mp4")
        assert meta.generated_at.tzinfo is not None


class TestIVideoGeneratorProtocol:
    """
    Verify that a class satisfying IVideoGenerator protocol
    can be used where IVideoGenerator is expected (structural subtyping).
    """

    def test_protocol_satisfied_by_mock_engine(self) -> None:
        from tests.mocks.mock_engines import MockText2VideoEngine, _make_test_config

        engine = MockText2VideoEngine(config=_make_test_config())
        # IVideoGenerator requires: initialize, generate, cleanup
        assert callable(engine.initialize)
        assert callable(engine.generate)
        assert callable(engine.cleanup)

    def test_protocol_satisfied_by_i2v_engine(self) -> None:
        from tests.mocks.mock_engines import MockImage2VideoEngine, _make_test_config

        engine = MockImage2VideoEngine(config=_make_test_config())
        assert callable(engine.initialize)
        assert callable(engine.generate)
        assert callable(engine.cleanup)
