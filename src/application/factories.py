"""Factory for creating processors."""

import os
from typing import Optional
from src.domain.protocols import IProcessor
from src.domain.exceptions import ProcessorNotAvailableError
from src.infrastructure.processors import RifePytorchWrapper, RealESRGANPytorchWrapper
from src.infrastructure.processors.subtitle import SubtitleRemoverWrapper
from src.shared.logging import get_logger

# New imports for SAM2 + OCR pipeline
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_adapter import Sam2Adapter
from src.infrastructure.inpainting.propainter_adapter import ProPainterAdapter
from src.services.masking.service import TextMaskService
from src.services.cleaner_service import SubtitleRemoverService

logger = get_logger(__name__)


class ProcessorFactory:
    """
    Factory for creating video processors with auto-detection.

    Supports both shell-based wrappers (default) and native Python implementations.

    Use native implementations for:
    - Better debugging (step-by-step in PyCharm)
    - No shell dependencies
    - Cleaner code

    Enable with:
        factory = ProcessorFactory(use_native=True)
        # or
        export USE_NATIVE_PROCESSORS=1
    """

    def __init__(self, use_native: Optional[bool] = None):
        """
        Initialize factory.

        Args:
            use_native: Use native Python implementations instead of shell wrappers.
                       If None, reads from USE_NATIVE_PROCESSORS env var.
        """
        self._logger = get_logger(__name__)

        # Determine whether to use native implementations
        # Default to '1' (native) for better debugging and pure Python code
        if use_native is None:
            env_value = os.getenv('USE_NATIVE_PROCESSORS', '1')
            use_native = env_value == '1'
            self._logger.debug(f"USE_NATIVE_PROCESSORS env={env_value}, use_native={use_native}")

        self.use_native = use_native

        if self.use_native:
            self._logger.info("[NATIVE] Using NATIVE Python processors (no shell scripts)")
        else:
            self._logger.info("[SHELL] Using shell-wrapped processors (default)")

    def _inject_pure_pytorch_corrblock(self):
        """
        Inject Pure PyTorch CorrBlock into ProPainter's RAFT module.

        ProPainter's RAFT imports:
            from .corr import CorrBlock, AlternateCorrBlock

        We replace spatial_correlation_sampler with Pure PyTorch version.

        **CRITICAL**: ProPainter runs in subprocess, so sys.modules injection
        doesn't work. We need to create actual file: /opt/ProPainter/RAFT/corr.py

        Design pattern: File-based dependency injection (works for subprocess)
        """
        import shutil
        from pathlib import Path

        try:
            # 1. Get paths
            propainter_raft = Path("/opt/ProPainter/RAFT")
            corr_py_dest = propainter_raft / "corr.py"
            corr_py_source = Path(__file__).parent.parent.parent / "docker" / "patches" / "raft_corr.py"

            # 2. Check if ProPainter exists
            if not propainter_raft.exists():
                self._logger.error(f"❌ ProPainter RAFT not found at {propainter_raft}")
                return

            # 3. Backup original if exists (only once)
            if corr_py_dest.exists() and not (propainter_raft / "corr.py.original").exists():
                shutil.copy(corr_py_dest, propainter_raft / "corr.py.original")
                self._logger.info(f"✅ Backed up original corr.py to corr.py.original")

            # 4. ALWAYS overwrite to ensure latest version (e.g. with debug prints)
            # Don't skip if file exists - we need to update it!

            # 5. Copy our Pure PyTorch corr.py
            if not corr_py_source.exists():
                self._logger.error(f"❌ Source corr.py not found at {corr_py_source}")
                # Create it inline - SELF-CONTAINED VERSION (no imports from project)
                corr_py_content = '''#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module - SELF-CONTAINED
======================================================

This file contains the COMPLETE implementation inline.
No imports from external project needed - avoids circular imports.
"""
import torch
import torch.nn.functional as F


class CorrBlock:
    """
    Simple Correlation Block for RAFT - GUARANTEED compatibility.
    
    Self-contained implementation - no external dependencies.
    """
    
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, **kwargs):
        import sys
        print(f"[CorrBlock.__init__] Called with num_levels={num_levels}, radius={radius}, fmap1.shape={fmap1.shape}", file=sys.stderr, flush=True)
        
        self.num_levels = num_levels
        self.radius = radius
        self.device = fmap1.device
        self.dtype = fmap1.dtype
        
        # Normalize
        fmap1 = fmap1.float()
        fmap2 = fmap2.float()
        
        # Build correlation pyramid
        self.corr_pyramid = []
        
        for i in range(num_levels):
            B, C, H, W = fmap1.shape
            
            # Compute all-pairs correlation
            fmap1_flat = fmap1.view(B, C, H * W)
            fmap2_flat = fmap2.view(B, C, H * W)
            
            # Correlation: [B, H*W, H*W]
            corr = torch.matmul(fmap1_flat.transpose(1, 2), fmap2_flat)
            corr = corr / torch.sqrt(torch.tensor(C, dtype=fmap1.dtype, device=fmap1.device))
            
            # Reshape: [B, H, W, H, W]
            corr = corr.view(B, H, W, H, W)
            self.corr_pyramid.append(corr)
            
            # Downsample for next level
            if i < num_levels - 1:
                fmap1 = F.avg_pool2d(fmap1, 2, stride=2)
                fmap2 = F.avg_pool2d(fmap2, 2, stride=2)
        
        print(f"[CorrBlock.__init__] Completed successfully, pyramid has {len(self.corr_pyramid)} levels", file=sys.stderr, flush=True)
    
    def __call__(self, coords):
        """Sample correlation at flow coordinates."""
        import sys
        print(f"[CorrBlock.__call__] Called with coords.shape={coords.shape}", file=sys.stderr, flush=True)
        r = self.radius
        B, _, H, W = coords.shape
        
        out_pyramid = []
        
        for i, corr in enumerate(self.corr_pyramid):
            # Scale coords for this level
            coords_lvl = coords / (2 ** i)
            
            _, H_corr, W_corr, _, _ = corr.shape
            
            # Integer coordinates
            x0 = torch.clamp(coords_lvl[:, 0].long(), 0, W_corr - 1)
            y0 = torch.clamp(coords_lvl[:, 1].long(), 0, H_corr - 1)
            
            # Sample neighborhood
            out_list = []
            for dy in range(-r, r+1):
                for dx in range(-r, r+1):
                    x = torch.clamp(x0 + dx, 0, W_corr - 1)
                    y = torch.clamp(y0 + dy, 0, H_corr - 1)
                    
                    # Index tensors
                    batch_idx = torch.arange(B, device=self.device).view(B, 1, 1).expand(B, H, W)
                    h_idx = torch.arange(H, device=self.device).view(1, H, 1).expand(B, H, W)
                    w_idx = torch.arange(W, device=self.device).view(1, 1, W).expand(B, H, W)
                    
                    # Sample
                    vals = corr[batch_idx, h_idx, w_idx, y, x]
                    out_list.append(vals)
            
            # Stack
            out_lvl = torch.stack(out_list, dim=1)  # [B, (2*r+1)^2, H, W]
            out_pyramid.append(out_lvl)
        
        # Concatenate all levels
        out = torch.cat(out_pyramid, dim=1)
        return out


# AlternateCorrBlock is just an alias
AlternateCorrBlock = CorrBlock

__all__ = ['CorrBlock', 'AlternateCorrBlock']
'''
                corr_py_dest.write_text(corr_py_content)
            else:
                shutil.copy(corr_py_source, corr_py_dest)

            self._logger.info("✅ Injected Pure PyTorch CorrBlock into ProPainter RAFT (file-based)")
            self._logger.info(f"   Created: {corr_py_dest}")
            self._logger.info("   ProPainter subprocess will use Pure PyTorch correlation")

        except Exception as e:
            self._logger.error(f"❌ Failed to inject Pure PyTorch CorrBlock: {e}")
            self._logger.error("   ProPainter may fail if it tries to use spatial-correlation-sampler")

    def _validate_corrblock_injection(self) -> bool:
        """
        Validate that CorrBlock injection succeeded and ProPainter subprocess can use it.

        This is a critical pre-flight check that prevents:
            File "/opt/ProPainter/RAFT/raft.py", line 109, in forward
                corr_fn = CorrBlock

        **CRITICAL**: Checks file-based injection (not sys.modules) since
        ProPainter runs in subprocess.

        Design pattern: Fail-fast validation

        Returns:
            bool: True if validation passed

        Raises:
            RuntimeError: If CorrBlock injection failed and ProPainter will crash
        """
        from pathlib import Path
        import subprocess
        import sys

        try:
            # Check 1: Verify corr.py file exists
            corr_py_path = Path("/opt/ProPainter/RAFT/corr.py")
            if not corr_py_path.exists():
                raise RuntimeError(
                    f"CorrBlock injection failed: {corr_py_path} does not exist.\n"
                    f"ProPainter subprocess cannot import CorrBlock."
                )

            # Check 2: Verify it's our Pure PyTorch version
            content = corr_py_path.read_text()
            if "Pure PyTorch" not in content and "pure_pytorch_correlation" not in content:
                self._logger.warning(
                    f"⚠️  {corr_py_path} exists but may not be our Pure PyTorch version.\n"
                    f"   This may cause issues with spatial-correlation-sampler."
                )

            # Check 3: Test import in separate Python process (simulate ProPainter subprocess)
            test_code = """
import sys
sys.path.insert(0, '/opt/ProPainter')
sys.path.insert(0, '/root/vastai_inerup')  # For Pure PyTorch import
try:
    from RAFT.corr import CorrBlock, AlternateCorrBlock
    print('SUCCESS')
except Exception as e:
    print(f'FAIL: {e}')
"""
            result = subprocess.run(
                [sys.executable, '-c', test_code],
                capture_output=True,
                text=True,
                timeout=5
            )

            if 'SUCCESS' not in result.stdout:
                raise RuntimeError(
                    f"CorrBlock injection validation failed in subprocess:\n"
                    f"STDOUT: {result.stdout}\n"
                    f"STDERR: {result.stderr}\n"
                    f"ProPainter subprocess will not be able to import CorrBlock."
                )

            self._logger.info("✅ CorrBlock validation passed: ProPainter subprocess can import Pure PyTorch")
            return True

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                "CorrBlock validation timeout (5 seconds).\n"
                "Import test hung - this indicates a serious problem."
            )
        except RuntimeError:
            raise  # Re-raise validation errors
        except Exception as e:
            # Unexpected error during validation
            self._logger.error(f"❌ Unexpected error during CorrBlock validation: {e}")
            raise RuntimeError(
                f"CorrBlock validation failed with unexpected error: {e}\n"
                f"ProPainter may not work correctly."
            )

    def create_interpolator(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """
        Create interpolator processor.

        Args:
            prefer: Backend preference ('auto', 'pytorch', 'native')

        Returns:
            Interpolator processor instance
        """
        # If native implementations requested, try native first
        if self.use_native or prefer == 'native':
            try:
                from src.infrastructure.processors.rife.native_wrapper import RIFENativeWrapper
                if RIFENativeWrapper.is_available():
                    self._logger.info("Using RIFE native Python backend")
                    return RIFENativeWrapper()
                else:
                    self._logger.warning("RIFE native is not available (is_available=False), falling back to shell wrapper")
            except ImportError as e:
                self._logger.warning(f"RIFE native import failed: {e}, falling back to shell wrapper")
                if prefer == 'native':
                    raise ProcessorNotAvailableError("RIFE native not available")
                # Fall through to shell wrapper if not explicitly native

        # Shell wrapper (default)
        if prefer in ('auto', 'pytorch'):
            if RifePytorchWrapper and getattr(RifePytorchWrapper, 'is_available', lambda: False)():
                self._logger.info("Using RIFE pytorch backend (shell wrapper)")
                return RifePytorchWrapper()
            raise ProcessorNotAvailableError("No RIFE backend available")


        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")

    def create_subtitle_remover(self, prefer: str = 'auto', lang: str = 'en', backend: str = 'auto', roi: Optional[str] = None) -> Optional[IProcessor]:
        """
        Create subtitle removal processor.

        Args:
            prefer: Backend preference ('auto', 'native', 'propainter') - deprecated, use backend parameter
            lang: Language code for OCR ('en', 'ru', etc.)
            backend: Backend preference ('auto', 'native', 'propainter', 'sam2')
            roi: Region of Interest string. "bottom" (default, 60%), "full" (100%), or float 0.0-1.0

        Returns:
            Subtitle remover processor instance

        Note:
            GPU is required for subtitle removal, but not explicitly checked here.
            If GPU is missing, PaddleOCR/SAM2 will fail with clear error messages.
        """
        # Note: GPU check removed - it was causing false negatives when torch
        # imports before pure PyTorch correlation is installed. PaddleOCR/SAM2
        # will validate GPU when they actually need it.

        # Determine backend (prefer parameter for backward compatibility)
        if backend == 'auto' and prefer != 'auto':
            # If prefer is specified and backend is auto, use prefer
            backend = prefer
        
        # New SAM2 + OCR pipeline
        if backend in ('sam2', 'auto'):
            try:
                # 1. OCR
                ocr = PaddleWrapper(lang=lang, use_gpu=True)
                
                # 2. SAM 2
                # Путь к чекпоинту должен быть в конфиге или ENV
                sam2_ckpt = "/opt/sam2_checkpoints/sam2_hiera_small.pt"
                sam2 = Sam2Adapter(checkpoint_path=sam2_ckpt)
                
                # 3. Mask Service
                mask_service = TextMaskService(ocr=ocr, sam2=sam2)
                
                # 4. Inject Pure PyTorch CorrBlock into ProPainter RAFT (CRITICAL!)
                # ProPainter's RAFT tries to import CorrBlock from spatial_correlation_sampler
                # But we replaced it with Pure PyTorch version, so we need to inject it
                self._inject_pure_pytorch_corrblock()

                # 5. Validate CorrBlock injection
                self._validate_corrblock_injection()

                # 6. Inpainter
                inpainter = ProPainterAdapter()
                
                # 7. Debug mode detection
                import os
                debug_mode = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'

                # 8. Главный сервис
                return SubtitleRemoverService(mask_service, inpainter, lang=lang, roi_factor=roi, debug=debug_mode)
            except Exception as e:
                self._logger.warning(f"SAM2 pipeline failed to initialize: {e}")
                if backend == 'sam2':
                    raise ProcessorNotAvailableError(f"SAM2 pipeline not available: {e}")
                # Fall through to old backend if auto
        
        # Check for old subtitle remover backend (for backward compatibility)
        if backend in ('auto', 'propainter', 'native'):  # native тоже перенаправляем на ProPainter
            if SubtitleRemoverWrapper.is_available():
                self._logger.info(f"Using legacy subtitle remover backend (lang={lang}, roi={roi})")
                # Pass roi parameter to wrapper
                return SubtitleRemoverWrapper(lang=lang, roi=roi)
            else:
                raise ProcessorNotAvailableError("Subtitle remover not available (requires ProPainter installation in /opt/ProPainter)")
        
        raise ProcessorNotAvailableError(f"Unknown backend: {backend}")

    def create_watermark_remover(self,
                                 roi: str = 'top-right',
                                 prefer: str = 'auto',
                                 persistence_threshold: float = 0.8,
                                 expansion: int = 10) -> Optional[IProcessor]:
        """
        Create watermark removal processor.

        Args:
            roi: ROI string (single or multi: "top-right,bottom-left")
            prefer: Backend preference (currently only 'auto' supported)
            persistence_threshold: Ratio of frames a pixel must appear in (0.0-1.0)
            expansion: Mask expansion radius in pixels

        Returns:
            Watermark remover processor instance

        Note:
            GPU is required for watermark removal, but not explicitly checked here.
            If GPU is missing, ProPainter/inpainting will fail with clear error messages.
        """
        # Note: GPU check removed - same reason as subtitle remover
        try:
            from src.infrastructure.processors.watermark.wrapper import WatermarkRemoverWrapper

            if WatermarkRemoverWrapper.is_available():
                self._logger.info(f"Creating watermark remover (roi={roi}, persistence={persistence_threshold})")
                return WatermarkRemoverWrapper(
                    roi=roi,
                    static_detection=True,
                    persistence_threshold=persistence_threshold,
                    expansion=expansion
                )
            else:
                raise ProcessorNotAvailableError(
                    "Watermark remover not available (requires ProPainter installation in /opt/ProPainter)"
                )
        except ImportError as e:
            raise ProcessorNotAvailableError(f"Watermark remover dependencies not found: {e}")

    def create_upscaler(self, prefer: str = 'auto') -> Optional[IProcessor]:
        """
        Create upscaler processor.

        Args:
            prefer: Backend preference ('auto', 'pytorch', 'native')

        Returns:
            Upscaler processor instance
        """
        # If native implementations requested, try native first
        if self.use_native or prefer == 'native':
            try:
                from src.infrastructure.processors.realesrgan.native_wrapper import RealESRGANNativeWrapper
                if RealESRGANNativeWrapper.is_available():
                    self._logger.info("Using Real-ESRGAN native Python backend")
                    return RealESRGANNativeWrapper()
                else:
                    self._logger.warning("Real-ESRGAN native is not available (is_available=False), falling back to shell wrapper")
            except ImportError as e:
                self._logger.warning(f"Real-ESRGAN native import failed: {e}, falling back to shell wrapper")
                if prefer == 'native':
                    raise ProcessorNotAvailableError("Real-ESRGAN native not available")
                # Fall through to shell wrapper if not explicitly native

        # Shell wrapper (default)
        if prefer in ('auto', 'pytorch'):
            if RealESRGANPytorchWrapper and getattr(RealESRGANPytorchWrapper, 'is_available', lambda: False)():
                self._logger.info("Using Real-ESRGAN pytorch backend (shell wrapper)")
                return RealESRGANPytorchWrapper()
            raise ProcessorNotAvailableError("No Real-ESRGAN backend available")


        else:
            raise ProcessorNotAvailableError(f"Unknown prefer: {prefer}")
