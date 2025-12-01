"""
Tests for pipeline_v2.py entry point.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from io import StringIO

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


class TestPipelineV2EntryPoint:
    """Test pipeline_v2.py entry point."""

    def test_imports_successfully(self):
        """Test that pipeline_v2.py can be imported without errors."""
        import pipeline_v2
        assert pipeline_v2 is not None

    def test_has_main_function(self):
        """Test that main function is imported from presentation.cli."""
        from presentation.cli import main
        assert callable(main)

    def test_path_setup(self):
        """Test that src directory is added to sys.path."""
        import pipeline_v2

        # pipeline_v2.py should add src to path
        src_path = str(Path(__file__).parent.parent.parent / "src")

        # Check that some src path is in sys.path
        # (exact path may vary due to normalization)
        has_src = any('src' in p for p in sys.path)
        assert has_src, "src directory should be in sys.path"


class TestCLIMain:
    """Test presentation.cli.main() function."""

    @pytest.fixture
    def mock_config(self):
        """Create mock config object."""
        config = Mock()
        config.input_url = "https://example.com/video.mp4"
        config.mode = "upscale"
        config.scale = 2.0
        config.target_fps = None
        config.interp_factor = 1.0
        config.prefer = "auto"
        config.strategy = "interp-then-upscale"
        config.strict = False
        config.job_id = "test_job_123"
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.temp_dir = Path("/tmp")
        return config

    @pytest.fixture
    def mock_result_success(self):
        """Create mock successful ProcessingResult."""
        from domain.models import ProcessingResult
        result = ProcessingResult(
            success=True,
            output_path=Path("/tmp/output.mp4"),
            frames_processed=100,
            duration_seconds=10.5,
            metrics={'total_time': 10.5}
        )
        return result

    @pytest.fixture
    def mock_result_failure(self):
        """Create mock failed ProcessingResult."""
        from domain.models import ProcessingResult
        result = ProcessingResult(
            success=False,
            output_path=None,
            frames_processed=0,
            duration_seconds=0.0,
            errors=["Test error"]
        )
        return result

    @patch('presentation.cli.create_orchestrator_from_config')
    @patch('presentation.cli.ConfigLoader')
    @patch('sys.argv', ['pipeline_v2.py', '--input', 'https://example.com/video.mp4', '--mode', 'upscale'])
    def test_main_success(self, mock_config_loader_class, mock_create_orchestrator, mock_config, mock_result_success):
        """Test successful pipeline execution."""
        from presentation.cli import main

        # Setup mocks
        mock_loader = Mock()
        mock_loader.load.return_value = mock_config
        mock_config_loader_class.return_value = mock_loader

        mock_orchestrator = Mock()
        mock_orchestrator.process.return_value = mock_result_success
        mock_create_orchestrator.return_value = mock_orchestrator

        # Run main
        exit_code = main()

        # Assertions
        assert exit_code == 0
        mock_loader.load.assert_called_once()
        mock_orchestrator.process.assert_called_once()

    @patch('presentation.cli.create_orchestrator_from_config')
    @patch('presentation.cli.ConfigLoader')
    @patch('sys.argv', ['pipeline_v2.py', '--input', 'https://example.com/video.mp4', '--mode', 'upscale'])
    def test_main_failure(self, mock_config_loader_class, mock_create_orchestrator, mock_config, mock_result_failure):
        """Test failed pipeline execution."""
        from presentation.cli import main

        # Setup mocks
        mock_loader = Mock()
        mock_loader.load.return_value = mock_config
        mock_config_loader_class.return_value = mock_loader

        mock_orchestrator = Mock()
        mock_orchestrator.process.return_value = mock_result_failure
        mock_create_orchestrator.return_value = mock_orchestrator

        # Run main
        exit_code = main()

        # Assertions
        assert exit_code == 1
        mock_orchestrator.process.assert_called_once()

    @patch('presentation.cli.ConfigLoader')
    @patch('sys.argv', ['pipeline_v2.py', '--input', 'https://example.com/video.mp4'])
    def test_main_domain_exception(self, mock_config_loader_class):
        """Test handling of DomainException."""
        from presentation.cli import main
        from domain.exceptions import DomainException

        # Setup mock to raise exception
        mock_loader = Mock()
        mock_loader.load.side_effect = DomainException("Test error")
        mock_config_loader_class.return_value = mock_loader

        # Run main
        exit_code = main()

        # Should return 1 on error
        assert exit_code == 1

    @patch('sys.argv', ['pipeline_v2.py', '--input', 'test.mp4', '--output', '/tmp/output', '--mode', 'upscale', '--scale', '2', '--target-fps', '60', '--prefer', 'pytorch', '--strict', '--verbose'])
    @patch('presentation.cli.ConfigLoader')
    @patch('presentation.cli.create_orchestrator_from_config')
    def test_cli_arguments_parsed(self, mock_create_orchestrator, mock_config_loader_class, mock_config, mock_result_success):
        """Test that CLI arguments are correctly parsed and applied to config."""
        from presentation.cli import main

        # Setup mocks
        mock_loader = Mock()
        mock_loader.load.return_value = mock_config
        mock_config_loader_class.return_value = mock_loader

        mock_orchestrator = Mock()
        mock_orchestrator.process.return_value = mock_result_success
        mock_create_orchestrator.return_value = mock_orchestrator

        # Run main
        exit_code = main()

        # Check that config was modified with CLI args
        assert mock_config.input_url == 'test.mp4'
        assert mock_config.output_dir == Path('/tmp/output')
        assert mock_config.mode == 'upscale'
        assert mock_config.scale == 2.0
        assert mock_config.target_fps == 60
        assert mock_config.prefer == 'pytorch'
        assert mock_config.strict is True

        assert exit_code == 0

    @patch('sys.argv', ['pipeline_v2.py', '--help'])
    def test_help_argument(self):
        """Test --help argument."""
        from presentation.cli import main

        # --help should raise SystemExit
        with pytest.raises(SystemExit) as exc_info:
            main()

        # Should exit with 0 (help message shown)
        assert exc_info.value.code == 0

    @patch('sys.argv', ['pipeline_v2.py'])
    def test_no_arguments_uses_defaults(self):
        """Test that pipeline uses config defaults when no CLI arguments provided."""
        from presentation.cli import main

        # Should load config.yaml and fail because no input_url
        # Returns exit code 1 (error) instead of raising
        exit_code = main()

        # Should fail gracefully with exit code 1
        assert exit_code == 1


class TestCreateOrchestratorFromConfig:
    """Test create_orchestrator_from_config factory function."""

    @pytest.fixture
    def minimal_config(self):
        """Create minimal config."""
        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "upscale"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")
        return config

    def test_creates_orchestrator_without_b2(self, minimal_config):
        """Test creating orchestrator without B2 credentials."""
        from presentation.cli import create_orchestrator_from_config

        orchestrator = create_orchestrator_from_config(minimal_config)

        assert orchestrator is not None
        assert orchestrator._downloader is not None
        assert orchestrator._extractor is not None
        assert orchestrator._assembler is not None
        assert orchestrator._uploader is not None  # Dummy uploader

    def test_creates_orchestrator_with_b2(self):
        """Test creating orchestrator with B2 credentials."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = "test-bucket"
        config.b2_key = "test-key"
        config.b2_secret = "test-secret"
        config.b2_endpoint = "https://s3.us-west-004.backblazeb2.com"
        config.mode = "upscale"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")

        orchestrator = create_orchestrator_from_config(config)

        assert orchestrator is not None
        # B2S3Uploader should be created (not dummy)

    def test_creates_upscaler_when_mode_upscale(self):
        """Test that upscaler is created when mode is 'upscale'."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "upscale"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")

        with patch('presentation.cli.ProcessorFactory') as mock_factory_class:
            mock_factory = Mock()
            mock_factory_class.return_value = mock_factory
            mock_factory.create_upscaler.return_value = Mock()
            mock_factory.create_interpolator.return_value = None

            orchestrator = create_orchestrator_from_config(config)

            # Should call create_upscaler
            mock_factory.create_upscaler.assert_called_once()

    def test_creates_interpolator_when_mode_interp(self):
        """Test that interpolator is created when mode is 'interp'."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "interp"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")

        with patch('presentation.cli.ProcessorFactory') as mock_factory_class:
            mock_factory = Mock()
            mock_factory_class.return_value = mock_factory
            mock_factory.create_upscaler.return_value = None
            mock_factory.create_interpolator.return_value = Mock()

            orchestrator = create_orchestrator_from_config(config)

            # Should call create_interpolator
            mock_factory.create_interpolator.assert_called_once()

    def test_creates_both_processors_when_mode_both(self):
        """Test that both processors are created when mode is 'both'."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "both"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")

        with patch('presentation.cli.ProcessorFactory') as mock_factory_class:
            mock_factory = Mock()
            mock_factory_class.return_value = mock_factory
            mock_factory.create_upscaler.return_value = Mock()
            mock_factory.create_interpolator.return_value = Mock()

            orchestrator = create_orchestrator_from_config(config)

            # Should call both
            mock_factory.create_upscaler.assert_called_once()
            mock_factory.create_interpolator.assert_called_once()

    def test_handles_processor_creation_failure_non_strict(self):
        """Test that processor creation failure is handled in non-strict mode."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "upscale"
        config.prefer = "auto"
        config.strict = False
        config.temp_dir = Path("/tmp")

        with patch('presentation.cli.ProcessorFactory') as mock_factory_class:
            mock_factory = Mock()
            mock_factory_class.return_value = mock_factory
            mock_factory.create_upscaler.side_effect = Exception("GPU not available")

            # Should not raise in non-strict mode
            orchestrator = create_orchestrator_from_config(config)
            assert orchestrator is not None

    def test_raises_processor_creation_failure_strict(self):
        """Test that processor creation failure raises in strict mode."""
        from presentation.cli import create_orchestrator_from_config

        config = Mock()
        config.b2_bucket = None
        config.b2_key = None
        config.b2_secret = None
        config.mode = "upscale"
        config.prefer = "auto"
        config.strict = True
        config.temp_dir = Path("/tmp")

        with patch('presentation.cli.ProcessorFactory') as mock_factory_class:
            mock_factory = Mock()
            mock_factory_class.return_value = mock_factory
            mock_factory.create_upscaler.side_effect = Exception("GPU not available")

            # Should raise in strict mode
            with pytest.raises(Exception):
                create_orchestrator_from_config(config)


