"""Metrics collection and monitoring."""

import time
from typing import Dict, Any, Optional
from collections import defaultdict


class MetricsCollector:
    """
    Collects and tracks metrics for video processing operations.
    Implements IMetricsCollector protocol.
    """

    def __init__(self):
        self._start_time = time.time()
        self._timers: Dict[str, float] = {}
        self._metrics: Dict[str, Any] = defaultdict(list)
        self._counters: Dict[str, int] = defaultdict(int)

    def start_timer(self, name: str) -> None:
        """Start a named timer."""
        self._timers[name] = time.time()

    def stop_timer(self, name: str) -> float:
        """
        Stop a named timer and return elapsed time.

        Args:
            name: Timer name

        Returns:
            Elapsed time in seconds

        Raises:
            KeyError: If timer was not started
        """
        if name not in self._timers:
            raise KeyError(f"Timer '{name}' was not started")

        elapsed = time.time() - self._timers[name]
        self.record_metric(f"{name}_duration", elapsed)
        del self._timers[name]
        return elapsed

    def record_metric(self, name: str, value: Any) -> None:
        """Record a metric value."""
        self._metrics[name].append(value)

    def increment_counter(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        self._counters[name] += amount

    def get_counter(self, name: str) -> int:
        """Get counter value."""
        return self._counters.get(name, 0)

    def get_metric(self, name: str) -> list:
        """Get all values for a metric."""
        return self._metrics.get(name, [])

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary of all metrics.

        Returns:
            Dictionary with metric summaries
        """
        summary = {
            "total_elapsed": self.elapsed_time(),
            "counters": dict(self._counters),
            "metrics": {}
        }

        for name, values in self._metrics.items():
            if values:
                if all(isinstance(v, (int, float)) for v in values):
                    summary["metrics"][name] = {
                        "count": len(values),
                        "sum": sum(values),
                        "avg": sum(values) / len(values),
                        "min": min(values),
                        "max": max(values),
                    }
                else:
                    summary["metrics"][name] = {
                        "count": len(values),
                        "values": values
                    }

        return summary

    def elapsed_time(self) -> float:
        """Get total elapsed time since initialization."""
        return time.time() - self._start_time

    def reset(self) -> None:
        """Reset all metrics and timers."""
        self._start_time = time.time()
        self._timers.clear()
        self._metrics.clear()
        self._counters.clear()

    def print_summary(self) -> None:
        """Print a formatted summary of metrics."""
        summary = self.get_summary()
        print("\n" + "="*60)
        print("METRICS SUMMARY")
        print("="*60)
        print(f"Total Elapsed: {summary['total_elapsed']:.2f}s")

        if summary['counters']:
            print("\nCounters:")
            for name, value in summary['counters'].items():
                print(f"  {name}: {value}")

        if summary['metrics']:
            print("\nMetrics:")
            for name, data in summary['metrics'].items():
                if 'avg' in data:
                    print(f"  {name}:")
                    print(f"    count: {data['count']}")
                    print(f"    avg: {data['avg']:.3f}")
                    print(f"    min: {data['min']:.3f}")
                    print(f"    max: {data['max']:.3f}")

        print("="*60 + "\n")

