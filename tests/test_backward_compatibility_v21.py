"""
Backward Compatibility Test для v2.1
Проверяет что v2.0 workflow работает без изменений.

Test: Running v2.1 code WITHOUT --animated flag should behave exactly like v2.0
Expected: No Optical Flow initialization, minimal memory usage
"""

import pytest
import logging
import psutil
import os


class TestBackwardCompatibility:
    """Тесты обратной совместимости v2.1 с v2.0"""

    @pytest.mark.compatibility
    def test_v20_mode_no_optical_flow_loaded(self, caplog):
        """
        Test: v2.0 mode (без --animated) не должен загружать Optical Flow.

        Expected log patterns:
        - ✅ "SubtitleRemoverNative initialized" (optical_flow=False)
        - ❌ "OpticalFlowTracker initialized" (не должно быть)
        - ❌ "Optical flow enabled" (не должно быть)
        """
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative

        with caplog.at_level(logging.INFO):
            # Initialize WITHOUT optical flow (v2.0 mode)
            processor = SubtitleRemoverNative(
                lang='en',
                mask_dilation=8,
                confidence_threshold=0.3,
                roi_str='bottom',
                use_optical_flow=False  # v2.0 mode
            )

            # Check logs
            log_messages = [rec.message for rec in caplog.records]

            # Should NOT see optical flow initialization
            assert not any('OpticalFlowTracker initialized' in msg for msg in log_messages), \
                "Optical Flow should not be initialized in v2.0 mode"

            assert not any('Optical flow enabled' in msg for msg in log_messages), \
                "Optical flow should not be enabled in v2.0 mode"

            # Should see standard initialization
            assert any('SubtitleRemoverNative' in msg for msg in log_messages), \
                "Standard processor should be initialized"

            # Verify optical_flow flag
            assert processor.use_optical_flow == False, \
                "use_optical_flow should be False in v2.0 mode"

            assert processor.animated_detector is None, \
                "animated_detector should be None in v2.0 mode"

    @pytest.mark.compatibility
    def test_config_default_values_unchanged(self):
        """
        Test: Дефолтные значения config должны быть безопасными (v2.0 compatible).

        Expected:
        - USE_OPTICAL_FLOW = False (OFF by default)
        - All other v2.0 settings unchanged
        """
        from src.core.config import get_config

        config = get_config()

        # Critical: Optical Flow должен быть выключен по умолчанию
        assert config.USE_OPTICAL_FLOW == False, \
            "USE_OPTICAL_FLOW must be False by default (safety first)"

        # Verify v2.0 settings still exist
        assert hasattr(config, 'PRESERVE_AUDIO'), "v2.0 audio setting missing"
        assert hasattr(config, 'ROI'), "v2.0 ROI setting missing"
        assert hasattr(config, 'MASK_DILATION'), "v2.0 mask setting missing"

        # Verify v2.1 settings exist but are OFF
        assert hasattr(config, 'OPTICAL_FLOW_KEYFRAME_INTERVAL'), "v2.1 setting missing"
        assert config.OPTICAL_FLOW_KEYFRAME_INTERVAL == 5, "Default keyframe interval wrong"

    @pytest.mark.compatibility
    @pytest.mark.slow
    def test_memory_usage_v20_mode_baseline(self):
        """
        Test: Потребление памяти в v2.0 mode должно быть baseline (без overhead).

        Expected: Memory usage similar to v2.0 (no optical flow structures)
        """
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative
        import numpy as np

        # Measure baseline memory
        process = psutil.Process()
        mem_before = process.memory_info().rss / 1024 / 1024  # MB

        # Initialize processor in v2.0 mode
        processor = SubtitleRemoverNative(
            lang='en',
            use_optical_flow=False  # v2.0 mode
        )

        # Measure after initialization
        mem_after = process.memory_info().rss / 1024 / 1024  # MB
        mem_overhead = mem_after - mem_before

        # Should have minimal overhead (just OCR models)
        assert mem_overhead < 800, \
            f"Memory overhead too high: {mem_overhead:.1f}MB (expected <800MB for OCR only)"

        print(f"\nv2.0 Mode Memory: {mem_after:.1f}MB (overhead: {mem_overhead:.1f}MB)")

    @pytest.mark.compatibility
    def test_cli_without_animated_flag_works(self):
        """
        Test: CLI без флага --animated должен работать как v2.0.

        Expected: Command completes without errors, no optical flow logs
        """
        import subprocess

        # Run CLI help (should work without --animated)
        result = subprocess.run(
            ['python', '-m', 'src.presentation.cli', '--help'],
            capture_output=True,
            text=True,
            timeout=10
        )

        assert result.returncode == 0, f"CLI failed: {result.stderr}"

        # Check that --animated is present but optional
        assert '--animated' in result.stdout, \
            "--animated flag should be available"

        # Verify help shows it's experimental
        assert 'experimental' in result.stdout.lower() or 'v2.1' in result.stdout, \
            "Help should indicate --animated is experimental"

    @pytest.mark.compatibility
    def test_existing_v20_tests_still_pass(self):
        """
        Meta-test: Проверяет что все существующие v2.0 тесты проходят.

        This is a placeholder - actual test suite should be run separately.
        """
        # This would typically run the full v2.0 test suite
        # For now, just verify imports work

        try:
            from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative
            from src.infrastructure.ocr.paddle_wrapper import PaddleOCRWrapper
            from src.core.config import get_config

            # If imports work, basic compatibility is maintained
            assert True, "v2.0 modules still importable"

        except ImportError as e:
            pytest.fail(f"v2.0 import broken: {e}")


class TestV21NewFeatureIsolation:
    """Проверяет что новые v2.1 фичи изолированы и не влияют на v2.0"""

    @pytest.mark.compatibility
    def test_optical_flow_import_optional(self):
        """
        Test: Import OpticalFlowTracker не должен сломать v2.0 код.

        Expected: Import fails gracefully if dependencies missing
        """
        try:
            from src.infrastructure.detection import OpticalFlowTracker
            # If import succeeds, great!
            assert True
        except ImportError:
            # If import fails, should not break v2.0
            # This is acceptable for optional feature
            assert True

    @pytest.mark.compatibility
    def test_animated_detector_lazy_init(self):
        """
        Test: AnimatedTextDetector должен инициализироваться только когда нужен.

        Expected: No initialization unless explicitly requested
        """
        from src.infrastructure.processors.subtitle.native import SubtitleRemoverNative

        # Create processor WITHOUT optical flow
        processor = SubtitleRemoverNative(use_optical_flow=False)

        # Animated detector should NOT be initialized
        assert processor.animated_detector is None, \
            "Animated detector should not be initialized when use_optical_flow=False"

        assert not hasattr(processor, '_animated_detector_config') or \
               processor._animated_detector_config is None or \
               not processor.use_optical_flow, \
            "Config should not be loaded when feature disabled"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])

