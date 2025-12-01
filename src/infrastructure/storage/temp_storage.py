"""Temporary storage management."""

import tempfile
import shutil
from pathlib import Path
from typing import Optional

from domain.protocols import ITempStorage
from shared.logging import get_logger

logger = get_logger(__name__)


class TempStorage:
    """Manages temporary workspaces for video processing jobs."""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize temp storage manager.

        Args:
            base_dir: Base directory for temp files (defaults to system temp)
        """
        self.base_dir = base_dir or Path(tempfile.gettempdir())
        self._logger = get_logger(__name__)
        self._workspaces = {}

    def create_workspace(self, job_id: str) -> Path:
        """
        Create a temporary workspace for a job.

        Args:
            job_id: Unique job identifier

        Returns:
            Path to created workspace
        """
        workspace = self.base_dir / f"vastai_job_{job_id}"
        workspace.mkdir(parents=True, exist_ok=True)

        self._workspaces[job_id] = workspace
        self._logger.info(f"Created workspace: {workspace}")

        return workspace

    def get_workspace(self, job_id: str) -> Optional[Path]:
        """
        Get existing workspace for a job.

        Args:
            job_id: Job identifier

        Returns:
            Workspace path if exists, None otherwise
        """
        workspace = self._workspaces.get(job_id)
        if workspace and workspace.exists():
            return workspace

        # Try to find it on disk
        workspace = self.base_dir / f"vastai_job_{job_id}"
        if workspace.exists():
            self._workspaces[job_id] = workspace
            return workspace

        return None

    def cleanup(self, workspace: Path, keep_on_error: bool = False) -> None:
        """
        Clean up a workspace directory.

        Args:
            workspace: Path to workspace
            keep_on_error: If True, don't delete if errors occurred
        """
        if not workspace.exists():
            return

        if keep_on_error:
            self._logger.warning(f"Keeping workspace for debugging: {workspace}")
            return

        try:
            shutil.rmtree(workspace)
            self._logger.info(f"Cleaned up workspace: {workspace}")

            # Remove from tracking
            for job_id, ws in list(self._workspaces.items()):
                if ws == workspace:
                    del self._workspaces[job_id]

        except Exception as e:
            self._logger.error(f"Failed to cleanup workspace {workspace}: {e}")

    def cleanup_all(self) -> None:
        """Clean up all tracked workspaces."""
        for workspace in list(self._workspaces.values()):
            self.cleanup(workspace, keep_on_error=False)

