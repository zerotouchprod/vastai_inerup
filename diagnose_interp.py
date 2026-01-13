#!/usr/bin/env python3
"""
Diagnostic script for RIFE interpolation issues.

Analyzes logs and frames to identify why output videos are shorter than expected.
"""

import sys
from pathlib import Path
import subprocess
import json


def get_video_info(video_path):
    """Get video information using ffprobe."""
    cmd = [
        'ffprobe',
        '-v', 'quiet',
        '-print_format', 'json',
        '-show_format',
        '-show_streams',
        str(video_path)
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)

        video_stream = None
        for stream in data.get('streams', []):
            if stream.get('codec_type') == 'video':
                video_stream = stream
                break

        if not video_stream:
            return None

        # Parse FPS
        fps_str = video_stream.get('avg_frame_rate', '0/1')
        if '/' in fps_str:
            num, den = fps_str.split('/')
            fps = float(num) / float(den) if float(den) > 0 else 0
        else:
            fps = float(fps_str)

        duration = float(data.get('format', {}).get('duration', 0))
        nb_frames = int(video_stream.get('nb_frames', 0))

        return {
            'fps': fps,
            'duration': duration,
            'nb_frames': nb_frames,
            'width': int(video_stream.get('width', 0)),
            'height': int(video_stream.get('height', 0)),
            'codec': video_stream.get('codec_name', 'unknown')
        }
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None


def count_frames_in_dir(frames_dir):
    """Count frames in a directory."""
    frames_dir = Path(frames_dir)
    if not frames_dir.exists():
        return 0, []

    frames = sorted(frames_dir.glob("frame_*.png"))
    return len(frames), frames


def analyze_frame_sequence(frames):
    """Check for gaps in frame sequence."""
    if not frames:
        return None

    frame_numbers = []
    for f in frames:
        try:
            # Extract number from frame_000001.png
            num = int(f.stem.split('_')[1])
            frame_numbers.append(num)
        except (IndexError, ValueError):
            pass

    if not frame_numbers:
        return None

    frame_numbers.sort()
    expected = list(range(frame_numbers[0], frame_numbers[-1] + 1))
    missing = set(expected) - set(frame_numbers)

    return {
        'first': frame_numbers[0],
        'last': frame_numbers[-1],
        'count': len(frame_numbers),
        'expected_count': len(expected),
        'missing': sorted(missing)
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose_interp.py <input_video> [output_video] [frames_dir]")
        print("Example: python diagnose_interp.py input.mp4 output.mp4 /tmp/job_xxx/interpolated")
        sys.exit(1)

    input_video = Path(sys.argv[1])
    output_video = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    frames_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    print("═══════════════════════════════════════════════════════")
    print("RIFE INTERPOLATION DIAGNOSTIC TOOL")
    print("═══════════════════════════════════════════════════════\n")

    # Analyze input video
    if input_video.exists():
        print("📹 INPUT VIDEO")
        info = get_video_info(input_video)
        if info:
            print(f"  Path: {input_video}")
            print(f"  Resolution: {info['width']}×{info['height']}")
            print(f"  FPS: {info['fps']:.2f}")
            print(f"  Duration: {info['duration']:.2f}s")
            print(f"  Frames (reported): {info['nb_frames']}")
            print(f"  Calculated frames: {info['fps'] * info['duration']:.0f}")
            print(f"  Codec: {info['codec']}")
            input_info = info
        else:
            print(f"  ❌ Could not analyze {input_video}")
            input_info = None
    else:
        print(f"❌ Input video not found: {input_video}")
        input_info = None

    print()

    # Analyze output video
    if output_video and output_video.exists():
        print("📹 OUTPUT VIDEO")
        info = get_video_info(output_video)
        if info:
            print(f"  Path: {output_video}")
            print(f"  Resolution: {info['width']}×{info['height']}")
            print(f"  FPS: {info['fps']:.2f}")
            print(f"  Duration: {info['duration']:.2f}s")
            print(f"  Frames (reported): {info['nb_frames']}")
            print(f"  Calculated frames: {info['fps'] * info['duration']:.0f}")
            print(f"  Codec: {info['codec']}")
            output_info = info

            # Compare with input
            if input_info:
                print("\n  📊 COMPARISON")
                duration_diff = output_info['duration'] - input_info['duration']
                fps_ratio = output_info['fps'] / input_info['fps'] if input_info['fps'] > 0 else 0

                print(f"  Duration change: {duration_diff:+.2f}s ({duration_diff/input_info['duration']*100:+.1f}%)")
                print(f"  FPS ratio: {fps_ratio:.2f}x")

                if abs(duration_diff) > 0.5:
                    print(f"  ⚠️ Duration mismatch > 0.5s!")
                if fps_ratio < 1.9 or fps_ratio > 2.1:
                    print(f"  ⚠️ FPS ratio not close to 2x!")
        else:
            print(f"  ❌ Could not analyze {output_video}")
    elif output_video:
        print(f"❌ Output video not found: {output_video}")

    print()

    # Analyze frames directory
    if frames_dir and frames_dir.exists():
        print("📁 INTERPOLATED FRAMES")
        frame_count, frames = count_frames_in_dir(frames_dir)
        print(f"  Directory: {frames_dir}")
        print(f"  Frame count: {frame_count}")

        if frames:
            print(f"  First frame: {frames[0].name}")
            print(f"  Last frame: {frames[-1].name}")

            # Check sequence
            seq_info = analyze_frame_sequence(frames)
            if seq_info:
                print(f"\n  📋 SEQUENCE ANALYSIS")
                print(f"  Frame numbers: {seq_info['first']} → {seq_info['last']}")
                print(f"  Actual frames: {seq_info['count']}")
                print(f"  Expected frames: {seq_info['expected_count']}")

                if seq_info['missing']:
                    print(f"  ⚠️ Missing frames: {len(seq_info['missing'])}")
                    if len(seq_info['missing']) <= 20:
                        print(f"     {seq_info['missing']}")
                    else:
                        print(f"     First 20: {seq_info['missing'][:20]}")
                else:
                    print(f"  ✓ No gaps in frame sequence")

                # Calculate expected interpolation
                if input_info:
                    expected_interp_frames = input_info['nb_frames'] + (input_info['nb_frames'] - 1) * 1  # 2x interp
                    print(f"\n  📊 INTERPOLATION ANALYSIS (assuming 2x)")
                    print(f"  Input frames: {input_info['nb_frames']}")
                    print(f"  Expected output: {expected_interp_frames}")
                    print(f"  Actual output: {frame_count}")
                    print(f"  Difference: {frame_count - expected_interp_frames:+d}")

                    if frame_count != expected_interp_frames:
                        print(f"  ⚠️ Frame count mismatch!")
    elif frames_dir:
        print(f"❌ Frames directory not found: {frames_dir}")

    print("\n═══════════════════════════════════════════════════════")


if __name__ == '__main__':
    main()

