# 🚢 Deployment Checklist - ProPainter GPU Stability Fix

## Pre-Deployment Verification

### 1. Environment Check ✅
```bash
# Verify Python version
python --version  # Should be 3.10+

# Verify PyTorch installation
python -c "import torch; print(torch.__version__)"  # Should be 2.11.0+

# Verify CUDA availability
python -c "import torch; print(torch.cuda.is_available())"  # Should be True

# Check GPU info
nvidia-smi
```

### 2. Code Verification ✅
```bash
# Pull latest code
git pull origin main

# Verify key files exist
ls -la src/infrastructure/gpu/stability.py
ls -la COMPLETE_CONTEXT_FOR_AGENT.md
ls -la FINAL_SOLUTION_SUMMARY.md

# Check patch injection code
grep "safe_matmul" src/application/factories.py
```

### 3. Dependencies Check ✅
```bash
# Verify all packages installed
pip list | grep torch
pip list | grep opencv
pip list | grep numpy

# Check ProPainter installation
ls -la /opt/ProPainter/inference_propainter.py
```

---

## Deployment Steps

### Step 1: Backup Current State
```bash
# Backup ProPainter files (in case rollback needed)
cp /opt/ProPainter/RAFT/corr.py /opt/ProPainter/RAFT/corr.py.backup.$(date +%Y%m%d)
cp /opt/ProPainter/model/modules/sparse_transformer.py /opt/ProPainter/model/modules/sparse_transformer.py.backup.$(date +%Y%m%d)
```

### Step 2: Deploy Code
```bash
# Pull latest code
cd /apps/PycharmProjects/vastai_interup_ztp
git pull origin main

# Verify commit
git log --oneline -5
```

### Step 3: Test Run
```bash
# Test with small video (3 seconds)
python pipeline_v2.py \
  --input https://example.com/test_video_3sec.mp4 \
  --mode remove-subtitles \
  --roi 0.05,0.4,0.9,0.3

# Check for success
echo $?  # Should be 0
```

### Step 4: Verify Patches Applied
```bash
# Check safe_matmul injection
grep "def safe_matmul" /opt/ProPainter/model/modules/sparse_transformer.py
# Should output: def safe_matmul(tensor_a, tensor_b):

# Check CorrBlock replacement
head -20 /opt/ProPainter/RAFT/corr.py | grep "Pure PyTorch"
# Should output comment with "Pure PyTorch"

# Check global stability
head -30 /opt/ProPainter/inference_propainter.py | grep "TF32"
# Should output: torch.backends.cuda.matmul.allow_tf32 = False
```

### Step 5: Production Test
```bash
# Test with real video (full length)
python pipeline_v2.py \
  --input https://example.com/production_video.mp4 \
  --mode remove-subtitles \
  --roi 0.05,0.4,0.9,0.3

# Monitor logs
tail -f job.log | grep -i "error\|cpu fallback\|success"
```

---

## Post-Deployment Verification

### Success Criteria ✅

1. **No CUBLAS Errors**
   ```bash
   grep -i "CUBLAS" job.log
   # Should be empty or only in fallback messages
   ```

2. **CPU Fallback Working** (if needed)
   ```bash
   grep "CPU fallback" job.log | wc -l
   # Should be < 1% of total operations
   ```

3. **Video Processing Complete**
   ```bash
   ls -la output/
   # Should contain processed video
   ```

4. **Audio Preserved**
   ```bash
   ffprobe output/video.mp4 2>&1 | grep -i audio
   # Should show audio stream
   ```

5. **Performance Acceptable**
   ```bash
   # Processing time should be < 1.2x original
   # (10% overhead is acceptable)
   ```

---

## Monitoring

### Key Metrics to Track

```bash
# 1. Success rate
grep "Processing complete" job.log | wc -l
grep "ERROR" job.log | wc -l

# 2. CPU fallback frequency
grep "CPU fallback" job.log | wc -l

# 3. Average processing time
grep "Processing took" job.log | awk '{sum+=$NF; count++} END {print sum/count}'

# 4. GPU utilization
nvidia-smi dmon -s u -c 10
```

### Alert Conditions ⚠️

- ❌ CUBLAS errors present → Patches not applied
- ⚠️ CPU fallback >1% → GPU driver issues
- ⚠️ Processing time >1.5x → Performance degradation
- ❌ Success rate <95% → Investigation needed

---

## Rollback Procedure

### If Deployment Fails

```bash
# 1. Stop processing
killall python

# 2. Restore backups
cp /opt/ProPainter/RAFT/corr.py.backup.* /opt/ProPainter/RAFT/corr.py
cp /opt/ProPainter/model/modules/sparse_transformer.py.backup.* /opt/ProPainter/model/modules/sparse_transformer.py

# 3. Revert code
git reset --hard HEAD~1

# 4. Test original code
python pipeline_v2.py --input test.mp4 --mode remove-subtitles
```

---

## Troubleshooting

### Issue 1: Patches Not Applied
**Symptom**: Still getting CUBLAS errors

**Solution**:
```bash
# Manual patch injection
python scripts/inject_safe_matmul.py

# Verify
grep "def safe_matmul" /opt/ProPainter/model/modules/sparse_transformer.py
```

### Issue 2: Import Errors
**Symptom**: `ModuleNotFoundError: No module named 'src.infrastructure.gpu'`

**Solution**:
```bash
# Check PYTHONPATH
echo $PYTHONPATH

# Add to path if needed
export PYTHONPATH=/apps/PycharmProjects/vastai_interup_ztp:$PYTHONPATH
```

### Issue 3: GPU Not Detected
**Symptom**: ProPainter using CPU (slow)

**Solution**:
```bash
# Check CUDA
python -c "import torch; print(torch.cuda.is_available())"

# Check GPU visibility
nvidia-smi
echo $CUDA_VISIBLE_DEVICES

# Reset if needed
unset CUDA_VISIBLE_DEVICES
```

---

## Documentation

### For Developers
- `COMPLETE_CONTEXT_FOR_AGENT.md` - Full technical context
- `SAFE_MATMUL_ARCHITECTURE.md` - Architecture decisions
- `src/infrastructure/gpu/stability.py` - Implementation

### For Users
- `QUICK_REFERENCE.md` - Quick start guide
- `FINAL_SOLUTION_SUMMARY.md` - Executive summary
- `README.md` - Project overview

---

## Sign-Off

### Deployment Approved By
- [ ] Senior Developer
- [ ] QA Lead
- [ ] DevOps Engineer

### Checklist Complete ✅
- [ ] Pre-deployment verification passed
- [ ] Code deployed successfully
- [ ] Patches applied and verified
- [ ] Test run completed
- [ ] Production test passed
- [ ] Post-deployment verification passed
- [ ] Monitoring configured
- [ ] Documentation updated

### Deployment Date: ___________
### Deployed By: ___________
### Production URL: ___________

---

**Status**: Ready for Production 🚀  
**Risk Level**: Low (CPU fallback ensures 100% uptime)  
**Rollback Time**: < 5 minutes

