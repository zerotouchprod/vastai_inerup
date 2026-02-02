"""
Integration tests for Image-to-Video workflow.
"""

import pytest
from unittest.mock import MagicMock, patch
from PIL import Image
from io import BytesIO
import base64

from src.services.generation.orchestrator import GenerationOrchestrator
from src.services.generation.models import GenJob, GenerationMode


@pytest.fixture
def mock_cogvideo_i2v_pipeline():
    """Mock CogVideoX I2V pipeline."""
    with patch('diffusers.CogVideoXImageToVideoPipeline') as mock_cls:
        mock_pipe = MagicMock()

        # Mock generation
        def mock_call(*args, **kwargs):
            import numpy as np
            frames = [np.zeros((480, 720, 3), dtype=np.uint8) for _ in range(49)]
            return MagicMock(frames=[frames])

        mock_pipe.__call__ = mock_call
        mock_pipe.enable_model_cpu_offload = MagicMock()
        mock_pipe.enable_vae_slicing = MagicMock()
        mock_pipe.enable_tiling = MagicMock()
        mock_pipe.enable_xformers_memory_efficient_attention = MagicMock()

        mock_cls.from_pretrained.return_value = mock_pipe

        yield mock_pipe


@pytest.fixture
def mock_b2_client():
    """Mock B2 client."""
    with patch('src.infrastructure.storage.b2_client.B2Client') as mock_cls:
        mock_client = MagicMock()
        mock_client.upload_file = MagicMock()
        mock_client.get_presigned_url = MagicMock(return_value="https://b2.example.com/video.mp4")
        mock_cls.return_value = mock_client
        yield mock_client


@pytest.fixture
def sample_image_base64():
    """Create sample image as base64 data URI."""
    img = Image.new('RGB', (512, 512), color='blue')
    buffer = BytesIO()
    img.save(buffer, format='JPEG')
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/jpeg;base64,{encoded}"


@pytest.fixture
def sample_image_file(tmp_path):
    """Create sample image file."""
    img = Image.new('RGB', (512, 512), color='red')
    file_path = tmp_path / "test_image.jpg"
    img.save(file_path)
    return str(file_path)


class TestImage2VideoBasic:
    """Basic I2V workflow tests."""

    def test_i2v_single_prompt(self, mock_cogvideo_i2v_pipeline, mock_b2_client, sample_image_base64):
        """Test I2V with single prompt and base64 image."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["Make the character wave"],
            input_images=[sample_image_base64]
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.successful == 1
        assert result.failed == 0
        assert len(result.results) == 1
        assert result.results[0].success is True
        assert result.results[0].url is not None

    def test_i2v_batch(self, mock_cogvideo_i2v_pipeline, mock_b2_client, sample_image_base64):
        """Test I2V batch processing."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["animate 1", "animate 2", "animate 3"],
            input_images=[sample_image_base64] * 3
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.successful == 3
        assert result.failed == 0
        assert len(result.results) == 3

    def test_i2v_with_file_path(self, mock_cogvideo_i2v_pipeline, mock_b2_client, sample_image_file):
        """Test I2V with local file path."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["animate this"],
            input_images=[sample_image_file]
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.successful == 1
        assert result.results[0].success is True


class TestImage2VideoParameters:
    """Tests for I2V generation parameters."""

    def test_i2v_with_seed(self, mock_cogvideo_i2v_pipeline, sample_image_base64):
        """Test I2V with seed for reproducibility."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"],
            input_images=[sample_image_base64],
            seed=42
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.results[0].success is True

    def test_i2v_custom_parameters(self, mock_cogvideo_i2v_pipeline, sample_image_base64):
        """Test I2V with custom generation parameters."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"],
            input_images=[sample_image_base64],
            guidance_scale=7.0,
            num_inference_steps=30,
            num_frames=25,
            fps=12
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.results[0].success is True


class TestImage2VideoValidation:
    """Tests for I2V input validation."""

    def test_i2v_missing_input_images(self):
        """Test validation fails without input_images."""
        with pytest.raises(ValueError, match="input_images required"):
            GenJob(
                mode=GenerationMode.IMAGE2VIDEO,
                prompts=["test"]
                # Missing input_images
            )

    def test_i2v_length_mismatch(self, sample_image_base64):
        """Test validation fails on length mismatch."""
        with pytest.raises(ValueError, match="must match"):
            GenJob(
                mode=GenerationMode.IMAGE2VIDEO,
                prompts=["prompt1", "prompt2"],
                input_images=[sample_image_base64]  # Only 1 image for 2 prompts
            )

    def test_t2v_with_input_images_rejected(self, sample_image_base64):
        """Test T2V mode rejects input_images."""
        with pytest.raises(ValueError, match="not allowed"):
            GenJob(
                mode=GenerationMode.TEXT2VIDEO,
                prompts=["test"],
                input_images=[sample_image_base64]  # Not allowed for T2V
            )


class TestImage2VideoErrorHandling:
    """Tests for I2V error handling."""

    def test_i2v_invalid_image_url(self, mock_cogvideo_i2v_pipeline):
        """Test handling of invalid image URL."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"],
            input_images=["https://invalid.example.com/nonexistent.jpg"]
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        # Should complete but with failure
        assert result.successful == 0
        assert result.failed == 1
        assert result.results[0].success is False
        assert "Failed to load input image" in result.results[0].error

    def test_i2v_corrupt_base64(self, mock_cogvideo_i2v_pipeline):
        """Test handling of corrupt base64 data."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"],
            input_images=["data:image/jpeg;base64,INVALID!!!"]
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.failed == 1
        assert "Failed to load input image" in result.results[0].error


class TestImage2VideoB2Integration:
    """Tests for I2V with B2 upload."""

    def test_i2v_upload_success(self, mock_cogvideo_i2v_pipeline, mock_b2_client, sample_image_base64):
        """Test successful B2 upload."""
        job = GenJob(
            mode=GenerationMode.IMAGE2VIDEO,
            prompts=["test"],
            input_images=[sample_image_base64],
            output_prefix="i2v/test/"
        )

        orchestrator = GenerationOrchestrator()
        result = orchestrator.process_job(job)

        assert result.results[0].success is True
        assert result.results[0].url.startswith("https://")
        mock_b2_client.upload_file.assert_called_once()

    def test_i2v_without_b2(self, mock_cogvideo_i2v_pipeline, sample_image_base64):
        """Test I2V without B2 client (local only)."""
        with patch('src.infrastructure.storage.b2_client.B2Client', side_effect=Exception("No B2")):
            job = GenJob(
                mode=GenerationMode.IMAGE2VIDEO,
                prompts=["test"],
                input_images=[sample_image_base64]
            )

            orchestrator = GenerationOrchestrator()
            result = orchestrator.process_job(job)

            assert result.results[0].success is True
            assert result.results[0].url.startswith("file://")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
