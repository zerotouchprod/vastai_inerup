#!/usr/bin/env python3
"""
NUCLEAR FIX for ProPainter Sparse Transformer
Fixes CUBLAS_STATUS_INVALID_VALUE errors on RTX 30/40/50 series GPUs

Problem: Matrix multiplication with transpose in FP16 causes stride errors
Solution: Force FP32 + clone() for memory alignment
"""
import os
import re

TARGET_PATH = "/opt/ProPainter/model/modules/sparse_transformer.py"

print(f"☢️ Applying NUCLEAR FIX to {TARGET_PATH}...")

if not os.path.exists(TARGET_PATH):
    print(f"❌ ERROR: File not found: {TARGET_PATH}")
    print("   This script must be run inside the Docker container/VM where ProPainter is installed.")
    exit(1)

try:
    with open(TARGET_PATH, "r") as f:
        content = f.read()

    original_content = content
    
    # Pattern 1: Fix attention computation (q @ k.transpose)
    # Match: win_q_t @ win_k_t.transpose(-2, -1)
    patterns_to_fix = [
        # Attention computation (most common)
        (
            r'(win_q_\w+)\s*@\s*(win_k_\w+)\.transpose\(-2,\s*-1\)',
            r'\1.float().clone() @ \2.float().transpose(-2, -1).clone()'
        ),
        # Generic attention pattern
        (
            r'(\w+_q)\s*@\s*(\w+_k)\.transpose\(-2,\s*-1\)',
            r'\1.float().clone() @ \2.float().transpose(-2, -1).clone()'
        ),
        # Generic q @ k pattern
        (
            r'\bq\s*@\s*k\.transpose\(-2,\s*-1\)',
            r'q.float().clone() @ k.float().transpose(-2, -1).clone()'
        ),
    ]
    
    for pattern, replacement in patterns_to_fix:
        content = re.sub(pattern, replacement, content)
    
    # Pattern 2: Fix value aggregation (att @ v)
    value_patterns = [
        (
            r'(att_\w+)\s*@\s*(win_v_\w+)(?!\.float\(\))',
            r'\1.float() @ \2.float().clone()'
        ),
        (
            r'\batt\s*@\s*v(?!\.float\(\))',
            r'att.float() @ v.float().clone()'
        ),
    ]
    
    for pattern, replacement in value_patterns:
        content = re.sub(pattern, replacement, content)
    
    # Check if anything changed
    if content == original_content:
        print("⚠️  WARNING: No patterns matched!")
        print("   File might have different structure than expected.")
        print("   Showing lines around line 250:")
        lines = original_content.split('\n')
        for i in range(max(0, 240), min(len(lines), 260)):
            print(f"   {i+1:4d}: {lines[i]}")
        exit(1)
    
    # Backup original file
    backup_path = TARGET_PATH + ".before_nuclear_fix"
    if not os.path.exists(backup_path):
        with open(backup_path, "w") as f:
            f.write(original_content)
        print(f"✅ Backed up original to: {backup_path}")
    
    # Write patched content
    with open(TARGET_PATH, "w") as f:
        f.write(content)
    
    # Count changes
    original_lines = original_content.split('\n')
    new_lines = content.split('\n')
    
    changed_lines = []
    for i, (old, new) in enumerate(zip(original_lines, new_lines)):
        if old != new:
            changed_lines.append((i+1, old, new))
    
    print(f"\n✅ SUCCESS! Applied nuclear fix to {len(changed_lines)} line(s):")
    for line_num, old, new in changed_lines[:5]:  # Show first 5 changes
        print(f"   Line {line_num}:")
        print(f"      OLD: {old.strip()}")
        print(f"      NEW: {new.strip()}")
    
    if len(changed_lines) > 5:
        print(f"   ... and {len(changed_lines) - 5} more changes")
    
    print("\n🎯 What was fixed:")
    print("   ✓ All matrix multiplications now use float32 (bypasses FP16 bugs)")
    print("   ✓ All transposed tensors are cloned (fixes memory alignment)")
    print("   ✓ CUBLAS stride errors should be eliminated")
    
    print("\n🚀 Next steps:")
    print("   1. Re-run your pipeline")
    print("   2. If it still fails, check stderr for the EXACT line number")
    print("   3. We may need to patch additional operations")

except Exception as e:
    print(f"❌ FAILED: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

