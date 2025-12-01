"""
Unit tests for Vast.ai client.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

from infrastructure.vastai.client import VastAIClient
from domain.vastai import VastOffer, VastInstance, VastInstanceConfig
from domain.exceptions import VideoProcessingError


@pytest.fixture
def mock_api_key():
    """Provide mock API key."""
    return "test_vast_api_key_123456"


class TestVastOffer:
    """Test VastOffer model."""

    def test_create_offer(self):
        """Test creating Vast offer."""
        offer = VastOffer(
            id=12345,
            gpu_name="RTX 3090",
            num_gpus=1,
            total_flops=35.58,
            vram_mb=24576,
            price_per_hour=0.25,
            reliability=0.95,
            inet_up=100.0,
            inet_down=100.0,
            storage_cost=0.01
        )

        assert offer.id == 12345
        assert offer.gpu_name == "RTX 3090"
        assert offer.num_gpus == 1
        assert offer.vram_mb == 24576
        assert offer.price_per_hour == 0.25
        assert offer.reliability == 0.95

    def test_offer_str_representation(self):
        """Test offer string representation."""
        offer = VastOffer(
            id=100,
            gpu_name="RTX 4090",
            num_gpus=2,
            total_flops=40.0,
            vram_mb=49152,
            price_per_hour=0.50,
            reliability=0.98,
            inet_up=200.0,
            inet_down=200.0,
            storage_cost=0.02
        )

        result = str(offer)
        assert "Offer #100" in result
        assert "2x RTX 4090" in result
        assert "49152MB VRAM" in result
        assert "$0.500/hr" in result


class TestVastInstance:
    """Test VastInstance model."""

    def test_create_instance(self):
        """Test creating Vast instance."""
        instance = VastInstance(
            id=54321,
            status="running",
            ssh_host="123.45.67.89",
            ssh_port=12345,
            actual_status="running",
            gpu_name="RTX 3090",
            num_gpus=1,
            price_per_hour=0.25
        )

        assert instance.id == 54321
        assert instance.status == "running"
        assert instance.ssh_host == "123.45.67.89"
        assert instance.ssh_port == 12345
        assert instance.gpu_name == "RTX 3090"

    def test_instance_is_running(self):
        """Test checking if instance is running."""
        instance = VastInstance(
            id=1,
            status="running",
            actual_status="running"
        )
        assert instance.is_running is True

        instance_stopped = VastInstance(
            id=2,
            status="stopped",
            actual_status="stopped"
        )
        assert instance_stopped.is_running is False

    def test_instance_is_terminated(self):
        """Test checking if instance is terminated."""
        instance = VastInstance(
            id=1,
            status="stopped"
        )
        assert instance.is_terminated is True

        instance_exited = VastInstance(
            id=2,
            status="exited"
        )
        assert instance_exited.is_terminated is True

        instance_running = VastInstance(
            id=3,
            status="running"
        )
        assert instance_running.is_terminated is False

    def test_instance_str_representation(self):
        """Test instance string representation."""
        instance = VastInstance(
            id=999,
            status="running"
        )

        assert str(instance) == "Instance #999 (running)"


class TestVastInstanceConfig:
    """Test VastInstanceConfig model."""

    def test_create_config(self):
        """Test creating instance config."""
        config = VastInstanceConfig(
            image="pytorch/pytorch:2.0.0-cuda11.7-cudnn8-runtime",
            disk=50,
            env={
                "INPUT_URL": "https://example.com/video.mp4",
                "MODE": "upscale"
            },
            onstart="bash /workspace/entrypoint.sh",
            label="test-job",
            min_vram_gb=12.0,
            max_price_per_hour=0.40,
            min_reliability=0.92
        )

        assert config.image.startswith("pytorch")
        assert config.disk == 50
        assert config.env["MODE"] == "upscale"
        assert config.min_vram_gb == 12.0

    def test_config_to_dict(self):
        """Test converting config to dict."""
        config = VastInstanceConfig(
            image="test/image",
            disk=40,
            env={"KEY": "value"},
            onstart="startup.sh",
            label="my-job"
        )

        result = config.to_dict()

        assert result["image"] == "test/image"
        assert result["disk"] == 40
        assert result["env"] == {"KEY": "value"}
        assert result["onstart"] == "startup.sh"
        assert result["label"] == "my-job"
        assert result["runtype"] == "oneshot"  # Default value


class TestVastAIClientBasic:
    """Test VastAIClient basic functionality (without complex API mocking)."""

    def test_initialization_with_api_key(self):
        """Test client initialization with API key."""
        client = VastAIClient(api_key="test_api_key")

        assert client.api_key == "test_api_key"
        assert client.api_base == "https://api.vast.ai/v0"

    def test_initialization_from_env(self, monkeypatch):
        """Test client initialization from environment."""
        monkeypatch.setenv('VAST_API_KEY', 'env_api_key')

        client = VastAIClient()

        assert client.api_key == 'env_api_key'

    def test_initialization_fails_without_api_key(self):
        """Test client initialization fails without API key."""
        with pytest.raises(ValueError, match="VAST_API_KEY"):
            VastAIClient()

    def test_session_initialized(self):
        """Test that requests session is initialized."""
        client = VastAIClient(api_key="test_key")

        assert client.session is not None
        assert 'Accept' in client.session.headers


# Note: Full API integration tests would require real API access or complex mocking
# The domain models (VastOffer, VastInstance, VastInstanceConfig) are tested above
# For now, basic client initialization is tested


