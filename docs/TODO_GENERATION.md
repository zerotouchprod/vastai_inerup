# TODO: Video Generation Module Implementation

## Phase 1: Text-to-Video MVP ⏳ (В РАБОТЕ)

### 1.1 Domain Layer 📋
- [ ] `src/domain/generation.py`
  - [ ] `IVideoGenerator` protocol
  - [ ] `GenerationMode` enum
  - [ ] Domain exceptions (GenerationError, NSFWContentError)
- [ ] Tests: `tests/unit/domain/test_generation_protocols.py`

### 1.2 Configuration ⚙️
- [ ] `src/services/generation/config.py`
  - [ ] `GenerationConfig` with all env vars
  - [ ] Properties: torch_dtype, temp_dir_path, hf_cache_path
  - [ ] `get_optimization_kwargs()` method
- [ ] Tests: `tests/unit/services/generation/test_config.py`

### 1.3 Data Models 📊
- [ ] `src/services/generation/models.py`
  - [ ] `GenerationMode` enum
  - [ ] `GenJob` with validators
  - [ ] `GenerationResult`
  - [ ] `BatchGenerationResult`
  - [ ] JSON serialization methods
- [ ] Tests: `tests/unit/services/generation/test_models.py`

### 1.4 Engine Layer - Base & T2V 🎬
- [ ] `src/services/generation/engines/__init__.py`
- [ ] `src/services/generation/engines/base.py`
  - [ ] `BaseVideoEngine` abstract class
  - [ ] `_check_safety()` method
  - [ ] `_create_generator()` method
  - [ ] `cleanup()` method
- [ ] `src/services/generation/engines/text2video.py`
  - [ ] `CogVideoText2VideoEngine` class
  - [ ] `initialize()` - load CogVideoX-5b
  - [ ] `generate()` - T2V generation
  - [ ] `_export_video()` method
- [ ] Tests:
  - [ ] `tests/unit/services/generation/engines/test_base_engine.py`
  - [ ] `tests/unit/services/generation/engines/test_text2video_engine.py`

### 1.5 Orchestrator 🎭
- [ ] `src/services/generation/orchestrator.py`
  - [ ] `GenerationOrchestrator` class
  - [ ] `process_job()` method
  - [ ] `_get_engine()` - mode selection
  - [ ] `_process_single_prompt()` method
  - [ ] B2 upload integration
  - [ ] `_cleanup_temporary_files()` method
- [ ] Tests: `tests/unit/services/generation/test_orchestrator.py`

### 1.6 CLI Entrypoint 🖥️
- [ ] `src/entrypoints/run_gen.py`
  - [ ] Argument parsing
  - [ ] Job loading from JSON
  - [ ] Orchestrator initialization
  - [ ] JSON output
  - [ ] Error handling
- [ ] Tests: `tests/integration/entrypoints/test_run_gen.py`

### 1.7 Docker Image 🐳
- [ ] `requirements.gen.txt`
  - [ ] torch, diffusers, transformers
  - [ ] xformers, accelerate
  - [ ] boto3, pydantic
- [ ] `Dockerfile.gen`
  - [ ] Multi-stage build
  - [ ] Dependencies installation
  - [ ] Health check
  - [ ] Volume mounts
- [ ] Tests: `tests/docker/test_generation_image.sh`

### 1.8 Integration Tests 🧪
- [ ] `tests/integration/generation/test_text2video_workflow.py`
  - [ ] E2E test with mocks
  - [ ] Real generation test (GPU required)
  - [ ] Error scenarios
  - [ ] B2 upload verification

### 1.9 Documentation 📝
- [x] `IMPLEMENTATION_PLAN_GENERATION.md` ✅
- [x] `ARCHITECTURE_RECOMMENDATIONS_GENERATION.md` ✅
- [x] Update `README_GENERATION.md` ✅

---

## Phase 2: Image-to-Video Support 🖼️ (ПЛАНИРУЕТСЯ)

### 2.1 Image Utilities
- [ ] `src/services/generation/utils/__init__.py`
- [ ] `src/services/generation/utils/image_loader.py`
  - [ ] `ImageLoader` class
  - [ ] `load_from_url()`
  - [ ] `load_from_base64()`
  - [ ] `load_from_path()`
  - [ ] `load()` auto-detection
- [ ] Tests: `tests/unit/services/generation/utils/test_image_loader.py`

### 2.2 I2V Engine
- [ ] `src/services/generation/engines/image2video.py`
  - [ ] `CogVideoImage2VideoEngine` class
  - [ ] `initialize()` - load CogVideoX-I2V
  - [ ] `generate()` - I2V generation
  - [ ] `_preprocess_image()` method
- [ ] Tests: `tests/unit/services/generation/engines/test_image2video_engine.py`

### 2.3 Orchestrator Update
- [ ] Update `orchestrator.py`
  - [ ] I2V support in `_get_engine()`
  - [ ] I2V logic in `_process_single_prompt()`
- [ ] Tests: `tests/unit/services/generation/test_orchestrator_i2v.py`

### 2.4 Models Update
- [ ] Update `GenJob` model
  - [ ] `input_images` field
  - [ ] Validator for I2V mode
- [ ] Update tests

### 2.5 Integration Tests
- [ ] `tests/integration/generation/test_image2video_workflow.py`
  - [ ] E2E I2V test with mocks
  - [ ] Real I2V generation (GPU)
  - [ ] Image loading scenarios

### 2.6 Documentation
- [ ] Update `README_GENERATION.md`
  - [ ] I2V examples
  - [ ] Image formats documentation
- [ ] Add `examples/generation/image2video_example.py`

---

## Phase 3: Production Ready 🚀 (БУДУЩЕЕ)

### 3.1 Performance Optimizations
- [ ] Torch compile support
- [ ] Flash Attention 2
- [ ] Dynamic batch sizing
- [ ] Model pool for reuse
- [ ] Async B2 upload

### 3.2 Monitoring
- [ ] `src/services/generation/metrics.py`
  - [ ] Prometheus metrics
  - [ ] Duration tracking
  - [ ] VRAM monitoring
- [ ] Structured logging (JSON)

### 3.3 Error Recovery
- [ ] State persistence
- [ ] Retry logic with exponential backoff
- [ ] Graceful shutdown
- [ ] Resume after crash

### 3.4 Load Testing
- [ ] Benchmark scripts
- [ ] Stress tests
- [ ] VRAM profiling
- [ ] Cost analysis

---

## Checklist для запуска

### Before first deployment
- [ ] All Phase 1 tests pass
- [ ] Docker image builds successfully
- [ ] Manual GPU test completed
- [ ] B2 credentials configured
- [ ] Documentation reviewed

### Verification
```bash
# Unit tests
pytest tests/unit/services/generation/ -v

# Integration tests (no GPU)
pytest tests/integration/generation/ -v -m "not gpu"

# Docker build
docker build -f Dockerfile.gen -t video-gen:test .

# Dry run
docker run --rm video-gen:test \
  python -m src.entrypoints.run_gen \
  --job '{"prompts": ["test"]}' \
  --dry-run
```

---

## Progress Tracker

| Phase | Status | Progress | ETA |
|-------|--------|----------|-----|
| Phase 1: T2V MVP | 🔨 In Progress | 0% | 2 weeks |
| Phase 2: I2V Support | 📋 Planned | 0% | 1 week |
| Phase 3: Production | 💡 Future | 0% | 1 week |

**Last Updated**: 2026-02-02

---

## Notes

- Приоритет: Phase 1 critical path
- GPU тесты запускаются вручную
- B2 credentials для CI/CD через secrets
- Model cache volume mount для ускорения development
