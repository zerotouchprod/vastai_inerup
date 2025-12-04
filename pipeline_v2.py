#!/usr/bin/env python3
"""
Refactored pipeline entry point (OOP + SOLID).
Drop-in replacement for pipeline.py with improved architecture.
"""

import os
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Enable native Python processors by default (unless explicitly disabled)
if 'USE_NATIVE_PROCESSORS' not in os.environ:
    os.environ['USE_NATIVE_PROCESSORS'] = '1'

from presentation.cli import main

if __name__ == '__main__':
    sys.exit(main())

