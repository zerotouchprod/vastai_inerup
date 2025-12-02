#!/usr/bin/env python3
"""
Modern instance monitor using new VastAI client infrastructure.

Usage:
    # Monitor specific instance
    python monitor.py 28397367

    # With custom refresh interval
    python monitor.py 28397367 --interval 10

    # Show more log lines
    python monitor.py 28397367 --tail 500
"""

import sys
import time
import argparse
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from infrastructure.vastai.client import VastAIClient
from shared.logging import get_logger

logger = get_logger(__name__)


class InstanceMonitor:
    """Monitor Vast.ai instance and stream logs."""

    def __init__(self, instance_id: int):
        self.instance_id = instance_id
        self.client = VastAIClient()
        self.last_log_lines = []        # Track previous log lines to show only new ones
        self.consecutive_errors = 0     # Track API errors for backoff
        self.max_backoff = 60           # Max backoff delay

    def get_info(self):
        """Get instance info."""
        try:
            return self.client.get_instance(self.instance_id)
        except Exception as e:
            logger.error(f"Failed to get instance info: {e}")
            return None

    def print_header(self):
        """Print instance information header."""
        info = self.get_info()
        if not info:
            print(f"❌ Instance #{self.instance_id} not found")
            return False

        print(f"\n{'='*70}")
        print(f"📍 Monitoring Instance #{self.instance_id}")
        print(f"{'='*70}")
        print(f"GPU:         {info.gpu_name}")
        print(f"Status:      {info.status}")
        print(f"State:       {info.actual_status}")
        print(f"Price:       ${info.price_per_hour:.4f}/hr")

        if info.ssh_host and info.ssh_port:
            print(f"SSH:         ssh -p {info.ssh_port} root@{info.ssh_host}")

        print(f"{'='*70}\n")
        return True


    def monitor(self, tail: int = 1000, interval: int = 5, auto_destroy: bool = False, full_logs: bool = False):
        """
        Monitor instance logs in real-time.

        Args:
            tail: Number of lines to retrieve
            interval: Refresh interval in seconds
            auto_destroy: Automatically destroy instance on completion
            full_logs: Show all logs on first check (not just last 50)
        """
        if not self.print_header():
            return

        print("🔄 Streaming logs... (Ctrl+C to stop monitoring)\n")

        check_count = 0
        last_status = None

        try:
            while True:
                check_count += 1
                current_time = time.strftime('%H:%M:%S')

                # Get instance status
                info = self.get_info()
                if not info:
                    # Don't exit - implement exponential backoff
                    self.consecutive_errors += 1
                    backoff_delay = min(interval * (2 ** (self.consecutive_errors - 1)), self.max_backoff)

                    print(f"\n⚠️  Failed to get instance info (API error or rate limit)")
                    print(f"    Retry attempt #{self.consecutive_errors}, waiting {backoff_delay:.0f}s...")
                    print(f"    (Press Ctrl+C to stop monitoring)")

                    time.sleep(backoff_delay)
                    continue

                # Reset error counter on success
                if self.consecutive_errors > 0:
                    print(f"\n✅ Connection restored after {self.consecutive_errors} failed attempts")
                    self.consecutive_errors = 0

                # Show status changes
                status_str = f"{info.actual_status} / {info.status}"
                if status_str != last_status:
                    print(f"\n[{current_time}] 📊 Status: {status_str}")
                    last_status = status_str

                # Progress indicator
                if check_count % 2 == 0:
                    # Show different indicator based on instance state
                    state_indicator = "🔄" if info.actual_status not in ['stopped', 'exited'] else "💤"
                    print(f"[{current_time}] {state_indicator} Check #{check_count}...", end='\r', flush=True)

                # Get logs - SIMPLE: just get them and show new ones
                try:
                    logs = self.client.get_instance_logs(self.instance_id, tail=tail)

                    if logs:
                        lines = logs.split('\n')
                        current_lines = [l.rstrip() for l in lines if l.strip()]  # Clean lines

                        if not self.last_log_lines:
                            # First time - show all available logs
                            print()
                            for line in current_lines:
                                print(line)
                            print()
                            self.last_log_lines = current_lines
                        else:
                            # Find new lines
                            new_lines = []
                            if current_lines and self.last_log_lines:
                                # Find last line from previous check
                                try:
                                    last_line = self.last_log_lines[-1]
                                    idx = current_lines.index(last_line)
                                    new_lines = current_lines[idx + 1:]
                                except (ValueError, IndexError):
                                    # Can't find marker - show last 20 lines
                                    new_lines = current_lines[-20:]
                            elif current_lines:
                                # Have current but no previous - show all
                                new_lines = current_lines

                            # Print new lines
                            if new_lines:
                                for line in new_lines:
                                    print(line)
                                print()

                            # Update state
                            self.last_log_lines = current_lines

                    else:
                        # No logs yet
                        if check_count % 3 == 0:
                            print(f"  ⏳ Waiting for logs... (check #{check_count})")

                except Exception as e:
                    print(f"[{current_time}] ⚠️  Error fetching logs: {e}")

                # Check if stopped - but DON'T exit, just inform
                if info.actual_status in ['stopped', 'exited']:
                    # Only show this message once when status changes
                    if last_status and not any(x in last_status for x in ['stopped', 'exited']):
                        print(f"\n⚠️  Instance stopped (status: {info.actual_status})")
                        print(f"    Still monitoring... (logs won't update until instance restarts)")
                        print(f"    Press Ctrl+C to stop monitoring\n")

                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n⏸️  Monitoring stopped by user (Ctrl+C)")
            print(f"\n💡 Commands:")
            print(f"   Resume:  python monitor.py {self.instance_id}")
            print(f"   Destroy: python monitor.py {self.instance_id} --destroy")
            print(f"\n{'='*70}")
            print("Monitoring finished")
            print(f"{'='*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Monitor Vast.ai instance logs',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor instance
  python monitor.py 28397367
  
  # Show all logs on startup (not just recent)
  python monitor.py 28397367 --full
  
  # With custom interval and more log lines
  python monitor.py 28397367 --interval 10 --tail 2000
  
  # Auto-destroy on completion
  python monitor.py 28397367 --auto-destroy
  
  # Just destroy instance
  python monitor.py 28397367 --destroy
        """
    )

    parser.add_argument('instance_id', type=int, help='Instance ID to monitor')
    parser.add_argument('--tail', type=int, default=1000, help='Number of log lines (default: 1000)')
    parser.add_argument('--interval', type=int, default=5, help='Refresh interval in seconds (default: 5)')
    parser.add_argument('--auto-destroy', action='store_true', help='Auto-destroy on completion')
    parser.add_argument('--destroy', action='store_true', help='Just destroy instance and exit')
    parser.add_argument('--full', action='store_true', help='Show all logs on first check')

    args = parser.parse_args()

    monitor = InstanceMonitor(args.instance_id)

    # Just destroy if requested
    if args.destroy:
        print(f"🧹 Destroying instance #{args.instance_id}...")
        client = VastAIClient()
        if client.destroy_instance(args.instance_id):
            print(f"✅ Instance #{args.instance_id} destroyed")
        else:
            print(f"❌ Failed to destroy instance")
        return

    # Monitor
    monitor.monitor(
        tail=args.tail,
        interval=args.interval,
        auto_destroy=args.auto_destroy,
        full_logs=args.full
    )


if __name__ == '__main__':
    main()

