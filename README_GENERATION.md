# Video Generation Module (Text-to-Video & Image-to-Video)

Standalone video generation worker for Vast.ai GPU instances. Generates videos from text prompts or images using CogVideoX models and uploads to Backblaze B2/S3 storage.

> **🎉 STATUS: FULLY IMPLEMENTED** - Both T2V and I2V modes are production-ready!

## Features

- **Text-to-Video Generation**: Uses THUDM/CogVideoX-5b-I2V model for high-quality video generation from text
- **Image-to-Video Generation**: ✅ **NOW AVAILABLE!** Uses THUDM/CogVideoX-5b-I2V to animate static images
- **Unified Model**: Single model for both T2V and I2V workflows (optimized for anime/stylized content)
- **All-in-One Docker**: Model baked into image for instant startup (no download wait!)
- **Dual Mode Support**: Single unified API for both T2V and I2V workflows
- **Batch Processing**: Supports multiple prompts in a single job for efficient GPU utilization
- **Safety Checking**: Integrated NSFW content filtering using Stable Diffusion safety checker
- **Optimized for 24GB VRAM**: CPU offload, VAE slicing, tiling, and bfloat16 precision
- **B2/S3 Integration**: Uploads generated videos to Backblaze B2 or any S3-compatible storage
- **Isolated Runtime**: Separate Docker image without OpenCV/PaddleOCR dependencies
- **Vast.ai Ready**: Optimized for deployment on Vast.ai GPU instances

> **📋 Full Documentation**: See [IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md](./IMPLEMENTATION_PLAN_TEXT2VIDEO_I2V.md) for detailed architecture and [IMPLEMENTATION_COMPLETE.md](./IMPLEMENTATION_COMPLETE.md) for completion status

## Architecture

```
src/domain/
└── generation.py          # Generation protocols and domain models

src/services/generation/
├── config.py              # Configuration with environment variables
├── models.py              # Pydantic models (GenJob, GenerationResult)
├── engines/
│   ├── base.py           # BaseVideoEngine abstract class
│   ├── text2video.py     # CogVideoX Text-to-Video engine
│   └── image2video.py    # CogVideoX Image-to-Video engine (planned)
├── utils/
│   └── image_loader.py   # Image loading utilities (planned)
└── orchestrator.py        # GenerationOrchestrator with B2 integration

src/entrypoints/
└── run_gen.py            # CLI entry point for worker

docker/
└── Dockerfile.gen        # Isolated Docker image

tests/
├── unit/
│   └── services/generation/    # Unit tests
└── integration/
    └── generation/             # Integration tests
```

**Design Principles:**
- **Strategy Pattern**: Different engines for T2V/I2V modes
- **Dependency Injection**: B2Client and Config injected into Orchestrator
- **Fail-Safe**: Continue processing on single failure, report all results
- **Isolation**: No dependencies on OCR/OpenCV subsystems

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

### Text-to-Video Mode

```json
{
  "mode": "text2video",                   // Optional: Generation mode (default: text2video)
  "prompts": ["string", "..."],           // Required: List of text prompts
  "negative_prompt": "string",            // Optional: Negative prompt
  "seed": 42,                             // Optional: Random seed
  "guidance_scale": 6.0,                  // Optional: Guidance scale (1.0-20.0)
  "num_inference_steps": 50,              // Optional: Inference steps (10-200)
  "num_frames": 49,                       // Optional: Number of frames (1-96)
  "fps": 8,                               // Optional: Output FPS (1-30)
  "output_prefix": "generated/",          // Optional: Output path prefix
  "metadata": {"key": "value"}            // Optional: Additional metadata
}
```

### Image-to-Video Mode *(Coming Soon)*

```json
{
  "mode": "image2video",                  // Required: Set to image2video
  "prompts": ["string", "..."],           // Required: Animation descriptions
  "input_images": [                       // Required: Input images (URLs or base64)
    "https://example.com/image.jpg",
    "data:image/jpeg;base64,/9j/4AAQ..."
  ],
  "negative_prompt": "string",            // Optional: Negative prompt
  "seed": 42,                             // Optional: Random seed
  "guidance_scale": 6.0,                  // Optional: Guidance scale (1.0-20.0)
  "num_inference_steps": 50,              // Optional: Inference steps (10-200)
  "num_frames": 49,                       // Optional: Number of frames (1-96)
  "fps": 8,                               // Optional: Output FPS (1-30)
  "output_prefix": "generated/",          // Optional: Output path prefix
  "metadata": {"key": "value"}            // Optional: Additional metadata
}
```

**Notes:**
- For `image2video` mode, `input_images` array must have same length as `prompts`
- Input images can be URLs, local paths, or base64-encoded data URIs
- Each prompt describes how to animate the corresponding input image

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GEN_T2V_MODEL_ID` | `THUDM/CogVideoX-5b` | HuggingFace Text-to-Video model ID |
| `GEN_I2V_MODEL_ID` | `THUDM/CogVideoX-5b-I2V` | HuggingFace Image-to-Video model ID |
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

### Project Structure

See [IMPLEMENTATION_PLAN_GENERATION.md](./IMPLEMENTATION_PLAN_GENERATION.md) for detailed architecture and implementation roadmap.

### Testing

```bash
# Run import tests
python tests/test_generation_imports.py

# Test without GPU (mocks)
pytest tests/unit/services/generation/ -xvs

# Integration tests (requires GPU)
pytest tests/integration/generation/ -xvs -m gpu
```

### Adding New Models

1. Extend `BaseVideoEngine` class in `src/services/generation/engines/base.py`
2. Implement engine in `src/services/generation/engines/`
3. Add model configuration to `GenerationConfig`
4. Update `requirements.gen.txt` with new dependencies
5. Update `GenerationOrchestrator._get_engine()` to handle new mode

### Extending for Image-to-Video

> **Status**: Planned for Phase 2. See [IMPLEMENTATION_PLAN_GENERATION.md](./IMPLEMENTATION_PLAN_GENERATION.md#этап-2-image-to-video-приоритет-средний)

1. Implement `ImageLoader` utility in `src/services/generation/utils/`
2. Create `CogVideoImage2VideoEngine` class in `src/services/generation/engines/image2video.py`
3. Update `GenJob` model to support `mode` and `input_images` fields
4. Update `GenerationOrchestrator` to handle I2V workflow
5. Add comprehensive tests for I2V pipeline

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
