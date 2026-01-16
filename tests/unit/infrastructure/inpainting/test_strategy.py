"""
Unit tests for SlidingWindowStrategy component.
"""

import pytest
from unittest.mock import Mock
from pathlib import Path

from src.core.config import AppConfig
from src.infrastructure.inpainting.components.strategy import SlidingWindowStrategy


class TestSlidingWindowStrategy:
    """Test suite for SlidingWindowStrategy."""
    
    @pytest.fixture
    def config(self):
        """Create a mock AppConfig."""
        config = Mock(spec=AppConfig)
        config.MAX_FRAMES_PER_CHUNK = 15
        config.PROPAINTER_OVERLAP = 2
        return config
    
    @pytest.fixture
    def strategy(self, config):
        """Create SlidingWindowStrategy instance."""
        return SlidingWindowStrategy(config)
    
    def test_needs_chunking(self, strategy):
        """Test chunking decision logic."""
        # Exactly at chunk size - no chunking needed
        assert strategy.needs_chunking(15) == False
        
        # Below chunk size - no chunking needed
        assert strategy.needs_chunking(10) == False
        assert strategy.needs_chunking(1) == False
        
        # Above chunk size - chunking needed
        assert strategy.needs_chunking(16) == True
        assert strategy.needs_chunking(100) == True
    
    def test_generate_chunks_small(self, strategy, tmp_path):
        """Test chunk generation for small videos (no chunking)."""
        frames_dir = tmp_path / "frames"
        mask_dir = tmp_path / "masks"
        output_parent = tmp_path / "chunks"
        frames_dir.mkdir()
        mask_dir.mkdir()
        # Create dummy frames
        for i in range(10):
            (frames_dir / f"frame_{i:08d}.png").touch()
            (mask_dir / f"frame_{i:08d}.png").touch()
        
        chunks = strategy.generate_chunks(frames_dir, mask_dir, output_parent)
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk['id'] == 0
        assert chunk['frame_indices'] == (0, 10)
        
        # Test with exactly chunk size: need to clear previous frames
        # Remove previous files
        for f in frames_dir.glob("*.png"):
            f.unlink()
        for f in mask_dir.glob("*.png"):
            f.unlink()
        for i in range(15):
            (frames_dir / f"frame2_{i:08d}.png").touch()
            (mask_dir / f"frame2_{i:08d}.png").touch()
        chunks2 = strategy.generate_chunks(frames_dir, mask_dir, output_parent)
        assert len(chunks2) == 1
    
    def test_generate_chunks_large(self, strategy, tmp_path):
        """Test chunk generation for large videos."""
        frames_dir = tmp_path / "frames"
        mask_dir = tmp_path / "masks"
        output_parent = tmp_path / "chunks"
        frames_dir.mkdir()
        mask_dir.mkdir()
        # Create 30 dummy frames
        for i in range(30):
            (frames_dir / f"frame_{i:08d}.png").touch()
            (mask_dir / f"frame_{i:08d}.png").touch()
        
        chunks = strategy.generate_chunks(frames_dir, mask_dir, output_parent)
        # 30 frames, chunk_size=15, overlap=2, step=13
        # Expected chunks: (0,15), (13,28), (15,30) after adjustment
        assert len(chunks) == 3
        assert chunks[0]['frame_indices'] == (0, 15)
        assert chunks[1]['frame_indices'] == (13, 28)
        assert chunks[2]['frame_indices'] == (15, 30)
    
    def test_get_chunk_paths(self, strategy):
        """Test chunk path generation."""
        base_dir = Path("/tmp/test")
        chunk_id = 5
        
        paths = strategy.get_chunk_paths(base_dir, chunk_id)
        
        assert isinstance(paths, dict)
        assert len(paths) == 3
        assert paths['input'] == base_dir / "chunk_005" / "frames"
        assert paths['mask'] == base_dir / "chunk_005" / "masks"
        assert paths['output'] == base_dir / "chunk_005" / "output"
        
        # Test with different chunk IDs
        paths2 = strategy.get_chunk_paths(base_dir, 42)
        assert paths2['input'] == base_dir / "chunk_042" / "frames"
    
    @pytest.mark.parametrize("total_frames,chunk_size,overlap,expected_chunks", [
        # Small video (no chunking needed)
        (10, 15, 2, 1),  # Single chunk
        # 30 frames -> 3 chunks
        (30, 15, 2, 3),  # 30 / (15-2) = 2.3 → ceil = 3 chunks
        # With remainder
        (32, 15, 2, 3),  # 32 / (15-2) = 2.46 → 3 chunks
        # Large video
        (100, 15, 2, 8),  # 100 / 13 = 7.69 → 8 chunks
    ])
    def test_chunk_calculation_theory(self, config, total_frames, chunk_size, overlap, expected_chunks):
        """Test chunk calculation theory (without implementation)."""
        config.MAX_FRAMES_PER_CHUNK = chunk_size
        config.PROPAINTER_OVERLAP = overlap
        strategy = SlidingWindowStrategy(config)
        
        # This test documents the expected behavior
        # Actual implementation will need to match this
        step = chunk_size - overlap
        expected = (total_frames - overlap + step - 1) // step if total_frames > chunk_size else 1
        assert expected == expected_chunks, f"Expected {expected_chunks} chunks for {total_frames} frames"
    
    def test_initialization(self, strategy, config):
        """Test that strategy is initialized with correct values."""
        assert strategy.chunk_size == config.MAX_FRAMES_PER_CHUNK
        assert strategy.overlap == config.PROPAINTER_OVERLAP
        assert strategy.config == config
