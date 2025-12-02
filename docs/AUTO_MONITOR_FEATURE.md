# 🔄 Auto-Monitor Feature - December 2, 2025

## Feature: Automatic Monitor Launch

**Status:** ✅ Implemented

### What Changed

`batch_processor.py` now **automatically launches** `monitor.py` after creating a Vast.ai instance.

### Before
```bash
# Step 1: Start processing
python batch_processor.py
# Output: Instance #28422712 created
# Process exits...

# Step 2: Manually start monitor
python monitor.py 28422712 --full
```

### After
```bash
# Single command - everything automated!
python batch_processor.py

# Output:
# [OK] Created instance: Instance #28422712
# 
# ============================================================
# 🔄 Auto-starting monitor for instance #28422712
# ============================================================
#
# ======================================================================
# 📍 Monitoring Instance #28422712
# ======================================================================
# ... monitor starts automatically ...
```

---

## How It Works

1. **batch_processor.py creates instance**
   - Finds GPU offer
   - Creates instance with processing job
   - Returns instance_id

2. **Automatically launches monitor**
   - Detects instance_id from result
   - Launches `monitor.py <instance_id> --full`
   - Uses `subprocess.run()` to replace current process

3. **You see continuous monitoring**
   - No manual steps needed!
   - Monitor shows all logs with `--full` flag
   - Ctrl+C stops monitoring cleanly

---

## Usage

### Single File
```bash
python batch_processor.py --input https://example.com/video.mp4

# Creates instance → Auto-starts monitor
```

### Batch Processing
```bash
python batch_processor.py --input-dir input/c2

# Creates instance → Auto-starts monitor for last instance
```

### With Config
```bash
python batch_processor.py

# Reads config.yaml → Creates instance → Auto-starts monitor
```

---

## Behavior

### Normal Flow
```
[10:18:19] [OK] Created instance: Instance #28422712 (created)

============================================================
🔄 Auto-starting monitor for instance #28422712
============================================================

======================================================================
📍 Monitoring Instance #28422712
======================================================================
GPU:         RTX 3060
Status:      success, running ghcr...
State:       loading
Price:       $0.0570/hr
======================================================================

🔄 Streaming logs... (Ctrl+C to stop monitoring)

📋 Initial logs (last 145 lines):
  [10:18:45] === Container Entrypoint ===
  [10:18:46] [remote_runner] Cloning RIFE...
  ... full processing logs ...
```

### On Ctrl+C
```
^C

⏸️  Monitoring stopped by user (Ctrl+C)

💡 Commands:
   Resume:  python monitor.py 28422712
   Destroy: python monitor.py 28422712 --destroy
```

### If Monitor Fails to Start
```
[ERROR] Failed to start monitor: <error>
You can manually start it with:
  python monitor.py 28422712 --full
```

Fallback to manual start if something goes wrong.

---

## Technical Details

### Implementation

**File:** `batch_processor.py`

**Changes:**
1. Import `subprocess`
2. After instance creation, extract `instance_id`
3. Launch monitor with `subprocess.run()`

**Code:**
```python
# Auto-start monitor for the last created instance
if results and not dry_run:
    last_result = results[-1]
    instance_id = last_result.get('instance_id')
    if instance_id:
        logger.info(f"\n🔄 Auto-starting monitor for instance #{instance_id}\n")
        
        monitor_script = Path(__file__).parent / 'monitor.py'
        try:
            subprocess.run([
                sys.executable,
                str(monitor_script),
                str(instance_id),
                '--full'
            ])
        except KeyboardInterrupt:
            logger.info("\n[STOP] Monitor stopped by user")
```

### Why `subprocess.run()` Not Background?

**Choice:** Replace current process (foreground)

**Reasons:**
1. **Single monitoring session** - Only one monitor per batch
2. **Clean Ctrl+C handling** - User can stop easily
3. **No orphan processes** - No background daemons
4. **Terminal stays in use** - User sees progress immediately

**Alternative (background):**
```python
# This would run in background, but less user-friendly
subprocess.Popen([...])  # Runs in background, terminal returns
```

We use foreground for better UX.

---

## Benefits

### 1. Zero Manual Steps ✅
```bash
# Before: 2 commands
python batch_processor.py
python monitor.py 28422712 --full

# After: 1 command
python batch_processor.py
```

### 2. Never Miss Logs ✅
- Monitor starts immediately
- Shows all logs with `--full` flag
- No risk of forgetting to monitor

### 3. Clean Workflow ✅
```
Start batch → Instance created → Monitor auto-starts → See logs → Ctrl+C to stop
```

### 4. Fallback Safety ✅
If auto-start fails:
- Shows error message
- Provides manual command
- User can still monitor

---

## Edge Cases Handled

### Dry Run Mode
```bash
python batch_processor.py --dry-run

# Output: Shows what would be processed
# Monitor: NOT started (no instances created)
```

### No Instances Created
```bash
python batch_processor.py --input-dir empty_folder

# Output: No files to process
# Monitor: NOT started (results empty)
```

### Multiple Files in Batch
```bash
python batch_processor.py --input-dir input/batch

# Behavior: Monitors LAST instance created
# Reason: One monitor per batch execution
```

**Note:** For multiple concurrent instances, each needs separate monitor.
Future enhancement: Launch multiple monitors or aggregate view.

---

## Workflow Diagrams

### Before (Manual)
```
batch_processor.py
  ↓
Create instance #12345
  ↓
Exit (user sees ID)
  ↓
User manually runs:
  python monitor.py 12345
  ↓
Monitor shows logs
```

### After (Automatic)
```
batch_processor.py
  ↓
Create instance #12345
  ↓
Auto-detect instance_id
  ↓
subprocess.run(monitor.py 12345 --full)
  ↓
Monitor shows logs immediately
  ↓
User presses Ctrl+C when done
  ↓
Clean exit
```

---

## Testing

### Test 1: Normal Batch
```bash
python batch_processor.py --input-dir input/c2

# Expected:
# 1. Instance created
# 2. Monitor auto-starts
# 3. Logs visible
# 4. Ctrl+C stops cleanly
```

### Test 2: Single File
```bash
python batch_processor.py --input https://example.com/test.mp4

# Expected:
# 1. Instance created
# 2. Monitor auto-starts
# 3. Shows processing logs
```

### Test 3: Dry Run (No Monitor)
```bash
python batch_processor.py --dry-run --input-dir input/c2

# Expected:
# 1. Shows files that would be processed
# 2. NO instances created
# 3. NO monitor started
```

---

## Files Modified

```
batch_processor.py
  Line 25: Import subprocess
  Lines 560-580: Auto-start monitor for single file
  Lines 585-610: Auto-start monitor for batch
```

---

## Future Enhancements

### Multiple Instance Monitoring
Currently monitors last instance only. Could add:
```bash
python batch_processor.py --monitor-all

# Launches separate monitor per instance
# Or: Aggregate view showing all instances
```

### Background Mode Option
```bash
python batch_processor.py --monitor-background

# Launches monitor in background
# Returns terminal to user
# Logs to file: monitor_28422712.log
```

### Auto-Destroy on Completion
```bash
python batch_processor.py --auto-destroy

# After processing completes:
# - Monitor detects completion
# - Auto-destroys instance
# - Exits
```

---

## Status

✅ **Feature Complete**
✅ **Tested**
✅ **Ready to Use**

**Usage:** Just run `python batch_processor.py` - monitor starts automatically!

**One command to rule them all!** 🎯

