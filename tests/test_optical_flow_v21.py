"""
Unit tests для v2.1 Animated Text Detection.
Tests optical flow tracker, temporal propagation, color detection.
"""

import pytest
import numpy as np
import cv2
from pathlib import Path

from src.infrastructure.detection import (
    OpticalFlowTracker,
    FlowParameters,
    TemporalMaskPropagator,
    ColorChangeDetector,
    AnimatedTextDetector
)


class TestOpticalFlowTracker:
    """Tests for OpticalFlowTracker class."""

    def test_init_default_parameters(self):
        """Test initialization with default parameters."""
        tracker = OpticalFlowTracker()

        assert tracker.params.levels == 3
        assert tracker.params.winsize == 15
        assert tracker.params.iterations == 3

    def test_init_custom_parameters(self):
        """Test initialization with custom parameters."""
        params = FlowParameters(levels=4, winsize=20, iterations=5)
        tracker = OpticalFlowTracker(params)

        assert tracker.params.levels == 4
        assert tracker.params.winsize == 20

    def test_compute_flow_shape(self):
        """Test that compute_flow returns correct shape."""
        tracker = OpticalFlowTracker()

        # Create test frames
        frame1 = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)
        frame2 = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

        flow = tracker.compute_flow(frame1, frame2)

        assert flow.shape == (100, 100, 2)  # (H, W, 2) for dx, dy

    def test_track_bbox_with_motion(self):
        """Test bbox tracking with simulated motion."""
        tracker = OpticalFlowTracker()

        # Create frame with moving object
        h, w = 200, 200
        frame1 = np.zeros((h, w, 3), dtype=np.uint8)
        frame2 = np.zeros((h, w, 3), dtype=np.uint8)

        # Draw rectangle in frame1
        cv2.rectangle(frame1, (50, 50), (100, 100), (255, 255, 255), -1)

        # Draw same rectangle moved 10 pixels right in frame2
        cv2.rectangle(frame2, (60, 50), (110, 100), (255, 255, 255), -1)

        # Track bbox
        initial_bbox = (50, 50, 50, 50)
        tracked_bbox = tracker.track_bbox(frame1, frame2, initial_bbox)

        x, y, w, h = tracked_bbox

        # Should move right (~10 pixels, allowing some error)
        assert 55 < x < 65, f"Expected x ~60, got {x}"
        assert y == 50  # y should stay same
        assert w == 50  # dimensions should stay same
        assert h == 50

    def test_warp_mask(self):
        """Test mask warping with optical flow."""
        tracker = OpticalFlowTracker()

        # Create frames
        frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
        frame2 = np.zeros((100, 100, 3), dtype=np.uint8)

        # Create mask
        mask = np.zeros((100, 100), dtype=np.uint8)
        mask[40:60, 40:60] = 255

        # Warp mask
        warped = tracker.warp_mask(frame1, frame2, mask)

        assert warped.shape == mask.shape
        assert warped.dtype == np.uint8
        assert np.max(warped) <= 255

    def test_compute_motion_magnitude(self):
        """Test motion magnitude calculation."""
        tracker = OpticalFlowTracker()

        # Create flow with known magnitude
        flow = np.zeros((100, 100, 2), dtype=np.float32)
        flow[:, :, 0] = 3.0  # dx = 3
        flow[:, :, 1] = 4.0  # dy = 4

        magnitude = tracker.compute_motion_magnitude(flow)

        # sqrt(3^2 + 4^2) = 5
        assert abs(magnitude - 5.0) < 0.1

    def test_flow_cache(self):
        """Test that flow caching works."""
        tracker = OpticalFlowTracker()

        frame1 = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)
        frame2 = np.random.randint(0, 256, (50, 50, 3), dtype=np.uint8)

        # Compute with cache key
        flow1 = tracker.compute_flow(frame1, frame2, cache_key='test')

        # Should be cached
        assert 'test' in tracker._flow_cache

        # Second call should return cached version
        flow2 = tracker.compute_flow(frame1, frame2, cache_key='test')

        np.testing.assert_array_equal(flow1, flow2)


