# 🚀 Quick Start - batch_processor.py

## Один файл для всего! ✨

---

## 📋 Чеклист перед запуском

- [x] `.env` файл с credentials
- [x] `config.yaml` настроен
- [x] Файлы в B2 (`input/c1/` или другая директория)

---

## ⚡ Запуск

```bash
python batch_processor.py
```

**Всё!** Остальное автоматически:
- ✅ Загрузит remote config
- ✅ Найдёт файлы в B2
- ✅ Найдёт дешёвый инстанс
- ✅ Создаст и запустит
- ✅ Склонирует репозиторий
- ✅ Запустит обработку
- ✅ Покажет логи
- ✅ Выведет URL результата
- ✅ Уничтожит инстанс

---

## 🎯 Что увидишь

```
[INFO] [+] Downloading remote config...
[INFO] [OK] Remote config merged
[INFO] [OK] B2 client initialized
[INFO] [OK] Vast.ai client initialized
[INFO] [LIST] Listing files from B2: input/c1
[INFO] [OK] Found 1 video files
[INFO] [RUN] Processing file: https://...
[INFO] [OK] Selected offer: RTX 5060 Ti @ $0.071/hr
[INFO] [OK] Created instance: #28397367
[INFO] [OK] Instance running
[INFO] [MONITOR] Monitoring instance #28397367...
[INFO]   [LOG] === Remote Runner Starting ===
[INFO]   [LOG] Cloning repository...
...
[INFO] [RESULT] Download URL: https://noxfvr-videos...
[INFO] [CLEANUP] Destroying instance #28397367...
[INFO] [OK] Instance destroyed
[INFO] [OK] Batch processing complete: 1 files submitted
```

---

## 🔧 Опции

### Dry run (посмотреть что будет обработано)
```bash
python batch_processor.py --dry-run
```

### Другая директория
```bash
python batch_processor.py --input-dir input/urgent
```

### Другой preset
```bash
python batch_processor.py --preset high
```

---

## ❓ Troubleshooting

### Проблема: B2 client not initialized
**Решение:** Проверь `.env` файл
```env
B2_KEY=your_key
B2_SECRET=your_secret
B2_BUCKET=noxfvr-videos
B2_ENDPOINT=https://s3.us-west-004.backblazeb2.com
```

### Проблема: Vast.ai client not initialized
**Решение:** Проверь `.env` файл
```env
VAST_API_KEY=your_vast_api_key
```

### Проблема: No files to process
**Решение:** Проверь имя директории в remote config или используй `--input-dir`

### Проблема: No suitable offers found
**Решение:** Увеличь `max_price` в preset или используй другой preset

---

## 📚 Подробности

См. полную документацию:
- `BATCH_PROCESSOR_SUCCESS.md`
- `BATCH_PROCESSOR_MONITORING.md`
- `FINAL_COMPLETE_DEC1.md`

---

**Версия:** 2.1  
**Дата:** 1 декабря 2025  
**Статус:** Production Ready ✅

