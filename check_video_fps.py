"""Check actual FPS of output video."""
import subprocess
import json
import sys

def check_video_fps(video_path):
    """Use ffprobe to check actual video FPS."""
    cmd = [
        'ffprobe',
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=r_frame_rate,nb_frames,duration',
        '-of', 'json',
        video_path
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        if 'streams' in data and len(data['streams']) > 0:
            stream = data['streams'][0]
            
            # Parse r_frame_rate (fraction like "48/1")
            fps_str = stream.get('r_frame_rate', '0/1')
            num, den = map(int, fps_str.split('/'))
            fps = num / den if den != 0 else 0
            
            nb_frames = stream.get('nb_frames', 'N/A')
            duration = stream.get('duration', 'N/A')
            
            print(f"Video: {video_path}")
            print(f"  FPS: {fps} ({fps_str})")
            print(f"  Frames: {nb_frames}")
            print(f"  Duration: {duration}s")
            
            if duration != 'N/A' and nb_frames != 'N/A':
                try:
                    calc_fps = int(nb_frames) / float(duration)
                    print(f"  Calculated FPS: {calc_fps:.2f}")
                except:
                    pass
            
            return fps
        else:
            print(f"No video stream found in {video_path}")
            return None
            
    except subprocess.CalledProcessError as e:
        print(f"ffprobe error: {e.stderr}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_video_fps.py <video_path>")
        print("\nTo check a remote video, first download it:")
        print("  wget <url> -O test_video.mp4")
        print("  python check_video_fps.py test_video.mp4")
        sys.exit(1)
    
    video_path = sys.argv[1]
    check_video_fps(video_path)

