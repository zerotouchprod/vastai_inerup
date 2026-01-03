"""
Quality metrics for video processing validation.
Implements PSNR, SSIM, and other quality measurements.
"""

import numpy as np
import cv2
from pathlib import Path
from typing import Tuple, Optional
import logging

try:
    from skimage.metrics import structural_similarity as ssim
    from skimage.metrics import peak_signal_noise_ratio as psnr
    SKIMAGE_AVAILABLE = True
except ImportError:
    SKIMAGE_AVAILABLE = False
    logging.warning("scikit-image not available, using fallback implementations")

logger = logging.getLogger(__name__)


def calculate_psnr(img1: np.ndarray, img2: np.ndarray, max_value: float = 255.0) -> float:
    """
    Calculate Peak Signal-to-Noise Ratio between two images.

    Args:
        img1: First image (reference)
        img2: Second image (processed)
        max_value: Maximum possible pixel value (255 for uint8)

    Returns:
        PSNR value in dB (higher is better, >40dB is excellent)
    """
    if SKIMAGE_AVAILABLE:
        return psnr(img1, img2, data_range=max_value)

    # Fallback implementation
    mse = np.mean((img1.astype(float) - img2.astype(float)) ** 2)
    if mse == 0:
        return float('inf')

    psnr_value = 20 * np.log10(max_value / np.sqrt(mse))
    return psnr_value


def calculate_ssim(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Calculate Structural Similarity Index between two images.

    Args:
        img1: First image (reference)
        img2: Second image (processed)

    Returns:
        SSIM value between 0 and 1 (1 = identical, >0.95 is excellent)
    """
    if SKIMAGE_AVAILABLE:
        # Convert to grayscale if color
        if len(img1.shape) == 3:
            img1_gray = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
            img2_gray = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
        else:
            img1_gray = img1
            img2_gray = img2

        return ssim(img1_gray, img2_gray)

    # Fallback: use simple correlation
    img1_flat = img1.flatten().astype(float)
    img2_flat = img2.flatten().astype(float)

    correlation = np.corrcoef(img1_flat, img2_flat)[0, 1]
    return max(0.0, correlation)  # Clamp to [0, 1]


def compare_videos_quality(
    original_video: Path,
    processed_video: Path,
    sample_frames: int = 10,
    roi: Optional[Tuple[int, int, int, int]] = None
) -> dict:
    """
    Compare quality between original and processed video.

    Args:
        original_video: Path to original video
        processed_video: Path to processed video
        sample_frames: Number of frames to sample
        roi: Optional ROI (x, y, w, h) to compare only specific region

    Returns:
        Dict with quality metrics
    """
    try:
        # Open videos
        cap_orig = cv2.VideoCapture(str(original_video))
        cap_proc = cv2.VideoCapture(str(processed_video))

        if not cap_orig.isOpened() or not cap_proc.isOpened():
            raise ValueError("Failed to open video files")

        # Get video properties
        total_frames_orig = int(cap_orig.get(cv2.CAP_PROP_FRAME_COUNT))
        total_frames_proc = int(cap_proc.get(cv2.CAP_PROP_FRAME_COUNT))

        if total_frames_orig != total_frames_proc:
            logger.warning(
                f"Frame count mismatch: original={total_frames_orig}, "
                f"processed={total_frames_proc}"
            )

        # Sample frames uniformly
        frame_indices = np.linspace(0, min(total_frames_orig, total_frames_proc) - 1,
                                   sample_frames, dtype=int)

        psnr_values = []
        ssim_values = []

        for frame_idx in frame_indices:
            # Seek to frame
            cap_orig.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            cap_proc.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)

            # Read frames
            ret_orig, frame_orig = cap_orig.read()
            ret_proc, frame_proc = cap_proc.read()

            if not ret_orig or not ret_proc:
                logger.warning(f"Failed to read frame {frame_idx}")
                continue

            # Apply ROI if specified
            if roi:
                x, y, w, h = roi
                frame_orig = frame_orig[y:y+h, x:x+w]
                frame_proc = frame_proc[y:y+h, x:x+w]

            # Calculate metrics
            try:
                psnr_val = calculate_psnr(frame_orig, frame_proc)
                ssim_val = calculate_ssim(frame_orig, frame_proc)

                psnr_values.append(psnr_val)
                ssim_values.append(ssim_val)

            except Exception as e:
                logger.warning(f"Failed to calculate metrics for frame {frame_idx}: {e}")

        cap_orig.release()
        cap_proc.release()

        # Calculate statistics
        if psnr_values and ssim_values:
            return {
                'psnr_mean': float(np.mean(psnr_values)),
                'psnr_std': float(np.std(psnr_values)),
                'psnr_min': float(np.min(psnr_values)),
                'psnr_max': float(np.max(psnr_values)),
                'ssim_mean': float(np.mean(ssim_values)),
                'ssim_std': float(np.std(ssim_values)),
                'ssim_min': float(np.min(ssim_values)),
                'ssim_max': float(np.max(ssim_values)),
                'frames_compared': len(psnr_values),
            }
        else:
            raise ValueError("No frames could be compared")

    except Exception as e:
        logger.error(f"Failed to compare video quality: {e}")
        return {
            'error': str(e),
            'psnr_mean': 0.0,
            'ssim_mean': 0.0
        }


def get_audio_duration(video_path: Path) -> Optional[float]:
    """Get audio track duration from video."""
    try:
        import ffmpeg
        probe = ffmpeg.probe(str(video_path))
        audio_streams = [s for s in probe['streams'] if s['codec_type'] == 'audio']

        if audio_streams:
            return float(audio_streams[0].get('duration', 0))
        return None

    except Exception as e:
        logger.warning(f"Failed to get audio duration: {e}")
        return None


def compare_audio_duration(original_video: Path, processed_video: Path) -> dict:
    """
    Compare audio duration between original and processed video.

    Returns:
        Dict with audio comparison results
    """
    orig_duration = get_audio_duration(original_video)
    proc_duration = get_audio_duration(processed_video)

    if orig_duration is None:
        return {
            'original_has_audio': False,
            'processed_has_audio': proc_duration is not None,
            'duration_match': False
        }

    if proc_duration is None:
        return {
            'original_has_audio': True,
            'processed_has_audio': False,
            'duration_match': False,
            'error': 'Processed video has no audio'
        }

    duration_diff = abs(orig_duration - proc_duration)

    return {
        'original_has_audio': True,
        'processed_has_audio': True,
        'original_duration': orig_duration,
        'processed_duration': proc_duration,
        'duration_diff': duration_diff,
        'duration_match': duration_diff < 0.1  # 100ms tolerance
    }


def validate_video_quality(
    original_video: Path,
    processed_video: Path,
    psnr_threshold: float = 40.0,
    ssim_threshold: float = 0.95,
    roi: Optional[Tuple[int, int, int, int]] = None
) -> Tuple[bool, dict]:
    """
    Validate that processed video meets quality thresholds.

    Args:
        original_video: Original video path
        processed_video: Processed video path
        psnr_threshold: Minimum acceptable PSNR (dB)
        ssim_threshold: Minimum acceptable SSIM (0-1)
        roi: Optional ROI to check (for non-processed regions)

    Returns:
        Tuple of (passed: bool, metrics: dict)
    """
    metrics = compare_videos_quality(original_video, processed_video, roi=roi)

    passed = (
        'error' not in metrics and
        metrics.get('psnr_mean', 0) >= psnr_threshold and
        metrics.get('ssim_mean', 0) >= ssim_threshold
    )

    return passed, metrics

