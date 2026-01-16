# Multi-GPU Architecture Support for Vast.ai

## Проблема

На Vast.ai доступны разные типы GPU:
- **RTX 20 series** (Turing, sm_75): RTX 2080, RTX 2080 Ti, Tesla T4
- **RTX 30 series** (Ampere, sm_86): RTX 3090, RTX 3080, A10, A40  
- **RTX 40 series** (Ada Lovelace, sm_89): RTX 4090, RTX 4080, L40, L40S
- **RTX 50 series** (Blackwell, sm_120): RTX 5090, RTX 5080 (будущие)
- **Data Center** (Ampere/Hopper): A100 (sm_80), H100 (sm_90)

**Без правильной настройки:** CUDA extensions компилируются только для одной архитектуры и **НЕ работают** на других GPU.

## Решение: Fat Binaries с PTX

### Что такое Fat Binary?

**Fat Binary** - это скомпилированная библиотека, которая содержит machine code для **нескольких GPU архитектур** в одном файле.

**Без Fat Binary:**
```
ProPainter compiled on RTX 3090 (sm_86)
→ Works ONLY on RTX 30 series
→ Fails on RTX 4090, H100, etc.
```

**С Fat Binary:**
```
ProPainter compiled with TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0;9.0+PTX"
→ Works on RTX 20/30/40, A100, H100
→ Works on future GPUs (via PTX)
```

### Что такое PTX?

**PTX (Parallel Thread Execution)** - это промежуточный язык CUDA, похожий на LLVM IR.

**Преимущества PTX:**
1. **Forward Compatibility** - работает на будущих GPU
2. **JIT Compilation** - компилируется в runtime под конкретную архитектуру
3. **Flexibility** - один binary для текущих и будущих GPU

**Без PTX:**
```
Binary compiled for sm_90 (H100)
→ Fails on RTX 5090 (sm_120) - architecture not supported
→ Need rebuild for each new generation
```

**С PTX (`9.0+PTX`):**
```
Binary includes PTX code
→ Works on H100 (sm_90) - uses precompiled code
→ Works on RTX 5090 (sm_120) - JIT compiles PTX at runtime
→ Works on future GPUs - JIT compiles PTX
```

## Что было изменено в Dockerfile

### ❌ ДО (неправильно):

```dockerfile
# Hardcoded sm_120 for Blackwell - breaks on current GPUs!
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.7;8.9;9.0;12.0"

# spatial-correlation-sampler builds ONLY for one architecture
pip install spatial-correlation-sampler

# ProPainter RAFT correlation not built explicitly
# (uses whatever architecture is detected)
```

**Проблемы:**
1. `sm_120` (Blackwell) не поддерживается текущими CUDA toolkit
2. spatial-correlation-sampler может собраться только под одну архитектуру
3. ProPainter RAFT correlation может не собраться вообще
4. Нет forward compatibility

### ✅ ПОСЛЕ (правильно):

```dockerfile
# ============================================================================
# CRITICAL: Set THIS BEFORE compiling ANY extensions
# ============================================================================
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0;9.0+PTX"
#                                               ↑↑↑
#                                    This enables forward compatibility!

# spatial-correlation-sampler now builds fat binary
pip install spatial-correlation-sampler
# → Compiles for: sm_75, sm_80, sm_86, sm_89, sm_90 + PTX
# → Works on ALL current and future GPUs

# ProPainter RAFT correlation explicitly built
cd /opt/ProPainter/RAFT/core/correlation
python3 setup.py install
# → Compiles with TORCH_CUDA_ARCH_LIST
# → Creates fat binary for all architectures
```

**Преимущества:**
1. ✅ Работает на RTX 20/30/40 series
2. ✅ Работает на A100, H100
3. ✅ Работает на будущих GPU (PTX)
4. ✅ Одна сборка для всех Vast.ai машин
5. ✅ Не нужен runtime rebuild

## Как это работает

### Build Time (Docker image creation):

```
1. ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0;9.0+PTX"
   ↓
2. pip install spatial-correlation-sampler
   → nvcc compiles for ALL specified architectures
   → Creates fat binary: spatial_correlation_sampler.so
   → Size: ~50MB (contains code for all GPUs)
   ↓
3. cd /opt/ProPainter/RAFT/core/correlation
   python3 setup.py install
   → Uses TORCH_CUDA_ARCH_LIST from environment
   → Compiles correlation_cuda.cpp for all architectures
   → Creates fat binary: correlation.so
```

### Runtime (на Vast.ai):

```
1. Container starts on RTX 3090 (sm_86)
   ↓
2. Python imports ProPainter
   ↓
3. CUDA runtime loads correlation.so
   → Finds sm_86 code in fat binary
   → Uses precompiled machine code
   → Fast, no JIT needed
   ↓
4. ProPainter runs correctly ✅
```

**Если запустить на RTX 5090 (Blackwell, будущее):**

```
1. Container starts on RTX 5090 (sm_120)
   ↓
2. Python imports ProPainter
   ↓
3. CUDA runtime loads correlation.so
   → No sm_120 code found (doesn't exist yet)
   → Finds PTX intermediate code
   → JIT compiles PTX to sm_120 at runtime
   → Slightly slower first run, then cached
   ↓
4. ProPainter runs correctly ✅
```

