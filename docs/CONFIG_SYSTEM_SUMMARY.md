# Configuration System - Summary

## ✅ Completed

Все важные параметры для тонкой настройки удаления субтитров и водяных знаков вынесены в конфигурационные файлы с подробными комментариями.

---

## 📁 Созданные файлы

### 1. Конфигурационные модули

**`src/infrastructure/processors/subtitle_removal_config.py`** (348 строк)
- 🎯 Все параметры OCR детекции
- 🎯 Параметры расширения bounding box
- 🎯 Параметры дилатации и morphological closing
- 🎯 Параметры CLAHE enhancement
- 🎯 Настройки производительности
- 🎯 4 готовых профиля: `conservative`, `balanced`, `aggressive`, `minimal`

**`src/infrastructure/processors/watermark_removal_config.py`** (386 строк)
- 🎯 Параметры статической детекции
- 🎯 Параметры color-aware детекции
- 🎯 Параметры edge detection
- 🎯 Параметры расширения маски
- 🎯 Настройки производительности
- 🎯 5 готовых профилей для разных типов водяных знаков

### 2. Документация

**`docs/TUNING_GUIDE.md`** (521 строка)
- 📖 Полное руководство по настройке
- 📖 Примеры решения типичных проблем
- 📖 Справочная таблица всех параметров
- 📖 Инструкции по тестированию изменений

---

## 🔧 Обновленные файлы

### Интеграция с существующим кодом

1. **`src/services/cleaner_service.py`**
   - ✅ Импорт `subtitle_removal_config as SRC`
   - ✅ Все хардкодные значения заменены на `SRC.*`
   - ✅ Поддержка `FORCE_KERNEL_SIZE` env variable
   - ✅ Конфигурируемый dual-pass OCR
   - ✅ Конфигурируемые интервалы GPU cleanup

2. **`src/infrastructure/processors/watermark/wrapper.py`**
   - ✅ Импорт `watermark_removal_config as WRC`
   - ✅ Использование дефолтных значений из конфига
   - ✅ Параметры можно переопределить при инициализации

3. **`src/infrastructure/image_processing/watermark_detector.py`**
   - ✅ Импорт `watermark_removal_config as WRC`
   - ✅ Адаптивная выборка кадров на основе `SAMPLE_FRAME_COUNT`

---

## 📊 Ключевые параметры

### Для удаления субтитров

| Что контролирует | Параметр | Дефолт |
|------------------|----------|--------|
| Чувствительность OCR | `OCR_CONFIDENCE_THRESHOLD` | 0.05 |
| Двойной проход OCR | `OCR_DUAL_PASS_ENABLED` | True |
| Горизонтальное расширение | `BBOX_EXPAND_HORIZONTAL` | 15px |
| Вертикальное расширение | `BBOX_EXPAND_VERTICAL` | 20px |
| Начальная дилатация | `DILATION_ITERATIONS_INITIAL` | 2 |
| Морфологическое закрытие | `MORPHOLOGICAL_CLOSING_ITERATIONS` | 1 |
| Финальная дилатация | `DILATION_ITERATIONS_FINAL` | 1 |
| Сила CLAHE | `CLAHE_CLIP_LIMIT` | 4.0 |

### Для удаления водяных знаков

| Что контролирует | Параметр | Дефолт |
|------------------|----------|--------|
| Порог персистентности | `PERSISTENCE_THRESHOLD` | 0.80 |
| Количество семплов | `SAMPLE_FRAME_COUNT` | 30 |
| Мин. размер региона | `MIN_REGION_AREA` | 100px |
| Расширение маски | `MASK_EXPANSION_RADIUS` | 10px |
| Цветовая детекция | `USE_COLOR_DETECTION` | True |
| Цветовой порог | `COLOR_DIFF_THRESHOLD` | 30 |
| Сглаживание маски | `MASK_BLUR_SIGMA` | 2.0 |

---

## 🎨 Использование

### Способ 1: Редактирование конфига напрямую

