import os
import sys
import cv2
import torch
import logging
import numpy as np
import shutil
from pathlib import Path
import time
from typing import List, Optional
import gc

# --- UTILS SETUP ---
import warnings
warnings.filterwarnings('ignore')

# Suppress PaddleOCR logs
import os
os.environ['PADDLEOCR_LOG_LEVEL'] = 'CRITICAL'
os.environ['GLOG_minloglevel'] = '3'

PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
if PROPAINTER_ROOT not in sys.path:
    sys.path.append(PROPAINTER_ROOT)

logger = logging.getLogger(__name__)

# --- IMPORTS ---
try:
    from model.propainter import InpaintGenerator
    # Define read_video helper if missing or broken in repo
    def read_video_local(path: str, gray: bool = False):
        """Robust video reader that returns CPU numpy arrays."""
        from inference_propainter import read_frame_from_videos
        frames, fps, size, video_name = read_frame_from_videos(path)
        arrs = []
        for f in frames:
            if gray:
                f = f.convert('L')
                arr = np.array(f, dtype=np.uint8)[..., np.newaxis]
            else:
                f = f.convert('RGB')
                arr = np.array(f, dtype=np.uint8)
            arrs.append(arr)
        return np.stack(arrs, axis=0), fps
except ImportError:
    logger.warning("ProPainter modules not found")

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

