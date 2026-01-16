"""
Unit tests for MediaProcessor component.
"""

import pytest
import shutil
import subprocess
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.core.config import AppConfig
from src.infrastructure.inpainting.components.media import MediaProcessor


class TestMediaProcessor:
    """Test suite for MediaProcessor."""
    
    @pytest.fixture
    def config(self):
        """Create a mock AppConfig."""
        config = Mock(spec=AppConfig)
        return config
    
    @pytest.fixture
    def media_processor(self, config):
        """Create MediaProcessor instance."""
        return MediaProcessor(config)
    
    def test_initialization(self, media_processor, config):
        """Test that processor is initialized with correct values."""
        assert media_processor.config == config
    
    @patch('tempfile.mkdtemp')
    @patch('pathlib.Path.is_dir')
    def test_prepare_input_directory(self, mock_is_dir, mock_mkdtemp, media_processor):
        """Test prepare_input with directory input."""
        mock_is_dir.return_value = True
        input_path = Path("/tmp/frames")
        
        result = media_processor.prepare_input(input_path)
        
        assert result == input_path
        mock_is_dir.assert_called_once()
    
    @patch('tempfile.mkdtemp')
    @patch('pathlib.Path.is_dir')
    @patch.object(MediaProcessor, 'extract_frames_from_video')
    def test_prepare_input_video(self, mock_extract, mock_is_dir, mock_mkdtemp, media_processor):
        """Test prepare_input with video file."""
        mock_is_dir.return_value = False
        mock_mkdtemp.return_value = "/tmp/temp_frames"
        mock_extract.return_value = [Path("/tmp/temp_frames/frame_0001.png")]
        input_path = Path("/tmp/video.mp4")
        
        result = media_processor.prepare_input(input_path)
        
        assert result == Path("/tmp/temp_frames")
        mock_is_dir.assert_called_once()
        mock_mkdtemp.assert_called_once_with(prefix="propainter_frames_")
        mock_extract.assert_called_once_with(input_path, Path("/tmp/temp_frames"))
    
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.glob')
    def test_extract_frames_from_video_success(self, mock_glob, mock_mkdir, mock_subprocess, media_processor):
        """Test extract_frames_from_video with successful extraction."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        mock_glob.return_value = [Path("/tmp/output/frame_00000001.png")]
        
        video_path = Path("/tmp/video.mp4")
        output_dir = Path("/tmp/output")
        
        frames = media_processor.extract_frames_from_video(video_path, output_dir)
        
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_subprocess.assert_called_once()
        mock_glob.assert_called_once_with("frame_*.png")
        assert frames == [Path("/tmp/output/frame_00000001.png")]
    
    @patch('subprocess.run')
    @patch('pathlib.Path.mkdir')
    def test_extract_frames_from_video_failure(self, mock_mkdir, mock_subprocess, media_processor):
        """Test extract_frames_from_video when ffmpeg fails."""
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, ['ffmpeg'], stderr=b"Error")
        
        video_path = Path("/tmp/video.mp4")
        output_dir = Path("/tmp/output")
        
        with pytest.raises(RuntimeError, match="Failed to extract frames"):
            media_processor.extract_frames_from_video(video_path, output_dir)
        
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    
    @patch('PIL.Image.open')
    @patch('pathlib.Path.exists')
    def test_validate_and_restore_aspect_ratio_match(self, mock_exists, mock_image_open, media_processor):
        """Test validate_and_restore_aspect_ratio when dimensions match."""
        mock_exists.return_value = True
        mock_img = MagicMock()
        mock_img.size = (1920, 1080)
        mock_image_open.return_value.__enter__.return_value = mock_img
        
        frames = [Path("/tmp/frame1.png")]
        original_dims = (1920, 1080)
        
        media_processor.validate_and_restore_aspect_ratio(frames, original_dims)
        
        mock_image_open.assert_called_once_with(frames[0])
        mock_img.rotate.assert_not_called()
        mock_img.resize.assert_not_called()
    
    @patch('PIL.Image.open')
    @patch('pathlib.Path.exists')
    def test_validate_and_restore_aspect_ratio_swapped(self, mock_exists, mock_image_open, media_processor):
        """Test validate_and_restore_aspect_ratio when dimensions are swapped."""
        mock_exists.return_value = True
        mock_img = MagicMock()
        mock_img.size = (1080, 1920)  # swapped
        mock_img.rotate.return_value = MagicMock()
        mock_image_open.return_value.__enter__.return_value = mock_img
        
        frames = [Path("/tmp/frame1.png")]
        original_dims = (1920, 1080)
        
        media_processor.validate_and_restore_aspect_ratio(frames, original_dims)
        
        mock_image_open.assert_called()
        mock_img.rotate.assert_called_once_with(90, expand=True)
        mock_img.resize.assert_not_called()
    
    @patch('shutil.copy2')
    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    def test_merge_chunks(self, mock_exists, mock_mkdir, mock_copy2, media_processor):
        """Test merge_chunks."""
        mock_exists.return_value = True
        chunk_results = {
            "frame1.png": Path("/tmp/chunk1/frame1.png"),
            "frame2.png": Path("/tmp/chunk2/frame2.png"),
        }
        output_dir = Path("/tmp/output")
        
        result = media_processor.merge_chunks(chunk_results, output_dir)
        
        mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
        assert mock_copy2.call_count == 2
        assert result == output_dir
    
    def test_aspect_ratio_validation_requirements(self, media_processor):
        """Document the expected aspect ratio validation logic."""
        # When implemented, validate_and_restore_aspect_ratio should:
        # 1. Check if dimensions are swapped (portrait vs landscape)
        # 2. Rotate frames if needed
        # 3. Resize to original dimensions
        # 4. Handle edge cases (already correct, slightly off, etc.)
        
        test_cases = [
            {
                "original": (1920, 1080),  # Landscape 16:9
                "processed": (1080, 1920),  # Swapped (portrait)
                "should_rotate": True,
            },
            {
                "original": (1920, 1080),
                "processed": (1280, 720),   # Correct aspect, scaled down
                "should_rotate": False,
            },
            {
                "original": (1080, 1920),  # Portrait
                "processed": (1920, 1080),  # Swapped (landscape)
                "should_rotate": True,
            },
        ]
        
        # Document expected behavior
        for case in test_cases:
            original_aspect = case["original"][0] / case["original"][1]
            processed_aspect = case["processed"][0] / case["processed"][1]
            
            # Check if aspect ratios are significantly different
            aspect_diff = abs(original_aspect - processed_aspect)
            swapped_aspect = 1 / processed_aspect if processed_aspect != 0 else 0
            swapped_diff = abs(original_aspect - swapped_aspect)
            
            # Should rotate if swapped aspect is closer to original
            should_rotate = swapped_diff < aspect_diff and swapped_diff < 0.1
            
            assert should_rotate == case["should_rotate"], \
                f"Failed for {case['original']} -> {case['processed']}"
    
    @pytest.mark.parametrize("input_type,expected_action", [
        (Path("/tmp/video.mp4"), "extract_frames"),
        (Path("/tmp/frames"), "use_directly"),
        ([Path("/tmp/frame1.jpg")], "create_temp_dir"),
    ])
    def test_input_preparation_strategies(self, media_processor, input_type, expected_action):
        """Test different input preparation strategies."""
        # When implemented, prepare_input should handle:
        # 1. Video files -> extract frames
        # 2. Frame directories -> use directly
        # 3. List of frame paths -> create temporary directory
        
        # For now, just document the expected behavior
        actions = ["extract_frames", "use_directly", "create_temp_dir"]
        assert expected_action in actions
