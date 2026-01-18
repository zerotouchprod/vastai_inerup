# Text-to-Video Generation Module

Standalone text-to-video generation worker for Vast.ai GPU instances. Generates videos from text prompts using CogVideoX-5b model and uploads to Backblaze B2/S3 storage.

## Features

- **Text-to-Video Generation**: Uses THUDM/CogVideoX-5b model for high-quality video generation
- **Batch Processing**: Supports multiple prompts in a single job for efficient GPU utilization
- **Safety Checking**: Integrated NSFW content filtering using Stable Diffusion safety checker
- **Optimized for 24GB VRAM**: CPU offload, VAE slicing, tiling, and bfloat16 precision
- **B2/S3 Integration**: Uploads generated videos to Backblaze B2 or any S3-compatible storage
- **Isolated Runtime**: Separate Docker image without OpenCV/PaddleOCR dependencies
- **Vast.ai Ready**: Optimized for deployment on Vast.ai GPU instances

## Architecture

```
src/services/generation/
├── config.py              # Configuration with environment variables
├── models.py              # Pydantic models (GenJob, GenerationResult)
├── engine.py              # CogVideoEngine with safety checking
└── orchestrator.py        # GenerationOrchestrator with B2 integration

src/entrypoints/
└── run_gen.py            # CLI entry point for worker

docker/
└── Dockerfile.gen        # Isolated Docker image
```

## Quick Start

### 1. Build Docker Image

```bash
docker build -f Dockerfile.gen -t video-gen:latest .
```

### 2. Run Single Prompt

```bash
docker run --rm --gpus all \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["A cat dancing in the rain"]}'
```

### 3. Run Batch with Custom Parameters

```bash
docker run --rm --gpus all \
  -v /path/to/hf_cache:/root/.cache/huggingface \
  -e B2_KEY="your_key" \
  -e B2_SECRET="your_secret" \
  -e B2_BUCKET="your_bucket" \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{
    "prompts": [
      "A cyberpunk city at night",
      "A sunset over mountains",
      "Underwater coral reef"
    ],
    "guidance_scale": 7.0,
    "num_inference_steps": 40,
    "output_prefix": "generated/videos/"
  }'
```

## Job Specification

The `--job` parameter accepts a JSON string with the following structure:

```json
{
  "prompts": ["string", "..."],           // Required: List of text prompts
  "negative_prompt": "string",            // Optional: Negative prompt
  "seed": 42,                             // Optional: Random seed
  "guidance_scale": 6.0,                  // Optional: Guidance scale (1.0-20.0)
  "num_inference_steps": 50,              // Optional: Inference steps (10-200)
  "output_prefix": "generated/",          // Optional: Output path prefix
  "metadata": {"key": "value"}            // Optional: Additional metadata
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEN_MODEL_ID` | `THUDM/CogVideoX-5b` | HuggingFace model ID |
| `GEN_ENABLE_SAFETY_CHECKER` | `true` | Enable NSFW content filtering |
| `GEN_DEFAULT_GUIDANCE_SCALE` | `6.0` | Default guidance scale |
| `GEN_DEFAULT_NUM_INFERENCE_STEPS` | `50` | Default inference steps |
| `GEN_DEFAULT_NUM_FRAMES` | `49` | Frames per video (~6 seconds) |
| `GEN_DEFAULT_FPS` | `8` | Output video FPS |
| `HF_HOME` | `/root/.cache/huggingface` | HuggingFace cache directory |
| `TEMP_DIR` | `/tmp/generation` | Temporary files directory |
| `B2_KEY` | - | Backblaze B2 application key |
| `B2_SECRET` | - | Backblaze B2 secret key |
| `B2_BUCKET` | - | B2 bucket name |
| `B2_ENDPOINT` | `https://s3.us-west-004.backblazeb2.com` | B2 endpoint |

### Performance Optimizations

- **CPU Offload**: Moves unused model layers to CPU (`GEN_ENABLE_CPU_OFFLOAD=true`)
- **VAE Slicing**: Processes VAE in slices to reduce VRAM (`GEN_ENABLE_VAE_SLICING=true`)
- **Tiling**: Processes large images in tiles (`GEN_ENABLE_TILING=true`)
- **bfloat16**: Uses bfloat16 precision for Ampere GPUs (`GEN_USE_BFLOAT16=true`)
- **XFormers**: Memory efficient attention (`GEN_USE_XFORMERS=true`)

## Vast.ai Deployment

### Recommended Instance Configuration

- **GPU**: RTX 3090, RTX 4090, or similar with 24GB+ VRAM
- **Disk Space**: 50GB+ (for models and temporary files)
- **Docker Command**:

```bash
docker run --rm --gpus all \
  -v /root/.cache/huggingface:/root/.cache/huggingface \
  -e B2_KEY=${B2_KEY} \
  -e B2_SECRET=${B2_SECRET} \
  -e B2_BUCKET=${B2_BUCKET} \
  video-gen:latest \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ${PROMPTS}}'
```

### Volume Mounts for Performance

1. **Model Cache**: Mount `/root/.cache/huggingface` to avoid re-downloading models
2. **Output Directory**: Mount local directory for debugging outputs

## Development

### Testing

```bash
# Run import tests
python tests/test_generation_imports.py

# Test without GPU (mocks)
pytest tests/ -xvs -k generation
```

### Adding New Models

1. Extend `CogVideoEngine` class in `engine.py`
2. Add model configuration to `GenerationConfig`
3. Update `requirements.gen.txt` with new dependencies

### Extending for Image-to-Video

1. Create `ImageToVideoEngine` class
2. Add to `GenerationOrchestrator` with conditional loading
3. Extend `GenJob` model with `mode` field

## Troubleshooting

### Common Issues

1. **Out of Memory (OOM)**
   - Enable CPU offload: `GEN_ENABLE_CPU_OFFLOAD=true`
   - Reduce batch size: Use fewer prompts per job
   - Enable VAE slicing: `GEN_ENABLE_VAE_SLICING=true`

2. **Slow Generation**
   - Use bfloat16: `GEN_USE_BFLOAT16=true`
   - Enable xformers: `GEN_USE_XFORMERS=true`
   - Reduce inference steps: `num_inference_steps=30`

3. **B2 Upload Failed**
   - Check credentials: `B2_KEY`, `B2_SECRET`, `B2_BUCKET`
   - Verify network connectivity
   - Check bucket permissions

4. **Model Download Issues**
   - Mount cache volume: `-v /path/to/cache:/root/.cache/huggingface`
   - Set HF token: `-e HF_TOKEN=your_token`

### Logging

Enable verbose logging for debugging:

```bash
python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}' \
  --verbose
```

## Output Format

### Successful Response

```json
{
  "job_id": "uuid",
  "success": true,
  "total_prompts": 3,
  "successful": 3,
  "failed": 0,
  "duration_seconds": 45.2,
  "results": [
    {
      "prompt_index": 0,
      "prompt": "A cat dancing...",
      "output_key": "generated/uuid_0_hash.mp4",
      "url": "https://presigned.url/video.mp4",
      "size_bytes": 5242880,
      "success": true,
      "error": null
    }
  ]
}
```

### Error Response

```json
{
  "success": false,
  "error": "Error message"
}
```

## License

Part of the vastai_inerup project. See main LICENSE file for details.

## Support

- GitHub Issues: [Project Repository](https://github.com/zerotouchprod/vastai_inerup)
- Documentation: See `ARCHITECTURE_DIAGRAMS.md` and `COMPLETE_ARCHITECTURE_DOCUMENTATION.md`