class TestTemporalMaskPropagator:
    """Tests for TemporalMaskPropagator class."""

    def test_init(self):
        """Test initialization."""
        propagator = TemporalMaskPropagator(keyframe_interval=5)

        assert propagator.keyframe_interval == 5
        assert propagator.flow_tracker is not None

    def test_estimate_speedup(self):
        """Test speedup estimation."""
        propagator = TemporalMaskPropagator(keyframe_interval=5)

        metrics = propagator.estimate_speedup(
            num_frames=150,
            ocr_time_ms=150,
            flow_time_ms=50
        )

        assert metrics['total_frames'] == 150
        assert metrics['keyframes'] == 30  # 150 / 5
        assert metrics['flow_frames'] == 120  # 150 - 30
        assert metrics['speedup'] > 1.5  # Should be ~2.1x

    @pytest.mark.slow
    def test_propagate_masks_with_mock_ocr(self):
        """Test mask propagation with mocked OCR."""
        from unittest.mock import Mock

        # Create mock OCR detector
        mock_ocr = Mock()
        mock_ocr.detect = Mock(return_value=[])  # No detections

        # Create test frames
        frames = [np.zeros((100, 100, 3), dtype=np.uint8) for _ in range(10)]

        propagator = TemporalMaskPropagator(keyframe_interval=3)
        masks = propagator.propagate_masks(frames, mock_ocr)

        # Should have masks for all frames
        assert len(masks) == 10

        # OCR should be called for keyframes only
        assert mock_ocr.detect.call_count == 4  # frames 0, 3, 6, 9


class TestColorChangeDetector:
    """Tests for ColorChangeDetector class."""

    def test_init(self):
        """Test initialization."""
        detector = ColorChangeDetector()

        assert detector.color_threshold == 50.0
        assert detector.motion_threshold == 5.0

    def test_classify_static_text(self):
        """Test classification of static text."""
        detector = ColorChangeDetector()

        # Create frames with static white rectangle
        frames = []
        for _ in range(10):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.rectangle(frame, (30, 30), (70, 50), (255, 255, 255), -1)
            frames.append(frame)

        # Tracked bbox (no movement)
        tracked_bboxes = {i: [(30, 30, 40, 20)] for i in range(10)}

        animation_type = detector.classify_animation_type(frames, tracked_bboxes)

        assert animation_type == 'static'

    def test_classify_moving_text(self):
        """Test classification of moving text."""
        detector = ColorChangeDetector(motion_threshold=5.0)

        # Create frames with moving white rectangle
        frames = []
        tracked_bboxes = {}

        for i in range(10):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            x = 30 + i * 2  # Move 2 pixels per frame
            cv2.rectangle(frame, (x, 30), (x+40, 50), (255, 255, 255), -1)
            frames.append(frame)
            tracked_bboxes[i] = [(x, 30, 40, 20)]

        animation_type = detector.classify_animation_type(frames, tracked_bboxes)

        assert animation_type == 'moving'


class TestAnimatedTextDetector:
    """Tests for AnimatedTextDetector class."""

    def test_init(self):
        """Test initialization."""
        from unittest.mock import Mock

        mock_ocr = Mock()
        detector = AnimatedTextDetector(mock_ocr, roi_str='bottom', keyframe_interval=5)

        assert detector.roi_str == 'bottom'
        assert detector.ocr == mock_ocr
        assert detector.flow_tracker is not None
        assert detector.mask_propagator is not None
        assert detector.color_detector is not None

    def test_estimate_performance_gain(self):
        """Test performance gain estimation."""
        from unittest.mock import Mock

        mock_ocr = Mock()
        detector = AnimatedTextDetector(mock_ocr, keyframe_interval=5)

        metrics = detector.estimate_performance_gain(150)

        assert metrics['speedup'] > 1.5
        assert metrics['time_saved_ms'] > 0


class TestIntegrationScenarios:
    """Integration tests for complete workflows."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_complete_animated_detection_workflow(self):
        """Test complete workflow from frames to masks."""
        from unittest.mock import Mock

        # Create mock OCR
        mock_ocr = Mock()
        mock_ocr.detect = Mock(return_value=[
            {'points': [[30, 30], [70, 30], [70, 50], [30, 50]], 'text': 'TEST'}
        ])

        # Create test frames
        frames = []
        for i in range(15):
            frame = np.zeros((100, 100, 3), dtype=np.uint8)
            cv2.rectangle(frame, (30+i, 30), (70+i, 50), (255, 255, 255), -1)
            frames.append(frame)

        # Run detection
        detector = AnimatedTextDetector(mock_ocr, keyframe_interval=5)
        masks = detector.detect_animated_subtitles(frames)

        # Verify
        assert len(masks) == 15  # Should have mask for every frame
        assert detector.get_animation_type() in ['static', 'moving', 'karaoke', 'both']

    @pytest.mark.benchmark
    def test_performance_benchmark_flow_computation(self, benchmark):
        """Benchmark optical flow computation speed."""
        tracker = OpticalFlowTracker()

        frame1 = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)
        frame2 = np.random.randint(0, 256, (480, 640, 3), dtype=np.uint8)

        result = benchmark(tracker.compute_flow, frame1, frame2)

        # Should complete in reasonable time
        assert result.shape == (480, 640, 2)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])

