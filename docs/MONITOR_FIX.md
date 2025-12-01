# Monitor Fix: Ignore Old Success Markers

## Problem
The monitor script was detecting old `VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY` markers from previous job runs and exiting immediately, preventing proper monitoring of new/current jobs.

### Example Issue
When monitoring instance #28402704:
1. Instance has logs from a previous successful run at 18:42:06
2. Monitor starts at 19:42:05
3. Monitor immediately finds old success marker and exits
4. User cannot monitor the NEW job that is actually running

## Solution
Track the baseline count of success markers when monitoring starts, and only exit when the count INCREASES (indicating a NEW completion).

### Key Changes
1. **Added baseline tracking**:
   ```python
   self.initial_success_count = 0  # Count at monitor start
   self.seen_new_success = False   # Track new completion
   ```

2. **Establish baseline on first check**:
   ```python
   if check_count == 1:
       self.initial_success_count = logs.count(self.success_marker)
       if self.initial_success_count > 0:
           print(f"Found {self.initial_success_count} old markers")
   ```

3. **Only exit on NEW success**:
   ```python
   current_count = logs.count(self.success_marker)
   if current_count > self.initial_success_count:
       # NEW completion detected!
       break
   ```

## Behavior After Fix

### Before
- Monitors instance #28402704
- Finds old success marker from 18:42:06
- Exits immediately ❌

### After
- Monitors instance #28402704
- Detects 2 old success markers: "ℹ️  Found 2 old markers"
- Shows: "⏳ Waiting for NEW completion..."
- Continues monitoring
- Only exits when a NEW (3rd) success marker appears ✅

## Log Output Format

Each log line now includes TWO timestamps:

```
[19:42:05] [LOG] ✅ B2 upload successful and verified
[19:42:06] [LOG] VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY
[19:42:07] [LOG] Assembling from mids
```

Where:
- **First timestamp** `[19:42:05]` = When the monitor RECEIVED this log line (local time)
- **[LOG]** = Marker that this is a log line from the instance

This helps track:
- When each log line was received by the monitor
- Time gaps between operations  
- Progress over time
- Real-time lag between container and monitor

## Test Verification
```bash
python test_monitor_fix.py
```

Output confirms:
- ✓ Detects 2 baseline markers
- ✓ Doesn't exit when no new markers
- ✓ Exits only when new (3rd) marker appears

## Usage
```bash
# Normal monitoring (will ignore old completions)
python monitor.py 28402704

# With auto-destroy on NEW completion
python monitor.py 28402704 --auto-destroy

# Custom refresh interval
python monitor.py 28402704 --interval 10

# Show more log lines  
python monitor.py 28402704 --tail 500
```

## Example Output

```
======================================================================
📍 Monitoring Instance #28402704
======================================================================
GPU:         RTX 3060
Status:      success, running ghcr.io/zerotouchprod/pytorch-fat-07110957:latest
State:       running
Price:       $0.0653/hr
======================================================================

🔄 Streaming logs... (Ctrl+C to stop monitoring)

[19:42:05] 📊 Status: running / success, running
  ℹ️  Found 2 old success marker(s) from previous run(s)
  ⏳ Waiting for NEW completion...

  [19:42:05] [LOG] ✅ B2 upload successful and verified
  [19:42:06] [LOG] VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY
  [19:42:07] [LOG] Assembling from mids
  [19:42:08] [LOG] Processing frame 145/289
  ...
  [19:43:15] [LOG] ✅ Upload complete
  [19:43:15] [LOG] VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY

======================================================================
🎉 SUCCESS! NEW processing completed!
======================================================================
  Old completions: 2
  New completions: 1

📥 Result URL:
   https://noxfvr-videos.s3.us-west-004.backblazeb2.com/...

Instance: #28402704
GPU:      RTX 3060
Price:    $0.0653/hr
```

## Related Files
- `monitor.py` - Main monitor script (fixed)
- `test_monitor_fix.py` - Logic verification test

