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

            # 4. ALWAYS use inline version - most reliable!
            # Source file on server may be outdated
            self._logger.info(f"📝 Creating bulletproof inline corr.py:")
            self._logger.info(f"   Dest: {corr_py_dest}")

            # Create it inline - BULLETPROOF IMPLEMENTATION
            corr_py_content = '''#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module - BULLETPROOF
===================================================

This matches the ORIGINAL C++ API exactly but uses Pure PyTorch internally.
Accepts ANY arguments for maximum compatibility.
"""
import torch
import torch.nn.functional as F


def bilinear_sampler(img, coords, mode='bilinear', mask=False):
    """Bilinear sampler for grid sampling"""
    H, W = img.shape[-2:]
    xgrid, ygrid = coords.split([1,1], dim=-1)
    xgrid = 2*xgrid/(W-1) - 1
    ygrid = 2*ygrid/(H-1) - 1

    grid = torch.cat([xgrid, ygrid], dim=-1)
    img = F.grid_sample(img, grid, align_corners=True)

    if mask:
        mask = (xgrid > -1) & (ygrid > -1) & (xgrid < 1) & (ygrid < 1)
        return img, mask.float()

    return img


class CorrBlock:
    """
    Correlation Block - matches original C++ API exactly.
    
    BULLETPROOF: Accepts *args, **kwargs for maximum compatibility.
    """
    
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, *args, **kwargs):
        # Accept ANY arguments - be compatible with any calling convention
        self.num_levels = num_levels
        self.radius = radius
        self.corr_pyramid = []

        # All pairs correlation (original algorithm)
        corr = CorrBlock.corr(fmap1, fmap2)

        batch, h1, w1, dim, h2, w2 = corr.shape
        corr = corr.reshape(batch*h1*w1, dim, h2, w2)

        self.corr_pyramid.append(corr)
        for i in range(self.num_levels-1):
            corr = F.avg_pool2d(corr, 2, stride=2)
            self.corr_pyramid.append(corr)

    def __call__(self, coords):
        """Sample correlation at coordinates."""
        r = self.radius
        coords = coords.permute(0, 2, 3, 1)
        batch, h1, w1, _ = coords.shape

        out_pyramid = []
        for i in range(self.num_levels):
            corr = self.corr_pyramid[i]
            dx = torch.linspace(-r, r, 2*r+1, device=coords.device)
            dy = torch.linspace(-r, r, 2*r+1, device=coords.device)
            # Use default indexing (ij) for compatibility
            delta_y, delta_x = torch.meshgrid(dy, dx)
            delta = torch.stack([delta_y, delta_x], axis=-1)

            centroid_lvl = coords.reshape(batch*h1*w1, 1, 1, 2) / 2**i
            delta_lvl = delta.view(1, 2*r+1, 2*r+1, 2)
            coords_lvl = centroid_lvl + delta_lvl

            corr = bilinear_sampler(corr, coords_lvl)
            corr = corr.view(batch, h1, w1, -1)
            out_pyramid.append(corr)

        out = torch.cat(out_pyramid, dim=-1)
        return out.permute(0, 3, 1, 2).contiguous().float()

    @staticmethod
    def corr(fmap1, fmap2):
        """Compute all-pairs correlation"""
        batch, dim, ht, wd = fmap1.shape
        fmap1 = fmap1.view(batch, dim, ht*wd)
        fmap2 = fmap2.view(batch, dim, ht*wd)

        corr = torch.matmul(fmap1.transpose(1,2), fmap2)
        corr = corr.view(batch, ht, wd, 1, ht, wd)
        return corr / torch.sqrt(torch.tensor(dim).float())


# AlternateCorrBlock is just an alias
AlternateCorrBlock = CorrBlock

__all__ = ['CorrBlock', 'AlternateCorrBlock']
'''
            corr_py_dest.write_text(corr_py_content)
            self._logger.info(f"   ✅ Created inline corr.py ({len(corr_py_content)} bytes)")

            # Verify file was written
            if corr_py_dest.exists():
                size = corr_py_dest.stat().st_size
                content_preview = corr_py_dest.read_text()[:200]
                self._logger.info(f"   ✅ Verification: {corr_py_dest} exists ({size} bytes)")
                if "[CorrBlock.__init__]" in corr_py_dest.read_text():
                    self._logger.info(f"   ✅ Debug prints confirmed in file")
                else:
                    self._logger.warning(f"   ⚠️  Debug prints NOT found in file!")
            else:
                self._logger.error(f"   ❌ File not created: {corr_py_dest}")

            self._logger.info("✅ Injected Pure PyTorch CorrBlock into ProPainter RAFT (file-based)")
            self._logger.info(f"   Created: {corr_py_dest}")
            self._logger.info("   ProPainter subprocess will use Pure PyTorch correlation")

            # CRITICAL FIX: Patch raft.py to ensure it imports our corr.py
            # Problem: raft.py imports fail at runtime in subprocess
            # Solution: Force explicit import from .corr instead of trying spatial_correlation_sampler
            raft_py = propainter_raft / "raft.py"
            if raft_py.exists():
                raft_content = raft_py.read_text()

                # Check if already patched
                if "# PATCHED: Pure PyTorch import" not in raft_content:
                    # Find the import line
                    old_import = "from .corr import CorrBlock, AlternateCorrBlock"
                    new_import = """# PATCHED: Pure PyTorch import (no spatial_correlation_sampler)
from .corr import CorrBlock, AlternateCorrBlock"""

                    if old_import in raft_content:
                        raft_content = raft_content.replace(old_import, new_import)
                        raft_py.write_text(raft_content)
                        self._logger.info("✅ Patched raft.py import to use Pure PyTorch CorrBlock")
                    else:
                        self._logger.warning("⚠️  Could not find import line in raft.py to patch")
                else:
                    self._logger.info("✅ raft.py already patched for Pure PyTorch")

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
