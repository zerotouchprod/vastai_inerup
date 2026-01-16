#!/usr/bin/env python3
"""
Refactored pipeline entry point (OOP + SOLID).
Drop-in replacement for pipeline.py with improved architecture.

Auto-restart: If CUDA extension rebuild succeeds (exit code 42),
automatically restarts the process to load the new extension.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Enable native Python processors by default (unless explicitly disabled)
if 'USE_NATIVE_PROCESSORS' not in os.environ:
    os.environ['USE_NATIVE_PROCESSORS'] = '1'

from src.presentation.cli import main


def log_restart(msg):
    """Log with timestamp for restart operations."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [auto-restart] {msg}", flush=True)


if __name__ == '__main__':
    max_restarts = 3
    restart_count = 0

    while restart_count <= max_restarts:
        exit_code = main()

        if exit_code == 0:
            # Success
            sys.exit(0)

        elif exit_code == 42:
            # Special code: CUDA extension rebuilt, restart needed
            restart_count += 1
            log_restart("")
            log_restart("=" * 80)
            log_restart(f"🔄 CUDA extension rebuilt (exit code 42)")
            log_restart(f"   Auto-restart {restart_count}/{max_restarts}...")
            log_restart("=" * 80)
            log_restart("")

            if restart_count <= max_restarts:
                log_restart("Waiting 2 seconds before restart...")
                time.sleep(2)
                log_restart("Restarting pipeline_v2.py with same arguments...")
                log_restart("")
                # Continue loop to restart
                continue
            else:
                log_restart(f"❌ Max restarts ({max_restarts}) exceeded")
                log_restart("   This may indicate a persistent CUDA issue")
                log_restart("   Please check logs above for errors")
                sys.exit(1)

        else:
            # Other exit code (error)
            sys.exit(exit_code)

    # Should never reach here
    log_restart("❌ Max restarts exceeded")
    sys.exit(1)


