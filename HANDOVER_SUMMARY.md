# 📦 Пакет передачи знаний - Краткое резюме

## ✅ Что создано

Создан полный пакет документации для передачи контекста проблемы с ProPainter CUDA compatibility:

### 📄 4 документа:

1. **HANDOVER_README.md** (этот файл) - Точка входа
2. **CONTEXT_FOR_HANDOVER.md** - Детальный контекст (~500 строк)
3. **QUICK_DEBUG_GUIDE.md** - Команды и quick fixes
4. **ARCHITECTURE_DIAGRAMS.md** - Визуальные схемы

---

## 🎯 Текущая ситуация (одним предложением)

ProPainter падает с `CUBLAS_STATUS_INVALID_VALUE` на RTX 30/40/50 series из-за проблем выравнивания памяти при операциях `transpose() + @`, решение - добавить `.contiguous()` во все такие места или применить глобальный monkey-patch.

---

## ✅ Что уже исправлено

- ✅ Заменён C++ `spatial-correlation-sampler` на Pure PyTorch CorrBlock
- ✅ Пропатчен RAFT (corr.py полностью перезаписан)
- ✅ Пропатчен Transformer (3 места в sparse_transformer.py)

---

## ❌ Что ещё нужно исправить

Найти и пропатчить оставшиеся `transpose() + @` операции в:
- `/opt/ProPainter/model/propainter.py` (скорее всего здесь)
- `/opt/ProPainter/model/modules/deformable_transformer.py`
- Другие файлы в `model/modules/*.py`

**Команда для поиска:**
```bash
cd /opt/ProPainter
grep -rn "\.transpose.*@\|@.*\.transpose" --include="*.py" | grep -v PATCHED
```

---

## 🚀 Следующему агенту

1. **Начать с:** `HANDOVER_README.md` (навигация)
2. **Изучить:** `CONTEXT_FOR_HANDOVER.md` (история проблемы)
3. **Использовать:** `QUICK_DEBUG_GUIDE.md` (команды)
4. **Понять:** `ARCHITECTURE_DIAGRAMS.md` (схемы)

---

## 🔧 Рекомендуемое решение

**Вариант 1 (быстро):** Глобальный monkey-patch в начале `pipeline_v2.py`:
```python
import torch
original_transpose = torch.Tensor.transpose
def safe_transpose(self, dim0, dim1):
    return original_transpose(self, dim0, dim1).contiguous()
torch.Tensor.transpose = safe_transpose
```

**Вариант 2 (чисто):** Найти и пропатчить каждый файл индивидуально через `factories.py`

---

## 📞 Ключевые файлы

- `src/application/factories.py` - ВСЯ логика патчинга
- `docker/patches/raft_corr.py` - Референс Pure PyTorch CorrBlock
- `pipeline_v2.py` - Точка входа

---

## 💡 Главная идея решения

**Проблема:** Современные GPU требуют строгого выравнивания памяти (memory alignment)  
**Причина:** `tensor.transpose()` создаёт view с нестандартными strides  
**Решение:** Принудительное копирование (`.contiguous()` или `.clone()`)

---

## ✅ Критерий успеха

В логах должно появиться:
```
[XX:XX:XX] [propainter_adapter] [INFO] ✅ ProPainter chunk 1 completed
[XX:XX:XX] [cleaner_service] [INFO] ✅ Subtitle removal completed
```

---

**Всё готово для передачи! 🚀**

**Создано:** 16 января 2026  
**Коммиты:** 3 (документация)  
**Branch:** main_rmsubs_roi_ar  
**Статус:** Готово к передаче ✅

