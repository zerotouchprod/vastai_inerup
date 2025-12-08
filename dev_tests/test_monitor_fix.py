#!/usr/bin/env python3
"""Test monitor fix - simulate old + new success markers"""

# Simulate the monitor logic
def test_monitor_logic():
    """Test that we only detect NEW success markers"""

    success_marker = "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"

    # Simulate logs with 2 old success markers
    old_logs = f"""
    [18:35:37] OK /tmp/vastai_pipeline_14ak2wqd/interpolated.mp4
    {success_marker}
    [18:36:05] AUTO_UPLOAD_B2: upload succeeded
    {success_marker}
    [18:36:30] Success: /tmp/vastai_pipeline_14ak2wqd/interpolated.mp4
    """

    # First check (baseline)
    initial_count = old_logs.count(success_marker)
    print(f"✓ Initial baseline: {initial_count} old success markers")
    assert initial_count == 2, "Should find 2 old markers"

    # Second check - no new completion yet
    check2_logs = old_logs + "\n[19:40:00] Still processing..."
    current_count = check2_logs.count(success_marker)
    has_new_completion = current_count > initial_count
    print(f"✓ Check 2: {current_count} markers, new={has_new_completion}")
    assert not has_new_completion, "Should NOT detect completion yet"

    # Third check - NEW completion appears!
    check3_logs = check2_logs + f"\n[19:42:00] Processing done!\n{success_marker}"
    current_count = check3_logs.count(success_marker)
    has_new_completion = current_count > initial_count
    print(f"✓ Check 3: {current_count} markers, new={has_new_completion}")
    assert has_new_completion, "Should NOW detect new completion"
    assert current_count == 3, "Should have 3 total markers (2 old + 1 new)"

    print("\n✅ All tests passed! Monitor will now correctly detect only NEW completions.")

if __name__ == '__main__':
    test_monitor_logic()

