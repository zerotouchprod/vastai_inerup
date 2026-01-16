# 🔧 Quick Debug Guide - ProPainter CUDA Issues

## 🚨 Текущая проблема

```
RuntimeError: CUDA error: CUBLAS_STATUS_INVALID_VALUE when calling 
`cublasSgemmStridedBatched(...)`
```

Падает на строке 433 в `inference_propainter.py`:
```python
pred_img = model(selected_imgs, ...)
```

---

## 📍 Быстрая диагностика

### 1. Подключиться к Vast.ai
```bash
ssh -p 12345 root@ssh8.vast.ai
cd ~/vastai_inerup
```

### 2. Найти проблемные операции
```bash
cd /opt/ProPainter

# Найти ВСЕ transpose + matmul
grep -rn "\.transpose.*@\|@.*\.transpose" --include="*.py" | grep -v "PATCHED"

# Приоритетные файлы для проверки:
grep -n "transpose.*@" model/propainter.py
grep -n "transpose.*@" model/modules/deformable_transformer.py
grep -n "transpose.*@" model/modules/*.py
```

### 3. Проверить текущие патчи
```bash
# RAFT (должен быть пропатчен)
head -30 /opt/ProPainter/RAFT/corr.py | grep -i "pure pytorch"

# Transformer (должен быть пропатчен)
grep -n "PATCHED" /opt/ProPainter/model/modules/sparse_transformer.py

# Сколько файлов ещё нужно патчить?
grep -r "\.transpose.*@" /opt/ProPainter --include="*.py" | grep -v PATCHED | wc -l
```

---

## 🛠️ Быстрые фиксы

### Фикс №1: Глобальный monkey-patch (самый простой)

Добавить в начало `pipeline_v2.py`:
```python
import torch

# ГЛОБАЛЬНЫЙ FIX для всех transpose операций
original_transpose = torch.Tensor.transpose

def safe_transpose(self, dim0, dim1):
    result = original_transpose(self, dim0, dim1)
    return result.contiguous()  # Принудительное выравнивание

torch.Tensor.transpose = safe_transpose
print("✅ Global transpose monkey-patch applied")
```

### Фикс №2: Отключить TF32 глобально

В `factories.py` в начале `create_subtitle_remover()`:
```python
# Disable TensorFloat32 globally (causes stride issues on RTX 30/40/50)
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
self._logger.info("✅ Disabled TF32 globally for CUDA stability")
```

### Фикс №3: Патчить конкретные файлы

Если нашли проблемный файл (например, `model/propainter.py`), добавить метод:
```python
def _patch_propainter_model(self):
    """Patch main ProPainter model for CUDA stride safety"""
    from pathlib import Path
    
    model_path = Path("/opt/ProPainter/model/propainter.py")
    if not model_path.exists():
        return
    
    content = model_path.read_text()
    
    # Найти все "X @ Y.transpose(-2, -1)" и добавить .contiguous()
    import re
    pattern = r'(@\s+\w+\.transpose\([^)]+\))'
    replacement = r'\1.contiguous()  # PATCHED: memory alignment'
    
    if "# PATCHED: memory alignment" not in content:
        content = re.sub(pattern, replacement, content)
        model_path.write_text(content)
        self._logger.info("✅ Patched ProPainter main model")
```

Вызвать в `create_subtitle_remover()` после Transformer патча.

---

## 🔍 Детальная отладка

### Добавить debug wrapper в inference_propainter.py

SSH на машину:
```bash
cd /opt/ProPainter
cp inference_propainter.py inference_propainter.py.backup
```

Отредактировать строку 433:
```python
# БЫЛО:
pred_img = model(selected_imgs, selected_pred_flows_bi, selected_masks, selected_update_masks, l_t)

# СТАЛО:
try:
    pred_img = model(selected_imgs, selected_pred_flows_bi, selected_masks, selected_update_masks, l_t)
except RuntimeError as e:
    print("\n" + "="*80)
    print("❌ MODEL FORWARD FAILED AT LINE 433")
    print("="*80)
    print(f"Error: {e}")
    print(f"selected_imgs shape: {selected_imgs.shape}")
    print(f"selected_imgs dtype: {selected_imgs.dtype}")
    print(f"selected_imgs device: {selected_imgs.device}")
    print(f"selected_imgs is_contiguous: {selected_imgs.is_contiguous()}")
    import traceback
    traceback.print_exc()
    print("="*80)
    raise
```

Перезапустить:
```bash
python3 ~/vastai_inerup/pipeline_v2.py --input "..." --output /workspace/output --mode remove-subtitles
```

---

## 📊 Проверка результатов

### Ожидаемый успешный лог:
```
[13:XX:XX] [src.infrastructure.inpainting.propainter_adapter] [INFO] Processing Chunk 1/25: Frames 3
[13:XX:XX] [src.infrastructure.inpainting.propainter_adapter] [INFO] ✅ Chunk 1 completed
[13:XX:XX] [src.infrastructure.inpainting.propainter_adapter] [INFO] Processing Chunk 2/25: Frames 3
...
[13:XX:XX] [src.services.cleaner_service] [INFO] ✅ Subtitle removal completed
```

### Проверка видео выхода:
```bash
ls -lh /workspace/output/
ffprobe /workspace/output/final.mp4
```

---

## 🎯 Чеклист решения

- [ ] Нашли ВСЕ `transpose() + @` операции в ProPainter
- [ ] Либо пропатчили каждый файл индивидуально
- [ ] Либо применили глобальный monkey-patch
- [ ] Отключили TF32 глобально
- [ ] Протестировали на RTX 3090
- [ ] Протестировали на RTX 4090
- [ ] Протестировали на RTX 5070 Ti
- [ ] Commit + Push изменений
- [ ] Обновили документацию

---

## 📞 Если всё равно не работает

### План Б: Форк ProPainter

1. Форкнуть репозиторий: https://github.com/sczhou/ProPainter
2. Заменить ВСЕ `@` операции на безопасные:
```python
# БЫЛО:
result = a @ b.transpose(-2, -1)

# СТАЛО:
result = torch.matmul(a, b.transpose(-2, -1).contiguous())
```
3. Обновить Dockerfile:
```dockerfile
# БЫЛО:
RUN git clone https://github.com/sczhou/ProPainter.git /opt/ProPainter

# СТАЛО:
RUN git clone https://github.com/YOUR_USERNAME/ProPainter.git /opt/ProPainter
```

### План В: Использовать другую библиотеку

Альтернативы ProPainter для inpainting:
- E2FGVI: https://github.com/MCG-NKU/E2FGVI
- STTN: https://github.com/researchmm/STTN
- FuseFormer: https://github.com/ruiliu-ai/FuseFormer

---

**Последнее обновление:** 16 января 2026  
**Статус:** В процессе отладки

