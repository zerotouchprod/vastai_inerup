"""Quick test to download and check the output video FPS."""
import subprocess
import requests
import tempfile
import os

# Latest successful job
url = "https://noxfvr-videos.s3.us-west-004.backblazeb2.com/testjobboth4.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=00473dbc426dc620000000009%2F20251205%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20251205T202518Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=81883c7565bdfaed11b654d81e7e4188194e3d860d03a3f9306dd12a3c5be7be"

print("Downloading video...")
response = requests.get(url)

if response.status_code == 200:
    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as f:
        f.write(response.content)
        temp_path = f.name

    print(f"Downloaded {len(response.content)} bytes")
    print(f"Saved to: {temp_path}")
    print()

    # Check with ffprobe
    print("Checking video properties with ffprobe...")
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate,nb_frames,duration,width,height',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1',
        temp_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)

    # Cleanup
    os.unlink(temp_path)
    print(f"\nCleaned up temp file")
else:
    print(f"Failed to download: HTTP {response.status_code}")

