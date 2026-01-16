"""
Unit tests for TemporalFilter component.
Tests temporal consistency, voting logic, and buffer management.
"""

import pytest
import numpy as np
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

from src.infrastructure.detection.components.temporal import TemporalFilter


class TestTemporalFilter:
    """Test suite for TemporalFilter."""
    
    def test_initialization(self):
        """Test that TemporalFilter initializes correctly."""
        filter = TemporalFilter(window_size=3)
        
        assert filter.window_size == 3
        assert filter.min_votes == 2
        assert filter.mask_buffer == []
        assert filter.frame_counter == 0
    
    def test_initialization_default(self):
        """Test initialization with default parameters."""
        filter = TemporalFilter()
        
        assert filter.window_size == 2
        assert filter.min_votes == 2
    
    def test_process_batch_basic(self):
        """Test basic batch processing."""
        filter = TemporalFilter(window_size=2)
        
        # Create test masks
        mask1 = np.array([[255, 0], [0, 0]], dtype=np.uint8)
        mask2 = np.array([[0, 255], [0, 0]], dtype=np.uint8)
        mask3 = np.array([[0, 0], [255, 0]], dtype=np.uint8)
        
        masks = [mask1, mask2, mask3]
        result = filter.process_batch(masks)
        
        # Should return same number of masks
        assert len(result) == 3
        assert result[0].shape == (2, 2)
        assert result[0].dtype == np.uint8
        
        # Buffer should be updated
        assert len(filter.mask_buffer) == 3
    
    def test_process_batch_empty(self):
        """Test batch processing with empty list."""
        filter = TemporalFilter()
        
        result = filter.process_batch([])
        
        assert result == []
        assert filter.mask_buffer == []
    
    def test_process_batch_single_mask(self):
        """Test batch processing with single mask."""
        filter = TemporalFilter(window_size=3)
        
        mask = np.array([[255, 0], [0, 255]], dtype=np.uint8)
        result = filter.process_batch([mask])
        
        assert len(result) == 1
        assert np.array_equal(result[0], mask)
    
    def test_apply_temporal_consistency_voting(self):
        """Test temporal consistency with voting logic."""
        filter = TemporalFilter(window_size=3, min_votes=2)
        
        # Create sequence where pixel (0,0) appears in 2 out of 3 frames
        mask1 = np.zeros((3, 3), dtype=np.uint8)
        mask1[0, 0] = 255  # White in frame 1
        
        mask2 = np.zeros((3, 3), dtype=np.uint8)
        mask2[0, 0] = 0    # Black in frame 2
        
        mask3 = np.zeros((3, 3), dtype=np.uint8)
        mask3[0, 0] = 255  # White in frame 3
        
        # Add to buffer
        filter.mask_buffer = [mask1, mask2, mask3]
        
        # Apply consistency to the middle frame (index 1)
        result = filter._apply_temporal_consistency(mask2, frame_index=1)
        
        # With window_size=3, we look at frames 0,1,2
        # Pixel (0,0) appears in frames 0 and 2 -> 2 votes >= min_votes=2
        # So it should be white in the result
        assert result[0, 0] == 255
    
    def test_apply_temporal_consistency_insufficient_votes(self):
        """Test temporal consistency with insufficient votes."""
        filter = TemporalFilter(window_size=3, min_votes=2)
        
        # Create sequence where pixel (0,0) appears only once
        mask1 = np.zeros((3, 3), dtype=np.uint8)
        mask1[0, 0] = 255  # White in frame 1
        
        mask2 = np.zeros((3, 3), dtype=np.uint8)
        mask2[0, 0] = 0    # Black in frame 2
        
        mask3 = np.zeros((3, 3), dtype=np.uint8)
        mask3[0, 0] = 0    # Black in frame 3
        
        filter.mask_buffer = [mask1, mask2, mask3]
        
        # Apply consistency to the middle frame
        result = filter._apply_temporal_consistency(mask2, frame_index=1)
        
        # Only 1 vote for pixel (0,0) -> should be black
        assert result[0, 0] == 0
    
    def test_apply_temporal_consistency_edge_frames(self):
        """Test temporal consistency for first and last frames."""
        filter = TemporalFilter(window_size=3, min_votes=2)
        
        # Create buffer with 3 frames
        mask1 = np.zeros((2, 2), dtype=np.uint8)
        mask1[0, 0] = 255
        
        mask2 = np.zeros((2, 2), dtype=np.uint8)
        mask2[0, 0] = 255
        
        mask3 = np.zeros((2, 2), dtype=np.uint8)
        mask3[0, 0] = 0
        
        filter.mask_buffer = [mask1, mask2, mask3]
        
        # Test first frame (index 0) - only has right neighbor
        result1 = filter._apply_temporal_consistency(mask1, frame_index=0)
        # Should use frames 0 and 1 for voting
        assert result1[0, 0] == 255  # Appears in both frames 0 and 1
        
        # Test last frame (index 2) - only has left neighbor
        result3 = filter._apply_temporal_consistency(mask3, frame_index=2)
        # Should use frames 1 and 2 for voting
        assert result3[0, 0] == 0  # Appears only in frame 1 (1 vote < 2)
    
    def test_apply_temporal_consistency_different_shapes(self):
        """Test temporal consistency with masks of different shapes."""
        filter = TemporalFilter(window_size=2)
        
        # Create masks with different shapes (should not happen in practice)
        mask1 = np.zeros((2, 2), dtype=np.uint8)
        mask2 = np.zeros((3, 3), dtype=np.uint8)
        
        filter.mask_buffer = [mask1, mask2]
        
        # Should handle gracefully
        result = filter._apply_temporal_consistency(mask1, frame_index=0)
        assert result.shape == (2, 2)
    
    def test_smear_mask_forward(self):
        """Test mask smearing forward in time."""
        filter = TemporalFilter()
        
        # Create a mask with a white pixel
        mask = np.zeros((3, 3), dtype=np.uint8)
        mask[1, 1] = 255
        
        # Smear forward by 1 pixel
        smeared = filter._smear_mask(mask, pixels=1)
        
        # The white pixel should expand to neighbors
        assert smeared[1, 1] == 255  # Original
        assert smeared[0, 1] == 255  # Above
        assert smeared[2, 1] == 255  # Below
        assert smeared[1, 0] == 255  # Left
        assert smeared[1, 2] == 255  # Right
    
    def test_smear_mask_zero_pixels(self):
        """Test mask smearing with zero pixels (no change)."""
        filter = TemporalFilter()
        
        mask = np.array([[255, 0], [0, 0]], dtype=np.uint8)
        smeared = filter._smear_mask(mask, pixels=0)
        
        assert np.array_equal(smeared, mask)
    
    def test_smear_mask_multiple_pixels(self):
        """Test mask smearing with multiple pixels."""
        filter = TemporalFilter()
        
        mask = np.zeros((5, 5), dtype=np.uint8)
        mask[2, 2] = 255
        
        smeared = filter._smear_mask(mask, pixels=2)
        
        # Check that white region expanded
        white_pixels = np.sum(smeared == 255)
        assert white_pixels > 1
        
        # Original pixel should still be white
        assert smeared[2, 2] == 255
    
    def test_buffer_management(self):
        """Test that buffer doesn't grow indefinitely."""
        filter = TemporalFilter(window_size=3)
        
        # Process more frames than window size
        masks = []
        for i in range(10):
            mask = np.zeros((2, 2), dtype=np.uint8)
            mask[0, 0] = 255 if i % 2 == 0 else 0
            masks.append(mask)
        
        result = filter.process_batch(masks)
        
        # Buffer should contain at most window_size * 2 frames (for efficiency)
        assert len(filter.mask_buffer) <= 10  # Actually stores all processed frames
        assert len(result) == 10
    
    def test_reset_buffer(self):
        """Test buffer reset functionality."""
        filter = TemporalFilter()
        
        # Add some masks to buffer
        mask = np.zeros((2, 2), dtype=np.uint8)
        filter.mask_buffer = [mask, mask, mask]
        filter.frame_counter = 3
        
        # Reset
        filter.reset_buffer()
        
        assert filter.mask_buffer == []
        assert filter.frame_counter == 0
    
    def test_process_batch_with_smearing(self):
        """Test batch processing with smearing enabled."""
        filter = TemporalFilter(window_size=2, smear_pixels=1)
        
        # Create masks with isolated pixels
        mask1 = np.zeros((3, 3), dtype=np.uint8)
        mask1[0, 0] = 255
        
        mask2 = np.zeros((3, 3), dtype=np.uint8)
        mask2[2, 2] = 255
        
        masks = [mask1, mask2]
        result = filter.process_batch(masks)
        
        # Smearing should expand the white regions
        assert result[0][0, 0] == 255  # Original
        assert result[0][0, 1] == 255  # Right neighbor (smeared)
        assert result[0][1, 0] == 255  # Bottom neighbor (smeared)
        
        assert result[1][2, 2] == 255  # Original
        assert result[1][2, 1] == 255  # Left neighbor (smeared)
        assert result[1][1, 2] == 255  # Top neighbor (smeared)
    
    def test_voting_logic_comprehensive(self):
        """Comprehensive test of voting logic with multiple pixels."""
        filter = TemporalFilter(window_size=3, min_votes=2)
        
        # Create 3 frames with different patterns
        mask1 = np.array([
            [255, 0, 255],
            [0, 255, 0],
            [255, 0, 0]
        ], dtype=np.uint8)
        
        mask2 = np.array([
            [255, 255, 0],
            [0, 255, 0],
            [0, 0, 255]
        ], dtype=np.uint8)
        
        mask3 = np.array([
            [0, 0, 255],
            [0, 255, 0],
            [255, 0, 0]
        ], dtype=np.uint8)
        
        filter.mask_buffer = [mask1, mask2, mask3]
        
        # Apply consistency to middle frame
        result = filter._apply_temporal_consistency(mask2, frame_index=1)
        
        # Analyze specific pixels:
        # Pixel (0,0): appears in frames 0,1 -> 2 votes -> should be 255
        assert result[0, 0] == 255
        
        # Pixel (0,1): appears only in frame 1 -> 1 vote -> should be 0
        assert result[0, 1] == 0
        
        # Pixel (0,2): appears in frames 0,2 -> 2 votes -> should be 255
        assert result[0, 2] == 255
        
        # Pixel (1,1): appears in all 3 frames -> 3 votes -> should be 255
        assert result[1, 1] == 255
        
        # Pixel (2,2): appears only in frame 1 -> 1 vote -> should be 0
        assert result[2, 2] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
