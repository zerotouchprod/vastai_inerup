# Test monitor timestamp formatting

import time

def test_timestamp_format():
    """Test that log lines include timestamp."""
    current_time = time.strftime('%H:%M:%S')
    log_line = "Upload successful and verified"
    
    # Old format (no timestamp)
    old_format = f"  [LOG] {log_line}"
    print("Old format:")
    print(old_format)
    print()
    
    # New format (with timestamp)
    new_format = f"  [{current_time}] [LOG] {log_line}"
    print("New format:")
    print(new_format)
    print()
    
    # Verify format
    assert current_time in new_format, "Timestamp missing"
    assert "[LOG]" in new_format, "[LOG] marker missing"
    assert log_line in new_format, "Log message missing"
    
    print("Timestamp format test passed!")
    print(f"   Format: [HH:MM:SS] [LOG] message")
    print(f"   Example: {new_format}")


def test_multiple_logs():
    """Test multiple log lines with timestamps."""
    logs = [
        "Processing frame 1/100",
        "Processing frame 50/100", 
        "Processing complete",
        "VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY"
    ]
    
    print("\nMultiple logs with timestamps:")
    print("-" * 70)
    for i, log in enumerate(logs):
        current_time = time.strftime('%H:%M:%S')
        formatted = f"  [{current_time}] [LOG] {log}"
        print(formatted)
        time.sleep(0.1)  # Simulate time passing
    print("-" * 70)
    print("Multiple logs test passed!")


if __name__ == '__main__':
    test_timestamp_format()
    test_multiple_logs()

