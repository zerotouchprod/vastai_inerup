# 📖 Документация для передачи проекта

## 🎯 Цель

Полная передача контекста проблемы с ProPainter CUDA compatibility следующему агенту без потери информации.

---

## 📚 Структура документации

### 1. [CONTEXT_FOR_HANDOVER.md](CONTEXT_FOR_HANDOVER.md) - Главный документ
**Объём:** ~500 строк детального описания  
**Язык:** Русский

**Содержит:**
- ✅ Краткое резюме проблемы
- ✅ Архитектура проекта (структура файлов)
- ✅ Точка входа на Vast.ai
- ✅ Полная история проблем (3 основные проблемы)
- ✅ Эволюция решений (6 итераций)
- ✅ Детальное описание патчинга (2 метода)
- ✅ Docker окружение
- ✅ Процесс отладки на Vast.ai
- ✅ Текущий статус (что работает / что нет)
- ✅ Следующие шаги
- ✅ Критические моменты для нового агента
- ✅ Философия решения (Senior Approach)

**Читать первым!**

---

### 2. [QUICK_DEBUG_GUIDE.md](QUICK_DEBUG_GUIDE.md) - Шпаргалка
**Объём:** Краткие команды и quick fixes  
**Язык:** Русский

**Содержит:**
- ⚡ Команды для быстрой диагностики
- ⚡ 3 готовых варианта фикса
- ⚡ Debug wrapper для добавления в код
- ⚡ Чеклист решения
- ⚡ План Б и План В

**Использовать при отладке!**

---

### 3. [ARCHITECTURE_DIAGRAMS.md](../ARCHITECTURE_DIAGRAMS.md) - Визуализация
**Объём:** ASCII диаграммы и схемы  
**Язык:** Русский с английскими терминами

**Содержит:**
- 📊 Общая схема потока данных
- 📊 Детальная схема патчинга CorrBlock
- 📊 Схема патчинга Transformer
- 📊 Карта файлов ProPainter со статусами
- 📊 Timeline исправлений
- 📊 Ключевые инсайты с примерами кода

**Читать для понимания архитектуры!**

---

## 🚀 Quick Start для нового агента

### Шаг 1: Прочитать контекст
```bash
# Открыть главный документ
cat CONTEXT_FOR_HANDOVER.md

# Изучить раздел "Текущий статус"
# Изучить раздел "Следующие шаги"
```

### Шаг 2: Изучить архитектуру
```bash
# Посмотреть визуальные схемы
cat ARCHITECTURE_DIAGRAMS.md

# Понять места патчинга
# Понять почему предыдущие решения не сработали
```

### Шаг 3: Подключиться к Vast.ai
```bash
# Получить credentials из vast_submit.py output
ssh -p PORT root@sshX.vast.ai
cd ~/vastai_inerup
```

### Шаг 4: Диагностика
```bash
# Использовать команды из QUICK_DEBUG_GUIDE.md
cd /opt/ProPainter
grep -rn "\.transpose.*@" --include="*.py" | grep -v PATCHED
```

### Шаг 5: Применить фикс
```bash
# Выбрать один из 3 вариантов из QUICK_DEBUG_GUIDE.md
# Вариант 1: Глобальный monkey-patch (рекомендуется)
# Вариант 2: Отключить TF32
# Вариант 3: Патчить конкретные файлы
```

### Шаг 6: Тестирование
```bash
python3 ~/vastai_inerup/pipeline_v2.py \
  --input "https://..." \
  --output /workspace/output \
  --mode remove-subtitles

# Проверить логи
tail -f ~/vastai_inerup/job.log
```

---

## 🎯 Текущая проблема (кратко)

**Симптом:**
```
RuntimeError: CUDA error: CUBLAS_STATUS_INVALID_VALUE
File "/opt/ProPainter/inference_propainter.py", line 433
    pred_img = model(...)
```

**Что уже исправлено:**
- ✅ RAFT CorrBlock (Pure PyTorch)
- ✅ Transformer attention (3 места)

