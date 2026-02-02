"""
Integration tests for Text-to-Video workflow.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.services.generation.models import GenJob, GenerationMode, BatchGenerationResult
from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.config import GenerationConfig


@pytest.fixture
def config():
    """Create test configuration."""
    return GenerationConfig()


@pytest.fixture
def mock_b2_client():
    """Create mock B2 client."""
    client = Mock()
    client.upload_file = Mock()
    client.get_presigned_url = Mock(return_value="https://fake.url/video.mp4")
    return client


@pytest.fixture
def mock_engine():
    """Create mock engine."""
    engine = Mock()
    engine.initialize = Mock()
    engine.generate = Mock(return_value=Path("/tmp/fake_video.mp4"))
    engine.cleanup = Mock()
    return engine


def test_text2video_workflow_single_prompt(config, mock_b2_client, mock_engine):
    """Test T2V workflow with single prompt."""
    # Create job
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["A cat dancing"]
    )

    # Create orchestrator with mocks
    orchestrator = GenerationOrchestrator(config=config, b2_client=mock_b2_client)

    # Mock engine selection
    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        # Mock file operations
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 1024 * 1024  # 1MB

            with patch('pathlib.Path.unlink'):
                # Process job
                result = orchestrator.process_job(job)

    # Assertions
    assert isinstance(result, BatchGenerationResult)
    assert result.job_id == job.id
    assert result.mode == GenerationMode.TEXT2VIDEO
    assert result.total_prompts == 1
    assert result.successful == 1
    assert result.failed == 0
    assert len(result.results) == 1

    # Check that engine was initialized
    mock_engine.initialize.assert_called_once()

    # Check that generate was called
    mock_engine.generate.assert_called_once()

    # Check that B2 upload was called
    mock_b2_client.upload_file.assert_called_once()


def test_text2video_workflow_multiple_prompts(config, mock_b2_client, mock_engine):
    """Test T2V workflow with multiple prompts."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["Prompt 1", "Prompt 2", "Prompt 3"]
    )

    orchestrator = GenerationOrchestrator(config=config, b2_client=mock_b2_client)

    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 2 * 1024 * 1024
            with patch('pathlib.Path.unlink'):
                result = orchestrator.process_job(job)

    assert result.total_prompts == 3
    assert result.successful == 3
    assert len(result.results) == 3
    assert mock_engine.generate.call_count == 3
    assert mock_b2_client.upload_file.call_count == 3


def test_text2video_workflow_without_b2(config, mock_engine):
    """Test T2V workflow without B2 upload."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["Test prompt"]
    )

    # No B2 client
    orchestrator = GenerationOrchestrator(config=config, b2_client=None)

    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 1024 * 1024
            with patch('pathlib.Path.unlink'):
                result = orchestrator.process_job(job)

    assert result.successful == 1
    # URL should be file:// since no B2
    assert result.results[0].url.startswith("file://")


def test_text2video_workflow_generation_failure(config, mock_b2_client, mock_engine):
    """Test T2V workflow when generation fails."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["Bad prompt"]
    )

    # Make engine raise exception
    mock_engine.generate.side_effect = Exception("Generation failed")

    orchestrator = GenerationOrchestrator(config=config, b2_client=mock_b2_client)

    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        result = orchestrator.process_job(job)

    assert result.total_prompts == 1
    assert result.successful == 0
    assert result.failed == 1
    assert result.results[0].success is False
    assert "Generation failed" in result.results[0].error


def test_text2video_workflow_partial_failure(config, mock_b2_client, mock_engine):
    """Test T2V workflow with partial failures."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["Good prompt", "Bad prompt", "Another good prompt"]
    )

    # Make second call fail
    mock_engine.generate.side_effect = [
        Path("/tmp/video1.mp4"),
        Exception("Failed"),
        Path("/tmp/video3.mp4")
    ]

    orchestrator = GenerationOrchestrator(config=config, b2_client=mock_b2_client)

    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 1024 * 1024
            with patch('pathlib.Path.unlink'):
                result = orchestrator.process_job(job)

    assert result.total_prompts == 3
    assert result.successful == 2
    assert result.failed == 1

    # Check individual results
    assert result.results[0].success is True
    assert result.results[1].success is False
    assert result.results[2].success is True


def test_text2video_workflow_with_custom_parameters(config, mock_b2_client, mock_engine):
    """Test T2V workflow with custom generation parameters."""
    job = GenJob(
        mode=GenerationMode.TEXT2VIDEO,
        prompts=["Custom prompt"],
        negative_prompt="bad quality",
        seed=42,
        guidance_scale=7.5,
        num_inference_steps=30,
        num_frames=25
    )

    orchestrator = GenerationOrchestrator(config=config, b2_client=mock_b2_client)

    with patch.object(orchestrator, '_get_engine', return_value=mock_engine):
        with patch('pathlib.Path.stat') as mock_stat:
            mock_stat.return_value.st_size = 1024 * 1024
            with patch('pathlib.Path.unlink'):
                result = orchestrator.process_job(job)

    # Check that parameters were passed to engine
    call_kwargs = mock_engine.generate.call_args[1]
    assert call_kwargs['negative_prompt'] == "bad quality"
    assert call_kwargs['seed'] == 42
    assert call_kwargs['guidance_scale'] == 7.5
    assert call_kwargs['num_inference_steps'] == 30
    assert call_kwargs['num_frames'] == 25


@pytest.mark.skip(reason="Phase 2 - I2V not implemented yet")
def test_image2video_workflow_not_implemented(config):
    """Test that I2V mode raises NotImplementedError."""
    job = GenJob(
        mode=GenerationMode.IMAGE2VIDEO,
        prompts=["Animate this"],
        input_images=["https://example.com/image.jpg"]
    )

    orchestrator = GenerationOrchestrator(config=config)

    with pytest.raises(NotImplementedError, match="Phase 2"):
        orchestrator.process_job(job)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
