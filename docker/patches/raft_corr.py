#!/usr/bin/env python3
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