**Что ещё нужно исправить:**
- ❓ Найти ВСЕ `transpose() + @` операции в ProPainter
- ❓ Пропатчить их аналогично Transformer
- ❓ Или применить глобальный monkey-patch

**Где искать:**
```bash
/opt/ProPainter/model/propainter.py             # Скорее всего здесь
/opt/ProPainter/model/modules/deformable_transformer.py
/opt/ProPainter/model/modules/*.py
```

---

## 📂 Структура кода (где что находится)

```
src/application/factories.py
├── _inject_pure_pytorch_corrblock()     # ⭐ Инъекция CorrBlock
├── _patch_raft_py()                     # 🔧 Патч RAFT imports
└── _patch_propainter_transformer()      # 🔧 Патч Transformer

docker/patches/raft_corr.py              # 📄 Референсная реализация
                                         # (НЕ используется напрямую!)

pipeline_v2.py                           # 🚪 Точка входа Vast.ai
```

---

## 🆘 Если застрял

### Проблема: Не понимаю что происходит
**Решение:** Прочитать раздел "История проблем и решений" в CONTEXT_FOR_HANDOVER.md

### Проблема: Нужны команды для диагностики
**Решение:** Открыть QUICK_DEBUG_GUIDE.md

### Проблема: Не понимаю архитектуру патчинга
**Решение:** Посмотреть схемы в ARCHITECTURE_DIAGRAMS.md

### Проблема: Ошибка повторяется после фикса
**Решение:** Проверить раздел "Следующие шаги" в CONTEXT_FOR_HANDOVER.md

### Проблема: Нужен альтернативный подход
**Решение:** См. "План Б" и "План В" в QUICK_DEBUG_GUIDE.md

---

## 🔗 Связанная документация

### Уже существующие документы:
- `docs/TITANIUM_SOLUTION.md` - Обзор Pure PyTorch решения
- `docs/TITANIUM_V3_ARCHITECTURE.md` - Архитектурное описание
- `MULTI_GPU_COMPLETE.md` - Multi-GPU поддержка

### Файлы для изучения:
- `src/application/factories.py` - ВСЯ логика патчинга
- `src/infrastructure/inpainting/propainter_adapter.py` - Обёртка ProPainter
- `docker/patches/raft_corr.py` - Референсная реализация

---

## ✅ Чеклист для нового агента

Перед началом работы убедитесь, что:
- [ ] Прочитали CONTEXT_FOR_HANDOVER.md полностью
- [ ] Изучили схемы в ARCHITECTURE_DIAGRAMS.md
- [ ] Понимаете почему spatial-correlation-sampler не работает
- [ ] Понимаете что такое stride alignment error
- [ ] Знаете где происходит runtime patching
- [ ] Имеете доступ к Vast.ai инстансу
- [ ] Умеете подключаться по SSH

После решения проблемы:
- [ ] Обновили CONTEXT_FOR_HANDOVER.md (раздел "Текущий статус")
- [ ] Добавили новые команды в QUICK_DEBUG_GUIDE.md
- [ ] Обновили схемы в ARCHITECTURE_DIAGRAMS.md
- [ ] Сделали commit + push
- [ ] Протестировали на RTX 3090/4090/5070

---

## 📞 Контакты и ресурсы

**GitHub Repo:** (ваш репозиторий)  
**Branch:** `main_rmsubs_roi_ar`

**ProPainter:**
- GitHub: https://github.com/sczhou/ProPainter
- Paper: https://arxiv.org/abs/2309.03897

**RAFT:**
- GitHub: https://github.com/princeton-vl/RAFT
- Paper: https://arxiv.org/abs/2003.12039

**PyTorch CUDA:**
- Docs: https://pytorch.org/docs/stable/notes/cuda.html
- cuBLAS: https://docs.nvidia.com/cuda/cublas/

---

**Создано:** 16 января 2026  
**Автор:** GitHub Copilot  
**Версия:** 1.0

**Удачи в отладке! 🚀**

