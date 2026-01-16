#!/usr/bin/env python3
"""
Quick test to verify RIFE interpolation frame count calculations.
"""

def calculate_expected_frames(input_frames, factor):
    """
    Calculate expected output frames for RIFE interpolation.
    
    Args:
        input_frames: Number of input frames
        factor: Interpolation factor (2 = double, 3 = triple, etc.)
    
    Returns:
        Expected output frame count
    """
    pairs = input_frames - 1
    mids_per_pair = max(1, int(round(factor)) - 1)
    expected = input_frames + (pairs * mids_per_pair)
    return expected, pairs, mids_per_pair


def test_scenarios():
    """Test common scenarios."""
    print("═══════════════════════════════════════════════════════")
    print("RIFE Frame Count Calculator")
    print("═══════════════════════════════════════════════════════\n")
    
    scenarios = [
        # (input_frames, factor, description)
        (192, 2.0, "7.1s video @ 27fps, 2x interpolation"),
        (192, 3.0, "7.1s video @ 27fps, 3x interpolation"),
        (240, 2.0, "10s video @ 24fps, 2x interpolation"),
        (145, 2.0, "6s video @ 24fps, 2x interpolation (from logs)"),
        (488, 2.0, "8.13s video @ 60fps, 2x interpolation"),
    ]
    
    for input_frames, factor, description in scenarios:
        expected, pairs, mids_per_pair = calculate_expected_frames(input_frames, factor)
        
        # Calculate durations assuming original FPS
        if "27fps" in description:
            original_fps = 27
        elif "24fps" in description:
            original_fps = 24
        elif "60fps" in description:
            original_fps = 60
        else:
            original_fps = 24
        
        original_duration = input_frames / original_fps
        target_fps = original_fps * factor
        output_duration = expected / target_fps
        
        print(f"📊 {description}")
        print(f"   Input: {input_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
        print(f"   Factor: {factor}x")
        print(f"   Pairs: {pairs}")
        print(f"   Mids per pair: {mids_per_pair}")
        print(f"   Expected output: {expected} frames")
        print(f"   Target FPS: {original_fps} × {factor} = {target_fps:.0f} fps")
        print(f"   Output duration: {expected} ÷ {target_fps:.0f} = {output_duration:.2f}s")
        
        # Check if duration is preserved
        duration_diff = abs(output_duration - original_duration)
        if duration_diff < 0.1:
            print(f"   ✓ Duration preserved (diff: {duration_diff:.3f}s)")
        else:
            print(f"   ⚠️ Duration changed by {duration_diff:.2f}s!")
        
        print()


def calculate_for_input():
    """Interactive calculator."""
    print("\n" + "─" * 55)
    print("Interactive Calculator")
    print("─" * 55)
    
    try:
        input_frames = int(input("Enter number of input frames: "))
        factor = float(input("Enter interpolation factor (e.g., 2.0): "))
        original_fps = float(input("Enter original FPS: "))
        
        expected, pairs, mids_per_pair = calculate_expected_frames(input_frames, factor)
        
        original_duration = input_frames / original_fps
        target_fps = original_fps * factor
        output_duration = expected / target_fps
        
        print(f"\n📊 Results:")
        print(f"   Input: {input_frames} frames @ {original_fps:.2f} fps = {original_duration:.2f}s")
        print(f"   Pairs to process: {pairs}")
        print(f"   Intermediate frames per pair: {mids_per_pair}")
        print(f"   Expected output: {expected} frames")
        print(f"   Target FPS: {target_fps:.2f} fps")
        print(f"   Output duration: {output_duration:.2f}s")
        print(f"   Duration change: {output_duration - original_duration:+.2f}s")
        
    except KeyboardInterrupt:
        print("\n\nCancelled.")
    except Exception as e:
        print(f"\nError: {e}")


if __name__ == '__main__':
    import sys
    
    # Run test scenarios
    test_scenarios()
    
    # Interactive mode if requested
    if len(sys.argv) > 1 and sys.argv[1] in ['-i', '--interactive']:
        calculate_for_input()

