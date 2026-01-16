#!/usr/bin/env python3
"""
Pure PyTorch RAFT correlation module.
Replaces spatial-correlation-sampler C++ extension.
"""
import sys
from pathlib import Path

# Find project root - try multiple possible locations
project_root = None
possible_roots = [
    Path("/root/vastai_inerup"),           # Vast.ai standard location
    Path("/workspace/project"),            # Docker standard location
    Path(__file__).parent.parent.parent.parent / "vastai_inerup",  # Relative from RAFT dir
    Path.home() / "vastai_inerup",         # User home directory
]

for root in possible_roots:
    if root.exists() and (root / "src" / "infrastructure" / "inpainting" / "pure_pytorch_correlation.py").exists():
        project_root = root
        break

if project_root is None:
    raise ImportError(
        "Cannot find vastai_inerup project root!\n"
        f"Tried: {[str(p) for p in possible_roots]}\n"
        "Please ensure project is installed at /root/vastai_inerup or /workspace/project"
    )

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
    AlternateCorrBlock = CorrBlock  # Alias
    __all__ = ['CorrBlock', 'AlternateCorrBlock']
except ImportError as e:
    raise ImportError(
        f"Failed to import Pure PyTorch CorrBlock from {project_root}:\n{e}\n"
        "Please ensure pure_pytorch_correlation.py exists in:\n"
        f"  {project_root}/src/infrastructure/inpainting/pure_pytorch_correlation.py"
    )

if __name__ == '__main__':
    print(f"✅ RAFT.corr module ready (project root: {project_root})")
    print(f"   CorrBlock: {CorrBlock}")
    print(f"   AlternateCorrBlock: {AlternateCorrBlock}")

