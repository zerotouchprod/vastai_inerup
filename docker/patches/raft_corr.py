#!/usr/bin/env python3
"""
Create fake RAFT/corr.py module with Pure PyTorch CorrBlock.

ProPainter subprocess imports: from RAFT.corr import CorrBlock, AlternateCorrBlock
We need to provide these classes from Pure PyTorch implementation.
"""
import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock

# ProPainter may also import AlternateCorrBlock
# Provide it as an alias to CorrBlock
AlternateCorrBlock = CorrBlock

# Export both names
__all__ = ['CorrBlock', 'AlternateCorrBlock']

if __name__ == '__main__':
    print(f"✅ RAFT.corr module ready")
    print(f"   CorrBlock: {CorrBlock}")
    print(f"   AlternateCorrBlock: {AlternateCorrBlock}")

