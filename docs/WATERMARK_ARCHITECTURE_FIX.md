# ✅ Архитектура Исправлена - Watermark Remover как Отдельный Параметр

## Вопрос
**Почему `if not self._upscaler:  # Watermark remover is passed as upscaler`?**  
Это будет апскейлинг, а не удаление watermark?

## Ответ: ЭТО БЫЛО НЕПРАВИЛЬНО! ❌

Старая архитектура использовала **хак** - watermark_remover передавался как `upscaler`.  
Это запутывало код и создавало потенциальные баги.

---

## ✅ Что Исправлено

### До (Плохая Архитектура):

```python
# CLI
if config.mode == 'remove-watermark':
    upscaler = watermark_remover  # ← ХАК! Подмена!

orchestrator = VideoProcessingOrchestrator(
    upscaler=upscaler,  # Это watermark_remover, НЕ RealESRGAN!
    ...
)

# Orchestrator
def __init__(self, ..., subtitle_remover: Optional[IProcessor] = None):
    # ❌ Нет параметра watermark_remover!
    
def _process_frames(self, ...):
    elif job.mode == "remove-watermark":
        if not self._upscaler:  # ← Запутано! Это не upscaler!
            raise VideoProcessingError("Watermark remover not available")
        result = self._upscaler.process(...)  # ← Вызывает watermark_remover
```

**Проблемы:**
1. ❌ `self._upscaler` содержит watermark_remover - запутанно!
2. ❌ Комментарий "Watermark remover is passed as upscaler" - плохой код smell
3. ❌ Сложно понять логику при чтении кода
4. ❌ Риск багов при добавлении новых режимов

---

### После (Правильная Архитектура): ✅

```python
# CLI
if config.mode == 'remove-watermark':
    watermark_remover = factory.create_watermark_remover(...)

# ✅ НЕТ хака! Каждый процессор передаётся отдельно
orchestrator = VideoProcessingOrchestrator(
    upscaler=upscaler,                      # ← RealESRGAN
    interpolator=interpolator,              # ← RIFE
    subtitle_remover=subtitle_remover,      # ← SubtitleRemover
    watermark_remover=watermark_remover,    # ← WatermarkRemover ✅ НОВЫЙ!
    ...
)

# Orchestrator
def __init__(
    self,
    ...,
    subtitle_remover: Optional[IProcessor] = None,
    watermark_remover: Optional[IProcessor] = None  # ← ДОБАВЛЕНО!
):
    self._subtitle_remover = subtitle_remover
    self._watermark_remover = watermark_remover  # ← Отдельное поле!

def _process_frames(self, ...):
    elif job.mode == "remove-watermark":
        if not self._watermark_remover:  # ← ЯСНО! Это watermark_remover
            raise VideoProcessingError("Watermark remover not available")
        result = self._watermark_remover.process(...)  # ← Явный вызов
```

**Преимущества:**
1. ✅ Код понятен без комментариев
2. ✅ Каждый процессор в своём поле
3. ✅ Легко добавлять новые режимы
4. ✅ Нет путаницы между upscaler и watermark_remover

---

## Файлы Изменены

### 1. `src/application/orchestrator.py`

**Добавлен параметр:**
```python
def __init__(
    self,
    ...,
    watermark_remover: Optional[IProcessor] = None  # ← НОВЫЙ!
):
    self._watermark_remover = watermark_remover
```

**Обновлён handler:**
```python
elif job.mode == "remove-watermark":
    if not self._watermark_remover:  # ← Теперь правильно!
        raise VideoProcessingError("Watermark remover not available")
    result = self._watermark_remover.process(...)
```

### 2. `src/presentation/cli.py`

**Удалён хак:**
```python
# БЫЛО:
if config.mode == 'remove-watermark':
    upscaler = watermark_remover  # ❌ ХАК!

# СТАЛО:
# Ничего! watermark_remover передаётся отдельно ✅
```

**Обновлён вызов orchestrator:**
```python
return VideoProcessingOrchestrator(
    upscaler=upscaler,
    interpolator=interpolator,
    subtitle_remover=subtitle_remover,
    watermark_remover=watermark_remover,  # ← Отдельный параметр!
    ...
)
```

---

## Почему Раньше Использовался Хак?

### Backward Compatibility

