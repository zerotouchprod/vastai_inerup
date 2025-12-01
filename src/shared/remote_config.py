"""
Remote config loader utility.

Handles downloading and merging remote configuration from config_url.
"""

import logging
from typing import Dict, Any, Optional
from pathlib import Path
import yaml

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


logger = logging.getLogger(__name__)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge override dict into base dict.

    Args:
        base: Base configuration
        override: Configuration to merge in (overrides base)

    Returns:
        Merged configuration
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def download_remote_config(
    config_url: str,
    timeout: int = 10,
    logger_instance: Optional[logging.Logger] = None
) -> Optional[Dict[str, Any]]:
    """
    Download and parse remote configuration from URL.

    Args:
        config_url: URL to download config from
        timeout: Request timeout in seconds
        logger_instance: Optional logger to use

    Returns:
        Parsed config dict, or None if failed
    """
    log = logger_instance or logger

    if not REQUESTS_AVAILABLE:
        log.error("requests library not available, cannot download remote config")
        return None

    if not config_url:
        return None

    try:
        log.info(f"[+] Downloading remote config: {config_url}")
        response = requests.get(config_url, timeout=timeout)
        response.raise_for_status()

        # Try to parse as JSON first, then YAML
        try:
            remote_config = response.json()
            log.info("[OK] Remote config parsed as JSON")
        except Exception:
            remote_config = yaml.safe_load(response.text)
            log.info("[OK] Remote config parsed as YAML")

        if not isinstance(remote_config, dict):
            log.warning("[WARN] Remote config is not a dict, ignoring")
            return None

        return remote_config

    except Exception as e:
        log.error(f"[ERROR] Failed to download remote config: {e}")
        return None


def load_config_with_remote(
    config_path: Path,
    logger_instance: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    Load config from YAML file and merge with remote config if config_url is set.

    Args:
        config_path: Path to config.yaml
        logger_instance: Optional logger to use

    Returns:
        Merged configuration

    Raises:
        FileNotFoundError: If config file doesn't exist
    """
    log = logger_instance or logger

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    # Load base config
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    # Check for remote config URL
    config_url = config.get('config_url', '').strip()
    if not config_url:
        return config

    # Download remote config
    remote_config = download_remote_config(config_url, logger_instance=log)
    if not remote_config:
        log.warning("Continuing with local config only")
        return config

    # Merge remote config
    merged = deep_merge(config, remote_config)
    log.info(f"[OK] Remote config merged: {list(remote_config.keys())}")

    # Show important merged params
    if 'video' in remote_config:
        log.info(f"  video params: {remote_config['video']}")
    if 'batch' in remote_config:
        log.info(f"  batch params: {remote_config['batch']}")

    return merged


def save_merged_config(
    config: Dict[str, Any],
    config_path: Path,
    logger_instance: Optional[logging.Logger] = None
) -> bool:
    """
    Save merged configuration back to file.

    Args:
        config: Configuration to save
        config_path: Path to save to
        logger_instance: Optional logger

    Returns:
        True if successful, False otherwise
    """
    log = logger_instance or logger

    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        log.info(f"[OK] Config saved to {config_path}")
        return True
    except Exception as e:
        log.error(f"[ERROR] Failed to save config: {e}")
        return False

