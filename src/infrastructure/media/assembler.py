"""Video assembler implementation."""

from pathlib import Path
from typing import List

from domain.protocols import IAssembler
from domain.exceptions import AssemblyError
from shared.logging import get_logger
from infrastructure.media.ffmpeg import FFmpegWrapper

logger = get_logger(__name__)


class FFmpegAssembler:
    """
    Assembles video from frames using FFmpeg.
    Implements IAssembler protocol.
    """

    def __init__(self):
        self._ffmpeg = FFmpegWrapper()
        self._logger = get_logger(__name__)
        self._preferred_encoder = "h264_nvenc"
        self._fallback_encoder = "libx264"

    def supports_encoder(self, encoder: str) -> bool:
        """Check if specific encoder is available."""
        return self._ffmpeg.test_encoder(encoder)

    def assemble(
        self,
        frames: List[Path],
        output_path: Path,
        fps: float,
        **options
    ) -> Path:
        """
        Assemble frames into a video file.

        Args:
            frames: List of frame file paths
            output_path: Output video path
            fps: Target frames per second
            **options: Additional options (encoder, pix_fmt, etc.)

        Returns:
            Path to assembled video

        Raises:
            AssemblyError: If assembly fails
        """
        if not frames:
            raise AssemblyError("No frames to assemble")

        frames_dir = frames[0].parent
        pattern = options.get('pattern', 'frame_%06d.png')
        encoder = options.get('encoder', self._preferred_encoder)
        pix_fmt = options.get('pix_fmt', 'yuv420p')

        self._logger.info(
            f"Assembling {len(frames)} frames at {fps} FPS with encoder: {encoder}"
        )

        try:
            # Try with preferred encoder first
            return self._ffmpeg.assemble_video(
                frames_dir=frames_dir,
                output_path=output_path,
                fps=fps,
                pattern=pattern,
                encoder=encoder,
                pix_fmt=pix_fmt
            )

        except AssemblyError as e:
            # If preferred encoder failed and it's nvenc, try fallback
            if encoder == self._preferred_encoder:
                self._logger.warning(
                    f"{encoder} failed, falling back to {self._fallback_encoder}"
                )
                self._logger.debug(f"Error was: {e}")

                try:
                    return self._ffmpeg.assemble_video(
                        frames_dir=frames_dir,
                        output_path=output_path,
                        fps=fps,
                        pattern=pattern,
                        encoder=self._fallback_encoder,
                        pix_fmt=pix_fmt
                    )
                except AssemblyError as e2:
                    raise AssemblyError(
                        f"Both {encoder} and {self._fallback_encoder} failed. "
                        f"Last error: {e2}"
                    )
            else:
                # No fallback available
                raise

