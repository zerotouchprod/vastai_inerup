# Docker Fix for Vast.ai - RTX 20-50 Series Support

## Проблема
Ошибка `sm_120 is not compatible with the current PyTorch installation` возникает при использовании RTX 5080 (Blackwell) с compute capability 12.0 (sm_120). Старые версии PyTorch не поддерживают архитектуру Blackwell.

## Решение

### 1. Исправленный Dockerfile
Используйте `Dockerfile.vastai.optimized` - он содержит все необходимые исправления:

- **PyTorch 2.5.0 с CUDA 12.6**: Нативная поддержка архитектуры Blackwell (sm_120)
- **Поддержка всех RTX серий**: sm_75 (20xx), sm_86/sm_87 (30xx), sm_89 (40xx), sm_120 (50xx)
- **Оптимизированные зависимости**: Удалены ненужные пакеты, улучшена производительность

### 2. Ключевые изменения

#### CUDA Architecture Support
```dockerfile
ENV TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.7;8.9;9.0;12.0"
```

#### PyTorch Installation
```dockerfile
RUN pip install --no-cache-dir \
    torch==2.5.0 \
    torchvision==0.20.0 \
    torchaudio==2.5.0 \
    --index-url https://download.pytorch.org/whl/cu126
```

#### Environment Variables
```dockerfile
ENV CUDA_HOME="/usr/local/cuda"
ENV LD_LIBRARY_PATH="/usr/local/cuda/lib64:${LD_LIBRARY_PATH}"
```

### 3. Как использовать

#### Для Vast.ai:
```bash
# Используйте оптимизированный Dockerfile
docker build -f Dockerfile.vastai.optimized -t vastai-interup:optimized .
```

#### Для локальной разработки:
```bash
# Используйте полный Dockerfile
docker build -f Dockerfile.pytorch.fat -t vastai-interup:pytorch-fat .
```

### 4. Поддерживаемые GPU

| Серия | Архитектура | Compute Capability |
|-------|-------------|-------------------|
| RTX 20xx | Turing | sm_75 |
| RTX 30xx | Ampere | sm_80, sm_86, sm_87 |
| RTX 40xx | Ada Lovelace | sm_89 |
| RTX 50xx | Blackwell | sm_120 |
| Hopper (H100) | Hopper | sm_90 |

### 5. Проверка работы

После запуска контейнера проверьте:
```bash
python3 -c "import torch; print(f'PyTorch: {torch.__version__}'); print(f'CUDA available: {torch.cuda.is_available()}'); print(f'CUDA capability: {torch.cuda.get_device_capability()}')"
```

### 6. Troubleshooting

Если все еще возникают проблемы:

1. **Проверьте версию драйвера NVIDIA**:
   ```bash
   nvidia-smi
   ```

2. **Проверьте CUDA в контейнере**:
   ```bash
   nvcc --version
   ```

3. **Проверьте PyTorch**:
   ```bash
   python3 -c "import torch; print(torch.version.cuda)"
   ```

## Важные моменты

- **CUDA 12.6**: Последняя стабильная версия с нативной поддержкой Blackwell
- **PyTorch 2.5.0 cu126**: Специальная сборка для CUDA 12.6 с поддержкой sm_120
- **TORCH_CUDA_ARCH_LIST**: Явно указывает поддерживаемые архитектуры, включая sm_120
- **Vast.ai**: Оптимизирован для работы на платформе Vast.ai со всеми современными GPU

## Файлы

- `Dockerfile.vastai.optimized` - Оптимизированная версия для Vast.ai
- `Dockerfile.pytorch.fat` - Полная версия с всеми зависимостями
- `README_VASTAI_FIX.md` - Этот файл с инструкциями
