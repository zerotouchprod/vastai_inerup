#!/usr/bin/env python3
"""
Verify interpolation video properties.
Downloads and checks the actual video file properties.
"""

import subprocess
import sys
import json
import urllib.request

def get_video_info(video_path):
    """Get video info using ffprobe."""
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'v:0',
            '-show_entries', 'stream=nb_frames,r_frame_rate,duration:format=duration',
            '-of', 'json',
            video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        stream = data.get('streams', [{}])[0]
        format_data = data.get('format', {})
        
        # Parse frame rate (it's a fraction like "48/1")
        fps_str = stream.get('r_frame_rate', '0/1')
        fps_num, fps_den = map(int, fps_str.split('/'))
        fps = fps_num / fps_den if fps_den != 0 else 0
        
        nb_frames = stream.get('nb_frames')
        if nb_frames:
            nb_frames = int(nb_frames)
        
        duration = stream.get('duration') or format_data.get('duration')
        if duration:
            duration = float(duration)
        
        return {
            'fps': fps,
            'nb_frames': nb_frames,
            'duration': duration,
            'raw': data
        }
    except Exception as e:
        print(f"Error getting video info: {e}")
        return None

def main():
    url = "https://noxfvr-videos.s3.us-west-004.backblazeb2.com/testjobboth4.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=00473dbc426dc620000000009%2F20251205%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20251205T202518Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=81883c7565bdfaed11b654d81e7e4188194e3d860d03a3f9306dd12a3c5be7be"
    
    print("Downloading video...")
    try:
        urllib.request.urlretrieve(url, "testjobboth4.mp4")
        print("✓ Downloaded testjobboth4.mp4")
    except Exception as e:
        print(f"❌ Download failed: {e}")
        sys.exit(1)
    
    print("\nAnalyzing video properties...")
    info = get_video_info("testjobboth4.mp4")
    
    if not info:
        print("❌ Could not analyze video (ffprobe not available?)")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("VIDEO PROPERTIES")
    print("="*60)
    print(f"FPS:        {info['fps']:.2f}")
    print(f"Frames:     {info['nb_frames']}")
    print(f"Duration:   {info['duration']:.2f}s")
    
    if info['nb_frames'] and info['fps']:
        calculated_duration = info['nb_frames'] / info['fps']
        print(f"Calculated: {info['nb_frames']} frames / {info['fps']:.2f} fps = {calculated_duration:.2f}s")
    
    print("\n" + "="*60)
    print("EXPECTED VALUES (from logs)")
    print("="*60)
    print("FPS:        48.00")
    print("Frames:     289")
    print("Duration:   6.02s")
    
    print("\n" + "="*60)
    print("VERIFICATION")
    print("="*60)
    
    checks = {
        "FPS is 48": abs(info['fps'] - 48.0) < 1.0,
        "Duration ~6s": abs(info['duration'] - 6.0) < 0.5 if info['duration'] else False,
    }
    
    for check, passed in checks.items():
        status = "✓" if passed else "❌"
        print(f"{status} {check}")
    
    if all(checks.values()):
        print("\n✅ Video properties are CORRECT")
        print("   The interpolation is working as expected.")
        print("   If the video appears shorter when playing, check:")
        print("   - Your video player settings")
        print("   - Browser caching")
        print("   - Compare with original video side-by-side")
    else:
        print("\n❌ Video properties are INCORRECT")
        print("   There may be an issue with the FFmpeg assembly.")
    
    print("\n" + "="*60)
    print("RAW FFPROBE DATA")
    print("="*60)
    print(json.dumps(info['raw'], indent=2))

if __name__ == '__main__':
    main()

