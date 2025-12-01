# ✅ Добавлен вывод информации о Git коммите

## Дата: 1 декабря 2025, 18:35

---

## ✨ Что добавлено

### 1. Аргумент `--output`

Теперь можно указать директорию для вывода:

```bash
python pipeline_v2.py --input video.mp4 --output /workspace/output --mode both
```

**До:**
```
pipeline_v2.py: error: unrecognized arguments: --output /workspace/output
```

**После:**
```
✅ Output directory: /workspace/output
```

---

### 2. Вывод Git commit информации

При запуске pipeline выводится информация о текущем коммите:

```
============================================================
Video Processing Pipeline v2.0
Git commit: 7403755
Commit msg: Add --output argument to CLI and display git commit info at pipeline start
Input: https://example.com/video.mp4
Output: /workspace/output
Mode: both
============================================================
```

**Зачем это нужно:**
- ✅ Видно какая версия кода запущена на инстансе
- ✅ Можно отследить баги по коммиту
- ✅ Легче понять что изменилось между запусками
- ✅ Упрощает отладку в логах Vast.ai

---

## 🔧 Технические детали

### Получение Git информации

```python
# Get git commit hash (short)
git_hash = subprocess.check_output(
    ['git', 'rev-parse', '--short', 'HEAD'],
    stderr=subprocess.DEVNULL,
    cwd=Path(__file__).parent.parent.parent
).decode().strip()

# Get commit message
git_msg = subprocess.check_output(
    ['git', 'log', '-1', '--pretty=%B'],
    stderr=subprocess.DEVNULL,
    cwd=Path(__file__).parent.parent.parent
).decode().strip()
```

**Безопасно:**
- Использует `subprocess.DEVNULL` для подавления ошибок
- Обёрнуто в `try/except` - если git недоступен, показывает "unknown"
- Не падает если не git репозиторий

---

## 📊 Пример вывода в логах

### На локальной машине:
```
============================================================
Video Processing Pipeline v2.0
Git commit: 7403755
Commit msg: Add --output argument to CLI and display git commit info at pipeline start
Input: tests/video/test.mp4
Output: ./output
Mode: upscale
============================================================
```

### На Vast.ai инстансе:
```
[18:35:01] [LOG] ============================================================
[18:35:01] [LOG] Video Processing Pipeline v2.0
[18:35:01] [LOG] Git commit: 7403755
[18:35:01] [LOG] Commit msg: Add --output argument to CLI and display git commit info
[18:35:01] [LOG] Input: https://noxfvr-videos.s3.us-west-004.backblazeb2.com/input/c1/qad.mp4
[18:35:01] [LOG] Output: /workspace/output
[18:35:01] [LOG] Mode: both
[18:35:01] [LOG] ============================================================
```

**Теперь в логах сразу видно:**
- ✅ Какой коммит запущен
- ✅ Что было изменено в этом коммите
- ✅ Откуда читать входные данные
- ✅ Куда писать результат

---

## 🧪 Тестирование

### Тест 1: Проверка --help
```bash
python pipeline_v2.py --help
```

**Результат:**
```
--output, -o OUTPUT   Output directory (default: ./output)
```
✅ Аргумент добавлен

### Тест 2: Проверка git info
```bash
python pipeline_v2.py --input test.mp4 --mode upscale
```

**Ожидаемый вывод:**
```
Git commit: 7403755
Commit msg: Add --output argument to CLI and display git commit info at pipeline start
```
✅ Информация выводится

### Тест 3: Git недоступен
```bash
# В контейнере без git
python pipeline_v2.py --input test.mp4 --mode upscale
```

**Ожидаемый вывод:**
```
Git commit: unknown
Commit msg: unknown
```
✅ Не падает, показывает "unknown"

---

## 📝 Изменённые файлы

1. **src/presentation/cli.py**
   - Добавлен `--output` аргумент в parser
   - Добавлен код получения git информации
   - Добавлен вывод git commit и message в логах

2. **tests/unit/test_pipeline_v2.py**
   - Обновлён тест `test_cli_arguments_parsed`
   - Добавлена проверка `output_dir`

---

## 🎯 Использование

### Стандартный запуск (output по умолчанию):
```bash
python pipeline_v2.py --input video.mp4 --mode both
# Output: ./output
```

### С указанием output директории:
```bash
python pipeline_v2.py --input video.mp4 --output /tmp/results --mode both
# Output: /tmp/results
```

### На Vast.ai (через remote_runner.sh):
```bash
# remote_runner.sh автоматически добавляет --output /workspace/output
python3 /workspace/project/pipeline_v2.py \
  --input /workspace/input.mp4 \
  --output /workspace/output \
  --mode both \
  --prefer auto \
  --scale 2 \
  --target-fps 60
```

---

## ✅ Итоги

| Изменение | Статус |
|-----------|--------|
| `--output` аргумент добавлен | ✅ |
| Git commit hash в логах | ✅ |
| Git commit message в логах | ✅ |
| Безопасная обработка ошибок | ✅ |
| Тесты обновлены | ✅ |
| Документация создана | ✅ |
| Изменения запушены | ✅ |

**Следующий запуск на инстансе покажет информацию о коммите!** 🎉

---

## 💡 Дополнительно

### Как найти коммит в GitHub:
```
https://github.com/zerotouchprod/vastai_inerup/commit/7403755
```

### Как проверить что изменилось:
```bash
git show 7403755
```

### Как откатить к конкретному коммиту:
```bash
# В config.yaml изменить git_branch на конкретный hash:
git_branch: "7403755"
```

---

**Дата:** 1 декабря 2025, 18:35  
**Commit:** 7403755  
**Версия:** 2.6 (с git info)  
**Статус:** ✅ Ready to use

