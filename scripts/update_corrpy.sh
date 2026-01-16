#!/bin/bash
# Update corr.py on running instance with new version that has robust path finding

echo "🔧 Updating /opt/ProPainter/RAFT/corr.py with robust path finding..."

# Create updated corr.py
cat > /opt/ProPainter/RAFT/corr.py << 'EOF'
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
    Path("/root/vastai_inerup"),           # Vast.ai standard
    Path("/workspace/project"),            # Docker standard
    Path.home() / "vastai_inerup",         # User home
]

for root in possible_roots:
    check_file = root / "src" / "infrastructure" / "inpainting" / "pure_pytorch_correlation.py"
    if root.exists() and check_file.exists():
        project_root = root
        break

if project_root is None:
    raise ImportError(
        "Cannot find vastai_inerup project!\n"
        f"Tried: {[str(p) for p in possible_roots]}\n"
        "Ensure project at /root/vastai_inerup or /workspace/project"
    )

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

try:
    from src.infrastructure.inpainting.pure_pytorch_correlation import CorrBlock
    AlternateCorrBlock = CorrBlock  # Alias
    __all__ = ['CorrBlock', 'AlternateCorrBlock']
except ImportError as e:
    raise ImportError(
        f"Failed to import Pure PyTorch CorrBlock from {project_root}:\n{e}"
    )
EOF

echo "✅ Updated /opt/ProPainter/RAFT/corr.py"

# Test it works
echo ""
echo "🧪 Testing import..."
python3 -c "
import sys
sys.path.insert(0, '/opt/ProPainter')
from RAFT.corr import CorrBlock, AlternateCorrBlock
print('✅ Import successful!')
print(f'   CorrBlock: {CorrBlock}')
print(f'   AlternateCorrBlock: {AlternateCorrBlock}')
"

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 corr.py updated and tested successfully!"
    echo "You can now re-run your pipeline."
else
    echo ""
    echo "❌ Test failed - check error above"
    exit 1
fi

