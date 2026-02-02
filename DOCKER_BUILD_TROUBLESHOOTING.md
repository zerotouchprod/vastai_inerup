# Docker Build Troubleshooting

## Common Issues & Solutions

### 1. `huggingface-cli: not found`

**Problem:** The `huggingface-cli` command is not in PATH during build.

**Solution:** ✅ **FIXED** in latest Dockerfile
- Changed from: `huggingface-cli download ...`
- Changed to: `/opt/venv/bin/huggingface-cli download ...`

**If you still see this error:**
```bash
# Make sure you're using the latest Dockerfile
git pull origin main  # or your branch
docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

---

### 2. Model Download Fails

**Symptoms:**
```
Error downloading model from HuggingFace
Connection timeout
Rate limit exceeded
```

**Solutions:**

#### Option A: Retry (HuggingFace rate limiting)
```bash
# Just try again after a few minutes
docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

#### Option B: Use HuggingFace Token
```bash
# Get token from https://huggingface.co/settings/tokens
docker build \
  -f docker/Dockerfile.gen \
  --build-arg HF_TOKEN="hf_your_token_here" \
  -t video-gen:latest .
```

Update Dockerfile to use token:
```dockerfile
ARG HF_TOKEN=""
RUN mkdir -p /model_cache && \
    echo "Downloading model: ${MODEL_ID}..." && \
    huggingface-cli login --token ${HF_TOKEN} && \
    /opt/venv/bin/huggingface-cli download ${MODEL_ID} \
    --exclude "*.bin" "*.onnx" "*.pb" "fp32/*" \
    --cache-dir /model_cache
```

#### Option C: Pre-download Model Locally
```bash
# Download model on host first
pip install huggingface_hub[cli]
huggingface-cli download THUDM/CogVideoX-5b-I2V \
  --exclude "*.bin" "*.onnx" "*.pb" "fp32/*" \
  --cache-dir ./model_cache

# Then mount it in Dockerfile (modify COPY step)
COPY ./model_cache /model_cache
```

---

### 3. Out of Disk Space

**Symptoms:**
```
no space left on device
failed to copy files
```

**Solutions:**

#### Check disk space:
```bash
df -h
docker system df
```

#### Clean up Docker:
```bash
# Remove unused images
docker image prune -a

# Full cleanup (WARNING: removes everything not running)
docker system prune -a --volumes

# Free up ~20GB minimum required
```

---

### 4. CUDA/GPU Issues

**Symptoms:**
```
CUDA not available
torch.cuda.is_available() returns False
```

**Solutions:**

#### Check NVIDIA drivers:
```bash
nvidia-smi
```

#### Check Docker GPU support:
```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

#### Install NVIDIA Container Toolkit:
```bash
# Ubuntu/Debian
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

---

### 5. Build Takes Too Long

**Normal:** 15-20 minutes (first build)

**If longer:**
- Model download is ~11GB (depends on internet speed)
- Use `--progress=plain` to see detailed progress
- Check network speed: `wget -O /dev/null https://huggingface.co/datasets/hf-internal-testing/test-audio-video/resolve/main/example.mp4`

---

### 6. Layer Caching Issues

**Problem:** Changes not reflected in build

**Solution:**
```bash
# Force rebuild without cache
docker build --no-cache -f docker/Dockerfile.gen -t video-gen:latest .

# Or rebuild from specific stage
docker build --no-cache-from=builder -f docker/Dockerfile.gen -t video-gen:latest .
```

---

### 7. Permission Denied

**Symptoms:**
```
permission denied while trying to connect to Docker daemon
```

**Solutions:**
```bash
# Add user to docker group
sudo usermod -aG docker $USER
newgrp docker

# Or use sudo
sudo docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

---

### 8. Missing Files in Context

**Symptoms:**
```
COPY failed: file not found
```

**Check:**
```bash
# Make sure you're in project root
pwd
# Should show: /home/fevr/PycharmProjects/vastai_inerup

# Check files exist
ls -la requirements.gen.txt
ls -la docker/Dockerfile.gen
ls -la src/

# Check .dockerignore isn't excluding needed files
cat .dockerignore
```

---

## Build Verification

### After successful build:

```bash
# 1. Check image exists
docker images video-gen:latest

# 2. Verify PyTorch
docker run --rm video-gen:latest \
  python -c "import torch; print(torch.__version__)"

# 3. Verify CUDA (requires GPU)
docker run --rm --gpus all video-gen:latest \
  python -c "import torch; print(torch.cuda.is_available())"

# 4. Verify model cached
docker run --rm video-gen:latest \
  ls -lh /root/.cache/huggingface/

# 5. Verify CLI works
docker run --rm video-gen:latest \
  python -m src.entrypoints.run_gen --help

# 6. Dry-run test
docker run --rm --gpus all video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}' --dry-run
```

---

## Performance Tips

### Faster builds:

1. **Use BuildKit:**
```bash
export DOCKER_BUILDKIT=1
docker build -f docker/Dockerfile.gen -t video-gen:latest .
```

2. **Parallel downloads:**
```bash
# Edit Dockerfile to use multiple workers (not recommended, may hit rate limits)
RUN /opt/venv/bin/huggingface-cli download ${MODEL_ID} \
    --exclude "*.bin" "*.onnx" "*.pb" "fp32/*" \
    --cache-dir /model_cache \
    --max-workers 4
```

3. **Use cache mounts:**
```dockerfile
# In Dockerfile (requires BuildKit)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.gen.txt
```

---

## Need Help?

1. **Check logs:**
```bash
docker build -f docker/Dockerfile.gen -t video-gen:latest . 2>&1 | tee build.log
```

2. **Interactive debugging:**
```bash
# Build up to failing step
docker build -f docker/Dockerfile.gen -t video-gen:debug --target builder .

# Enter container
docker run -it --rm video-gen:debug /bin/bash

# Test commands manually
/opt/venv/bin/huggingface-cli --version
```

3. **Check documentation:**
- `QUICKSTART_VIDEO_GEN.md`
- `README_GENERATION.md`
- `IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md`

---

## Emergency: Skip Model Baking

If all else fails, you can build without baked model and download at runtime:

```dockerfile
# Comment out the RUN huggingface-cli download step
# Set offline mode to false in Stage 2
ENV HF_HUB_OFFLINE="0"
```

Then model will download on first run (5-10 minutes delay).

---

**Most issues are resolved by:**
1. ✅ Using full path `/opt/venv/bin/huggingface-cli`
2. ✅ Ensuring sufficient disk space (20GB+)
3. ✅ Stable internet connection
4. ✅ Retry if HuggingFace rate limits
