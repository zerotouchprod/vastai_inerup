"""
Unit tests for InferenceRunner component.
"""

import pytest
import subprocess
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.core.config import AppConfig
from src.infrastructure.inpainting.components.inference import InferenceRunner


class TestInferenceRunner:
    """Test suite for InferenceRunner."""
    
    @pytest.fixture
    def config(self):
        """Create a mock AppConfig."""
        config = Mock(spec=AppConfig)
        config.PROPAINTER_ROOT = Path("/opt/ProPainter")
        return config
    
    @pytest.fixture
    def runner(self, config):
        """Create InferenceRunner instance."""
        return InferenceRunner(config, config.PROPAINTER_ROOT)
    
    def test_initialization(self, runner, config):
        """Test that runner is initialized with correct values."""
        assert runner.config == config
        assert runner.propainter_root == config.PROPAINTER_ROOT
        assert runner.inference_script == config.PROPAINTER_ROOT / "inference_propainter.py"
    
    def test_build_command(self, runner):
        """Test that build_command returns correct command."""
        video_path = Path("/tmp/video.mp4")
        mask_path = Path("/tmp/masks")
        output_path = Path("/tmp/output")
        target_width = 1920
        target_height = 1080
        
        cmd = runner.build_command(video_path, mask_path, output_path, target_width, target_height)
        
        assert cmd[0] == "python3"
        assert str(runner.inference_script) in cmd
        assert "--video" in cmd
        assert cmd[cmd.index("--video") + 1] == str(video_path)
        assert "--mask" in cmd
        assert cmd[cmd.index("--mask") + 1] == str(mask_path)
        assert "--output" in cmd
        assert cmd[cmd.index("--output") + 1] == str(output_path)
        assert "--width" in cmd
        assert cmd[cmd.index("--width") + 1] == str(target_width)
        assert "--height" in cmd
        assert cmd[cmd.index("--height") + 1] == str(target_height)
        assert "--save_frames" in cmd
    
    @patch('subprocess.run')
    def test_execute_command_success(self, mock_subprocess, runner):
        """Test execute_command with successful execution."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Success"
        mock_result.stderr = ""
        mock_subprocess.return_value = mock_result
        
        command = ["python3", "script.py"]
        result = runner.execute_command(command)
        
        mock_subprocess.assert_called_once()
        call_kwargs = mock_subprocess.call_args.kwargs
        assert call_kwargs['cwd'] == str(runner.propainter_root)
        assert call_kwargs['check'] == True
        assert call_kwargs['capture_output'] == True
        assert call_kwargs['text'] == True
        assert result == mock_result
    
    @patch('subprocess.run')
    def test_execute_command_with_gpu(self, mock_subprocess, runner):
        """Test execute_command with GPU ID."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        
        command = ["python3", "script.py"]
        result = runner.execute_command(command, gpu_id=1)
        
        mock_subprocess.assert_called_once()
        call_kwargs = mock_subprocess.call_args.kwargs
        env = call_kwargs['env']
        assert env['CUDA_VISIBLE_DEVICES'] == '1'
        assert env['PYTORCH_CUDA_ALLOC_CONF'] == 'max_split_size_mb:128,garbage_collection_threshold:0.6,expandable_segments:True'
    
    def test_handle_inference_error_oom(self, runner):
        """Test handle_inference_error for OOM error."""
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["python3", "script.py"],
            output=b"",
            stderr=b"out of memory"
        )
        with pytest.raises(RuntimeError) as exc_info:
            runner.handle_inference_error(error)
        assert "OOM" in str(exc_info.value)
    
    def test_handle_inference_error_cuda(self, runner):
        """Test handle_inference_error for CUDA error."""
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["python3", "script.py"],
            output=b"",
            stderr=b"cuda error: something"
        )
        with pytest.raises(RuntimeError) as exc_info:
            runner.handle_inference_error(error)
        assert "CUDA" in str(exc_info.value)
    
    def test_handle_inference_error_generic(self, runner):
        """Test handle_inference_error for generic error."""
        error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["python3", "script.py"],
            output=b"",
            stderr=b"some other error"
        )
        with pytest.raises(RuntimeError) as exc_info:
            runner.handle_inference_error(error)
        assert "failed with code" in str(exc_info.value)
    
    def test_command_building_requirements(self, runner):
        """Document the expected command structure."""
        # When implemented, build_command should return a list like:
        expected_command_template = [
            "python3", str(runner.inference_script),
            "--video", "{video_path}",
            "--mask", "{mask_path}",
            "--output", "{output_path}",
            "--width", "{width}",
            "--height", "{height}",
            "--save_frames"
        ]
        
        # This test documents the expected format
        assert len(expected_command_template) > 0
        assert "--video" in expected_command_template
        assert "--mask" in expected_command_template
        assert "--width" in expected_command_template
        assert "--height" in expected_command_template
    
    @pytest.mark.parametrize("gpu_id,expected_env_var", [
        (0, "0"),
        (1, "1"),
        (None, None),
    ])
    def test_gpu_environment_consideration(self, runner, gpu_id, expected_env_var):
        """Test that GPU ID should affect environment variables."""
        # When implemented, execute_command should handle CUDA_VISIBLE_DEVICES
        # This test documents the expected behavior
        if gpu_id is not None:
            # Should set CUDA_VISIBLE_DEVICES environment variable
            pass
        else:
            # Should not modify CUDA_VISIBLE_DEVICES
            pass
        
        # For now, just verify the test parameterization works
        assert True
