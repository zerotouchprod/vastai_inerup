"""
Standalone mocks for diffusers/torch heavy models.

Generates real 3-5 frame MP4 files via imageio+imageio-ffmpeg — no GPU, no model weights.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_video(path: str, frames: list[np.ndarray], fps: int = 8) -> None:
    """Write numpy RGB frames to MP4 using imageio-ffmpeg backend."""
    import imageio

    writer = imageio.get_writer(path, fps=fps, macro_block_size=None)
    for frame in frames:
        writer.append_data(frame)
    writer.close()


def _write_fake_video(num_frames: int = 5, fps: int = 8, delay: float = 0.0) -> Path:
    """Write a minimal real MP4 with random RGB frames and return its path."""
    if delay > 0:
        time.sleep(delay)

    out = Path(tempfile.gettempdir()) / f"fake_{uuid.uuid4().hex[:8]}.mp4"
    rng = np.random.default_rng(seed=42)
    frames = [
        rng.integers(0, 255, (480, 720, 3), dtype=np.uint8)
        for _ in range(num_frames)
    ]
    _write_video(str(out), frames, fps=fps)
    return out


def _make_fake_pil_image(delay: float = 0.0):
    """Return a minimal PIL Image for I2V input."""
    from PIL import Image as PILImage

    if delay > 0:
        time.sleep(delay)

    arr = np.zeros((480, 720, 3), dtype=np.uint8)
    arr[100:380, 100:620] = [30, 144, 255]
    return PILImage.fromarray(arr)


# ---------------------------------------------------------------------------
# Pipeline call results
# ---------------------------------------------------------------------------

class FakePipelineOutput:
    """Mimics diffusers pipeline output: .frames = [[pil, pil, ...]]"""

    def __init__(self, frames: list[Any]) -> None:
        self.frames = [frames]


# ---------------------------------------------------------------------------
# CogVideoXPipeline mock (Text-to-Video)
# ---------------------------------------------------------------------------

class MockCogVideoXPipeline:
    """Drop-in for diffusers.CogVideoXPipeline — no weights, no GPU."""

    def __init__(self, delay: float = 0.0, num_frames: int = 5) -> None:
        self._delay = delay
        self._num_frames = num_frames
        self.scheduler = MagicMock()
        self.unet = MagicMock()
        self.vae = MagicMock()
        self.text_encoder = MagicMock()

    @classmethod
    def from_pretrained(cls, *args: Any, delay: float = 0.0, **kwargs: Any) -> "MockCogVideoXPipeline":
        return cls(delay=delay)

    def enable_model_cpu_offload(self) -> None: ...
    def enable_vae_slicing(self) -> None: ...
    def enable_tiling(self) -> None: ...
    def enable_xformers_memory_efficient_attention(self) -> None: ...

    def __call__(self, prompt: str, num_frames: int = 5, fps: int = 8, **kwargs: Any) -> FakePipelineOutput:
        from PIL import Image as PILImage

        if self._delay > 0:
            time.sleep(self._delay)

        rng = np.random.default_rng(seed=0)
        n = num_frames or self._num_frames
        frames = [
            PILImage.fromarray(rng.integers(0, 255, (480, 720, 3), dtype=np.uint8))
            for _ in range(n)
        ]
        return FakePipelineOutput(frames)


# ---------------------------------------------------------------------------
# CogVideoXImageToVideoPipeline mock (Image-to-Video)
# ---------------------------------------------------------------------------

class MockCogVideoXImageToVideoPipeline(MockCogVideoXPipeline):
    """Drop-in for diffusers.CogVideoXImageToVideoPipeline."""

    @classmethod
    def from_pretrained(cls, *args: Any, delay: float = 0.0, **kwargs: Any) -> "MockCogVideoXImageToVideoPipeline":
        return cls(delay=delay)

    def __call__(self, prompt: str, image: Any = None, num_frames: int = 5, fps: int = 8, **kwargs: Any) -> FakePipelineOutput:
        return super().__call__(prompt=prompt, num_frames=num_frames, fps=fps, **kwargs)


# ---------------------------------------------------------------------------
# DiffusionPipeline mock (SDXL T2I stage for UNIVERSAL mode)
# ---------------------------------------------------------------------------

class MockDiffusionPipeline:
    """Drop-in for diffusers.DiffusionPipeline (T2I step)."""

    def __init__(self, delay: float = 0.0) -> None:
        self._delay = delay
        self.scheduler = MagicMock()
        self.unet = MagicMock()

    @classmethod
    def from_pretrained(cls, *args: Any, delay: float = 0.0, **kwargs: Any) -> "MockDiffusionPipeline":
        return cls(delay=delay)

    def enable_model_cpu_offload(self) -> None: ...
    def to(self, *args: Any, **kwargs: Any) -> "MockDiffusionPipeline":
        return self

    def __call__(self, prompt: str, **kwargs: Any) -> Any:
        if self._delay > 0:
            time.sleep(self._delay)
        output = MagicMock()
        output.images = [_make_fake_pil_image()]
        return output


# ---------------------------------------------------------------------------
# export_to_video mock  (diffusers.utils)
# ---------------------------------------------------------------------------

def mock_export_to_video(frames: list[Any], output_video_path: str, fps: int = 8) -> str:
    """Write PIL/ndarray frames to a real MP4 via imageio-ffmpeg."""
    from PIL import Image as PILImage

    np_frames = []
    for f in frames:
        if isinstance(f, PILImage.Image):
            np_frames.append(np.array(f.convert("RGB")))
        elif isinstance(f, np.ndarray):
            np_frames.append(f)
        else:
            np_frames.append(np.zeros((480, 720, 3), dtype=np.uint8))

    _write_video(output_video_path, np_frames, fps=fps)
    return output_video_path
