"""
Vast.ai API client implementation.

Infrastructure layer for Vast.ai integration.
"""

import os
import time
from typing import List, Dict, Any, Optional
import logging

from domain.vastai import (
    IVastClient,
    VastOffer,
    VastInstance,
    VastInstanceConfig
)
from domain.exceptions import VideoProcessingError

try:
    import requests
    from requests.exceptions import RequestException
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class VastAIClient:
    """
    Vast.ai API client implementation.

    Uses requests library to interact with Vast.ai public API.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Vast.ai client.

        Args:
            api_key: Vast.ai API key (reads from VAST_API_KEY env if None)
            api_base: API base URL (default: https://api.vast.ai/v0)
            logger: Logger instance
        """
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests library required. Install: pip install requests")

        self.api_key = api_key or os.getenv('VAST_API_KEY')
        if not self.api_key:
            raise ValueError("VAST_API_KEY not set")

        self.api_base = api_base or os.getenv('VAST_API_BASE', 'https://api.vast.ai/v0')
        self.logger = logger or logging.getLogger(__name__)

        # Setup session
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json',
        })

    def _request(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Make API request.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional request arguments

        Returns:
            Response JSON

        Raises:
            VideoProcessingError: On API error
        """
        url = f"{self.api_base.rstrip('/')}/{endpoint.lstrip('/')}"

        # Add API key to params
        params = kwargs.get('params', {})
        params['api_key'] = self.api_key
        kwargs['params'] = params

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except RequestException as e:
            error_msg = f"Vast.ai API request failed: {e}"
            self.logger.error(error_msg)
            raise VideoProcessingError(error_msg) from e

    def search_offers(
        self,
        min_vram_gb: float = 8.0,
        max_price: float = 0.5,
        min_reliability: float = 0.9,
        limit: int = 10
    ) -> List[VastOffer]:
        """Search for available GPU offers."""
        self.logger.info(
            f"Searching offers: min_vram={min_vram_gb}GB, "
            f"max_price=${max_price}/hr, min_reliability={min_reliability}"
        )

        # Build query
        query = {
            'verified': {'eq': True},
            'external': {'eq': False},
            'rentable': {'eq': True},
            'disk_space': {'gte': 50},
            'total_flops': {'gte': 1.0},
            'gpu_ram': {'gte': min_vram_gb * 1024},  # Convert to MB
            'dph_total': {'lte': max_price},
            'reliability2': {'gte': min_reliability},
            'inet_down': {'gte': 100},
            'inet_up': {'gte': 100},
        }

        try:
            import json
            response = self._request(
                'GET',
                'bundles',
                params={
                    'q': json.dumps(query),  # Vast.ai expects JSON string
                    'limit': limit,
                }
            )

            offers = response.get('offers', [])

            result = []
            for offer_data in offers:
                try:
                    # Client-side filtering (Vast.ai API sometimes ignores filters)
                    price = offer_data.get('dph_total', 999)
                    host_id = offer_data.get('host_id', 0)

                    # Skip if price too high
                    if price > max_price:
                        self.logger.debug(f"Skipping offer {offer_data['id']}: price ${price:.3f} > ${max_price}")
                        continue

                    # Skip if not enough VRAM
                    vram_gb = offer_data.get('gpu_ram', 0) / 1024
                    if vram_gb < min_vram_gb:
                        self.logger.debug(f"Skipping offer {offer_data['id']}: VRAM {vram_gb:.1f}GB < {min_vram_gb}GB")
                        continue

                    # Skip if reliability too low
                    reliability = offer_data.get('reliability2', 0)
                    if reliability < min_reliability:
                        self.logger.debug(f"Skipping offer {offer_data['id']}: reliability {reliability:.2f} < {min_reliability}")
                        continue

                    offer = VastOffer(
                        id=offer_data['id'],
                        gpu_name=offer_data.get('gpu_name', 'Unknown'),
                        num_gpus=offer_data.get('num_gpus', 1),
                        total_flops=offer_data.get('total_flops', 0),
                        vram_mb=offer_data.get('gpu_ram', 0),
                        price_per_hour=price,
                        reliability=reliability,
                        inet_up=offer_data.get('inet_up', 0),
                        inet_down=offer_data.get('inet_down', 0),
                        storage_cost=offer_data.get('storage_cost', 0),
                    )
                    result.append(offer)

                    # Stop when we have enough
                    if len(result) >= limit:
                        break

                except Exception as e:
                    self.logger.warning(f"Failed to parse offer: {e}")
                    continue

            # Sort by price (cheapest first)
            result.sort(key=lambda x: x.price_per_hour)

            self.logger.info(f"Found {len(result)} matching offers (after filtering)")
            if result:
                cheapest = result[0]
                self.logger.info(f"Cheapest: ${cheapest.price_per_hour:.3f}/hr, {cheapest.gpu_name}, {cheapest.vram_mb/1024:.0f}GB VRAM")

            return result

        except Exception as e:
            self.logger.error(f"Search offers failed: {e}")
            raise

    def create_instance(
        self,
        offer_id: int,
        config: VastInstanceConfig
    ) -> VastInstance:
        """Create instance from offer."""
        self.logger.info(f"Creating instance from offer #{offer_id}")

        # Build request payload
        payload = {
            'client_id': 'me',
            'image': config.image,
            'env': config.env,
            'disk': config.disk,
        }

        if config.onstart:
            payload['onstart'] = config.onstart

        if config.label:
            payload['label'] = config.label

        try:
            response = self._request(
                'PUT',
                f'asks/{offer_id}',
                json=payload
            )

            instance_id = response.get('new_contract')
            if not instance_id:
                raise VideoProcessingError("No instance ID in response")

            self.logger.info(f"Created instance #{instance_id}")

            # Return instance
            return VastInstance(
                id=instance_id,
                status='created'
            )

        except Exception as e:
            self.logger.error(f"Create instance failed: {e}")
            raise

    def get_instance(self, instance_id: int) -> VastInstance:
        """Get instance details."""
        try:
            response = self._request(
                'GET',
                f'instances/{instance_id}'
            )

            # Handle different response formats
            if isinstance(response, dict):
                instances = response.get('instances', [])
            elif isinstance(response, list):
                instances = response
            else:
                self.logger.error(f"Unexpected response type: {type(response)}, data: {response}")
                raise VideoProcessingError(f"Invalid API response format")

            if not instances:
                self.logger.warning(f"Instance #{instance_id} not found in API response")
                raise VideoProcessingError(f"Instance #{instance_id} not found")

            data = instances[0] if isinstance(instances, list) else instances

            # Validate required fields
            if not data or not isinstance(data, dict):
                self.logger.error(f"Invalid instance data: {data}")
                raise VideoProcessingError(f"Invalid instance data structure")

            return VastInstance(
                id=data.get('id', instance_id),
                status=data.get('status_msg', 'unknown'),
                actual_status=data.get('actual_status', 'unknown'),
                ssh_host=data.get('ssh_host'),
                ssh_port=data.get('ssh_port'),
                gpu_name=data.get('gpu_name'),
                num_gpus=data.get('num_gpus'),
                price_per_hour=data.get('dph_total'),
            )

        except VideoProcessingError:
            raise
        except Exception as e:
            self.logger.error(f"Get instance failed: {e.__class__.__name__}: {e}")
            raise VideoProcessingError(f"Failed to get instance: {e}") from e

    def get_instance_logs(self, instance_id: int, tail: int = 100) -> str:
        """
        Get instance container logs.

        Args:
            instance_id: Instance ID
            tail: Number of lines to retrieve

        Returns:
            Log output as string
        """
        try:
            response = self._request(
                'GET',
                f'instances/{instance_id}/logs',
                params={'tail': tail}
            )

            # Logs might be in different formats
            if isinstance(response, dict):
                return response.get('logs', '') or response.get('output', '')
            elif isinstance(response, str):
                return response
            else:
                return str(response)

        except Exception as e:
            self.logger.warning(f"Failed to get logs for instance #{instance_id}: {e}")
            return ""

    def destroy_instance(self, instance_id: int) -> bool:
        """Destroy instance."""
        self.logger.info(f"Destroying instance #{instance_id}")

        try:
            self._request(
                'DELETE',
                f'instances/{instance_id}'
            )

            self.logger.info(f"Destroyed instance #{instance_id}")
            return True

        except Exception as e:
            self.logger.error(f"Destroy instance failed: {e}")
            return False

    def wait_for_running(
        self,
        instance_id: int,
        timeout: int = 300,
        poll_interval: int = 10
    ) -> VastInstance:
        """Wait for instance to be running."""
        self.logger.info(f"Waiting for instance #{instance_id} to be running...")

        start_time = time.time()

        while True:
            elapsed = time.time() - start_time

            if elapsed > timeout:
                raise TimeoutError(
                    f"Instance #{instance_id} did not start within {timeout}s"
                )

            try:
                instance = self.get_instance(instance_id)

                if instance.is_running:
                    self.logger.info(f"Instance #{instance_id} is running!")
                    return instance

                if instance.is_terminated:
                    raise VideoProcessingError(
                        f"Instance #{instance_id} terminated unexpectedly"
                    )

                self.logger.info(
                    f"Instance #{instance_id} status: {instance.actual_status} "
                    f"(elapsed: {elapsed:.0f}s)"
                )

            except Exception as e:
                self.logger.warning(f"Error checking instance status: {e}")

            time.sleep(poll_interval)

