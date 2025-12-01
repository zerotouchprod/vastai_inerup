"""
Helper script to create test video for integration tests.

Usage:
    python tests/integration/create_test_video.py

This will create tests/video/test.mp4 using ffmpeg.
"""

import subprocess
from pathlib import Path
import sys


def create_test_video():
    """Create a test video using ffmpeg."""

    # Paths
    script_dir = Path(__file__).parent
    video_dir = script_dir.parent / "video"
    test_video = video_dir / "test.mp4"

    # Create directory
    video_dir.mkdir(parents=True, exist_ok=True)

    print("🎬 Creating test video...")
    print(f"   Output: {test_video}")

    # Check if ffmpeg is available
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ ffmpeg not found!")
        print("   Please install ffmpeg:")
        print("   - Windows: choco install ffmpeg")
        print("   - Mac: brew install ffmpeg")
        print("   - Linux: apt-get install ffmpeg")
        return False

    # Create test video with color bars and moving pattern
    cmd = [
        'ffmpeg',
        '-f', 'lavfi',
        '-i', 'testsrc=duration=5:size=640x360:rate=24',  # 5 seconds, 640x360, 24 fps
        '-pix_fmt', 'yuv420p',  # Compatible pixel format
        '-c:v', 'libx264',  # H.264 codec
        '-crf', '23',  # Quality
        '-preset', 'fast',  # Encoding speed
        '-y',  # Overwrite
        str(test_video)
    ]

    try:
        print("   Running ffmpeg...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        if test_video.exists():
            size_mb = test_video.stat().st_size / (1024 * 1024)
            print(f"✅ Test video created!")
            print(f"   Path: {test_video}")
            print(f"   Size: {size_mb:.2f} MB")
            print(f"   Duration: 5 seconds")
            print(f"   Resolution: 640x360")
            print(f"   FPS: 24")
            return True
        else:
            print("❌ Video file not created")
            return False

    except subprocess.CalledProcessError as e:
        print(f"❌ ffmpeg failed:")
        print(f"   {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


def verify_test_video():
    """Verify that test video exists and is valid."""

    video_dir = Path(__file__).parent.parent / "video"
    test_video = video_dir / "test.mp4"

    if not test_video.exists():
        print("❌ Test video not found")
        return False

    # Check with ffprobe
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,r_frame_rate,nb_frames',
            '-of', 'default=noprint_wrappers=1',
            str(test_video)
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        print("✅ Test video is valid:")
        for line in result.stdout.strip().split('\n'):
            if '=' in line:
                key, value = line.split('=')
                print(f"   {key}: {value}")

        return True

    except (subprocess.CalledProcessError, FileNotFoundError):
        # ffprobe not available, just check file size
        size_mb = test_video.stat().st_size / (1024 * 1024)
        print(f"✅ Test video exists ({size_mb:.2f} MB)")
        print("   (Install ffprobe for detailed info)")
        return True


def main():
    """Main function."""

    print("="*60)
    print("Test Video Creator")
    print("="*60)
    print()

    video_dir = Path(__file__).parent.parent / "video"
    test_video = video_dir / "test.mp4"

    # Check if video already exists
    if test_video.exists():
        print(f"⚠️  Test video already exists: {test_video}")
        response = input("   Recreate? (y/N): ").strip().lower()
        if response != 'y':
            print("   Keeping existing video")
            verify_test_video()
            return 0
        print()

    # Create video
    success = create_test_video()

    if not success:
        return 1

    print()
    print("="*60)
    print("Next steps:")
    print("  1. Run integration tests:")
    print("     pytest tests/integration/ -v")
    print()
    print("  2. Run with output:")
    print("     pytest tests/integration/ -v -s")
    print()
    print("  3. Run ML tests (requires GPU):")
    print("     RUN_ML_TESTS=1 pytest tests/integration/ -v")
    print("="*60)

    return 0


if __name__ == '__main__':
    sys.exit(main())

