# 📡 Instance Monitoring Guide

## Быстрый старт

### Мониторить уже запущенный инстанс

```bash
# Узнать ID инстанса из вывода batch_processor.py:
# [OK] Created instance: #28397367

# Мониторить этот инстанс
python monitor.py 28397367
```

**Результат:**
```
======================================================================
📍 Monitoring Instance #28397367
======================================================================
GPU:         RTX 5060 Ti
Status:      running
State:       running
Price:       $0.0710/hr
SSH:         ssh -p 41234 root@ssh6.vast.ai
======================================================================

🔄 Streaming logs... (Ctrl+C to stop monitoring)

[15:45:30] 📊 Status: running / running
  [LOG] === Remote Runner Starting ===
  [LOG] Cloning repository...
  [LOG] Repository cloned successfully
  [LOG] Starting video processing...

[15:45:40] 🔄 Check #2...
  [LOG] Processing frame 100/1000
  [LOG] GPU usage: 95%

...

[16:10:15] 🔄 Check #150...
  [LOG] Upload complete: https://noxfvr-videos...
  [LOG] VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY

======================================================================
🎉 SUCCESS! Processing completed!
======================================================================

📥 Result URL:
   https://noxfvr-videos.s3.us-west-004.backblazeb2.com/...

Instance: #28397367
GPU:      RTX 5060 Ti
Price:    $0.0710/hr

💡 To destroy instance:
   python monitor.py 28397367 --destroy

======================================================================
Monitoring finished
======================================================================
```

---

## Основные команды

### 1. Базовый мониторинг
```bash
python monitor.py 28397367
```

### 2. С автоматическим уничтожением
```bash
python monitor.py 28397367 --auto-destroy
```
После завершения инстанс автоматически уничтожится.

### 3. Изменить интервал обновления
```bash
# Обновлять каждые 10 секунд (вместо 5)
python monitor.py 28397367 --interval 10
```

### 4. Показывать больше логов
```bash
# Запрашивать 500 строк (вместо 200)
python monitor.py 28397367 --tail 500
```

### 5. Просто уничтожить инстанс
```bash
python monitor.py 28397367 --destroy
```

---

## Сценарии использования

### Сценарий 1: Запустил batch_processor, ушёл, вернулся

```bash
# 1. Запустили обработку и увидели ID
python batch_processor.py
# [OK] Created instance: #28397367

# 2. Закрыли терминал / вышли

# 3. Вернулись через час
python monitor.py 28397367

# 4. Видим что процесс завершён, получаем URL
# 5. Уничтожаем инстанс
python monitor.py 28397367 --destroy
```

### Сценарий 2: Мониторинг с автоочисткой

```bash
# Запустить и забыть - всё само сделается
python batch_processor.py  # Уже включает мониторинг!

# Или если инстанс уже запущен:
python monitor.py 28397367 --auto-destroy
```

### Сценарий 3: Проверка статуса без мониторинга

```bash
# Старый способ (через monitor_instance.py + vast_submit)
python monitor_instance.py 28397367

# Новый способ (через monitor.py + VastAIClient)
python monitor.py 28397367
# Нажать Ctrl+C сразу после вывода заголовка
```

---

## Сравнение: Старый vs Новый

| Аспект | monitor_instance.py | monitor.py |
|--------|---------------------|------------|
| **Зависимости** | vast_submit, requests | VastAIClient, clean architecture |
| **Импорты** | Старый API | Новый infrastructure layer |
| **Логирование** | Print statements | Structured logging |
| **Извлечение URL** | Regex в коде | Метод extract_result_url() |
| **Credentials** | Вручную | .env auto-load |
| **Ошибки** | Try/except без типов | Typed exceptions |
| **Тесты** | Нет | Можно добавить |

---

## Дополнительные фичи

### SSH подключение

Из вывода monitor.py берёте SSH команду:
```bash
SSH: ssh -p 41234 root@ssh6.vast.ai
```

И подключаетесь:
```bash
ssh -p 41234 root@ssh6.vast.ai

# На инстансе:
cd /workspace/project
ls -la
tail -f /var/log/syslog
```

### Просмотр логов вручную

```bash
# Через SSH
ssh -p 41234 root@ssh6.vast.ai
docker logs <container_id>

# Или через API
python -c "
from infrastructure.vastai.client import VastAIClient
client = VastAIClient()
logs = client.get_instance_logs(28397367, tail=100)
print(logs)
"
```

---

## Горячие клавиши

| Клавиша | Действие |
|---------|----------|
| `Ctrl+C` | Остановить мониторинг (инстанс продолжит работу) |

---

## Переменные окружения

### AUTO_DESTROY
```bash
# В .env файле:
AUTO_DESTROY=1  # Автоматически уничтожать после завершения
```

Или через CLI:
```bash
python monitor.py 28397367 --auto-destroy
```

---

## Интеграция с batch_processor.py

`batch_processor.py` уже включает мониторинг!

```python
# В batch_processor.py:
result_url = self._monitor_processing(instance.id, timeout=7200)
self.vast_client.destroy_instance(instance.id)
```

Но если нужно подключиться к уже запущенному:
```bash
python monitor.py <instance_id>
```

---

## Troubleshooting

### Проблема: "get_instance_logs() method not found"

**Решение:** Метод уже добавлен в `VastAIClient`. Проверьте:
```bash
grep -n "def get_instance_logs" src/infrastructure/vastai/client.py
# Должно найти строку 291
```

### Проблема: "Instance not found"

**Причины:**
1. Инстанс уже уничтожен
2. Неправильный ID
3. API ключ невалидный

**Проверка:**
```bash
# Список активных инстансов
python -c "
from infrastructure.vastai.client import VastAIClient
client = VastAIClient()
# TODO: добавить list_instances()
"
```

### Проблема: Логи не обновляются

**Причины:**
1. Скрипт на инстансе ещё не запустился
2. Скрипт завис
3. API не возвращает логи

**Решение:**
- Увеличить `--interval` до 10-15 секунд
- Подключиться через SSH и проверить вручную
- Проверить что `/workspace/project/scripts/remote_runner.sh` существует

---

## Примеры вывода

### Успешное завершение
```
🎉 SUCCESS! Processing completed!
📥 Result URL:
   https://noxfvr-videos.s3.../qad_result.mp4
```

### Ошибка
```
⚠️  Errors detected:
  ERROR: FFmpeg encoding failed
  Exception: AssemblyError
```

### Инстанс остановлен
```
⚠️  Instance stopped (status: exited)

Final logs:
  Processing completed
  Exit code: 0
```

---

## Расширение функционала

### Добавить webhook уведомления

```python
# В monitor.py добавить:
def send_webhook(self, url: str, result_url: str):
    import requests
    requests.post(url, json={
        'instance_id': self.instance_id,
        'result_url': result_url,
        'status': 'completed'
    })
```

### Сохранить результат в JSON

```python
# В monitor.py добавить:
def save_result(self, result_url: str):
    import json
    result = {
        'instance_id': self.instance_id,
        'result_url': result_url,
        'timestamp': time.time()
    }
    with open(f'result_{self.instance_id}.json', 'w') as f:
        json.dump(result, f)
```

---

## Итоги

**Используйте monitor.py для:**
- ✅ Мониторинга уже запущенных инстансов
- ✅ Получения URL результата
- ✅ Автоматического уничтожения
- ✅ Проверки статуса

**Используйте batch_processor.py для:**
- ✅ Запуска новых задач (уже включает мониторинг)

---

**Версия:** 1.0  
**Дата:** 1 декабря 2025  
**Статус:** Production Ready ✅

