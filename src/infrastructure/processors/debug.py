"""Debug utilities for processor wrappers."""

import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, Optional

class ProcessorDebugger:
    """
    Debug helper for processor wrappers.

    Usage:
        debugger = ProcessorDebugger('realesrgan')
        debugger.log_start(num_frames=100, output_dir='/tmp/out')
        debugger.log_step('loading_model', model_path='/path/to/model')
        debugger.log_end(True, frames_produced=100)

    Enable via:
        export DEBUG_PROCESSORS=1
    """

    def __init__(self, name: str, log_dir: Optional[Path] = None):
        self.name = name
        self.enabled = os.getenv('DEBUG_PROCESSORS', '0') == '1'

        if log_dir:
            self.log_file = log_dir / f"{name}_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        else:
            self.log_file = Path(f"/tmp/{name}_debug.log")

        if self.enabled:
            self.logger = self._setup_logger()
            self.logger.info("="*60)
            self.logger.info(f"Debug session started for {name}")
            self.logger.info(f"Log file: {self.log_file}")
            self.logger.info("="*60)

    def _setup_logger(self) -> logging.Logger:
        """Setup detailed file logger."""
        logger = logging.getLogger(f"debug.{self.name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()  # Clear existing handlers

        # File handler
        fh = logging.FileHandler(self.log_file, mode='w')
        fh.setLevel(logging.DEBUG)

        # Console handler for important messages
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        # Detailed format
        formatter = logging.Formatter(
            '[%(asctime)s] [%(levelname)-8s] %(message)s',
            datefmt='%H:%M:%S'
        )
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)

        logger.addHandler(fh)
        logger.addHandler(ch)

        return logger

    def log_start(self, **kwargs):
        """Log processing start with parameters."""
        if not self.enabled:
            return

        self.logger.info(f"▶️  START: {self.name}")
        for k, v in kwargs.items():
            self.logger.info(f"  📋 {k}: {v}")

    def log_step(self, step: str, **kwargs):
        """Log intermediate step."""
        if not self.enabled:
            return

        self.logger.debug(f"⏩ STEP: {step}")
        for k, v in kwargs.items():
            self.logger.debug(f"    {k}: {v}")

    def log_var(self, name: str, value: Any):
        """Log variable value."""
        if not self.enabled:
            return

        value_str = str(value)
        if len(value_str) > 100:
            value_str = value_str[:100] + "..."
        self.logger.debug(f"  🔢 {name} = {value_str}")

    def log_shell_command(self, cmd: list, env: Optional[Dict] = None):
        """Log shell command being executed."""
        if not self.enabled:
            return

        self.logger.info(f"🐚 Executing shell command:")
        self.logger.info(f"    {' '.join(str(c) for c in cmd)}")
        if env:
            self.logger.debug(f"  Environment overrides:")
            for k, v in env.items():
                self.logger.debug(f"    {k}={v}")

    def log_shell_output(self, returncode: int, stdout: str, stderr: str):
        """Log shell command output."""
        if not self.enabled:
            return

        self.logger.info(f"  Exit code: {returncode}")

        if stdout:
            stdout_lines = stdout.strip().split('\n')
            self.logger.debug(f"  STDOUT ({len(stdout_lines)} lines):")
            for line in stdout_lines[:50]:  # First 50 lines
                self.logger.debug(f"    {line}")
            if len(stdout_lines) > 50:
                self.logger.debug(f"    ... ({len(stdout_lines) - 50} more lines)")

        if stderr:
            stderr_lines = stderr.strip().split('\n')
            self.logger.warning(f"  STDERR ({len(stderr_lines)} lines):")
            for line in stderr_lines[:50]:
                self.logger.warning(f"    {line}")
            if len(stderr_lines) > 50:
                self.logger.warning(f"    ... ({len(stderr_lines) - 50} more lines)")

    def log_error(self, error: Exception, context: str = ""):
        """Log error with traceback."""
        if not self.enabled:
            return

        self.logger.error(f"❌ ERROR{' in ' + context if context else ''}: {error}")
        self.logger.error("Traceback:", exc_info=True)

    def log_end(self, success: bool, **kwargs):
        """Log processing end."""
        if not self.enabled:
            return

        status = "✅ SUCCESS" if success else "❌ FAILED"
        self.logger.info(f"⏹️  END: {self.name} - {status}")
        for k, v in kwargs.items():
            self.logger.info(f"  📊 {k}: {v}")

        self.logger.info("="*60)
        self.logger.info(f"Debug log saved to: {self.log_file}")
        self.logger.info("="*60)

    def is_enabled(self) -> bool:
        """Check if debugging is enabled."""
        return self.enabled


# Convenience function
def create_debugger(name: str) -> ProcessorDebugger:
    """Create a processor debugger instance."""
    return ProcessorDebugger(name)

