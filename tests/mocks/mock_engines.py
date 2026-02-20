"""
Mock engine implementations — no GPU, no real model weights.

Each mock patches the underlying pipeline at construction time so that
BaseVideoEngine._export_video writes a real MP4 via imageio.
All mocks accept a `delay` param for timing tests (pytest.mark.parametrize).
"""

from __future__ import annotations

import sys
import time
import types
import tempfile
from pathlib import Path
from typing import Any, Optional, cast
from unittest.mock import patch, MagicMock



# ---------------------------------------------------------------------------
# Inject fake diffusers / torch into sys.modules BEFORE any engine import.
# This prevents ImportError on machines without GPU stack.
# ---------------------------------------------------------------------------

def _install_diffusers_shim() -> None:
    """Insert minimal diffusers + torch stubs into sys.modules if absent."""
    if "diffusers" not in sys.modules:
        diffusers = types.ModuleType("diffusers")
        diffusers.CogVideoXPipeline = None          # replaced per-test
        diffusers.CogVideoXImageToVideoPipeline = None
        diffusers.DiffusionPipeline = None

        utils = types.ModuleType("diffusers.utils")
        utils.export_to_video = None                # replaced per-test
        diffusers.utils = utils

        sys.modules["diffusers"] = diffusers
        sys.modules["diffusers.utils"] = utils

    if "torch" not in sys.modules:
        torch = types.ModuleType("torch")
        torch.bfloat16 = "bfloat16"
        torch.float32 = "float32"
        torch.cuda = MagicMock()
        torch.cuda.is_available = lambda: False
        torch.Generator = MagicMock
        sys.modules["torch"] = torch

    if "transformers" not in sys.modules:
        transformers = types.ModuleType("transformers")
        transformers.pipeline = MagicMock()
        sys.modules["transformers"] = transformers

    if "xformers" not in sys.modules:
        sys.modules["xformers"] = types.ModuleType("xformers")


_install_diffusers_shim()


# ---------------------------------------------------------------------------
# Import engines AFTER shims are in place
# ---------------------------------------------------------------------------
from src.services.generation.config import GenerationConfig  # noqa: E402
from src.services.generation.engines.base import BaseVideoEngine  # noqa: E402
from tests.mocks.mock_diffusers import (  # noqa: E402
    MockCogVideoXPipeline,
    MockCogVideoXImageToVideoPipeline,
    MockDiffusionPipeline,
    mock_export_to_video,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_test_config() -> GenerationConfig:
    tmp = tempfile.mkdtemp()
    return GenerationConfig(
        TEMP_DIR=tmp,
        ENABLE_SAFETY_CHECKER=False,
        ENABLE_CPU_OFFLOAD=False,
        ENABLE_VAE_SLICING=False,
        ENABLE_TILING=False,
        USE_XFORMERS=False,
        MODEL_LOAD_TIMEOUT=10,
        GENERATION_TIMEOUT=30,
    )


# ---------------------------------------------------------------------------
# MockText2VideoEngine
# ---------------------------------------------------------------------------

class MockText2VideoEngine(BaseVideoEngine):
    """
    T2V engine backed by MockCogVideoXPipeline.

    Generates a real 5-frame MP4 without any GPU.
    Accepts `delay` to simulate inference time.
    """

    def __init__(self, delay: float = 0.0, config: Optional[GenerationConfig] = None) -> None:
        super().__init__(config or _make_test_config())
        self._delay = delay
        self._call_count = 0

    def initialize(self) -> None:
        self.pipe = MockCogVideoXPipeline(delay=self._delay)
        self._initialized = True

    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        fps: int = 8,
        **kwargs: Any,
    ) -> Path:
        from src.domain.exceptions import ModelNotLoadedError

        if not self._initialized:
            raise ModelNotLoadedError("MockText2VideoEngine not initialized")

        if self._delay > 0:
            time.sleep(self._delay)

        self._call_count += 1
        n_frames = num_frames or self.config.DEFAULT_NUM_FRAMES

        output = self.pipe(
            prompt=prompt,
            num_frames=n_frames,
            fps=fps,
        )
        frames = output.frames[0]

        with patch("diffusers.utils.export_to_video", side_effect=mock_export_to_video):
            return self._export_video(frames, prefix="t2v_mock", fps=fps)


