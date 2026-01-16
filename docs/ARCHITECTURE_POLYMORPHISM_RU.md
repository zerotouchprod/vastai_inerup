# 🏗️ Архитектура: Почему `self._upscaler` используется для Watermark Removal?

## ❓ Вопрос
> "Почему `if not self._upscaler:` для watermark remover? Это будет апскейлинг, а не удаление watermark?"

## ✅ Ответ: Это Полиморфизм!

**НЕТ**, апскейлинга не будет! Это архитектурное решение, использующее полиморфизм.

---

## 🔍 Как Это Работает

### 1. Все Процессоры Реализуют Один Интерфейс

```python
# src/domain/protocols.py
class IProcessor:
    def process(self, frames: List[Path], output_dir: Path, **options) -> ProcessingResult:
        """Обработать фреймы"""
        pass
```

**Все процессоры используют один интерфейс:**
- ✅ `RealESRGANWrapper` - апскейлинг
- ✅ `RIFEWrapper` - интерполяция
- ✅ `SubtitleRemoverWrapper` - удаление субтитров
- ✅ `WatermarkRemoverWrapper` - удаление watermark

### 2. CLI Подменяет Реализацию

```python
# src/presentation/cli.py

# Создаем нужный процессор
if config.mode == 'remove-watermark':
    watermark_remover = factory.create_watermark_remover(
        roi='top-right',
        prefer='native'
    )
    
    # 🔄 ПОДМЕНА: передаем watermark_remover как upscaler!
    upscaler = watermark_remover  # ← Полиморфизм!

elif config.mode == 'remove-subtitles':
    subtitle_remover = factory.create_subtitle_remover(
        lang='ru',
        roi='0.0,0.6,1.0,0.4'
    )
    
    # 🔄 ПОДМЕНА: передаем subtitle_remover как upscaler!
    upscaler = subtitle_remover  # ← Полиморфизм!

elif config.mode == 'upscale':
    # Настоящий апскейлер
    upscaler = factory.create_upscaler(
        prefer='native',
        scale=2
    )

# Создаем оркестратор
orchestrator = VideoProcessingOrchestrator(
    upscaler=upscaler,  # Может быть любой IProcessor!
    interpolator=interpolator,
    ...
)
```

### 3. Оркестратор Использует `job.mode` для Определения Логики

```python
# src/application/orchestrator.py

def _process_frames(self, job, frames, workspace):
    """Обработать фреймы на основе режима."""
    
    # 🔀 job.mode определяет, КАКОЙ блок кода выполнится!
    
    if job.mode == "upscale":
        # self._upscaler = RealESRGANWrapper
        output_dir = workspace / "upscaled"
        result = self._upscaler.process(frames, output_dir)  # → RealESRGAN.process()
        return sorted(output_dir.glob("*.png"))
    
    elif job.mode == "remove-watermark":
        # self._upscaler = WatermarkRemoverWrapper (подменили!)
        output_dir = workspace / "watermark_removed"
        result = self._upscaler.process(frames, output_dir)  # → WatermarkRemover.process()
        return sorted(output_dir.glob("*.png"))
    
    elif job.mode == "remove-subtitles":
        # self._subtitle_remover = SubtitleRemoverWrapper
        output_dir = workspace / "subtitles_removed"
        result = self._subtitle_remover.process(frames, output_dir)  # → SubtitleRemover.process()
        return sorted(output_dir.glob("*.png"))
    
    elif job.mode == "interp":
        # self._interpolator = RIFEWrapper
        output_dir = workspace / "interpolated"
        result = self._interpolator.process(frames, output_dir)  # → RIFE.process()
        return sorted(output_dir.glob("*.png"))
```

---

## 🎯 Почему Не Будет Апскейлинга?

### Потому что `job.mode` проверяется ПЕРВЫМ!

```python
# Когда приходит job с mode='remove-watermark'

if job.mode == "upscale":  # ❌ False! Пропускаем этот блок
    ...

elif job.mode == "remove-watermark":  # ✅ True! Выполняем ЭТО
    # Здесь self._upscaler = WatermarkRemoverWrapper
    result = self._upscaler.process(...)  # Вызывает WatermarkRemoverWrapper.process()
    # ↓
    # WatermarkRemoverWrapper.process():
    #   1. Создает persistent mask
    #   2. Запускает ProPainter inpainting
    #   3. Возвращает обработанные фреймы
    # ✅ УДАЛЕНИЕ WATERMARK, а не апскейлинг!
```

### Таблица: Что Выполняется При Разных Режимах

| `job.mode` | `self._upscaler` содержит | Какой метод вызывается | Что делает |
|------------|---------------------------|------------------------|------------|
| `"upscale"` | `RealESRGANWrapper` | `RealESRGAN.process()` | ✅ Апскейлинг (2x, 4x) |
| `"remove-watermark"` | `WatermarkRemoverWrapper` | `WatermarkRemover.process()` | ✅ Удаление watermark |
| `"remove-subtitles"` | `SubtitleRemoverWrapper` (в `self._subtitle_remover`) | `SubtitleRemover.process()` | ✅ Удаление субтитров |
| `"interp"` | `RealESRGANWrapper` | `RIFE.process()` (использует `self._interpolator`) | ✅ Интерполяция |

---

## 🤔 Почему Не Добавить Отдельный Параметр `watermark_remover`?

### Плохой Дизайн (Без Полиморфизма):

