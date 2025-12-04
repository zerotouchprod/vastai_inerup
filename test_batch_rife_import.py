#!/usr/bin/env python3
"""
Test script to verify batch_rife.py can load RIFE model in probe mode
Usage: python test_batch_rife_import.py
"""
import subprocess
import sys
import os

def test_probe_mode():
    """Test batch_rife.py in probe mode"""
    print("Testing batch_rife.py probe mode...")

    # Set up environment to simulate container
    env = os.environ.copy()
    env['REPO_DIR'] = '/workspace/project/RIFEv4.26_0921'  # Simulate container path

    # Run in probe mode
    result = subprocess.run(
        [sys.executable, 'batch_rife.py', '--probe'],
        capture_output=True,
        text=True,
        env=env,
        cwd=os.path.dirname(__file__)
    )

    print(f"Exit code: {result.returncode}")
    print(f"\nSTDOUT:\n{result.stdout}")
    if result.stderr:
        print(f"\nSTDERR:\n{result.stderr}")

    if result.returncode == 0:
        print("\n✅ SUCCESS: RIFE model loaded successfully")
        return True
    elif result.returncode == 2:
        print("\n❌ FAILED: No compatible RIFE model found")
        return False
    else:
        print(f"\n❌ FAILED: Unexpected exit code {result.returncode}")
        return False

if __name__ == '__main__':
    success = test_probe_mode()
    sys.exit(0 if success else 1)