class TestPipelineV2Integration:
    """Integration tests for pipeline_v2.py (if dependencies available)."""

    @pytest.mark.skipif(
        not Path('tests/video/test.mp4').exists(),
        reason="Test video not available"
    )
    def test_pipeline_with_test_video(self):
        """Integration test with real test video."""
        # This would be a full integration test
        # Skipped if test video not available
        pass


class TestSuccessMarker:
    """Test that success marker is printed correctly."""

    @patch('presentation.cli.create_orchestrator_from_config')
    @patch('presentation.cli.ConfigLoader')
    @patch('sys.argv', ['pipeline_v2.py', '--input', 'test.mp4'])
    @patch('sys.stdout', new_callable=StringIO)
    def test_success_marker_printed(self, mock_stdout, mock_config_loader_class, mock_create_orchestrator):
        """Test that VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY marker is printed on success."""
        from presentation.cli import main
        from domain.models import ProcessingResult

        # Setup mocks
        mock_config = Mock()
        mock_config.input_url = "test.mp4"
        mock_config.mode = "upscale"
        mock_config.scale = 2.0
        mock_config.target_fps = None
        mock_config.interp_factor = 1.0
        mock_config.prefer = "auto"
        mock_config.strategy = "interp-then-upscale"
        mock_config.strict = False
        mock_config.job_id = "test"
        mock_config.b2_bucket = None
        mock_config.b2_key = None
        mock_config.b2_secret = None
        mock_config.temp_dir = Path("/tmp")

        mock_loader = Mock()
        mock_loader.load.return_value = mock_config
        mock_config_loader_class.return_value = mock_loader

        mock_result = ProcessingResult(
            success=True,
            output_path=Path("/tmp/output.mp4"),
            frames_processed=100,
            duration_seconds=10.0,
            metrics={}
        )

        mock_orchestrator = Mock()
        mock_orchestrator.process.return_value = mock_result
        mock_create_orchestrator.return_value = mock_orchestrator

        # Run main
        exit_code = main()

        # Check output
        output = mock_stdout.getvalue()
        assert "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY" in output
        assert exit_code == 0


# Run tests
if __name__ == '__main__':
    pytest.main([__file__, '-v'])

