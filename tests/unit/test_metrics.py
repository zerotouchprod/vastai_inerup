"""Test metrics collector."""

import pytest
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from shared.metrics import MetricsCollector


def test_metrics_timer():
    """Test timer functionality."""
    metrics = MetricsCollector()

    metrics.start_timer('test')
    time.sleep(0.1)
    elapsed = metrics.stop_timer('test')

    assert elapsed >= 0.1
    assert len(metrics.get_metric('test_duration')) > 0


def test_metrics_counter():
    """Test counter functionality."""
    metrics = MetricsCollector()

    metrics.increment_counter('frames')
    metrics.increment_counter('frames')
    metrics.increment_counter('frames', amount=3)

    assert metrics.get_counter('frames') == 5


def test_metrics_summary():
    """Test summary generation."""
    metrics = MetricsCollector()

    metrics.record_metric('fps', 30.0)
    metrics.record_metric('fps', 29.5)
    metrics.record_metric('fps', 30.5)

    summary = metrics.get_summary()

    assert 'fps' in summary['metrics']
    assert summary['metrics']['fps']['count'] == 3
    assert summary['metrics']['fps']['avg'] == 30.0
