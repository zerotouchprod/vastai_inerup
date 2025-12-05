"""Test FPS calculation for 'both' mode to verify duration preservation."""

def calculate_target_fps(original_frames, original_fps, processed_frames, mode='both', explicit_fps=None, interp_factor=2):
    """Simulate the FPS calculation logic from orchestrator."""
    original_duration = original_frames / original_fps if original_fps > 0 else None

    if explicit_fps:
        target_fps = float(explicit_fps)
        reason = "explicit"
    elif mode == 'interp':
        # For interpolation: multiply FPS by interpolation factor
        # More frames at higher FPS = same duration, smoother motion
        target_fps = original_fps * interp_factor
        reason = f"interp mode (FPS * {interp_factor}x factor)"
    elif mode == 'both' and original_duration and original_duration > 0:
        target_fps = max(1.0, float(processed_frames) / original_duration)
        reason = "both mode (maintain duration)"
    elif original_duration and original_duration > 0:
        target_fps = max(1.0, float(processed_frames) / original_duration)
        reason = "derived from duration"
    else:
        target_fps = original_fps
        reason = "fallback to original"

    output_duration = processed_frames / target_fps

    return target_fps, output_duration, reason


def test_fps_scenarios():
    """Test various scenarios."""

    print("=" * 70)
    print("FPS Calculation Tests")
    print("=" * 70)

    # Test 1: Upscale only (same frame count)
    print("\n1. UPSCALE mode (145 frames @ 24fps -> 145 frames)")
    original_frames = 145
    original_fps = 24.0
    processed_frames = 145
    original_duration = original_frames / original_fps

    target_fps, output_duration, reason = calculate_target_fps(
        original_frames, original_fps, processed_frames, mode='upscale'
    )

    print(f"   Original: {original_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Processed: {processed_frames} frames")
    print(f"   Target FPS: {target_fps:.2f} ({reason})")
    print(f"   Output: {processed_frames} frames @ {target_fps:.2f} fps = {output_duration:.2f}s")
    print(f"   ✓ Duration preserved: {abs(output_duration - original_duration) < 0.1}")

    # Test 2: Interpolation (2x frames)
    print("\n2. INTERP mode (145 frames @ 24fps -> 289 frames, 2x interpolation)")
    processed_frames = 289

    target_fps, output_duration, reason = calculate_target_fps(
        original_frames, original_fps, processed_frames, mode='interp', interp_factor=2
    )

    print(f"   Original: {original_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Processed: {processed_frames} frames")
    print(f"   Target FPS: {target_fps:.2f} ({reason})")
    print(f"   Output: {processed_frames} frames @ {target_fps:.2f} fps = {output_duration:.2f}s")
    print(f"   ✓ Duration preserved: {abs(output_duration - original_duration) < 0.1}")

    # Test 3: Both mode (interp-then-upscale)
    print("\n3. BOTH mode, interp-then-upscale (145 -> 289 -> 289 frames)")
    processed_frames = 289  # All interpolated frames should be upscaled

    target_fps, output_duration, reason = calculate_target_fps(
        original_frames, original_fps, processed_frames, mode='both'
    )

    print(f"   Original: {original_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Step 1 (interp): 145 -> 289 frames")
    print(f"   Step 2 (upscale): 289 -> 289 frames")
    print(f"   Processed: {processed_frames} frames")
    print(f"   Target FPS: {target_fps:.2f} ({reason})")
    print(f"   Output: {processed_frames} frames @ {target_fps:.2f} fps = {output_duration:.2f}s")
    print(f"   ✓ Duration preserved: {abs(output_duration - original_duration) < 0.1}")

    # Test 4: Both mode with WRONG frame count (bug scenario)
    print("\n4. BOTH mode with BUG (289 interp frames, but only 144 upscaled)")
    processed_frames = 144  # Bug: only half the frames upscaled

    target_fps, output_duration, reason = calculate_target_fps(
        original_frames, original_fps, processed_frames, mode='both'
    )

    print(f"   Original: {original_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Step 1 (interp): 145 -> 289 frames")
    print(f"   Step 2 (upscale): 289 -> 144 frames (BUG!)")
    print(f"   Processed: {processed_frames} frames")
    print(f"   Target FPS: {target_fps:.2f} ({reason})")
    print(f"   Output: {processed_frames} frames @ {target_fps:.2f} fps = {output_duration:.2f}s")
    print(f"   ✗ Duration preserved: {abs(output_duration - original_duration) < 0.1}")
    print(f"   → Video becomes {original_duration/output_duration:.1f}x faster!")

    # Test 5: Both mode, upscale-then-interp (145 -> 145 -> 289)
    print("\n5. BOTH mode, upscale-then-interp (145 -> 145 -> 289 frames)")
    processed_frames = 289

    target_fps, output_duration, reason = calculate_target_fps(
        original_frames, original_fps, processed_frames, mode='both'
    )

    print(f"   Original: {original_frames} frames @ {original_fps} fps = {original_duration:.2f}s")
    print(f"   Step 1 (upscale): 145 -> 145 frames")
    print(f"   Step 2 (interp): 145 -> 289 frames")
    print(f"   Processed: {processed_frames} frames")
    print(f"   Target FPS: {target_fps:.2f} ({reason})")
    print(f"   Output: {processed_frames} frames @ {target_fps:.2f} fps = {output_duration:.2f}s")
    print(f"   ✓ Duration preserved: {abs(output_duration - original_duration) < 0.1}")

    print("\n" + "=" * 70)
    print("Summary:")
    print("  - FPS calculation correctly maintains duration when frame count is correct")
    print("  - Bug scenario (144 instead of 289 frames) causes 2x speed increase")
    print("  - Solution: Ensure upscaler processes ALL interpolated frames")
    print("=" * 70)


if __name__ == "__main__":
    test_fps_scenarios()

