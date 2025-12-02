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
        self.initial_success_count = 0  # Count of success markers at monitor start
        self.seen_new_success = False   # Track if we've seen a NEW success marker
        self.upload_url_marker = "B2 upload successful"
        self.last_upload_time = None    # Track when we saw the last upload
        self.consecutive_errors = 0     # Track consecutive API errors for backoff
        self.max_backoff = 60           # Max backoff delay in seconds
        self.first_logs_shown = False   # Track if we've shown initial logs

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

                # Get logs
                try:
                    logs = self.client.get_instance_logs(self.instance_id, tail=tail)

                    if logs:
                        lines = logs.split('\n')
                        current_size = len(logs)

                        # Detect if this is the first successful log fetch
                        is_first_successful_check = not self.first_logs_shown

                        # On first SUCCESSFUL check (could be check #1 or later after retries)
                        if is_first_successful_check:
                            self.first_logs_shown = True
                            self.initial_success_count = logs.count(self.success_marker)
                            if self.initial_success_count > 0:
                                print(f"\n  ℹ️  Found {self.initial_success_count} old success marker(s) from previous run(s)")
                                print(f"  ⏳ Waiting for NEW completion...")

                        # Show logs if:
                        # 1. First successful check (show initial logs)
                        # 2. Logs size increased (new content)
                        # 3. Every 10 checks even if no change (keep user informed)
                        should_show_logs = (
                            is_first_successful_check or
                            current_size > self.last_log_size or
                            check_count % 10 == 0
                        )

                        if should_show_logs:
                            # Determine how many lines to show
                            if is_first_successful_check:
                                # First successful check: show initial logs
                                new_lines = lines if full_logs else lines[-100:]
                                header = f"📋 Initial logs (last {len([l for l in new_lines if l.strip()])} lines):"
                            elif current_size > self.last_log_size:
                                # New content: show recent additions
                                new_lines = lines[-20:]
                                header = "📋 New logs:"
                            else:
                                # Periodic update: show last few lines
                                new_lines = lines[-10:]
                                header = "📋 Recent logs (periodic check):"

                            # Only print if there are non-empty lines
                            non_empty_lines = [l for l in new_lines if l.strip()]
                            if non_empty_lines:
                                print(f"\n{header}")
                                for line in non_empty_lines:
                                    # Extract timestamp from log line if present, otherwise use current time
                                    log_timestamp = current_time
                                    # Look for [HH:MM:SS] pattern in the log line
                                    timestamp_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                                    if timestamp_match:
                                        log_timestamp = timestamp_match.group(1)
                                    print(f"  [{log_timestamp}] {line}")
                                print()  # Empty line for readability

                            self.last_log_size = current_size

                        # Check for NEW completion (count must increase AND we need recent upload)
                        current_success_count = logs.count(self.success_marker)

                        # Track upload events - this is the definitive sign of new completion
                        has_new_upload = False
                        recent_lines = lines[-100:]
                        for i, line in enumerate(recent_lines):
                            if self.upload_url_marker in line:
                                # Found upload success marker
                                upload_time = current_time
                                timestamp_match = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', line)
                                if timestamp_match:
                                    upload_time = timestamp_match.group(1)

                                # Check if this is a NEW upload (different time than last)
                                if self.last_upload_time != upload_time:
                                    self.last_upload_time = upload_time
                                    has_new_upload = True
                                    print(f"\n  ✅ Detected new upload at {upload_time}")
                                break

                        # Only consider completion if we detected a new upload event
                        # The upload event is the definitive marker - it means:
                        # 1. Pipeline completed successfully
                        # 2. File was uploaded to B2
                        # 3. This is a NEW completion (not from previous run)
                        if has_new_upload and not self.seen_new_success:
                            self.seen_new_success = True  # Mark as seen
                            result_url = self.extract_result_url(logs)

                            print(f"\n{'='*70}")
                            print("🎉 SUCCESS! NEW processing completed!")
                            print(f"{'='*70}")
                            print(f"  Old completions: {self.initial_success_count}")
                            print(f"  New completions: {current_success_count - self.initial_success_count}")

                            if result_url:
                                print(f"\n📥 Result URL:")
                                print(f"   {result_url}\n")

                            print(f"Instance: #{self.instance_id}")
                            print(f"GPU:      {info.gpu_name}")
                            print(f"Price:    ${info.price_per_hour:.4f}/hr")

                            # Stop the instance (not destroy)
                            print(f"\n⏹️  Stopping instance...")
                            try:
                                if self.client.stop_instance(self.instance_id):
                                    print(f"✅ Instance #{self.instance_id} stopped")
                                else:
                                    print(f"⚠️  Failed to stop instance (may not be running)")
                            except Exception as e:
                                print(f"⚠️  Error stopping instance: {e}")

                            if auto_destroy:
                                print(f"\n🧹 Auto-destroying instance...")
                                if self.client.destroy_instance(self.instance_id):
                                    print(f"✅ Instance #{self.instance_id} destroyed")
                                    print(f"    Monitor will keep running (Press Ctrl+C to stop)")
                                else:
                                    print(f"⚠️  Failed to destroy instance")
                            else:
                                print(f"\n💡 To destroy instance:")
                                print(f"   python monitor.py {self.instance_id} --destroy")

                            # Continue monitoring - don't break the loop
                            print(f"\n🔄 Continuing to monitor logs and status...")
                            print(f"   Press Ctrl+C to stop monitoring\n")

                            # Reset for next completion
                            self.initial_success_count = current_success_count
                            self.seen_new_success = False

                        # Check for errors
                        if any(marker in logs for marker in ['ERROR', 'FAILED', 'Exception']):
                            # Show error context
                            error_lines = [l for l in lines[-30:] if any(e in l for e in ['ERROR', 'FAILED', 'Exception'])]
                            if error_lines:
                                print(f"\n⚠️  Errors detected:")
                                for line in error_lines[-5:]:
                                    print(f"  {line}")
                                print()
                    else:
                        # No logs available
                        if check_count == 1:
                            print(f"\n  ⚠️  No logs available yet (container may be starting...)\n")

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

