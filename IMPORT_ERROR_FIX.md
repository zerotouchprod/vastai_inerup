# 🔧 Исправление ImportError - 1 декабря 2025, 18:20

## Проблема

```
ImportError: cannot import name 'TempStorage' from 'infrastructure.storage'
```

Pipeline_v2.py не мог запуститься на инстансе из-за отсутствующих импортов.

---

## Решение

### 1. Удалены несуществующие импорты

**Файл:** `src/presentation/cli.py`

**Было:**
```python
from infrastructure.storage import TempStorage, PendingMarker
```

**Стало:**
```python
# Импорты удалены - эти классы не существуют в новой архитектуре
```

---

### 2. Заменён TempStorage на tempfile

**Файл:** `src/application/orchestrator.py`

**Было:**
```python
workspace = self._temp_storage.create_workspace(job.job_id)
# ... 
self._temp_storage.cleanup(workspace, keep_on_error=False)
```

**Стало:**
```python
import tempfile
import shutil

workspace = Path(tempfile.mkdtemp(prefix=f"job_{job.job_id}_"))
# ...
if workspace and workspace.exists():
    shutil.rmtree(workspace, ignore_errors=True)
```

---

### 3. Убран PendingMarker из B2S3Uploader

**Файл:** `src/presentation/cli.py`

**Было:**
```python
uploader = B2S3Uploader(
    ...
    pending_marker=PendingMarker()
)
```

**Стало:**
```python
uploader = B2S3Uploader(
    bucket=config.b2_bucket,
    endpoint=config.b2_endpoint,
    access_key=config.b2_key,
    secret_key=config.b2_secret
)
```

---

### 4. Упрощён DummyUploader

**Было:**
```python
class DummyUploader:
    def upload(...):
        ...
    def resume_pending(self):
        return []
```

**Стало:**
```python
class DummyUploader:
    def upload(self, file_path, key):
        return UploadResult(
            success=True, 
            url=f"file://{file_path}", 
            bucket="local", 
            key=key, 
            size_bytes=0
        )
```

---

## ✅ Изменённые файлы

1. `src/presentation/cli.py` - удалены импорты, убран PendingMarker
2. `src/application/orchestrator.py` - заменён TempStorage на tempfile

---

## 🧪 Тестирование

Теперь pipeline_v2.py должен запуститься на инстансе:

```bash
python3 /workspace/project/pipeline_v2.py --input /workspace/input.mp4 --output /workspace/output --mode both
```

**Ожидаемый результат:**
- ✅ Нет ImportError
- ✅ Временные директории создаются через tempfile
- ✅ Cleanup работает через shutil.rmtree
- ✅ Pipeline выполняется успешно

---

## 📝 Почему TempStorage удалён

В новой архитектуре:
- **Нет отдельного слоя для temp storage**
- **Python встроенный `tempfile` делает всё что нужно**
- **Не нужен PendingMarker** - за загрузку отвечает B2Client

---

## 🎯 Следующие шаги

1. **Закоммитить изменения**
2. **Запушить в git**
3. **Перезапустить инстанс** (новый код подтянется автоматически)
4. **Проверить что pipeline запускается**

---

**Дата:** 1 декабря 2025, 18:20  
**Версия:** 2.4 (исправлен ImportError)  
**Статус:** ✅ Готово к тестированию

