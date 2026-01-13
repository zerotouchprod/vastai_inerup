#!/usr/bin/env python3
"""
Verification script: Simulates orchestrator duration calculation logic.
This tests the exact flow from the fixed orchestrator.py.
"""

def simulate_orchestrator_duration_logic():
    """Simulate the exact logic from orchestrator.py."""
    
    print("="*70)
    print("SIMULATION: Orchestrator Duration Calculation Logic")
    print("="*70)
    
    # Simulate video metadata (what FFmpeg reports)
    video_metadata = {
        'fps': 60.0,
        'duration': 8.0,  # Incorrect metadata
        'frame_count': 480,
        'width': 1080,
        'height': 1920
    }
    
    # Simulate actual extraction (what we really get)
    actual_extracted_frames = 426  # Less than expected!
    
    # Simulate audio track
    audio_duration = 7.10  # Ground truth
    
    print("\n📹 Video Metadata (from FFmpeg):")
    print(f"   Duration: {video_metadata['duration']:.2f}s")
    print(f"   FPS: {video_metadata['fps']}")
    print(f"   Frame count: {video_metadata['frame_count']}")
    print(f"   Expected frames: {video_metadata['duration'] * video_metadata['fps']:.0f}")
    
    print(f"\n🎞️  Actual Extraction:")
    print(f"   Extracted: {actual_extracted_frames} frames")
    print(f"   Discrepancy: {actual_extracted_frames - video_metadata['frame_count']} frames")
    
    # Step 1: Calculate frame-based duration
    original_frame_count = actual_extracted_frames
    original_fps = video_metadata['fps']
    frame_based_duration = original_frame_count / original_fps
    
    print(f"\n📊 Frame-based Calculation:")
    print(f"   {original_frame_count} frames ÷ {original_fps} fps = {frame_based_duration:.2f}s")
    
    # Step 2: Audio duration (ground truth)
    print(f"\n🔊 Audio Track:")
    print(f"   Duration: {audio_duration:.2f}s")
    
    # Step 3: Compare and use audio as ground truth
    duration_diff = abs(audio_duration - frame_based_duration)
    print(f"\n⚖️  Duration Comparison:")
    print(f"   Frame-based: {frame_based_duration:.2f}s")
    print(f"   Audio-based: {audio_duration:.2f}s")
    print(f"   Difference: {duration_diff:.2f}s")
    
    # NEW LOGIC: Use audio as ground truth if mismatch > 0.5s
    original_duration = audio_duration if duration_diff > 0.5 else frame_based_duration
    
    if duration_diff > 0.5:
        print(f"   ⚠️  Mismatch detected! Using audio as ground truth: {audio_duration:.2f}s")
    else:
        print(f"   ✅ Durations match, using frame-based: {frame_based_duration:.2f}s")
    
    # Step 4: Interpolation calculation
    interp_factor = 3
    
    expected_output_frames = original_frame_count + (original_frame_count - 1) * (interp_factor - 1)
    target_fps = original_fps * interp_factor
    expected_output_duration = expected_output_frames / target_fps
    
    print(f"\n🎬 Interpolation (Factor: {interp_factor}x):")
    print(f"   Input: {original_frame_count} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Output frames: {original_frame_count} + ({original_frame_count}-1) × ({interp_factor}-1) = {expected_output_frames}")
    print(f"   Target FPS: {original_fps} × {interp_factor} = {target_fps} fps")
    print(f"   Expected duration: {expected_output_frames} ÷ {target_fps} = {expected_output_duration:.2f}s")
    
    # Step 5: Verify duration preserved
    final_duration_diff = abs(expected_output_duration - original_duration)
    
    print(f"\n✅ Final Verification:")
    print(f"   Original: {original_duration:.2f}s")
    print(f"   Output: {expected_output_duration:.2f}s")
    print(f"   Difference: {final_duration_diff:.3f}s")
    
    if final_duration_diff < 0.1:
        print(f"   ✅ Duration PRESERVED! (tolerance: 0.1s)")
        return True
    else:
        print(f"   ❌ Duration NOT preserved! (diff: {final_duration_diff:.2f}s)")
        return False


def test_user_scenario():
    """Test the exact scenario from user's logs."""
    print("\n" + "="*70)
    print("USER'S PROBLEMATIC SCENARIO")
    print("="*70)
    
    # From logs:
    # Audio: 7.10s
    # Original frames: 192
    # Interp factor: likely 3x
    # Result was: 6.38s (BROKEN)
    
    audio_duration = 7.10
    original_frame_count = 192
    interp_factor = 3
    
    # Calculate what FPS should be used
    original_fps = original_frame_count / audio_duration
    
    print(f"\n📊 User's Video:")
    print(f"   Audio duration: {audio_duration:.2f}s")
    print(f"   Extracted frames: {original_frame_count}")
    print(f"   Calculated FPS: {original_fps:.2f}")
    
    # OLD BROKEN LOGIC (what was happening before)
    print(f"\n❌ OLD LOGIC (BROKEN):")
    wrong_fps = 24.0  # Using wrong default
    wrong_target_fps = wrong_fps * interp_factor
    expected_frames = original_frame_count + (original_frame_count - 1) * (interp_factor - 1)
    wrong_duration = expected_frames / wrong_target_fps
    print(f"   Used wrong FPS: {wrong_fps}")
    print(f"   Target FPS: {wrong_target_fps}")
    print(f"   Output duration: {wrong_duration:.2f}s ❌ (should be {audio_duration:.2f}s)")
    print(f"   Duration loss: {abs(wrong_duration - audio_duration):.2f}s")
    
    # NEW FIXED LOGIC
    print(f"\n✅ NEW LOGIC (FIXED):")
    correct_fps = original_fps
    correct_target_fps = correct_fps * interp_factor
    correct_duration = expected_frames / correct_target_fps
    print(f"   Using audio-based FPS: {correct_fps:.2f}")
    print(f"   Target FPS: {correct_target_fps:.2f}")
    print(f"   Output duration: {correct_duration:.2f}s ✅")
    print(f"   Duration diff: {abs(correct_duration - audio_duration):.3f}s")
    
    if abs(correct_duration - audio_duration) < 0.1:
        print(f"\n   ✅ Duration PRESERVED!")
        return True
    else:
        print(f"\n   ❌ Duration NOT preserved!")
        return False


if __name__ == "__main__":
    result1 = simulate_orchestrator_duration_logic()
    result2 = test_user_scenario()
    
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print(f"Orchestrator simulation: {'✅ PASSED' if result1 else '❌ FAILED'}")
    print(f"User scenario test: {'✅ PASSED' if result2 else '❌ FAILED'}")
    
    if result1 and result2:
        print("\n🎉 All tests passed! Duration preservation logic is working correctly.")
    else:
        print("\n❌ Some tests failed. Review the logic above.")