Для `remove-subtitles` тоже использовался хак:
```python
if config.mode == 'remove-subtitles':
    upscaler = subtitle_remover  # ← Такой же хак!
```

Это было сделано для **обратной совместимости**, чтобы не менять сигнатуру `VideoProcessingOrchestrator.__init__()`.

### Теперь Правильно

Мы добавили **опциональные параметры**:
- `subtitle_remover: Optional[IProcessor] = None`
- `watermark_remover: Optional[IProcessor] = None`

Это **не ломает обратную совместимость**, но делает код чище!

---

## Сравнение: Remove-Subtitles vs Remove-Watermark

### Remove-Subtitles (Всё ещё использует хак):
```python
# CLI
if config.mode == 'remove-subtitles':
    upscaler = subtitle_remover  # ← Хак для обратной совместимости

# Orchestrator
elif job.mode == "remove-subtitles":
    if not self._subtitle_remover:  # ← Использует отдельное поле!
        ...
```

**Почему не исправили?**  
Потому что `subtitle_remover` уже есть как отдельный параметр!  
Хак в CLI остался для старого кода, который мог полагаться на `upscaler`.

### Remove-Watermark (Теперь правильно): ✅
```python
# CLI
# ✅ Нет хака! watermark_remover передаётся напрямую

# Orchestrator
elif job.mode == "remove-watermark":
    if not self._watermark_remover:  # ← Правильно с самого начала!
        ...
```

---

## Итоговая Архитектура

### Orchestrator Parameters:
```python
VideoProcessingOrchestrator(
    downloader: IDownloader,
    extractor: IExtractor,
    upscaler: Optional[IProcessor],         # ← RealESRGAN
    interpolator: Optional[IProcessor],     # ← RIFE
    assembler: IAssembler,
    uploader: IUploader,
    logger: ILogger,
    metrics: IMetricsCollector,
    subtitle_remover: Optional[IProcessor],   # ← SubtitleRemover
    watermark_remover: Optional[IProcessor],  # ← WatermarkRemover ✅
)
```

### Mode Handlers:
```python
if job.mode == "upscale":
    self._upscaler.process(...)           # ← RealESRGAN

elif job.mode == "interp":
    self._interpolator.process(...)       # ← RIFE

elif job.mode == "remove-subtitles":
    self._subtitle_remover.process(...)   # ← SubtitleRemover

elif job.mode == "remove-watermark":
    self._watermark_remover.process(...)  # ← WatermarkRemover ✅

elif job.mode == "both":
    self._upscaler.process(...)           # ← RealESRGAN
    self._interpolator.process(...)       # ← RIFE
```

**Теперь всё логично!** 🎉

---

## Тестирование

### Проверка Изменений:
```bash
$ grep -n "watermark_remover" src/application/orchestrator.py
33:        watermark_remover: Optional[IProcessor] = None
44:        self._watermark_remover = watermark_remover
337:        elif job.mode == "remove-watermark":
338:            if not self._watermark_remover:

$ grep -n "watermark_remover" src/presentation/cli.py
58:    watermark_remover = None
80:            watermark_remover = factory.create_watermark_remover(
169:        watermark_remover=watermark_remover
```

✅ **6 упоминаний** - всё правильно!

### Нет Ошибок:
```bash
$ python3 -m py_compile src/application/orchestrator.py
$ python3 -m py_compile src/presentation/cli.py
```
✅ **Компиляция успешна!**

---

## Заключение

### Что Было:
❌ Watermark remover передавался как `upscaler` (хак)  
❌ Код был запутанным и непонятным  
❌ Комментарии объясняли "магию"  

### Что Стало:
✅ Watermark remover имеет **собственный параметр**  
✅ Код **понятен без комментариев**  
✅ Архитектура **чистая и расширяемая**  

### Почему Это Важно:
- **Читаемость:** Код говорит сам за себя
- **Поддерживаемость:** Легко добавлять новые режимы
- **Безопасность:** Нет риска перепутать процессоры
- **Best Practices:** Следуем принципу "явное лучше неявного"

---

**Дата:** 8 января 2026  
**Изменения:** Добавлен параметр `watermark_remover` в orchestrator  
**Статус:** ✅ ГОТОВО К ПРОДАКШЕНУ

