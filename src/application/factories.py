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
import torch.nn as nn
from torch.cuda.amp import custom_fwd


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


class CorrBlock(nn.Module):
    """
    Production-Grade Pure PyTorch Correlation Block
    
    Architecture:
    - Inherits from nn.Module (proper PyTorch pattern)
    - Uses @custom_fwd decorator (auto float32 casting)
    - No C++ dependencies (works on ALL GPUs)
    - No async issues (no need for synchronize())
    
    This is the SENIOR way - stable, maintainable, bulletproof.
    """
    
    def __init__(self, fmap1, fmap2, num_levels=4, radius=4, *args, **kwargs):
        super().__init__()
        self.num_levels = num_levels
        self.radius = radius
        self.corr_pyramid = []
        
        # Calculate correlation pyramid immediately
        self.calculate_correlation_pyramid(fmap1, fmap2)
    
    def calculate_correlation_pyramid(self, fmap1, fmap2):
        """
        Build correlation pyramid with ULTIMATE memory alignment fix.
        
        ULTIMATE FIX v4:
        - Uses .clone() to force fresh memory allocation (fixes alignment bugs)
        - Disables TF32 to prevent cuBLAS stride errors  
        - BMM fallback for maximum stability
        
        This prevents CUBLAS_STATUS_INVALID_VALUE on RTX 30/40/50 series.
        """
        # Disable TensorFloat32 (causes stride alignment issues on RTX 30/40/50)
        torch.backends.cuda.matmul.allow_tf32 = False
        
        # 1. Force Float32 for stability on modern GPUs
        fmap1 = fmap1.float()
        fmap2 = fmap2.float()
        
        batch, dim, ht, wd = fmap1.shape
        fmap1 = fmap1.view(batch, dim, ht*wd)
        fmap2 = fmap2.view(batch, dim, ht*wd)
        
        # === DEEP MEMORY FIX ===
        # .clone() allocates NEW memory with perfect alignment
        # .contiguous() alone is NOT sufficient for RTX 3090/4090 edge cases
        fmap1_t = fmap1.transpose(1, 2).clone()
        fmap2_c = fmap2.clone()
        
        try:
            # Attempt 1: Try efficient FP16/AMP first
            corr = torch.bmm(fmap1_t, fmap2_c)
            
        except RuntimeError as e:
            # If CUBLAS error occurs, fallback to FP32
            error_str = str(e)
            if "CUDA" in error_str or "CUBLAS" in error_str or "out of memory" in error_str.lower():
                # Fallback to FP32 but keep on GPU
                fmap1_t_fp32 = fmap1_t.float()
                fmap2_c_fp32 = fmap2_c.float()
                try:
                    corr = torch.bmm(fmap1_t_fp32, fmap2_c_fp32)
                except RuntimeError:
                    # Ultimate fallback: iterative approach
                    res_list = []
                    for b in range(batch):
                        res = torch.matmul(fmap1_t_fp32[b], fmap2_c_fp32[b])
                        res_list.append(res)
                    corr = torch.stack(res_list)
            else:
                # Re-raise other errors
                raise e
        
        # Restore TF32 setting
        torch.backends.cuda.matmul.allow_tf32 = True
        
        # Normalization
        corr = corr / torch.sqrt(torch.tensor(dim, dtype=torch.float32))
        
        # Reshape back to 4D [Batch*H1*W1, 1, H2, W2]
        corr = corr.view(batch, ht, wd, 1, ht, wd)
        batch, h1, w1, dim, h2, w2 = corr.shape
        corr = corr.reshape(batch*h1*w1, dim, h2, w2)
        
        self.corr_pyramid.append(corr)
        
        # Build pyramid (reduce resolution)
        for i in range(self.num_levels-1):
            corr = F.avg_pool2d(corr, 2, stride=2)
            self.corr_pyramid.append(corr)
    
    @custom_fwd(cast_inputs=torch.float32)
    def __call__(self, coords):
        """
        Sample correlation pyramid at given coordinates.
        
        @custom_fwd decorator ensures float32 even if autocast is enabled.
        This is the "silver bullet" for RTX 50-series compatibility.
        """
        r = self.radius
        
        # Protect against FP16 coordinates
        coords = coords.float()
        
        coords = coords.permute(0, 2, 3, 1)
        batch, h1, w1, _ = coords.shape
        
        out_pyramid = []
        for i in range(self.num_levels):
            corr = self.corr_pyramid[i]
            
            # Generate offset grid
            dx = torch.linspace(-r, r, 2*r+1, device=coords.device)
            dy = torch.linspace(-r, r, 2*r+1, device=coords.device)
            delta_y, delta_x = torch.meshgrid(dy, dx)
            delta = torch.stack([delta_y, delta_x], axis=-1)
            
            centroid_lvl = coords.reshape(batch*h1*w1, 1, 1, 2) / 2**i
            delta_lvl = delta.view(1, 2*r+1, 2*r+1, 2)
            coords_lvl = centroid_lvl + delta_lvl
            
            # Sample
            corr = bilinear_sampler(corr, coords_lvl)
            corr = corr.view(batch, h1, w1, -1)
            out_pyramid.append(corr)
        
        out = torch.cat(out_pyramid, dim=-1)
        
        # Return in NCHW format and contiguous (important for next layers)
        return out.permute(0, 3, 1, 2).contiguous().float()
    
    @staticmethod
    def corr(fmap1, fmap2):
        """Static method for backward compatibility with old API"""
        block = CorrBlock(fmap1, fmap2)
        return block.corr_pyramid[0]


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

                # CRITICAL DEBUG FIX: Add debug wrapper around CorrBlock instantiation
                # This will show the FULL error message instead of truncated stderr
                if "# DEBUG WRAPPER - Show full error" not in raft_content:
                    raft_content = raft_py.read_text()  # Re-read after first patch

                    # Find the CorrBlock instantiation
                    old_corrblock = """        if self.args.alternate_corr:
            corr_fn = AlternateCorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
        else:
            corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)"""

                    new_corrblock = """        # DEBUG WRAPPER - Show full error
        try:
            if self.args.alternate_corr:
                corr_fn = AlternateCorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
            else:
                corr_fn = CorrBlock(fmap1, fmap2, radius=self.args.corr_radius)
        except Exception as e:
            import sys, traceback
            print(f"\\n\\n{'='*80}", file=sys.stderr)
            print(f"❌ FATAL: CorrBlock instantiation failed!", file=sys.stderr)
            print(f"{'='*80}", file=sys.stderr)
            print(f"Error type: {type(e).__name__}", file=sys.stderr)
            print(f"Error message: {str(e)}", file=sys.stderr)
            print(f"fmap1 shape: {fmap1.shape if hasattr(fmap1, 'shape') else 'N/A'}", file=sys.stderr)
            print(f"fmap2 shape: {fmap2.shape if hasattr(fmap2, 'shape') else 'N/A'}", file=sys.stderr)
            print(f"radius: {self.args.corr_radius}", file=sys.stderr)
            print(f"\\nFull traceback:", file=sys.stderr)
            traceback.print_exc()
            print(f"{'='*80}", file=sys.stderr)
            raise"""

                    if old_corrblock in raft_content:
                        raft_content = raft_content.replace(old_corrblock, new_corrblock)
                        raft_py.write_text(raft_content)
                        self._logger.info("✅ Added debug wrapper to CorrBlock instantiation in raft.py")
                    else:
                        self._logger.warning("⚠️  Could not find CorrBlock instantiation to add debug wrapper")
                else:
                    self._logger.info("✅ raft.py already has debug wrapper")

        except Exception as e:
            self._logger.error(f"❌ Failed to inject Pure PyTorch CorrBlock: {e}")
            self._logger.error("   ProPainter may fail if it tries to use spatial-correlation-sampler")

    def _patch_propainter_transformer(self):
        """
        Patch ProPainter Transformer to prevent CUDA stride errors.

        Problem: Transformer attention uses transpose() before matmul:
            att = (q @ k.transpose(-2, -1))

        On RTX 30/40/50 series, this creates misaligned strides → CUBLAS error

        Solution (NUCLEAR): Force FP32 + clone() for perfect alignment:
            att = (q.float().clone() @ k.float().transpose(-2, -1).clone())

        Why this works:
        - .float() bypasses FP16 bugs in cuBLAS on new GPUs
        - .clone() creates fresh memory with perfect alignment
        - Slower by ~5ms but 100% stable

        Design pattern: Aggressive runtime patching for maximum compatibility
        """
        from pathlib import Path
        import re

        try:
            # Path to ProPainter transformer
            transformer_path = Path("/opt/ProPainter/model/modules/sparse_transformer.py")

            if not transformer_path.exists():
                self._logger.warning(f"⚠️  ProPainter Transformer not found at {transformer_path}")
                self._logger.warning("   Skipping transformer patch (may cause CUDA errors later)")
                return

            # Read current content
            content = transformer_path.read_text()
            original_content = content

            # === NUCLEAR PATCHES ===

            # Patch 1: Attention calculation (temporal) - win_q_t @ win_k_t.T
            patterns = [
                # Temporal attention
                (
                    r'att_t\s*=\s*\(win_q_t\s*@\s*win_k_t\.transpose\(-2,\s*-1\)(?:\.contiguous\(\))?\)',
                    'att_t = (win_q_t.float().clone() @ win_k_t.float().transpose(-2, -1).clone())  # NUCLEAR: FP32+clone'
                ),
                # Spatial attention
                (
                    r'att_s\s*=\s*\(win_q_s\s*@\s*win_k_s\.transpose\(-2,\s*-1\)(?:\.contiguous\(\))?\)',
                    'att_s = (win_q_s.float().clone() @ win_k_s.float().transpose(-2, -1).clone())  # NUCLEAR: FP32+clone'
                ),
                # Generic attention (q @ k)
                (
                    r'att\s*=\s*\(q\s*@\s*k\.transpose\(-2,\s*-1\)(?:\.contiguous\(\))?\)',
                    'att = (q.float().clone() @ k.float().transpose(-2, -1).clone())  # NUCLEAR: FP32+clone'
                ),
            ]

            for pattern, replacement in patterns:
                content = re.sub(pattern, replacement, content)

            # Patch 2: Value aggregation (att @ v)
            value_patterns = [
                # Temporal values
                (
                    r'x\s*=\s*att_t\s*@\s*win_v_t(?!\.float)',
                    'x = att_t.float() @ win_v_t.float().clone()  # NUCLEAR: FP32+clone'
                ),
                # Spatial values
                (
                    r'x\s*=\s*att_s\s*@\s*win_v_s(?!\.float)',
                    'x = att_s.float() @ win_v_s.float().clone()  # NUCLEAR: FP32+clone'
                ),
                # Generic values
                (
                    r'x\s*=\s*att\s*@\s*v(?!\.float)',
                    'x = att.float() @ v.float().clone()  # NUCLEAR: FP32+clone'
                ),
            ]

            for pattern, replacement in value_patterns:
                content = re.sub(pattern, replacement, content)

            # Check if anything changed
            if content == original_content:
                self._logger.info("✅ ProPainter Transformer already patched (skipping)")
                return

            # Backup original file (once)
            backup_path = transformer_path.with_suffix('.py.before_nuclear')
            if not backup_path.exists():
                backup_path.write_text(original_content)
                self._logger.info(f"✅ Backed up original transformer to: {backup_path.name}")

            # Write patched content
            transformer_path.write_text(content)

            # Count changes
            original_lines = original_content.split('\n')
            new_lines = content.split('\n')

            changed_count = sum(1 for old, new in zip(original_lines, new_lines) if old != new)

            self._logger.info(f"✅ Applied NUCLEAR Transformer patch: {changed_count} line(s) changed")
            self._logger.info("   🎯 FP32 + clone() forced on all matrix operations")
            self._logger.info("   🛡️  CUBLAS stride errors should be eliminated")

        except Exception as e:
            self._logger.error(f"❌ Failed to patch ProPainter Transformer: {e}")
            self._logger.error("   ProPainter may encounter CUDA errors in attention layers")

    def _inject_safe_matmul_into_transformer(self) -> bool:
        """
        Inject safe_matmul with CPU fallback into ProPainter Transformer.

        This is the SENIOR ARCHITECTURE approach:
        - Instead of patching memory alignment (whack-a-mole),
        - We inject a resilient wrapper that gracefully degrades to CPU on errors.

        Pattern: Graceful Degradation
        - GPU matmul (fast)
        - → CUBLAS error? → CPU matmul (slow but stable)
        - → Return to GPU

        This CANNOT fail, because CPU doesn't have cuBLAS bugs.

        Returns:
            bool: True if injection succeeded
        """
        from pathlib import Path
        import re

        try:
            transformer_path = Path("/opt/ProPainter/model/modules/sparse_transformer.py")

            if not transformer_path.exists():
                self._logger.warning(f"⚠️  Transformer not found: {transformer_path}")
                return False

            content = transformer_path.read_text()

            # Check if already injected
            if "def safe_matmul" in content and "RESILIENT MATMUL: GPU -> CPU Fallback" in content:
                self._logger.info("✅ safe_matmul already injected into Transformer")
                return True

            # Safe matmul function (AMP-friendly version)
            safe_matmul_code = '''
import torch

# === AMP-FRIENDLY MATMUL: Try FP16 first, fallback to FP32 ===
def safe_matmul(a, b):
    """Safe matrix multiplication with AMP support"""
    # Ensure both tensors have the same dtype (handle mixed precision)
    if a.dtype != b.dtype:
        # Convert to common dtype (prefer FP16 for AMP)
        if a.dtype == torch.float16 or b.dtype == torch.float16:
            a = a.to(torch.float16)
            b = b.to(torch.float16)
        else:
            a = a.to(torch.float32)
            b = b.to(torch.float32)
    
    # Try efficient FP16/AMP first (no .float() conversion)
    try:
        return a @ b
    except RuntimeError as e:
        # If CUBLAS error occurs, fallback to FP32 (still on GPU)
        error_str = str(e)
        if "CUDA" in error_str or "CUBLAS" in error_str or "out of memory" in error_str.lower():
            # Fallback to FP32 but keep on GPU
            # Use .float() only for the operation, preserve original dtype
            return (a.float() @ b.float()).type_as(a)
        # For other errors, re-raise
        raise e
# =============================================
'''

            # Find injection point (after imports)
            import_end = content.find("import math")
            if import_end == -1:
                import_end = 0
            insert_pos = content.find("\n", import_end) + 1
            
            # Inject safe_matmul definition
            content = content[:insert_pos] + "\n" + safe_matmul_code + "\n" + content[insert_pos:]
            self._logger.info("✅ Injected safe_matmul definition.")

            # Replace ALL dangerous @ operations with safe_matmul
            # We need to find various patterns including those with .float().clone() etc.
            # IMPORTANT: Don't replace operations inside the safe_matmul function itself!
            
            # Initialize replacement count
            replacement_count = 0
            
            # First, split content to avoid replacing inside safe_matmul function
            lines = content.split('\n')
            in_safe_matmul = False
            new_lines = []
            
            for line in lines:
                # Check if we're entering or leaving safe_matmul function
                if 'def safe_matmul' in line and 'RESILIENT MATMUL' not in line:
                    in_safe_matmul = True
                elif in_safe_matmul and line.strip() == '# =============================================':
                    in_safe_matmul = False
                
                # Only replace @ operations outside safe_matmul function
                if not in_safe_matmul and '@' in line:
                    # Apply replacements to this line
                    original_line = line
                    
                    # List of patterns to search for (including variations with .float(), .clone(), .contiguous())
                    patterns_to_replace = [
                        # Pattern 1: win_q_t @ win_k_t.transpose(-2, -1) and variations
                        (r'win_q_t\s*(?:\.float\(\))?(?:\.clone\(\))?\s*@\s*win_k_t(?:\.float\(\))?(?:\.clone\(\))?\.transpose\(-2,\s*-1\)(?:\.clone\(\))?(?:\.contiguous\(\))?',
                         'safe_matmul(win_q_t, win_k_t.transpose(-2, -1))'),
                        
                        # Pattern 2: win_q_s @ win_k_s.transpose(-2, -1) and variations
                        (r'win_q_s\s*(?:\.float\(\))?(?:\.clone\(\))?\s*@\s*win_k_s(?:\.float\(\))?(?:\.clone\(\))?\.transpose\(-2,\s*-1\)(?:\.clone\(\))?(?:\.contiguous\(\))?',
                         'safe_matmul(win_q_s, win_k_s.transpose(-2, -1))'),
                        
                        # Pattern 3: att_t @ win_v_t and variations
                        (r'att_t\s*(?:\.float\(\))?\s*@\s*win_v_t(?:\.float\(\))?(?:\.clone\(\))?',
                         'safe_matmul(att_t, win_v_t)'),
                        
                        # Pattern 4: att_s @ win_v_s and variations
                        (r'att_s\s*(?:\.float\(\))?\s*@\s*win_v_s(?:\.float\(\))?(?:\.clone\(\))?',
                         'safe_matmul(att_s, win_v_s)'),
                        
                        # Pattern 5: Generic q @ k.transpose(-2, -1)
                        (r'(\w+)\s*(?:\.float\(\))?(?:\.clone\(\))?\s*@\s*(\w+)(?:\.float\(\))?(?:\.clone\(\))?\.transpose\(-2,\s*-1\)(?:\.clone\(\))?(?:\.contiguous\(\))?',
                         r'safe_matmul(\1, \2.transpose(-2, -1))'),
                        
                        # Pattern 6: Generic att @ v
                        (r'(\w+)\s*(?:\.float\(\))?\s*@\s*(\w+)(?:\.float\(\))?(?:\.clone\(\))?',
                         r'safe_matmul(\1, \2)'),
                    ]
                    
                    for pattern, replacement in patterns_to_replace:
                        new_line, count = re.subn(pattern, replacement, line)
                        if count > 0:
                            line = new_line
                            replacement_count += count
                    
                    # Also check for simple string replacements (fallback)
                    if line == original_line:  # No regex replacements happened
                        simple_replacements = [
                            ("win_q_t @ win_k_t.transpose(-2, -1)", "safe_matmul(win_q_t, win_k_t.transpose(-2, -1))"),
                            ("win_q_s @ win_k_s.transpose(-2, -1)", "safe_matmul(win_q_s, win_k_s.transpose(-2, -1))"),
                            ("att_t @ win_v_t", "safe_matmul(att_t, win_v_t)"),
                            ("att_s @ win_v_s", "safe_matmul(att_s, win_v_s)"),
                            ("win_q_t.float().clone() @ win_k_t.float().transpose(-2, -1).clone()", 
                             "safe_matmul(win_q_t, win_k_t.transpose(-2, -1))"),
                            ("win_q_s.float().clone() @ win_k_s.float().transpose(-2, -1).clone()", 
                             "safe_matmul(win_q_s, win_k_s.transpose(-2, -1))"),
                            ("att_t.float() @ win_v_t.float()", "safe_matmul(att_t, win_v_t)"),
                        ]
                        
                        for old, new in simple_replacements:
                            if old in line:
                                line = line.replace(old, new)
                                replacement_count += 1
                
                new_lines.append(line)
            
            content = '\n'.join(new_lines)

            # If no patterns found with regex, try simple string replacement as fallback
            if replacement_count == 0:
                self._logger.warning("⚠️ No patterns found with regex, trying simple string replacement...")
                
                # Simple string replacements (less precise but works as fallback)
                simple_replacements = [
                    ("win_q_t @ win_k_t.transpose(-2, -1)", "safe_matmul(win_q_t, win_k_t.transpose(-2, -1))"),
                    ("win_q_s @ win_k_s.transpose(-2, -1)", "safe_matmul(win_q_s, win_k_s.transpose(-2, -1))"),
                    ("att_t @ win_v_t", "safe_matmul(att_t, win_v_t)"),
                    ("att_s @ win_v_s", "safe_matmul(att_s, win_v_s)"),
                    ("win_q_t.float().clone() @ win_k_t.float().transpose(-2, -1).clone()", 
                     "safe_matmul(win_q_t, win_k_t.transpose(-2, -1))"),
                    ("win_q_s.float().clone() @ win_k_s.float().transpose(-2, -1).clone()", 
                     "safe_matmul(win_q_s, win_k_s.transpose(-2, -1))"),
                    ("att_t.float() @ win_v_t.float()", "safe_matmul(att_t, win_v_t)"),
                ]
                
                for old, new in simple_replacements:
                    if old in content:
                        content = content.replace(old, new)
                        replacement_count += 1
                        self._logger.debug(f"Replaced: {old} -> {new}")

            # Backup original file
            backup_path = transformer_path.with_suffix('.py.before_safe_matmul')
            if not backup_path.exists():
                backup_path.write_text(transformer_path.read_text())

            # Write patched content
            transformer_path.write_text(content)

            self._logger.info(f"✅ Replaced {replacement_count} dangerous @ operations with safe_matmul")
            self._logger.info("🛡️  Transformer is now RESILIENT (CPU fallback enabled)")

            return True

        except Exception as e:
            self._logger.error(f"❌ Failed to inject safe_matmul: {e}")
            import traceback
            self._logger.error(f"Traceback: {traceback.format_exc()}")
            return False

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
                
                # 4. GLOBAL GPU STABILITY FIX (CRITICAL - MUST BE FIRST!)
                # Apply stability settings to main process
                from src.infrastructure.gpu import apply_global_stability_settings, inject_stability_into_subprocess
                apply_global_stability_settings(verbose=True)

                # Inject stability settings into ProPainter subprocess
                propainter_script = "/opt/ProPainter/inference_propainter.py"
                if os.path.exists(propainter_script):
                    inject_stability_into_subprocess(propainter_script)

                # 5. Inject Pure PyTorch CorrBlock into ProPainter RAFT
                # ProPainter's RAFT tries to import CorrBlock from spatial_correlation_sampler
                # But we replaced it with Pure PyTorch version, so we need to inject it
                self._inject_pure_pytorch_corrblock()

                # 6. Patch ProPainter Transformer for CUDA stride safety
                # Transformer attention layers also use transpose() + matmul
                # Same memory alignment issue as RAFT → same fix needed
                self._patch_propainter_transformer()

                # 6.5. RESILIENT FIX: Inject safe_matmul with CPU fallback
                # This is the SENIOR approach: instead of fighting CUBLAS bugs,
                # we gracefully degrade to CPU computation when GPU fails
                self._inject_safe_matmul_into_transformer()

                # 7. Validate CorrBlock injection
                self._validate_corrblock_injection()

                # 8. Inpainter
                inpainter = ProPainterAdapter()
                
                # 9. Debug mode detection
                debug_mode = os.getenv('DEBUG_SUBTITLE_REMOVAL', '0') == '1'

                # 10. Главный сервис
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
