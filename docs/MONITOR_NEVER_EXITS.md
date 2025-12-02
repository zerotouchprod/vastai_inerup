# 🔄 Monitor Never Exits - Continuous Instance Monitoring

**Date:** December 2, 2025  
**Status:** ✅ Fixed

## Problem

Monitor was exiting in multiple scenarios:

1. **API Errors / Rate Limits** (429 Too Many Requests)
   ```
   Vast.ai API request failed: 429 Client Error
   ❌ Instance #28421359 no longer exists
   ======================================================================
   Monitoring finished
   ======================================================================
   ```

2. **Instance Stopped/Exited**
   ```
   ⚠️  Instance stopped (status: exited)
   Final logs:
   ...
   ======================================================================
   Monitoring finished
   ======================================================================
   ```

3. **Auto-Destroy Mode**
   ```
   ✅ Instance #28421359 destroyed
   
   ======================================================================
   Monitoring finished (instance destroyed)
   ======================================================================
   ```

**Expected Behavior:** Monitor should NEVER exit except on Ctrl+C, continuing to watch even if instance is stopped, destroyed, or API has errors.

---

## Solution

### 1. Never Exit on API Errors

**Before:**
```python
info = self.get_info()
if not info:
    print(f"\n❌ Instance #{self.instance_id} no longer exists")
    break  # ❌ EXIT
```

**After:**
```python
info = self.get_info()
if not info:
    # Exponential backoff for rate limits
    self.consecutive_errors += 1
    backoff_delay = min(interval * (2 ** (self.consecutive_errors - 1)), self.max_backoff)
    
    print(f"\n⚠️  Failed to get instance info (API error or rate limit)")
    print(f"    Retry attempt #{self.consecutive_errors}, waiting {backoff_delay:.0f}s...")
    print(f"    (Press Ctrl+C to stop monitoring)")
    
    time.sleep(backoff_delay)
    continue  # ✅ RETRY, NEVER EXIT
```

**Features:**
- Exponential backoff: 5s → 10s → 20s → 40s → 60s (max)
- Shows retry attempt number
- Auto-recovers when API comes back online
- Never gives up!

---

### 2. Never Exit When Instance Stops

**Before:**
```python
if info.actual_status in ['stopped', 'exited']:
    print(f"\n⚠️  Instance stopped (status: {info.actual_status})")
    # Show final logs
    ...
    break  # ❌ EXIT
```

**After:**
```python
if info.actual_status in ['stopped', 'exited']:
    # Only show message once when status changes
    if last_status and not any(x in last_status for x in ['stopped', 'exited']):
        print(f"\n⚠️  Instance stopped (status: {info.actual_status})")
        print(f"    Still monitoring... (logs won't update until instance restarts)")
        print(f"    Press Ctrl+C to stop monitoring\n")
# NO break - continue monitoring! ✅
```

**Features:**
- Shows status change only once (not spamming)
- Clearly indicates monitoring continues
- Ready to detect if instance restarts
- Progress indicator changes: 🔄 → 💤

---

### 3. Never Exit After Auto-Destroy

**Before:**
```python
if auto_destroy:
    if self.client.destroy_instance(self.instance_id):
        print(f"✅ Instance #{self.instance_id} destroyed")
        print(f"\nMonitoring finished (instance destroyed)")
        return  # ❌ EXIT
```

**After:**
```python
if auto_destroy:
    if self.client.destroy_instance(self.instance_id):
        print(f"✅ Instance #{self.instance_id} destroyed")
        print(f"    Monitor will keep running (Press Ctrl+C to stop)")
# NO return - keep monitoring! ✅
```

**Features:**
- Monitor continues even after destroy
- Can detect if instance is recreated with same ID
- User has full control (Ctrl+C to exit)

---

## New Features

### 1. Exponential Backoff for Rate Limits

```python
self.consecutive_errors = 0
self.max_backoff = 60

# On error:
backoff_delay = min(interval * (2 ** (self.consecutive_errors - 1)), self.max_backoff)
```

**Timeline Example:**
- Attempt 1: Wait 5s
- Attempt 2: Wait 10s  
- Attempt 3: Wait 20s
- Attempt 4: Wait 40s
- Attempt 5+: Wait 60s (max)

When connection is restored:
```
✅ Connection restored after 5 failed attempts
```

### 2. State-Aware Progress Indicator

```python
state_indicator = "🔄" if info.actual_status not in ['stopped', 'exited'] else "💤"
print(f"[{current_time}] {state_indicator} Check #{check_count}...")
```

**Running instance:**
```
[09:58:41] 🔄 Check #42...
```

**Stopped instance:**
```
[09:58:41] 💤 Check #42...
```

### 3. Clear Exit Message

Only appears on Ctrl+C:

```
⏸️  Monitoring stopped by user (Ctrl+C)

💡 Commands:
   Resume:  python monitor.py 28421359
   Destroy: python monitor.py 28421359 --destroy

======================================================================
Monitoring finished
======================================================================
```