```python
# Отредактируйте файл:
# src/infrastructure/processors/subtitle_removal_config.py

OCR_CONFIDENCE_THRESHOLD = 0.10  # Было: 0.05
BBOX_EXPAND_HORIZONTAL = 20      # Было: 15
```

Изменения применятся автоматически при следующем запуске.

### Способ 2: Применение профиля

```python
from src.infrastructure.processors import subtitle_removal_config as SRC

# Выберите профиль
SRC.apply_profile('conservative')  # Минимум ложных срабатываний
# или
SRC.apply_profile('aggressive')    # Максимальный охват
```

### Способ 3: Environment variable (для kernel size)

```bash
export FORCE_KERNEL_SIZE=50
python3 pipeline_v2.py --input video.mp4 --mode remove-subtitles
```

---

## 🔍 Отладка

### Проверка текущих значений

```python
# Для субтитров
from src.infrastructure.processors import subtitle_removal_config as SRC
SRC.validate_config()  # Покажет предупреждения об экстремальных значениях

# Для водяных знаков
from src.infrastructure.processors import watermark_removal_config as WRC
WRC.print_current_config()  # Выведет все текущие значения
```

### Debug mode

```bash
python3 pipeline_v2.py \
  --input video.mp4 \
  --mode remove-subtitles \
  --debug  # Сохранит диагностические изображения
```

Смотрите результаты в `output/debug/`:
- `*_mask.jpg` - сгенерированная маска (белое = удаляемая область)
- Если маска слишком большая → уменьшите агрессивность
- Если маска пропускает текст → увеличьте чувствительность

---

## 📋 Типичные сценарии настройки

### Проблема: "Удаляется слишком много"

```python
# Уменьшите агрессивность
OCR_CONFIDENCE_THRESHOLD = 0.15  # ↑
BBOX_EXPAND_HORIZONTAL = 10      # ↓
BBOX_EXPAND_VERTICAL = 15        # ↓
DILATION_ITERATIONS_INITIAL = 1  # ↓
```

### Проблема: "Пропускает некоторые субтитры"

```python
# Увеличьте чувствительность
OCR_CONFIDENCE_THRESHOLD = 0.01  # ↓
BBOX_EXPAND_HORIZONTAL = 25      # ↑
BBOX_EXPAND_VERTICAL = 30        # ↑
DILATION_ITERATIONS_INITIAL = 3  # ↑
```

### Проблема: "Медленная обработка"

```python
# Оптимизируйте производительность
OCR_DUAL_PASS_ENABLED = False    # Отключить двойной проход (2x быстрее)
GPU_CLEANUP_INTERVAL = 100       # Реже чистить память
DETECTION_SCALE_FACTOR = 0.25    # Для watermark: обработка на 1/4 разрешения
```

### Проблема: "Остаются артефакты по краям"

```python
# Увеличьте расширение и сглаживание
BBOX_EXPAND_HORIZONTAL = 20      # ↑
BBOX_EXPAND_VERTICAL = 25        # ↑
MASK_EXPANSION_RADIUS = 15       # Для watermark
MASK_BLUR_SIGMA = 3.0            # Для watermark
```

---

## ✨ Преимущества новой системы

1. ✅ **Единое место настройки**: Все параметры в двух файлах
2. ✅ **Подробные комментарии**: Для каждого параметра описано назначение и диапазон
3. ✅ **Готовые профили**: 4 профиля для субтитров, 5 для водяных знаков
4. ✅ **Валидация**: Автоматическое предупреждение об экстремальных значениях
5. ✅ **Обратная совместимость**: Старый код работает без изменений
6. ✅ **Документация**: Полное руководство по настройке с примерами

---

## 📚 Дополнительные материалы

- **Полное руководство**: `docs/TUNING_GUIDE.md`
- **Конфиг субтитров**: `src/infrastructure/processors/subtitle_removal_config.py`
- **Конфиг водяных знаков**: `src/infrastructure/processors/watermark_removal_config.py`

---

**Результат**: Теперь вы можете точно настроить агрессивность и чувствительность удаления субтитров и водяных знаков, просто изменяя значения констант в конфигурационных файлах! 🎉

