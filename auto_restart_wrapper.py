#!/usr/bin/env python3
"""
Auto-restart wrapper for CUDA extension rebuild.

This script wraps the main application and automatically restarts it
if spatial-correlation-sampler rebuild succeeded (exit code 42).

Usage:
    python auto_restart_wrapper.py <your_command> [args...]
    
Example:
    python auto_restart_wrapper.py python main.py --input video.mp4
"""

import sys
import subprocess
import time
from datetime import datetime

def log(msg):
    """Log with timestamp."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [auto-restart] {msg}", flush=True)

def main():
    if len(sys.argv) < 2:
        print("Usage: auto_restart_wrapper.py <command> [args...]")
        print("Example: auto_restart_wrapper.py python main.py --input video.mp4")
        sys.exit(1)
    
    command = sys.argv[1:]
    max_restarts = 3
    restart_count = 0
    
    log(f"Starting: {' '.join(command)}")
    log(f"Max auto-restarts: {max_restarts}")
    log("")
    
    while restart_count <= max_restarts:
        try:
            result = subprocess.run(command)
            exit_code = result.returncode
            
            if exit_code == 0:
                # Success
                log("✅ Process completed successfully")
                return 0
            
            elif exit_code == 42:
                # Special code: CUDA extension rebuilt, restart needed
                restart_count += 1
                log("")
                log("=" * 80)
                log(f"🔄 CUDA extension rebuilt (exit code 42)")
                log(f"   Restart {restart_count}/{max_restarts}...")
                log("=" * 80)
                log("")
                
                if restart_count <= max_restarts:
                    log("Waiting 2 seconds before restart...")
                    time.sleep(2)
                    log(f"Restarting: {' '.join(command)}")
                    log("")
                    continue
                else:
                    log(f"❌ Max restarts ({max_restarts}) exceeded")
                    log("   This may indicate a persistent CUDA issue")
                    return 1
            
            else:
                # Other error
                log(f"❌ Process failed with exit code {exit_code}")
                return exit_code
                
        except KeyboardInterrupt:
            log("⚠️  Interrupted by user (Ctrl+C)")
            return 130
        
        except Exception as e:
            log(f"❌ Unexpected error: {e}")
            return 1
    
    log("❌ Max restarts exceeded")
    return 1

if __name__ == "__main__":
    sys.exit(main())

