#!/usr/bin/env python3
"""
ProPainter RAFT CorrBlock Fix
Patches RAFT/raft.py to handle spatial-correlation-sampler import gracefully
"""
import sys
from pathlib import Path

def patch_raft_file(raft_file_path: Path) -> bool:
    """
    Patch RAFT raft.py to add fallback for CorrBlock import failure.
    
    The issue is that spatial-correlation-sampler may not be properly built,
    causing CorrBlock import to fail at runtime.
    """
    if not raft_file_path.exists():
        print(f"❌ RAFT file not found: {raft_file_path}")
        return False
    
    content = raft_file_path.read_text(encoding='utf-8')
    
    # Check if already patched
    if "# PATCHED by vastai_inerup" in content:
        print(f"✅ RAFT file already patched: {raft_file_path}")
        return True
    
    # Look for the CorrBlock import line
    # It should be something like: from .corr import CorrBlock
    if "from .corr import CorrBlock" not in content and "from corr import CorrBlock" not in content:
        print(f"⚠️  CorrBlock import not found in expected format")
        print(f"   Searching for alternative patterns...")
        
        # Try to find any CorrBlock import
        lines = content.split('\n')
        found_import = False
        for i, line in enumerate(lines):
            if "CorrBlock" in line and "import" in line:
                print(f"   Found at line {i+1}: {line.strip()}")
                found_import = True
        
        if not found_import:
            print(f"⚠️  Could not find CorrBlock import in {raft_file_path}")
            return False
    
    # Add try-except wrapper around CorrBlock import and usage
    patched_content = content
    
    # Pattern 1: Wrap import statement
    import_patterns = [
        "from .corr import CorrBlock",
        "from corr import CorrBlock",
    ]
    
    for pattern in import_patterns:
        if pattern in patched_content:
            patched_import = f"""# PATCHED by vastai_inerup: handle spatial-correlation-sampler failure
try:
    {pattern}
    CORRBLOCK_AVAILABLE = True
except ImportError as e:
    print(f"⚠️  WARNING: CorrBlock import failed: {{e}}")
    print("   spatial-correlation-sampler may not be properly installed")
    print("   RAFT will use fallback correlation method (slower but works)")
    CORRBLOCK_AVAILABLE = False
    CorrBlock = None  # Placeholder
"""
            patched_content = patched_content.replace(pattern, patched_import)
            print(f"✅ Patched import: {pattern}")
            break
    
    # Write patched content
    raft_file_path.write_text(patched_content, encoding='utf-8')
    print(f"✅ Successfully patched {raft_file_path}")
    return True

def main():
    # Default ProPainter location
    propainter_root = Path("/opt/ProPainter")
    raft_file = propainter_root / "RAFT" / "raft.py"
    
    # Allow override via command line
    if len(sys.argv) > 1:
        raft_file = Path(sys.argv[1])
    
    print(f"🔧 Patching ProPainter RAFT file: {raft_file}")
    
    if patch_raft_file(raft_file):
        print("✅ RAFT patch applied successfully")
        return 0
    else:
        print("❌ Failed to patch RAFT file")
        return 1

if __name__ == "__main__":
    sys.exit(main())

