#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module - CORRECT IMPLEMENTATION
==============================================================

This matches the ORIGINAL C++ API exactly but uses Pure PyTorch internally.
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

    This implementation uses Pure PyTorch but produces identical results.
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
        """
        Sample correlation at coordinates.

        Args:
            coords: Flow coordinates [B, 2, H, W]

        Returns:
            Correlation features [B, num_levels*(2*r+1)^2, H, W]
        """
        r = self.radius
        coords = coords.permute(0, 2, 3, 1)
        batch, h1, w1, _ = coords.shape

        out_pyramid = []
        for i in range(self.num_levels):
            corr = self.corr_pyramid[i]
            dx = torch.linspace(-r, r, 2*r+1, device=coords.device)
            dy = torch.linspace(-r, r, 2*r+1, device=coords.device)
            # Use default indexing (ij) for compatibility with older PyTorch
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
        """
        TITANIUM v2: Synchronized + Float32 forced

        Fixes async CUDA errors by forcing synchronization INSIDE try-except.
        Without sync, GPU crashes happen AFTER we exit try-except!
        """
        batch, dim, ht, wd = fmap1.shape
        fmap1 = fmap1.view(batch, dim, ht*wd)
        fmap2 = fmap2.view(batch, dim, ht*wd)

        try:
            # === PROTECTION AGAINST RTX 50-SERIES BUGS ===
            # 1. Force float32 (FP16 often breaks cuBLAS on new cards)
            fmap1_t = fmap1.transpose(1, 2).contiguous().float()
            fmap2_c = fmap2.contiguous().float()

            # 2. Matrix multiplication
            corr = torch.matmul(fmap1_t, fmap2_c)

            # 3. SYNCHRONIZATION (Critical!)
            # Force Python to WAIT for GPU operation to complete
            # This catches async CUDA errors HERE instead of later crash
            if torch.cuda.is_available():
                torch.cuda.synchronize()

        except RuntimeError as e:
            # === CPU LIFESAVER ===
            # If GPU crashes (even after sync), compute on CPU
            import sys
            print(f"⚠️ GPU Correlation CRASHED ({e}). Switching to CPU calculation...", file=sys.stderr)

            fmap1_cpu = fmap1.cpu().float()
            fmap2_cpu = fmap2.cpu().float()

            # Compute on CPU (slow but reliable, no cuBLAS)
            corr_cpu = torch.matmul(fmap1_cpu.transpose(1, 2), fmap2_cpu)

            # Move result back to GPU
            corr = corr_cpu.to(fmap1.device)

        corr = corr.view(batch, ht, wd, 1, ht, wd)
        return corr / torch.sqrt(torch.tensor(dim).float())


# AlternateCorrBlock is just an alias
AlternateCorrBlock = CorrBlock

__all__ = ['CorrBlock', 'AlternateCorrBlock']