---

## Usage Examples

### Basic - Never Stops Monitoring
```bash
python monitor.py 28421359

# Will run forever until Ctrl+C
# Handles:
# - Instance stopped ✅
# - Instance destroyed ✅
# - API rate limits ✅
# - Network errors ✅
```

### With Full Logs
```bash
python monitor.py 28421359 --full

# Shows ALL logs on start
# Then continues monitoring forever
```

### Auto-Destroy (Still Never Exits!)
```bash
python monitor.py 28421359 --auto-destroy

# Destroys instance on completion
# BUT monitor keeps running!
# Press Ctrl+C to stop
```

### Custom Interval
```bash
python monitor.py 28421359 --interval 10

# Checks every 10 seconds
# Backoff still applies on errors
```

---

## Testing Scenarios

### Scenario 1: API Rate Limit
```
⚠️  Failed to get instance info (API error or rate limit)
    Retry attempt #1, waiting 5s...
    (Press Ctrl+C to stop monitoring)

⚠️  Failed to get instance info (API error or rate limit)
    Retry attempt #2, waiting 10s...
    (Press Ctrl+C to stop monitoring)

✅ Connection restored after 2 failed attempts

[10:00:15] 📊 Status: running / success, running ghcr...
```

### Scenario 2: Instance Stops
```
[10:01:30] 📊 Status: running / success, running ghcr...

[10:01:35] 📊 Status: exited / success, running ghcr...

⚠️  Instance stopped (status: exited)
    Still monitoring... (logs won't update until instance restarts)
    Press Ctrl+C to stop monitoring

[10:01:40] 💤 Check #128...
[10:01:45] 💤 Check #130...
# Continues forever...
```

### Scenario 3: Pipeline Completes + Auto-Destroy
```
🎉 SUCCESS! NEW processing completed!
======================================================================
  Old completions: 0
  New completions: 1

📥 Result URL:
   https://s3.us-west-004.backblazeb2.com/...

Instance: #28421359
GPU:      RTX 3060
Price:    $0.0653/hr

⏹️  Stopping instance...
✅ Instance #28421359 stopped

🧹 Auto-destroying instance...
✅ Instance #28421359 destroyed
    Monitor will keep running (Press Ctrl+C to stop)

🔄 Continuing to monitor logs and status...
   Press Ctrl+C to stop monitoring

[10:02:00] 💤 Check #256...
[10:02:05] 💤 Check #258...
# Still running! Press Ctrl+C to exit
```

---

## Implementation Details

### Key Changes in `monitor.py`

1. **Removed all `break` statements** except after `KeyboardInterrupt`
2. **Removed all `return` statements** in monitoring loop
3. **Added exponential backoff** for resilient API error handling
4. **Added state tracking** for status change notifications
5. **Added visual indicators** (🔄/💤) for instance state

### State Machine

```
START
  ↓
MONITORING (infinite loop)
  ↓
  ├─ Get Instance Info
  │   ├─ Success → Update Status → Continue
  │   └─ Fail → Backoff → Retry ↺
  ↓
  ├─ Get Logs
  │   ├─ Success → Display → Continue
  │   └─ Fail → Log Error → Continue
  ↓
  ├─ Check Status
  │   ├─ Running → 🔄 indicator
  │   └─ Stopped → 💤 indicator → Continue
  ↓
  ├─ Sleep(interval)
  ↓
  └─ Loop ↺

ONLY EXIT: Ctrl+C → KeyboardInterrupt
```

---

## Migration Notes

**Before (old behavior):**
```bash
python monitor.py 28421359

# Would exit if:
# - API error
# - Instance stopped
# - Processing completed (in auto-destroy mode)
```

**After (new behavior):**
```bash
python monitor.py 28421359

# ONLY exits on: Ctrl+C
# Everything else: keeps running forever

# To stop monitoring:
# Press Ctrl+C
```

**No breaking changes** - all existing flags work the same way, just more resilient.

---

## Benefits

1. **🛡️ Resilient** - Handles API errors gracefully
2. **♾️ Continuous** - Never stops monitoring unless you want it to
3. **🔄 Auto-recovery** - Restores connection automatically
4. **📊 Informative** - Clear status indicators (🔄 running, 💤 stopped)
5. **🎯 Predictable** - Only one way to exit: Ctrl+C

---

## Files Modified

- `monitor.py` (lines 41-43, 109-122, 139-145, 256-265, 271-278)

## Commit Message

```
feat: monitor never exits except on Ctrl+C

- Add exponential backoff for API rate limits
- Never exit on instance stop/destroy
- Add state-aware progress indicators (🔄/💤)
- Improve error recovery and user feedback
- Monitor runs continuously until Ctrl+C

Fixes: Monitor exiting on API errors, stopped instances, and after destroy
```

---

**Status: ✅ Ready to Use**

The monitor is now truly "fire and forget" - start it once, and it'll keep watching until you explicitly stop it with Ctrl+C!

