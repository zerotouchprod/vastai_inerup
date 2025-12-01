# 🔧 Fix: Vast.ai onstart command execution error

## Дата: 1 декабря 2025, 19:15

---

## ❌ Проблема

Instance не запускается, ошибка:

```
Error response from daemon: failed to create task for container: 
failed to create shim task: OCI runtime create failed: 
runc create failed: unable to start container process: 
error during container init: 
exec: "cd /workspace && (rm -rf project || ...) && git clone ...": 
stat cd /workspace && ...: no such file or directory: unknown
```

---

## 🔍 Причина

**Vast.ai интерпретирует `onstart` как путь к исполняемому файлу**, а не как shell команду!

### Было (НЕПРАВИЛЬНО):
```python
onstart_cmd = (
    f"cd /workspace && "
    f"(rm -rf project || (sleep 2 && rm -rf project) || true) && "
    f"git clone -b {git_branch} {git_repo} project && "
    f"cd project && "
    f"bash scripts/remote_runner.sh"
)
```

Docker/runc пытается найти файл с именем `"cd /workspace && ..."` и падает с ошибкой `no such file or directory`.

---

## ✅ Решение

Обернуть команду в `/bin/bash -c '...'`:

```python
onstart_cmd = (
    f"/bin/bash -c 'cd /workspace && "
    f"(rm -rf project || (sleep 2 && rm -rf project) || true) && "
    f"git clone -b {git_branch} {git_repo} project && "
    f"cd project && "
    f"bash scripts/remote_runner.sh'"
)
```

**Теперь:**
- Vast.ai находит `/bin/bash` (существует в контейнере)
- Передаёт `-c '...'` как аргументы
- Bash выполняет команды внутри строки

---

## 📋 Что делает onstart команда

1. **`cd /workspace`** - переходим в рабочую директорию
2. **`(rm -rf project || ...)`** - удаляем старый project (с retry)
3. **`git clone -b {branch} {repo} project`** - клонируем нужную ветку
4. **`cd project`** - переходим в project
5. **`bash scripts/remote_runner.sh`** - запускаем runner

---

## 🔄 Ветка из конфига

Теперь ветка берётся из `config.yaml`:

```yaml
git_branch: "oop2"  # или "main", "dev", etc.
```

Это позволяет тестировать новый код без пересборки Docker образа!

---

## ✅ Результат после исправления

**Ожидаемые логи при старте инстанса:**

```
Cloning into 'project'...
remote: Enumerating objects: ...
remote: Counting objects: 100% ...
Receiving objects: 100% ...
Resolving deltas: 100% ...
=== Remote Runner Starting ===
Time: Sun Dec  1 19:XX:XX UTC 2025
[remote_runner] Checking external/RIFE...
[remote_runner] RIFE directory exists but RIFE_HDv3.py missing - re-cloning
[remote_runner] Cloning RIFE...
[remote_runner] ✓ RIFE_HDv3.py confirmed present
...
[17:XX:XX] [presentation.cli] [INFO] Git commit: 31dd3b0  ✅
```

---

## 📝 Связанные изменения

### Commits:
- `7a7f55b` - Stop instead of destroy
- `31dd3b0` - Fix onstart command (этот фикс)

### Файлы:
- `batch_processor.py` - исправлен onstart
- `src/infrastructure/vastai/client.py` - добавлен stop_instance()

---

## 🚀 Что дальше

После этого фикса:
1. ✅ Инстанс успешно запустится
2. ✅ Склонирует ветку `oop2` 
3. ✅ Перезаклонирует external/RIFE с проверкой
4. ✅ Pipeline запустится с новым кодом

**Теперь можно запускать `batch_processor.py` и всё должно работать!** 🎉

---

**Дата:** 1 декабря 2025, 19:16  
**Commit:** 31dd3b0  
**Статус:** ✅ Fixed & Pushed  
**Следующий шаг:** Запустить batch_processor.py для тестирования

