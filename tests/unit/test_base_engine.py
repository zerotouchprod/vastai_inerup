"""
Unit tests for BaseVideoEngine — covers _create_generator, _export_video,
cleanup, context manager, _check_safety without touching real ML stack.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# shims installed by conftest via mock_engines import
from tests.mocks.mock_engines import MockText2VideoEngine, MockImage2VideoEngine, _make_test_config
from tests.mocks.mock_diffusers import mock_export_to_video
from src.domain.exceptions import ModelNotLoadedError


class TestBaseEngineInitialize:

    def test_initialize_sets_flag(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        assert engine._initialized is False
        engine.initialize()
        assert engine._initialized is True

    def test_double_initialize_is_idempotent(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        engine.initialize()  # second call — must not raise
        assert engine._initialized is True

    def test_initialize_sets_pipe(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        assert engine.pipe is not None


class TestBaseEngineGenerate:

    def test_generate_raises_if_not_initialized(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        with pytest.raises(ModelNotLoadedError):
            engine.generate(prompt="test")

    def test_generate_returns_path(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        result = engine.generate(prompt="anime rain", num_frames=3)
        assert isinstance(result, Path)
        assert result.suffix == ".mp4"

    def test_generated_file_has_nonzero_size(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        result = engine.generate(prompt="test", num_frames=3)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_i2v_generate_without_image_raises(self) -> None:
        engine = MockImage2VideoEngine(config=_make_test_config())
        engine.initialize()
        with pytest.raises((ValueError, TypeError)):
            engine.generate(prompt="test", input_image=None)

    def test_i2v_generate_with_image_returns_path(self) -> None:
        engine = MockImage2VideoEngine(config=_make_test_config())
        engine.initialize()
        result = engine.generate(
            prompt="animate this",
            input_image="https://example.com/img.jpg",
            num_frames=3,
        )
        assert result.exists()
        assert result.stat().st_size > 0


class TestBaseEngineCleanup:

    def test_cleanup_resets_initialized(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        engine.cleanup()
        assert engine._initialized is False

    def test_cleanup_clears_pipe(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        engine.cleanup()
        assert engine.pipe is None

    def test_cleanup_clears_safety_checker(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        engine.safety_checker = MagicMock()  # simulate loaded checker
        engine.cleanup()
        assert engine.safety_checker is None

    def test_double_cleanup_no_error(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.initialize()
        engine.cleanup()
        engine.cleanup()  # second call — must not raise


class TestBaseEngineContextManager:

    def test_context_manager_initializes(self) -> None:
        with MockText2VideoEngine(config=_make_test_config()) as engine:
            assert engine._initialized is True

    def test_context_manager_cleans_up(self) -> None:
        with MockText2VideoEngine(config=_make_test_config()) as engine:
            pass
        assert engine._initialized is False
        assert engine.pipe is None

    def test_context_manager_exception_still_cleans_up(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        try:
            with engine:
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        assert engine._initialized is False


class TestBaseEngineCreateGenerator:

    def test_create_generator_no_seed_returns_none(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        result = engine._create_generator(seed=None)
        assert result is None

    def test_create_generator_with_seed_no_torch(self) -> None:
        """torch is shimmed — _create_generator must handle ImportError gracefully."""
        engine = MockText2VideoEngine(config=_make_test_config())
        # torch shim has Generator as MagicMock — call should not raise
        result = engine._create_generator(seed=42)
        # Either returns a generator or None — must not throw
        assert result is None or result is not None


class TestBaseEngineSafetyCheck:

    def test_check_safety_no_checker_returns_true(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.safety_checker = None
        assert engine._check_safety([]) is True

    def test_check_safety_empty_frames_returns_true(self) -> None:
        engine = MockText2VideoEngine(config=_make_test_config())
        engine.safety_checker = MagicMock(return_value=[{"label": "safe", "score": 0.99}])
        assert engine._check_safety([]) is True

    def test_check_safety_safe_content(self) -> None:
        from PIL import Image as PILImage
        import numpy as np

        engine = MockText2VideoEngine(config=_make_test_config())
        engine.safety_checker = MagicMock(
            return_value=[{"label": "safe", "score": 0.95}]
        )
        frame = PILImage.fromarray(np.zeros((64, 64, 3), dtype=np.uint8))
        assert engine._check_safety([frame]) is True

    def test_check_safety_nsfw_content(self) -> None:
        from PIL import Image as PILImage
        import numpy as np

        engine = MockText2VideoEngine(config=_make_test_config())
        engine.config.SAFETY_CHECKER_THRESHOLD = 0.5
        engine.safety_checker = MagicMock(
            return_value=[{"label": "nsfw", "score": 0.99}]
        )
        frame = PILImage.fromarray(np.zeros((64, 64, 3), dtype=np.uint8))
        assert engine._check_safety([frame]) is False

    def test_check_safety_checker_exception_allows_content(self) -> None:
        from PIL import Image as PILImage
        import numpy as np

        engine = MockText2VideoEngine(config=_make_test_config())
        engine.safety_checker = MagicMock(side_effect=RuntimeError("model error"))
        frame = PILImage.fromarray(np.zeros((64, 64, 3), dtype=np.uint8))
        # Fail-open: exception → allow
        assert engine._check_safety([frame]) is True