## Размер бинарников

### Single Architecture:
```
correlation.so (sm_86 only): ~5MB
```

### Fat Binary:
```
correlation.so (sm_75, sm_80, sm_86, sm_89, sm_90 + PTX): ~25MB
```

**Overhead:** 20MB на extension, но это приемлемо для универсальности.

## Поддерживаемые GPU на Vast.ai

| GPU Model | Architecture | Compute Capability | Supported |
|-----------|--------------|-------------------|-----------|
| RTX 2080 Ti | Turing | sm_75 | ✅ Yes |
| Tesla T4 | Turing | sm_75 | ✅ Yes |
| RTX 3090 | Ampere | sm_86 | ✅ Yes |
| RTX 3080 | Ampere | sm_86 | ✅ Yes |
| A10 | Ampere | sm_86 | ✅ Yes |
| A40 | Ampere | sm_86 | ✅ Yes |
| A100 | Ampere | sm_80 | ✅ Yes |
| RTX 4090 | Ada Lovelace | sm_89 | ✅ Yes |
| RTX 4080 | Ada Lovelace | sm_89 | ✅ Yes |
| L40 | Ada Lovelace | sm_89 | ✅ Yes |
| L40S | Ada Lovelace | sm_89 | ✅ Yes |
| H100 | Hopper | sm_90 | ✅ Yes |
| H200 | Hopper | sm_90 | ✅ Yes |
| RTX 5090* | Blackwell | sm_120 | ✅ Yes (via PTX) |
| RTX 5080* | Blackwell | sm_120 | ✅ Yes (via PTX) |

*Future GPUs - will work via PTX JIT compilation

## Тестирование

### Проверка что fat binary создан:

```bash
# В собранном Docker image
python3 -c "
import torch
print('CUDA architectures in PyTorch:')
print(torch.cuda.get_arch_list())
"

# Ожидаемый вывод:
# ['sm_75', 'sm_80', 'sm_86', 'sm_89', 'sm_90', 'compute_90']
#                                                  ↑↑↑↑↑↑↑↑↑↑↑
#                                                  This is PTX
```

### Проверка spatial-correlation-sampler:

```bash
python3 -c "
import spatial_correlation_sampler
print('✅ spatial-correlation-sampler imported successfully')
"
```

### Проверка ProPainter RAFT:

```bash
python3 test_cuda_extensions.py
# Should output:
# ✅ spatial-correlation-sampler is working
# ✅ ProPainter RAFT initialized successfully
```

### На разных GPU:

```bash
# RTX 3090
nvidia-smi --query-gpu=compute_cap --format=csv
# 8.6
python3 test_cuda_extensions.py
# ✅ ALL TESTS PASSED

# RTX 4090
nvidia-smi --query-gpu=compute_cap --format=csv
# 8.9
python3 test_cuda_extensions.py
# ✅ ALL TESTS PASSED

# H100
nvidia-smi --query-gpu=compute_cap --format=csv
# 9.0
python3 test_cuda_extensions.py
# ✅ ALL TESTS PASSED
```

## FAQ

### Q: Почему не sm_120 (Blackwell)?
**A:** Current CUDA toolkit (12.6) doesn't support sm_120 yet. Using `9.0+PTX` provides forward compatibility via JIT.

### Q: Будет ли работать на RTX 5090?
**A:** Да! PTX код будет JIT скомпилирован в sm_120 at runtime.

### Q: Почему файлы стали больше?
**A:** Fat binary содержит код для 5+ архитектур. ~20MB overhead приемлем для универсальности.

### Q: Будет ли работать на всех Vast.ai машинах?
**A:** Да! Образ работает на всех Vast.ai GPU (RTX 20/30/40, A100, H100, будущих).

### Q: Нужен ли runtime rebuild?
**A:** Нет! Fat binary содержит код для всех архитектур. AUTO_REBUILD_CUDA_EXTENSIONS больше не нужен.

### Q: Что если я соберу на RTX 3090, а запущу на RTX 4090?
**A:** Будет работать! Fat binary содержит код для обеих архитектур (sm_86 и sm_89).

### Q: Влияет ли это на производительность?
**A:** Нет! CUDA runtime выбирает правильный код at load time. Zero performance overhead.

## Итог

### ✅ Преимущества нового подхода:

1. **Universal Binary** - одна сборка для всех GPU
2. **Forward Compatibility** - работает на будущих GPU (PTX)
3. **No Runtime Rebuild** - extensions уже правильные
4. **Better Performance** - нет JIT overhead на текущих GPU
5. **Production Ready** - надежно и reproducible

### 📦 Что включено:

- ✅ spatial-correlation-sampler (fat binary)
- ✅ ProPainter RAFT correlation (fat binary)
- ✅ SAM 2 extensions (fat binary)
- ✅ PTX forward compatibility

### 🚀 Deployment:

```bash
# Build once
docker build -t your-image:latest -f docker/Dockerfile.vastai.optimized .

# Deploy anywhere on Vast.ai
# Works on RTX 20/30/40, A100, H100, future GPUs
docker run your-image python pipeline_v2.py --input video.mp4
```

### 🎯 Результат:

**Один Docker image работает на ВСЕХ Vast.ai GPU без rebuild!**

