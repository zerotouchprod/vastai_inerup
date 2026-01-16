#!/usr/bin/env python3
"""
Inject safe_matmul into ProPainter Transformer
==============================================

This script patches ProPainter's sparse_transformer.py to use safe_matmul
instead of raw @ operator, making it resilient to CUBLAS errors.

Architecture:
-------------
1. Add safe_matmul helper function to file
2. Replace all dangerous @ operations in attention layers
3. Create backup before modification

Usage:
------
    python scripts/inject_safe_matmul.py

Or from Python:
    from scripts.inject_safe_matmul import inject_safe_matmul_into_transformer
    inject_safe_matmul_into_transformer()
"""

import re
from pathlib import Path


# Safe matmul function to inject
SAFE_MATMUL_CODE = '''
def safe_matmul(tensor_a, tensor_b):
    """Safe @ operator with CPU fallback on CUBLAS errors."""
    try:
        return tensor_a @ tensor_b
    except RuntimeError as e:
        if "CUDA" in str(e) or "CUBLAS" in str(e):
            device = tensor_a.device
            return (tensor_a.cpu().float() @ tensor_b.cpu().float()).to(device)
        raise e
'''


def inject_safe_matmul_into_transformer(
    transformer_path: str = "/opt/ProPainter/model/modules/sparse_transformer.py",
    backup: bool = True,
    verbose: bool = True
) -> bool:
    """
    Inject safe_matmul into ProPainter's transformer.
    
    Args:
        transformer_path: Path to sparse_transformer.py
        backup: Create backup file before modification
        verbose: Print progress messages
        
    Returns:
        True if patched successfully, False if already patched or failed
    """
    path = Path(transformer_path)
    
    if not path.exists():
        if verbose:
            print(f"❌ File not found: {transformer_path}")
        return False
    
    # Read original file
    with open(path, "r") as f:
        content = f.read()
    
    # Check if already patched
    if "def safe_matmul" in content:
        if verbose:
            print(f"✅ Already patched: {transformer_path}")
        return False
    
    # Create backup
    if backup:
        backup_path = path.with_suffix(path.suffix + ".before_safe_matmul")
        with open(backup_path, "w") as f:
            f.write(content)
        if verbose:
            print(f"📦 Backup created: {backup_path}")
    
    # Step 1: Inject safe_matmul function after imports
    last_import_pos = content.rfind("import ")
    if last_import_pos == -1:
        last_import_pos = 0
    end_of_line = content.find("\n", last_import_pos)
    if end_of_line == -1:
        end_of_line = len(content)
    
    injection_point = end_of_line + 1
    new_content = (
        content[:injection_point] + 
        "\n" + SAFE_MATMUL_CODE + "\n" +
        content[injection_point:]
    )
    
    if verbose:
        print("✅ Injected safe_matmul function")
    
    # Step 2: Replace dangerous @ operations
    # Pattern: (tensor_a @ tensor_b) -> safe_matmul(tensor_a, tensor_b)
    
    replacements = [
        # Attention calculation: q @ k.T
        (r'(\w+)\s*@\s*(\w+)\.transpose\s*\(\s*-2\s*,\s*-1\s*\)',
         r'safe_matmul(\1, \2.transpose(-2, -1))'),
        
        # Value aggregation: att @ v
        (r'(att_[ts])\s*@\s*(\w+)',
         r'safe_matmul(\1, \2)'),
    ]
    
    replacement_count = 0
    for pattern, replacement in replacements:
        new_content, count = re.subn(pattern, replacement, new_content)
        replacement_count += count
    
    if verbose:
        print(f"✅ Replaced {replacement_count} @ operations with safe_matmul")
    
    # Write patched file
    with open(path, "w") as f:
        f.write(new_content)
    
    if verbose:
        print(f"🚀 Transformer is now RESILIENT: {transformer_path}")
    
    return True


def main():
    """CLI entry point."""
    import sys
    
    # Check if running in Docker/Vast.ai environment
    propainter_path = Path("/opt/ProPainter/model/modules/sparse_transformer.py")
    
    if propainter_path.exists():
        success = inject_safe_matmul_into_transformer(
            str(propainter_path),
            backup=True,
            verbose=True
        )
        sys.exit(0 if success else 1)
    else:
        print("❌ ProPainter not found at /opt/ProPainter")
        print("This script must be run inside the Docker container.")
        sys.exit(1)


if __name__ == "__main__":
    main()