# ---------------------------------------------------------------------------
# MockImage2VideoEngine
# ---------------------------------------------------------------------------

class MockImage2VideoEngine(BaseVideoEngine):
    """
    I2V engine backed by MockCogVideoXImageToVideoPipeline.

    Accepts `input_image` (ignored — fake frames always generated).
    """

    def __init__(self, delay: float = 0.0, config: Optional[GenerationConfig] = None) -> None:
        super().__init__(config or _make_test_config())
        self._delay = delay
        self._call_count = 0
        self._last_input_image: Optional[str] = None

    def initialize(self) -> None:
        self.pipe = MockCogVideoXImageToVideoPipeline(delay=self._delay)
        self._initialized = True

    def generate(
        self,
        prompt: str,
        input_image: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        fps: int = 8,
        **kwargs: Any,
    ) -> Path:
        from src.domain.exceptions import ModelNotLoadedError

        if not self._initialized:
            raise ModelNotLoadedError("MockImage2VideoEngine not initialized")

        if not input_image:
            raise ValueError("input_image is required for I2V engine")

        if self._delay > 0:
            time.sleep(self._delay)

        self._call_count += 1
        self._last_input_image = input_image
        n_frames = num_frames or self.config.DEFAULT_NUM_FRAMES

        output = self.pipe(
            prompt=prompt,
            image=input_image,
            num_frames=n_frames,
            fps=fps,
        )
        frames = output.frames[0]

        with patch("diffusers.utils.export_to_video", side_effect=mock_export_to_video):
            return self._export_video(frames, prefix="i2v_mock", fps=fps)


# ---------------------------------------------------------------------------
# MockUniversalEngine  (T2I → I2V two-stage)
# ---------------------------------------------------------------------------

class MockUniversalEngine(BaseVideoEngine):
    """
    UNIVERSAL mode: T2I (DiffusionPipeline) → I2V (CogVideoXImageToVideoPipeline).

    Tracks call counts for both stages so tests can assert ordering.
    """

    def __init__(self, delay: float = 0.0, config: Optional[GenerationConfig] = None) -> None:
        super().__init__(config or _make_test_config())
        self._delay = delay
        self.t2i_call_count = 0
        self.i2v_call_count = 0
        # Assigned in initialize() — use cast to silence static analysis
        self._t2i_pipe: MockDiffusionPipeline
        self._i2v_pipe: MockCogVideoXImageToVideoPipeline

    def initialize(self) -> None:
        self._t2i_pipe = MockDiffusionPipeline(delay=self._delay)
        self._i2v_pipe = MockCogVideoXImageToVideoPipeline(delay=self._delay)
        self._initialized = True

    def generate(
        self,
        prompt: str,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        guidance_scale: Optional[float] = None,
        num_inference_steps: Optional[int] = None,
        num_frames: Optional[int] = None,
        fps: int = 8,
        **kwargs: Any,
    ) -> Path:
        from src.domain.exceptions import ModelNotLoadedError

        if not self._initialized:
            raise ModelNotLoadedError("MockUniversalEngine not initialized")

        if self._delay > 0:
            time.sleep(self._delay)

        # Stage 1 — T2I: generate reference image
        t2i_pipe = cast(MockDiffusionPipeline, self._t2i_pipe)
        self.t2i_call_count += 1
        t2i_out = t2i_pipe(prompt=prompt)
        reference_image = t2i_out.images[0]

        # Stage 2 — I2V: animate reference image
        self.i2v_call_count += 1
        n_frames = num_frames or self.config.DEFAULT_NUM_FRAMES
        i2v_pipe: MockCogVideoXImageToVideoPipeline = self._i2v_pipe  # type: ignore[assignment]

        i2v_out = i2v_pipe(
            prompt=prompt,
            image=reference_image,
            num_frames=n_frames,
            fps=fps,
        )
        frames = i2v_out.frames[0]

        with patch("diffusers.utils.export_to_video", side_effect=mock_export_to_video):
            return self._export_video(frames, prefix="universal_mock", fps=fps)
