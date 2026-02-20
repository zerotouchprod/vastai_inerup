"""
Unit tests for GenerationResult and BatchGenerationResult edge cases.
Separated for focused coverage on result tracking logic.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.services.generation.models import (
    BatchGenerationResult,
    GenerationMode,
    GenerationResult,
)


class TestGenerationResultFields:

    def test_url_and_local_path_optional(self) -> None:
        r = GenerationResult(
            job_id="j42",
            prompt_index=0,
            prompt="cinematic rain",
            mode=GenerationMode.UNIVERSAL,
            output_key="out/video.mp4",
        )
        assert r.url is None
        assert r.local_path is None
        assert r.size_bytes is None
        assert r.num_frames is None

    def test_with_all_fields(self, tmp_path: Path) -> None:
        video = tmp_path / "vid.mp4"
        video.write_bytes(b"\x00" * 1024)

        r = GenerationResult(
            job_id="j1",
            prompt_index=1,
            prompt="test",
            mode=GenerationMode.IMAGE2VIDEO,
            output_key="out/i2v.mp4",
            url="https://cdn.example.com/vid.mp4",
            local_path=video,
            size_bytes=1024,
            num_frames=5,
            success=True,
        )
        assert r.size_bytes == 1024
        assert r.num_frames == 5
        assert r.url.startswith("https://")

    def test_error_field_on_failure(self) -> None:
        r = GenerationResult(
            job_id="j1",
            prompt_index=0,
            prompt="test",
            mode=GenerationMode.UNIVERSAL,
            output_key="out/fail.mp4",
            success=False,
            error="CUDA out of memory",
        )
        assert "CUDA" in r.error

    def test_mode_image2video(self) -> None:
        r = GenerationResult(
            job_id="j1",
            prompt_index=0,
            prompt="animate",
            mode=GenerationMode.IMAGE2VIDEO,
            output_key="out/i2v.mp4",
        )
        assert r.mode == GenerationMode.IMAGE2VIDEO


class TestBatchGenerationResultTracking:

    def _make_result(self, index: int, success: bool = True) -> GenerationResult:
        return GenerationResult(
            job_id="batch1",
            prompt_index=index,
            prompt=f"prompt {index}",
            mode=GenerationMode.UNIVERSAL,
            output_key=f"out/video_{index}.mp4",
            success=success,
            error=None if success else "error",
        )

    def test_results_list_aggregation(self) -> None:
        b = BatchGenerationResult(
            job_id="batch1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=3,
            successful=2,
            failed=1,
            results=[
                self._make_result(0),
                self._make_result(1),
                self._make_result(2, success=False),
            ],
        )
        assert len(b.results) == 3
        assert sum(1 for r in b.results if r.success) == 2

    def test_zero_duration_when_same_timestamp(self) -> None:
        now = datetime.now(timezone.utc)
        b = BatchGenerationResult(
            job_id="b1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=1,
            started_at=now,
            completed_at=now,
        )
        assert b.duration_seconds == pytest.approx(0.0, abs=0.01)

    def test_duration_with_large_delta(self) -> None:
        start = datetime.now(timezone.utc)
        b = BatchGenerationResult(
            job_id="b1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=1,
        )
        b.started_at = start
        b.completed_at = start + timedelta(minutes=5)
        assert b.duration_seconds == pytest.approx(300.0, abs=0.5)

    def test_empty_results_list_by_default(self) -> None:
        b = BatchGenerationResult(
            job_id="b1",
            mode=GenerationMode.UNIVERSAL,
            total_prompts=0,
        )
        assert b.results == []
