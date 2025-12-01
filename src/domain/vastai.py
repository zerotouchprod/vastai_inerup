"""
Vast.ai client domain models and protocols.

Domain layer for Vast.ai integration (SOLID).
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Protocol
from datetime import datetime


@dataclass
class VastOffer:
    """Vast.ai GPU offer."""
    id: int
    gpu_name: str
    num_gpus: int
    total_flops: float
    vram_mb: int
    price_per_hour: float
    reliability: float
    inet_up: float
    inet_down: float
    storage_cost: float

    def __str__(self) -> str:
        return (
            f"Offer #{self.id}: {self.num_gpus}x {self.gpu_name} "
            f"({self.vram_mb}MB VRAM) @ ${self.price_per_hour:.3f}/hr"
        )


@dataclass
class VastInstance:
    """Vast.ai instance."""
    id: int
    status: str
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    actual_status: Optional[str] = None
    gpu_name: Optional[str] = None
    num_gpus: Optional[int] = None
    price_per_hour: Optional[float] = None

    @property
    def is_running(self) -> bool:
        """Check if instance is running."""
        return self.actual_status == 'running'

    @property
    def is_terminated(self) -> bool:
        """Check if instance is terminated/stopped."""
        return self.status in ('stopped', 'exited')

    def __str__(self) -> str:
        return f"Instance #{self.id} ({self.status})"


@dataclass
class VastInstanceConfig:
    """Configuration for creating Vast.ai instance."""
    image: str
    disk: int  # GB
    env: Dict[str, str]
    onstart: Optional[str] = None
    label: Optional[str] = None
    runtype: str = 'oneshot'  # Run once, do not restart on failure

    # Resource requirements
    min_vram_gb: float = 8.0
    max_price_per_hour: float = 0.5
    min_reliability: float = 0.9

    def to_dict(self) -> Dict[str, Any]:
        """Convert to API request dict."""
        result = {
            'image': self.image,
            'disk': self.disk,
            'env': self.env,
            'runtype': self.runtype,
        }

        # Add optional fields only if set
        if self.onstart:
            result['onstart'] = self.onstart
        if self.label:
            result['label'] = self.label

        return result


class IVastClient(Protocol):
    """Protocol for Vast.ai API client."""

    def search_offers(
        self,
        min_vram_gb: float = 8.0,
        max_price: float = 0.5,
        min_reliability: float = 0.9,
        limit: int = 10
    ) -> List[VastOffer]:
        """
        Search for available GPU offers.

        Args:
            min_vram_gb: Minimum VRAM in GB
            max_price: Maximum price per hour
            min_reliability: Minimum reliability score
            limit: Maximum number of results

        Returns:
            List of matching offers
        """
        ...

    def create_instance(
        self,
        offer_id: int,
        config: VastInstanceConfig
    ) -> VastInstance:
        """
        Create instance from offer.

        Args:
            offer_id: Offer ID to use
            config: Instance configuration

        Returns:
            Created instance
        """
        ...

    def get_instance(self, instance_id: int) -> VastInstance:
        """
        Get instance details.

        Args:
            instance_id: Instance ID

        Returns:
            Instance details
        """
        ...

    def destroy_instance(self, instance_id: int) -> bool:
        """
        Destroy instance.

        Args:
            instance_id: Instance ID

        Returns:
            True if destroyed successfully
        """
        ...

    def wait_for_running(
        self,
        instance_id: int,
        timeout: int = 300,
        poll_interval: int = 10
    ) -> VastInstance:
        """
        Wait for instance to be running.

        Args:
            instance_id: Instance ID
            timeout: Timeout in seconds
            poll_interval: Poll interval in seconds

        Returns:
            Running instance

        Raises:
            TimeoutError: If timeout reached
        """
        ...

