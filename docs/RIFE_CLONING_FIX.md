# 🔧 Fix: RIFE external repo cloning

## Проблема

**Git commit в логах устарел!**
```
[17:54:03] [presentation.cli] [INFO] Git commit: f8a2379  ❌ старый!
```

Должен быть: `511ca27` (или новее)

**RIFE не клонируется при рестарте:**
```
[17:54:07] [ERROR] RIFE_HDv3.py not found. Searched: ['/workspace/project/external/RIFE', ...]
```

---

## Причины

### 1. Код не обновился на инстансе
Инстанс использует старый код (`f8a2379`), не видит новые исправления (`511ca27`, `d992f0f`)

**Решение:** Нужен рестарт инстанса чтобы Git подтянул свежий код

### 2. Логика проверки RIFE была неправильной
**Было (commit 511ca27):**
```bash
if [ ! -d "/workspace/project/external/RIFE" ] || [ ! -f "/workspace/project/external/RIFE/RIFE_HDv3.py" ]; then
  echo "[remote_runner] Cloning RIFE..."
  # ...
else
  echo "[remote_runner] RIFE already cloned and valid"  # ❌ Этого не было в логах!
fi
```

Проблема: директория `/workspace/project/external/RIFE` **существует**, но **пустая или битая**. Bash проверка `[ ! -f "..." ]` не выводит никаких логов.

---

## Исправления

### Commit d992f0f: Улучшенная логика + отладочные логи

```bash
echo "[remote_runner] Checking external/RIFE..."
if [ -d "/workspace/project/external/RIFE" ]; then
  if [ -f "/workspace/project/external/RIFE/RIFE_HDv3.py" ]; then
    echo "[remote_runner] RIFE already cloned and valid (RIFE_HDv3.py present)"
  else
    echo "[remote_runner] RIFE directory exists but RIFE_HDv3.py missing - re-cloning"  # ← NEW
    rm -rf /workspace/project/external/RIFE
    mkdir -p /workspace/project/external
    git clone --depth 1 https://github.com/hzwer/arXiv2020-RIFE.git /workspace/project/external/RIFE
    # ... copy models ...
  fi
else
  echo "[remote_runner] Cloning RIFE..."
  # ... clone ...
fi

# Verify after clone
if [ -f "/workspace/project/external/RIFE/RIFE_HDv3.py" ]; then
  echo "[remote_runner] ✓ RIFE_HDv3.py confirmed present"  # ← NEW
else
  echo "[remote_runner] ✗ ERROR: RIFE_HDv3.py still missing after clone!"  # ← NEW
  echo "[remote_runner] Listing /workspace/project/external/RIFE:"
  ls -la /workspace/project/external/RIFE/ 2>/dev/null || echo "Directory not found"
fi
```

**Улучшения:**
- ✅ Проверка идёт **до** клонирования
- ✅ Логи на каждый случай (directory exists, missing, valid)
- ✅ Финальная верификация после клонирования
- ✅ Debug listing если что-то не так

---

## Как проверить после рестарта

### Ожидаемые логи:

```
=== Remote Runner Starting ===
Time: Sun Dec  1 19:XX:XX UTC 2025
...
[remote_runner] Checking external/RIFE...
[remote_runner] RIFE directory exists but RIFE_HDv3.py missing - re-cloning
[remote_runner] Cloning RIFE...
Cloning into '/workspace/project/external/RIFE'...
[remote_runner] Copying preinstalled RIFE models to RIFE repo...
[remote_runner] Models copied successfully (1 .pkl files)
[remote_runner] ✓ RIFE_HDv3.py confirmed present  ← ЭТО КЛЮЧЕВОЕ!
```

### Проверка Git commit:
```
[17:XX:XX] [presentation.cli] [INFO] Git commit: d992f0f  ✅ новый!
[17:XX:XX] [presentation.cli] [INFO] Commit msg: Add debug logging for RIFE cloning...
```

### Проверка загрузки модели:
```
[17:XX:XX] [RIFENativeWrapper] [INFO] Loading RIFE model from RIFEv4.26_0921
[17:XX:XX] [RIFENativeWrapper] [INFO] Added /workspace/project/external/RIFE to sys.path
[17:XX:XX] [RIFENativeWrapper] [INFO] RIFE model loaded successfully  ✅
[17:XX:XX] [RIFENativeWrapper] [INFO] Processing 145 frames
```

---

## Что делать сейчас

### 1. Перезапустить инстанс
Инстанс нужно **остановить и запустить заново** (не рестарт контейнера!)

**Через batch_processor.py:**
```python
# Он сам остановит после таймаута
# Или вручную через Vast.ai:
vastai destroy instance <ID>
```

### 2. Запустить новую обработку
```bash
python batch_processor.py
```

Новый инстанс подтянет свежий код (commit `d992f0f`) и заработает!

---

## Timeline исправлений

| Commit | Дата | Что исправлено |
|--------|------|----------------|
| `f8a2379` | Dec 1, 18:46 | Fix RIFE import path |
| `511ca27` | Dec 1, 18:51 | Force re-clone if files missing |
| `d992f0f` | Dec 1, 19:00 | **Add debug logs + improve logic** |

---

## Итоги

✅ **Исправлено:**
- Native RIFE import path (`external/RIFE` в `sys.path`)
- Проверка наличия `RIFE_HDv3.py` перед клонированием
- Отладочные логи для диагностики

⏳ **Требуется:**
- Рестарт инстанса для подтягивания нового кода

🎯 **Ожидается:**
- Git commit: `d992f0f`
- RIFE клонируется успешно
- `RIFE_HDv3.py confirmed present`
- Pipeline успешно запускается

---

**Дата:** 1 декабря 2025, 19:01  
**Текущий commit:** d992f0f  
**Статус:** ✅ Pushed, ⏳ Awaiting instance restart

