"""
Global pytest fixtures for the video generation test suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import mock_engines first — _install_diffusers_shim() runs at module level
from tests.mocks.mock_engines import (
    MockText2VideoEngine,
    MockImage2VideoEngine,
    MockUniversalEngine,
)
from tests.mocks.mock_diffusers import mock_export_to_video

from src.services.generation.config import GenerationConfig
from src.services.generation.models import GenJob, GenerationMode


# ── shared tmp dir ────────────────────────────────────────────────────────────

@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    return tmp_path


# ── configs ───────────────────────────────────────────────────────────────────

@pytest.fixture
def gen_config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        TEMP_DIR=str(tmp_path),
        ENABLE_SAFETY_CHECKER=False,
        ENABLE_CPU_OFFLOAD=False,
        ENABLE_VAE_SLICING=False,
        ENABLE_TILING=False,
        USE_XFORMERS=False,
    )


# ── engine fixtures (delay=0 — fast path) ─────────────────────────────────────

@pytest.fixture
def t2v_engine(gen_config: GenerationConfig) -> MockText2VideoEngine:
    engine = MockText2VideoEngine(delay=0.0, config=gen_config)
    engine.initialize()
    return engine


@pytest.fixture
def i2v_engine(gen_config: GenerationConfig) -> MockImage2VideoEngine:
    engine = MockImage2VideoEngine(delay=0.0, config=gen_config)
    engine.initialize()
    return engine


@pytest.fixture
def universal_engine(gen_config: GenerationConfig) -> MockUniversalEngine:
    engine = MockUniversalEngine(delay=0.0, config=gen_config)
    engine.initialize()
    return engine


# ── GenJob factories ──────────────────────────────────────────────────────────

@pytest.fixture
def t2v_job() -> GenJob:
    return GenJob(
        prompts=["Anime girl walking in rain, cinematic"],
        mode=GenerationMode.UNIVERSAL,
        guidance_scale=6.0,
        num_inference_steps=50,
        num_frames=5,
        fps=8,
        output_prefix="test/",
    )


@pytest.fixture
def i2v_job() -> GenJob:
    return GenJob(
        prompts=["Anime girl walking in rain, cinematic"],
        mode=GenerationMode.IMAGE2VIDEO,
        input_images=["https://example.com/ref.png"],
        guidance_scale=6.0,
        num_inference_steps=50,
        num_frames=5,
        fps=8,
        output_prefix="test/",
    )


@pytest.fixture
def batch_t2v_job() -> GenJob:
    return GenJob(
        prompts=[
            "Anime girl walking in rain",
            "Dragon flying over castle at sunset",
            "Cyberpunk city neon lights",
        ],
        mode=GenerationMode.UNIVERSAL,
        num_frames=5,
        fps=8,
        output_prefix="test/batch/",
    )


# ── mock B2 client ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_b2_client() -> MagicMock:
    client = MagicMock()
    client.upload_file.return_value = None
    client.get_presigned_url.return_value = "https://b2.example.com/test/video.mp4"
    return client


@pytest.fixture
def mock_b2_client_failing() -> MagicMock:
    client = MagicMock()
    client.upload_file.side_effect = RuntimeError("B2 connection refused")
    return client


# ── export_to_video patch (used in integration tests) ─────────────────────────

@pytest.fixture(autouse=False)
def patch_export_to_video():
    with patch("diffusers.utils.export_to_video", side_effect=mock_export_to_video):
        yield