```python
class VideoProcessingOrchestrator:
    def __init__(
        self,
        upscaler: Optional[IProcessor],
        interpolator: Optional[IProcessor],
        subtitle_remover: Optional[IProcessor],
        watermark_remover: Optional[IProcessor],      # ← Новый параметр
        blur_remover: Optional[IProcessor],           # ← Еще один
        noise_remover: Optional[IProcessor],          # ← Еще один
        color_corrector: Optional[IProcessor],        # ← И так далее...
        ...
    ):
```

**Проблемы:**
- ❌ Конструктор становится огромным
- ❌ Нужно изменять оркестратор для каждого нового режима
- ❌ Дублирование кода
- ❌ Сложнее поддерживать

### Хороший Дизайн (С Полиморфизмом):

```python
class VideoProcessingOrchestrator:
    def __init__(
        self,
        upscaler: Optional[IProcessor],       # ← Универсальный процессор
        interpolator: Optional[IProcessor],
        subtitle_remover: Optional[IProcessor],
        ...
    ):
```

**Преимущества:**
- ✅ Простой конструктор
- ✅ Не нужно изменять оркестратор для новых режимов
- ✅ Переиспользование параметров через полиморфизм
- ✅ Легко поддерживать

---

## 📊 Пример Выполнения

### Команда:
```bash
python3 pipeline_v2.py \
  --mode remove-watermark \
  --input video.mp4 \
  --watermark-roi "top-right"
```

### Поток Выполнения:

1. **CLI создает процессор:**
   ```python
   watermark_remover = WatermarkRemoverWrapper(roi='top-right')
   upscaler = watermark_remover  # Подмена!
   ```

2. **CLI создает job:**
   ```python
   job = Job(
       mode='remove-watermark',  # ← Ключевое поле!
       input_url='video.mp4',
       ...
   )
   ```

3. **CLI создает оркестратор:**
   ```python
   orchestrator = VideoProcessingOrchestrator(
       upscaler=upscaler,  # = WatermarkRemoverWrapper
       ...
   )
   ```

4. **Оркестратор обрабатывает job:**
   ```python
   def process(self, job: Job):
       frames = self._extractor.extract_frames(...)
       
       # Вызываем _process_frames
       processed = self._process_frames(job, frames, workspace)
   ```

5. **_process_frames проверяет job.mode:**
   ```python
   def _process_frames(self, job, frames, workspace):
       if job.mode == "upscale":         # ❌ False
           ...
       elif job.mode == "remove-watermark":  # ✅ TRUE!
           # self._upscaler = WatermarkRemoverWrapper
           result = self._upscaler.process(...)
           # ↓ Вызывается WatermarkRemoverWrapper.process()
           # ↓ Удаляет watermark, НЕ делает апскейлинг!
   ```

6. **WatermarkRemoverWrapper.process() выполняется:**
   ```python
   def process(self, frames, output_dir, **options):
       # 1. Детектит статическую область watermark
       mask = self._generate_static_mask(frames)
       
       # 2. Запускает ProPainter inpainting
       ProPainterAdapter().process(frames, masks, output)
       
       # 3. Возвращает обработанные фреймы
       return ProcessingResult(success=True, ...)
   ```

---

## ✅ Вывод

### Это НЕ апскейлинг, потому что:

1. **`job.mode` определяет логику** - проверяется ПЕРВЫМ
2. **Полиморфизм** - все процессоры реализуют `IProcessor`
3. **CLI подменяет реализацию** - передает `WatermarkRemover` как `upscaler`
4. **В коде вызывается правильный метод** - `WatermarkRemover.process()`

### Аналогия:

Представь, что `self._upscaler` - это **переменная типа "процессор"**:

```python
processor = None  # Пустая переменная

if mode == "upscale":
    processor = RealESRGAN()  # Назначаем апскейлер
    
elif mode == "remove-watermark":
    processor = WatermarkRemover()  # Назначаем удалятель watermark

# Теперь вызываем:
processor.process()  # Какой метод вызовется?
# ↓
# Зависит от того, ЧТО в переменной processor!
# Если WatermarkRemover → вызовется WatermarkRemover.process()
# Если RealESRGAN → вызовется RealESRGAN.process()
```

---

## 🔧 Как Добавить Новый Режим?

Благодаря полиморфизму, это очень просто:

### 1. Создай новый процессор:
```python
class BlurRemoverWrapper(IProcessor):
    def process(self, frames, output_dir, **options):
        # Логика удаления blur
        ...
```

### 2. Добавь в CLI:
```python
if config.mode == 'remove-blur':
    blur_remover = factory.create_blur_remover()
    upscaler = blur_remover  # ← Подмена!
```

### 3. Добавь в оркестратор:
```python
elif job.mode == "remove-blur":
    result = self._upscaler.process(frames, output_dir)  # Вызовет BlurRemover.process()
    return sorted(output_dir.glob("*.png"))
```

✅ **Готово!** Не нужно изменять конструктор оркестратора.

---

## 📚 Дополнительные Ресурсы

- **Полиморфизм в Python:** https://docs.python.org/3/tutorial/classes.html#inheritance
- **Duck Typing:** https://en.wikipedia.org/wiki/Duck_typing
- **Dependency Injection:** https://en.wikipedia.org/wiki/Dependency_injection

---

**Последнее Обновление:** 8 января 2026  
**Автор:** GitHub Copilot  
**Статус:** ✅ Документация Complete

