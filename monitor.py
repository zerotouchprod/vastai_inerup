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
import re

logger = get_logger(__name__)


class InstanceMonitor:
    """Monitor Vast.ai instance and stream logs."""

    def __init__(self, instance_id: int):
        self.instance_id = instance_id
        self.client = VastAIClient()
        self.last_log_size = 0
        self.success_marker = "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"

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

    def extract_result_url(self, logs: str) -> str:
        """Extract result URL from logs."""
        url_pattern = r'https://[^\s]+'
        urls = re.findall(url_pattern, logs)

        for url in reversed(urls):
            if 'noxfvr-videos' in url and any(x in url for x in ['output/', 'both/', 'upscales/', 'interps/']):
                return url
        return None

    def monitor(self, tail: int = 200, interval: int = 5, auto_destroy: bool = False):
        """
        Monitor instance logs in real-time.

        Args:
            tail: Number of lines to retrieve
            interval: Refresh interval in seconds
            auto_destroy: Automatically destroy instance on completion
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
                    print(f"\n❌ Instance #{self.instance_id} no longer exists")
                    break

                # Show status changes
                status_str = f"{info.actual_status} / {info.status}"
                if status_str != last_status:
                    print(f"\n[{current_time}] 📊 Status: {status_str}")
                    last_status = status_str

                # Progress indicator
                if check_count % 2 == 0:
                    print(f"[{current_time}] 🔄 Check #{check_count}...", end='\r', flush=True)

                # Get logs
                try:
                    logs = self.client.get_instance_logs(self.instance_id, tail=tail)

                    if logs:
                        lines = logs.split('\n')

                        # Show new lines (simple approach - compare total size)
                        current_size = len(logs)
                        if current_size > self.last_log_size:
                            # Show recent new lines
                            new_lines = lines[-50:] if check_count == 1 else lines[-10:]
                            for line in new_lines:
                                if line.strip():
                                    print(f"  [LOG] {line}")

                            self.last_log_size = current_size
                            print()  # Empty line for readability

                        # Check for completion
                        if self.success_marker in logs:
                            result_url = self.extract_result_url(logs)

                            print(f"\n{'='*70}")
                            print("🎉 SUCCESS! Processing completed!")
                            print(f"{'='*70}")

                            if result_url:
                                print(f"\n📥 Result URL:")
                                print(f"   {result_url}\n")

                            print(f"Instance: #{self.instance_id}")
                            print(f"GPU:      {info.gpu_name}")
                            print(f"Price:    ${info.price_per_hour:.4f}/hr")

                            if auto_destroy:
                                print(f"\n🧹 Auto-destroying instance...")
                                if self.client.destroy_instance(self.instance_id):
                                    print(f"✅ Instance #{self.instance_id} destroyed")
                                else:
                                    print(f"⚠️  Failed to destroy instance")
                            else:
                                print(f"\n💡 To destroy instance:")
                                print(f"   python monitor.py {self.instance_id} --destroy")

                            break

                        # Check for errors
                        if any(marker in logs for marker in ['ERROR', 'FAILED', 'Exception']):
                            # Show error context
                            error_lines = [l for l in lines[-30:] if any(e in l for e in ['ERROR', 'FAILED', 'Exception'])]
                            if error_lines:
                                print(f"\n⚠️  Errors detected:")
                                for line in error_lines[-5:]:
                                    print(f"  {line}")
                                print()

                except Exception as e:
                    print(f"[{current_time}] ⚠️  Error fetching logs: {e}")

                # Check if stopped
                if info.actual_status in ['stopped', 'exited']:
                    print(f"\n⚠️  Instance stopped (status: {info.actual_status})")

                    # Show final logs
                    logs = self.client.get_instance_logs(self.instance_id, tail=50)
                    if logs:
                        print("\nFinal logs:")
                        for line in logs.split('\n')[-20:]:
                            if line.strip():
                                print(f"  {line}")

                    break

                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n\n⏸️  Monitoring stopped by user")
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
  
  # With custom interval
  python monitor.py 28397367 --interval 10
  
  # Auto-destroy on completion
  python monitor.py 28397367 --auto-destroy
  
  # Just destroy instance
  python monitor.py 28397367 --destroy
        """
    )

    parser.add_argument('instance_id', type=int, help='Instance ID to monitor')
    parser.add_argument('--tail', type=int, default=200, help='Number of log lines (default: 200)')
    parser.add_argument('--interval', type=int, default=5, help='Refresh interval in seconds (default: 5)')
    parser.add_argument('--auto-destroy', action='store_true', help='Auto-destroy on completion')
    parser.add_argument('--destroy', action='store_true', help='Just destroy instance and exit')

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
        auto_destroy=args.auto_destroy
    )


if __name__ == '__main__':
    main()

