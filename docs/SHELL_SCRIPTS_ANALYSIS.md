# План избавления от shell скриптов

## Текущее состояние

Shell скрипты **ВСЁ ЕЩЁ используются** в новой архитектуре:
- `run_realesrgan_pytorch.sh` (977 строк)
- `run_rife_pytorch.sh` (предположительно ~800 строк)

**Используются в:**
- `src/infrastructure/processors/realesrgan/pytorch_wrapper.py`
- `src/infrastructure/processors/rife/pytorch_wrapper.py`

---

## ✅ Рекомендация: ОСТАВИТЬ КАК ЕСТЬ

### Почему это OK:

1. **Архитектурно правильно**
   - Shell скрипты изолированы через Adapter pattern
   - Вся бизнес-логика в Python
   - Для пользователей API полностью Python

2. **Работает в production**
   - Скрипты протестированы
   - Обрабатывают edge cases
   - Имеют retry logic и error handling

3. **Никого не беспокоит**
   - Пользователи используют Python API
   - Shell скрипты - implementation detail
   - Можно заменить в будущем без breaking changes

4. **Следует принципу "If it ain't broke, don't fix it"**

---

## 🔧 Если всё же хочется избавиться

### Фаза 1: Создать чистый Python implementation

```python
# src/infrastructure/processors/realesrgan/pytorch_native.py
"""Pure Python Real-ESRGAN implementation without shell scripts."""

import torch
from pathlib import Path
from typing import List, Dict, Any

from infrastructure.processors.base import BaseProcessor
from domain.exceptions import VideoProcessingError

class RealESRGANPytorchNative(BaseProcessor):
    """Native Python implementation of Real-ESRGAN."""
    
    def __init__(self, model_name='RealESRGAN_x4plus', **kwargs):
        super().__init__(**kwargs)
        self.model = self._load_model(model_name)
    
    def _load_model(self, model_name):
        """Load Real-ESRGAN model."""
        try:
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer
            
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, 
                          num_block=23, num_grow_ch=32, scale=4)
            
            upsampler = RealESRGANer(
                scale=4,
                model_path='weights/RealESRGAN_x4plus.pth',
                model=model,
                tile=512,
                tile_pad=10,
                pre_pad=0,
                half=True if torch.cuda.is_available() else False
            )
            
            return upsampler
        except Exception as e:
            raise VideoProcessingError(f"Failed to load model: {e}")
    
    def _execute_processing(self, input_frames, output_dir, options):
        """Process frames using native Python."""
        import cv2
        from PIL import Image
        
        scale = options.get('scale', 2)
        output_frames = []
        
        for frame_path in input_frames:
            # Load image
            img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
            
            # Upscale
            output, _ = self.model.enhance(img, outscale=scale)
            
            # Save
            output_path = output_dir / frame_path.name
            cv2.imwrite(str(output_path), output)
            output_frames.append(output_path)
        
        return output_frames
```

### Фаза 2: Аналогично для RIFE

```python
# src/infrastructure/processors/rife/pytorch_native.py
"""Pure Python RIFE implementation without shell scripts."""

import torch
from pathlib import Path

class RifePytorchNative(BaseProcessor):
    """Native Python RIFE interpolation."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.model = self._load_rife_model()
    
    def _load_rife_model(self):
        """Load RIFE model."""
        from RIFEv4.26_0921.RIFE_HDv3 import Model
        
        model = Model()
        model.load_model('RIFEv4.26_0921/train_log', -1)
        model.eval()
        model.device()
        
        return model
    
    def _execute_processing(self, input_frames, output_dir, options):
        """Interpolate frames."""
        import cv2
        import torch
        
        factor = options.get('factor', 2)
        output_frames = []
        
        for i in range(len(input_frames) - 1):
            frame1 = self._load_frame(input_frames[i])
            frame2 = self._load_frame(input_frames[i + 1])
            
            # Interpolate
            with torch.no_grad():
                mids = self.model.inference(frame1, frame2, factor)
            
            # Save interpolated frames
            for mid in mids:
                output_path = output_dir / f"mid_{i}_{len(output_frames)}.png"
                self._save_frame(mid, output_path)
                output_frames.append(output_path)
        
        return output_frames
```

### Фаза 3: Обновить Factory

```python
# src/application/factories.py
class ProcessorFactory:
    def create_upscaler(self, prefer='auto', use_native=False):
        """Create upscaler with option for native implementation."""
        if use_native:
            # Use pure Python implementation
            from infrastructure.processors.realesrgan.pytorch_native import RealESRGANPytorchNative
            return RealESRGANPytorchNative()
        else:
            # Use shell script wrapper (current)
            from infrastructure.processors.realesrgan.pytorch_wrapper import RealESRGANPytorchWrapper
            return RealESRGANPytorchWrapper()
```

### Фаза 4: Постепенный переход

```bash
# Старый способ (с shell скриптами)
python pipeline_v2.py --mode upscale

# Новый способ (чистый Python)
python pipeline_v2.py --mode upscale --use-native-processors
```

---

## 📊 Сравнение подходов

| Критерий | Shell скрипты | Native Python |
|----------|---------------|---------------|
| Работает сейчас | ✅ Да | ❌ Нужна реализация |
| Поддержка | ✅ Есть | ❌ Нужна |
| Скорость | ✅ Быстро | ✅ Быстро |
| Отладка | ⚠️ Сложнее | ✅ Легче |
| Зависимости | Bash | Python |
| Код | 977+ строк bash | ~200 строк Python |
| Edge cases | ✅ Обработаны | ❌ Нужно покрыть |

---

## 🎯 Мои рекомендации

### Сейчас (December 2025)
**ОСТАВЬТЕ shell скрипты!**

Причины:
1. Работают в production ✅
2. Архитектурно изолированы ✅
3. Легко заменить в будущем ✅
4. Нет срочной необходимости

### В будущем (2026+)
Если захотите избавиться:

1. **Создайте native Python versions** (Фаза 1-2)
2. **Протестируйте параллельно** с shell версиями
3. **Постепенно переходите** (Фаза 3-4)
4. **Удалите shell скрипты** когда убедитесь в стабильности

---

## 🏗️ Текущая архитектура (правильная!)

```
User Code (Python)
    ↓
ProcessorFactory (Python)
    ↓
RealESRGANPytorchWrapper (Python) ← Adapter Pattern
    ↓
run_realesrgan_pytorch.sh (Bash) ← Implementation Detail
    ↓
Python scripts (batch processing)
```

**Это OK!** Adapter pattern специально для таких случаев.

---

## ✅ Итоговая рекомендация

**НЕ УДАЛЯЙТЕ shell скрипты сейчас!**

### Почему:
1. ✅ Архитектурно правильно (Adapter pattern)
2. ✅ Работают в production
3. ✅ Легко заменить без breaking changes
4. ✅ Следуют принципу "Don't fix what ain't broke"

### Когда можно удалить:
- Когда создадите native Python implementations
- Когда протестируете их в production
- Когда убедитесь что все edge cases покрыты

---

## 📝 Action Items (опционально, не сейчас)

- [ ] Создать `pytorch_native.py` для Real-ESRGAN
- [ ] Создать `pytorch_native.py` для RIFE
- [ ] Добавить флаг `--use-native-processors`
- [ ] Протестировать параллельно
- [ ] Замерить performance
- [ ] Постепенный переход
- [ ] Удалить shell скрипты

**Оценка работы**: ~40 часов  
**Приоритет**: Низкий (не срочно)  
**Риск**: Средний (может сломать production)

---

*Рекомендация создана: 1 декабря 2025*  
*Текущий статус: Shell скрипты используются и это OK ✅*