class SubtitleRemoverProPainter:
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        # OPTIMIZATION: Set allocator to reduce fragmentation
        os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True,max_split_size_mb:128'
        
        self.lang = lang
        self.mask_dilation = mask_dilation
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        self._init_ocr()
        self._init_propainter()
        
    def _init_ocr(self):
        if PaddleOCR is None:
            raise ImportError("PaddleOCR not installed")
        
        # Suppress stdout during OCR init
        from contextlib import redirect_stdout
        import io
        with redirect_stdout(io.StringIO()):
            self.ocr = PaddleOCR(
                lang=self.lang,
                use_angle_cls=False,
                use_gpu=False  # Strictly CPU to save VRAM
            )

    def _init_propainter(self):
        weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
        if not weights_path.exists():
            raise FileNotFoundError(f"Weights not found: {weights_path}")
            
        logger.info(f"Loading ProPainter on {self.device}...")
        self.model = InpaintGenerator(model_path=str(weights_path))
        self.model = self.model.to(self.device)
        self.model.eval()

    def process_frames(self, input_dir: Path, output_dir: Path):
        output_dir.mkdir(parents=True, exist_ok=True)
        tmp_mask_dir = output_dir.parent / "tmp_masks_propainter"
        if tmp_mask_dir.exists(): shutil.rmtree(tmp_mask_dir)
        tmp_mask_dir.mkdir()

        # 1. Generate Masks (CPU)
        frames = sorted(list(input_dir.glob("*.png")) + list(input_dir.glob("*.jpg")))
        if not frames: return
        
        logger.info(f"Generating masks for {len(frames)} frames...")
        self._generate_masks_batch(frames, tmp_mask_dir)

        # 2. Run Inference (Memory Optimized)
        logger.info("Running ProPainter Inference...")
        
        # Load raw data to CPU RAM (numpy)
        video_frames_np, _ = read_video_local(str(input_dir))
        video_masks_np, _ = read_video_local(str(tmp_mask_dir), gray=True)
        
        # Convert to Torch CPU Tensors
        # Shape: [T, H, W, C] -> [T, C, H, W]
        frames_t = torch.from_numpy(video_frames_np).permute(0, 3, 1, 2).float() / 255.0
        masks_t = torch.from_numpy(video_masks_np).permute(0, 3, 1, 2).float() / 255.0
        
        # Process in memory-safe chunks
        # CRITICAL: We pass CPU tensors here
        pred_frames = self._process_in_chunks_safe(frames_t, masks_t)
        
        # 3. Save Output
        self._save_frames(pred_frames, frames, output_dir)
        
        # Cleanup
        shutil.rmtree(tmp_mask_dir)
        torch.cuda.empty_cache()

    def _process_in_chunks_safe(self, frames_cpu: torch.Tensor, masks_cpu: torch.Tensor) -> np.ndarray:
        """
        Processes video in chunks, keeping the main data on CPU.
        Only moves active chunk to GPU.
        """
        T, C, H, W = frames_cpu.shape
        
        # Conservative chunk size calculation
        # ProPainter needs heavy memory for optical flow
        if self.device.type == 'cuda':
            total_mem_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
            free_mem_gb = (torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated()) / 1e9
            
            # Conservative estimate: 1 frame (720p/1080p) + flow overhead needs ~0.5GB buffer
            chunk_size = int(free_mem_gb * 1.5) # Try to be safe
            chunk_size = max(4, min(chunk_size, 10)) # Cap between 4 and 10 frames
        else:
            chunk_size = 5

        logger.info(f"Processing {T} frames in chunks of {chunk_size}...")
        
        output_chunks = []
        
        # Ensure masks are binary
        masks_cpu = (masks_cpu > 0.5).float()

        # Iterate
        for i in range(0, T, chunk_size):
            # Define window with overlap (ProPainter works better with context)
            # We strictly slice, ProPainter handles internal connections via recurrent flow
            start = i
            end = min(i + chunk_size, T)
            
            # 1. Move ONLY current chunk to GPU
            f_chunk = frames_cpu[start:end].unsqueeze(0).to(self.device) # [1, t, c, h, w]
            m_chunk = masks_cpu[start:end].unsqueeze(0).to(self.device)
            
            # 2. Prepare inputs
            masked_input = f_chunk * (1 - m_chunk)
            
            # Resize logic for 8-pixel alignment
            _, _, _, h, w = f_chunk.shape
            pad_h = (8 - h % 8) % 8
            pad_w = (8 - w % 8) % 8
            if pad_h > 0 or pad_w > 0:
                import torch.nn.functional as F
                masked_input = F.pad(masked_input, (0, pad_w, 0, pad_h))
                m_chunk = F.pad(m_chunk, (0, pad_w, 0, pad_h))
            
            # 3. Inference
            try:
                with torch.no_grad():
                    # Attempt mixed precision for VRAM saving
                    with torch.amp.autocast('cuda'):
                        # Try robust API call
                        pred = self._robust_forward(masked_input, m_chunk)
            except torch.cuda.OutOfMemoryError:
                logger.error("OOM inside chunk! Clearing cache and trying CPU fallback for this chunk.")
                torch.cuda.empty_cache()
                f_chunk = f_chunk.cpu()
                m_chunk = m_chunk.cpu()
                masked_input = masked_input.cpu()
                self.model.cpu()
                pred = self._robust_forward(masked_input, m_chunk)
                self.model.to(self.device) # Move back

            # 4. Cleanup chunk
            # Remove padding
            pred = pred[0, :, :, :h, :w]
            
            # Move result to CPU immediately
            output_chunks.append(pred.cpu())
            
            # Explicitly delete GPU tensors and clear cache
            del f_chunk, m_chunk, masked_input, pred
            torch.cuda.empty_cache()
            
            logger.info(f"Processed frames {start}-{end}")

        # Concatenate all CPU chunks
        return torch.cat(output_chunks, dim=0).permute(0, 2, 3, 1).numpy() * 255.0

    def _robust_forward(self, masked_input, masks):
        """Tries different API signatures for ProPainter."""
        try:
            # Newest API (7 args)
            b, t, c, h, w = masked_input.shape
            completed_flows = torch.zeros((b, t-1, 2, h, w), device=masked_input.device)
            return self.model(masked_input, completed_flows, masks, masks, 10, 'bilinear', 2)
        except Exception:
            try:
                # 4 args
                return self.model(masked_input, masks, masks, 10)
            except Exception:
                # 2 args
                return self.model(masked_input, masks)

    def _generate_masks_batch(self, paths: List[Path], out_dir: Path):
        # Using simple sequential processing to avoid threading overhead/errors with Paddle
        for p in paths:
            self._create_single_mask(p, out_dir / p.name)

    def _create_single_mask(self, img_path: Path, mask_path: Path):
        img = cv2.imread(str(img_path))
        if img is None: return
        h, w = img.shape[:2]
        mask = np.zeros((h, w), dtype=np.uint8)
        
        res = self.ocr.ocr(img, cls=False)
        if res and res[0]:
            for line in res[0]:
                coords = line[0]
                conf = line[1][1]
                if conf > 0.4:
                    pts = np.array(coords, dtype=np.int32).reshape((-1, 1, 2))
                    cv2.fillPoly(mask, [pts], 255)
        
        if self.mask_dilation > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (self.mask_dilation, self.mask_dilation))
            mask = cv2.dilate(mask, kernel, iterations=1)
        
        cv2.imwrite(str(mask_path), mask)

    def _save_frames(self, frames_np, original_paths, output_dir):
        frames_np = frames_np.astype(np.uint8)
        for i, frame in enumerate(frames_np):
            name = original_paths[i].name
            # RGB -> BGR
            cv2.imwrite(str(output_dir / name), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

# --- Wrapper for Orchestrator Compatibility ---
from domain.models import ProcessingResult
class SubtitleRemoverProPainterWrapper:
    def __init__(self, lang: str = 'en', mask_dilation: int = 12):
        self._lang = lang
        self._mask_dilation = mask_dilation
        self._processor = None
        self._logger = logging.getLogger(__name__)

    def process(self, input_frames: List[Path], output_dir: Path, **kwargs) -> ProcessingResult:
        import time
        start = time.time()
        # Find directory from list of files
        if not input_frames:
            return ProcessingResult(success=False, errors=["No frames"])
        input_dir = input_frames[0].parent
        
        try:
            if self._processor is None:
                self._processor = SubtitleRemoverProPainter(self._lang, self._mask_dilation)
            self._processor.process_frames(input_dir, output_dir)
            return ProcessingResult(
                success=True, 
                output_path=output_dir,
                frames_processed=len(input_frames),
                duration_seconds=time.time() - start
            )
        except Exception as e:
            self._logger.exception("ProPainter failed")
            return ProcessingResult(success=False, errors=[str(e)])

    @classmethod
    def is_available(cls) -> bool:
        """Check if ProPainter subtitle remover is available."""
        try:
            import cv2
            import torch
            import numpy as np
            from paddleocr import PaddleOCR  # noqa: F401
            
            # Check if ProPainter modules are available
            PROPAINTER_ROOT = os.getenv("PROPAINTER_ROOT", "/opt/ProPainter")
            if PROPAINTER_ROOT not in sys.path:
                sys.path.append(PROPAINTER_ROOT)
            
            try:
                from model.propainter import InpaintGenerator
                from inference_propainter import read_frame_from_videos
                
                # Check if weights exist
                weights_path = Path(PROPAINTER_ROOT) / "weights/ProPainter.pth"
                if not weights_path.exists():
                    logger.warning(f"ProPainter weights not found: {weights_path}")
                    return False
                    
                return True
            except ImportError:
                logger.warning("ProPainter modules not found")
                return False
                
        except ImportError:
            return False

    def supports_gpu(self) -> bool:
        """Check if GPU is supported (ProPainter uses GPU if available)."""
        return torch.cuda.is_available()
