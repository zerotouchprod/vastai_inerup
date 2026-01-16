#!/usr/bin/env python3
"""
Test script to verify interpolation duration calculations.
"""

def test_duration_calculation():
    """Test the duration calculation logic."""
    
    # Simulate the scenario from the logs
    original_frame_count = 192
    original_fps = 27.0
    interp_factor = 3
    
    # Calculate original duration
    original_duration = original_frame_count / original_fps
    print(f"Original: {original_frame_count} frames @ {original_fps} fps = {original_duration:.2f}s")
    
    # Calculate expected output frames
    # Formula: original_frames + (original_frames - 1) * (factor - 1)
    # This is because we add (factor-1) intermediate frames between each pair
    expected_output_frames = original_frame_count + (original_frame_count - 1) * (interp_factor - 1)
    print(f"Expected output: {expected_output_frames} frames")
    
    # Calculate target FPS (multiply by factor to maintain duration)
    target_fps = original_fps * interp_factor
    print(f"Target FPS: {original_fps} × {interp_factor} = {target_fps} fps")
    
    # Calculate expected output duration
    expected_duration = expected_output_frames / target_fps
    print(f"Expected duration: {expected_output_frames} ÷ {target_fps} = {expected_duration:.2f}s")
    
    # Verify duration is preserved
    duration_diff = abs(expected_duration - original_duration)
    print(f"\nDuration difference: {duration_diff:.2f}s")
    
    if duration_diff < 0.1:
        print("✅ Duration preserved!")
    else:
        print(f"❌ Duration changed by {duration_diff:.2f}s")
    
    # Additional test case from the user's logs
    print("\n" + "="*60)
    print("Test case 2: User's problematic video")
    print("="*60)
    
    # From the logs: 192 frames, should be ~7.1s
    original_frame_count_2 = 192
    audio_duration = 7.10
    original_fps_2 = original_frame_count_2 / audio_duration  # Calculate actual FPS
    
    print(f"Original: {original_frame_count_2} frames @ {original_fps_2:.2f} fps = {audio_duration:.2f}s (from audio)")
    
    expected_output_frames_2 = original_frame_count_2 + (original_frame_count_2 - 1) * (interp_factor - 1)
    target_fps_2 = original_fps_2 * interp_factor
    expected_duration_2 = expected_output_frames_2 / target_fps_2
    
    print(f"Expected output: {expected_output_frames_2} frames @ {target_fps_2:.2f} fps = {expected_duration_2:.2f}s")
    
    duration_diff_2 = abs(expected_duration_2 - audio_duration)
    print(f"Duration difference: {duration_diff_2:.3f}s")
    
    if duration_diff_2 < 0.1:
        print("✅ Duration preserved!")
    else:
        print(f"❌ Duration changed by {duration_diff_2:.2f}s")


if __name__ == "__main__":
    test_duration_calculation()

