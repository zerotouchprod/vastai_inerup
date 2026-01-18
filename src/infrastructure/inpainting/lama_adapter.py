"""
LaMaAdapter - Facade for LaMa inpainting using external inference script.
Uses /opt/LaMa-Wire/inference_lama.py for actual inference.
Optimized for RTX 2060 Mobile (6GB VRAM) with FP16 and resize to 1280px.
"""
import subprocess
import os
from pathlib import Path
from typing import Union, List, Optional
import cv2
import numpy as np

from src.shared.logging import get_logger
from src.core.config import get_config
from src.core.exceptions import ProcessorNotAvailableError
from src.schemas.roi import InpaintConfig

logger = get_logger(__name__)


class LaMaAdapter:
    """
    Adapter for LaMa inpainting that calls external inference script.
    Follows the same interface as ProPainterAdapter for compatibility.
    """
    
    def __init__(self):
        self.config = get_config()
        # Use local script within project
        self.script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "inference_lama.py"
        self.model_path = Path("/opt/lama_models/big-lama.pt")
        
        # Ensure script exists
        if not self.script_path.exists():
            logger.error(f"❌ LaMa script not found at {self.script_path}")
            logger.info("Please ensure scripts/inference_lama.py exists in the project")
            raise FileNotFoundError(f"LaMa script not found at {self.script_path}")
        
        logger.info(f"✅ LaMaAdapter initialized (script: {self.script_path}, model: {self.model_path})")
    
    
    def process(
        self, 
        frames_dir: Union[str, Path], 
        mask_dir: Union[str, Path], 
        output_dir: Union[str, Path]
    ) -> str:
        """
        Runs LaMa inference on the given directories.
        
        Args:
            frames_dir: Directory containing input frames
            mask_dir: Directory containing mask frames
            output_dir: Directory to save inpainted frames
            
        Returns:
            Path to output directory
            
        Raises:
            ProcessorNotAvailableError: If LaMa script fails
            RuntimeError: If subprocess fails
        """
        frames_dir = Path(frames_dir)
        mask_dir = Path(mask_dir)
        output_dir = Path(output_dir)
        
        logger.info(f"🚀 Starting LaMa Adapter on {frames_dir}")
        
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Build command
        cmd = [
            "python3", str(self.script_path),
            "--input_dir", str(frames_dir),
            "--mask_dir", str(mask_dir),
            "--output_dir", str(output_dir),
            "--model_path", str(self.model_path)
            # FP16 flag removed - script uses FP32 by default
        ]
        
        logger.debug(f"LaMa command: {' '.join(cmd)}")
        
        try:
            # Run inference from project root
            project_root = Path(__file__).parent.parent.parent.parent
            result = subprocess.run(
                cmd, 
                check=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True,
                cwd=str(project_root)  # Run from project root
            )
            
            # Log output
            if result.stdout:
                logger.info(f"LaMa stdout: {result.stdout[:500]}...")
            if result.stderr:
                logger.debug(f"LaMa stderr: {result.stderr[:500]}...")
            
            logger.info("✅ LaMa processing finished successfully")
            return str(output_dir)
            
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ LaMa failed with exit code {e.returncode}")
            logger.error(f"Stderr: {e.stderr[:1000]}")
            raise ProcessorNotAvailableError(
                f"LaMa execution failed: {e.stderr[:500]}"
            )
        except FileNotFoundError as e:
            logger.error(f"❌ LaMa script not found: {e}")
            raise ProcessorNotAvailableError(
                f"LaMa script not found at {self.script_path}"
            )
    
    def process_with_roi(
        self,
        frame: np.ndarray,
        mask: np.ndarray,
        config: Optional[InpaintConfig] = None
    ) -> np.ndarray:
        """
        Process single frame with ROI optimization.
        This is a simplified version that creates temporary directories
        and calls the main process method.
        
        Note: For production use, batch processing is recommended.
        """
        if config is None:
            config = InpaintConfig()
        
        import tempfile
        from pathlib import Path
        
        # Create temporary directories
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            frames_dir = tmp_path / "frames"
            masks_dir = tmp_path / "masks"
            output_dir = tmp_path / "output"
            
            frames_dir.mkdir()
            masks_dir.mkdir()
            output_dir.mkdir()
            
            # Save frame and mask
            frame_path = frames_dir / "frame_001.png"
            mask_path = masks_dir / "frame_001.png"
            
            cv2.imwrite(str(frame_path), frame)
            cv2.imwrite(str(mask_path), mask)
            
            # Process using main method
            try:
                self.process(frames_dir, masks_dir, output_dir)
                
                # Load result
                result_path = output_dir / "frame_001.png"
                if result_path.exists():
                    result = cv2.imread(str(result_path))
                    return result
                else:
                    raise RuntimeError("LaMa did not produce output")
                    
            except Exception as e:
                logger.error(f"LaMa ROI processing failed: {e}")
                if config.fallback_to_cv2:
                    logger.warning("Falling back to OpenCV Telea inpainting")
                    mask_uint8 = (mask > 0).astype(np.uint8) * 255
                    return cv2.inpaint(frame, mask_uint8, 3, cv2.INPAINT_TELEA)
                else:
                    raise
    
    def _inpaint_batch(
        self, 
        frames: List[np.ndarray], 
        masks: List[np.ndarray],
        use_roi: bool = False,
        padding_px: int = 50
    ) -> List[np.ndarray]:
        """
        Inpaint a batch of frames using LaMa.
        Creates temporary directories and calls process().
        """
        import tempfile
        from pathlib import Path
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            frames_dir = tmp_path / "frames"
            masks_dir = tmp_path / "masks"
            output_dir = tmp_path / "output"
            
            frames_dir.mkdir()
            masks_dir.mkdir()
            output_dir.mkdir()
            
            # Save all frames and masks
            for i, (frame, mask) in enumerate(zip(frames, masks)):
                frame_path = frames_dir / f"frame_{i:04d}.png"
                mask_path = masks_dir / f"frame_{i:04d}.png"
                cv2.imwrite(str(frame_path), frame)
                cv2.imwrite(str(mask_path), mask)
            
            # Process batch
            self.process(frames_dir, masks_dir, output_dir)
            
            # Load results
            results = []
            for i in range(len(frames)):
                result_path = output_dir / f"frame_{i:04d}.png"
                if result_path.exists():
                    result = cv2.imread(str(result_path))
                    results.append(result)
                else:
                    # Fallback to original frame
                    results.append(frames[i].copy())
            
            return results


# Backward compatibility
class LaMaModelAdapter:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("Use LaMaAdapter instead.")
