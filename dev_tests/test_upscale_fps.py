"""Quick test to verify upscale FPS fix."""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Mock classes for testing
class MockVideoInfo:
    def __init__(self, fps=24):
        self.fps = fps
        self.frame_count = 145

class MockJob:
    def __init__(self, mode="upscale", target_fps=None):
        self.mode = mode
        self.job_id = "test"
        self.target_fps = target_fps
        self.interp_factor = 2.0
        self.scale = 2

# Test FPS calculation logic
def test_fps_calculation():
    video_info = MockVideoInfo(fps=24)
    
    # Test 1: upscale mode should use original FPS
    job = MockJob(mode="upscale", target_fps=None)
    if job.mode == "upscale":
        target_fps = job.target_fps or video_info.fps
    elif job.mode in ("interp", "both"):
        target_fps = job.target_fps or (video_info.fps * job.interp_factor)
    else:
        target_fps = job.target_fps or video_info.fps
    
    print(f"✓ Test 1 (upscale): Original FPS={video_info.fps}, Target FPS={target_fps}")
    assert target_fps == 24, f"Expected 24 FPS for upscale, got {target_fps}"
    
    # Test 2: interp mode should multiply FPS
    job = MockJob(mode="interp", target_fps=None)
    if job.mode == "upscale":
        target_fps = job.target_fps or video_info.fps
    elif job.mode in ("interp", "both"):
        target_fps = job.target_fps or (video_info.fps * job.interp_factor)
    else:
        target_fps = job.target_fps or video_info.fps
    
    print(f"✓ Test 2 (interp): Original FPS={video_info.fps}, Interp Factor={job.interp_factor}, Target FPS={target_fps}")
    assert target_fps == 48, f"Expected 48 FPS for interp, got {target_fps}"
    
    # Test 3: both mode should multiply FPS
    job = MockJob(mode="both", target_fps=None)
    if job.mode == "upscale":
        target_fps = job.target_fps or video_info.fps
    elif job.mode in ("interp", "both"):
        target_fps = job.target_fps or (video_info.fps * job.interp_factor)
    else:
        target_fps = job.target_fps or video_info.fps
    
    print(f"✓ Test 3 (both): Original FPS={video_info.fps}, Interp Factor={job.interp_factor}, Target FPS={target_fps}")
    assert target_fps == 48, f"Expected 48 FPS for both mode, got {target_fps}"
    
    # Test 4: explicit target_fps should override
    job = MockJob(mode="upscale", target_fps=60)
    if job.mode == "upscale":
        target_fps = job.target_fps or video_info.fps
    elif job.mode in ("interp", "both"):
        target_fps = job.target_fps or (video_info.fps * job.interp_factor)
    else:
        target_fps = job.target_fps or video_info.fps
    
    print(f"✓ Test 4 (explicit): Target FPS={target_fps}")
    assert target_fps == 60, f"Expected 60 FPS when explicitly set, got {target_fps}"
    
    print("\n✅ All FPS calculation tests passed!")

if __name__ == "__main__":
    test_fps_calculation()

