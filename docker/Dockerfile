# Lightweight base image. For GPU use, replace with an NVIDIA CUDA base (see README).
FROM python:3.10-slim

# Install runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    git \
    wget \
    ca-certificates \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy project files
COPY . /workspace

# Install Python deps (minimal). If you need PyTorch, install the proper CUDA wheel inside the built image or use a CUDA base image.
RUN pip install --no-cache-dir -r requirements.txt || true

# Make entrypoint script executable
RUN chmod +x /workspace/run_on_vast.sh

ENTRYPOINT ["/workspace/run_on_vast.sh"]

