# Ручная настройка инстанса Vast AI для генерации видео

## Проблема
Docker образ `registry.gitlab.com/gfever/vastai_interup:video-gen` весит ~40GB, поэтому нужен инстанс с минимум 100GB диска.

## Решение
Нужно вручную выбрать инстанс через веб-интерфейс Vast AI с правильными параметрами.

## Шаги для ручного запуска:

### 1. Войдите на Vast AI
https://vast.ai/

### 2. Перейдите в "Create"
- Нажмите "Create" в верхнем меню

### 3. Настройте фильтры поиска:
```
GPU RAM: >= 24GB
Disk Space: >= 100GB
Price: <= $1.0/hour
Verified: Yes
Rentable: Yes
```

### 4. Выберите инстанс с параметрами:
- **GPU**: RTX 3090, RTX 4090, A100, V100 (минимум 24GB VRAM)
- **Диск**: минимум 100GB (лучше 200GB+)
- **Цена**: $0.10-$0.50/час
- **Локация**: US/EU для лучшей скорости

### 5. Настройте инстанс:
```
Image: registry.gitlab.com/gfever/vastai_interup:video-gen
Command: sleep 36000  # 10 часов для отладки
SSH: Enable
Jupyter: Optional
```

### 6. Запустите инстанс
- Нажмите "Rent"
- Подождите 20-40 минут для загрузки Docker образа

### 7. Подключитесь по SSH
После запуска:
```
ssh -p <PORT> root@<IP>
```
Пароль: обычно пустой или 'vastai'

### 8. Проверьте систему:
```bash
# Проверьте диск
df -h

# Проверьте Docker
docker ps
docker images

# Проверьте GPU
nvidia-smi
```

### 9. Запустите генерацию видео:
```bash
cd /workspace

# Тестовый запуск
python -m src.entrypoints.run_gen \
  --job '{"mode": "text2video", "prompts": ["A beautiful sunset over ocean waves"], "num_frames": 24, "fps": 8, "num_inference_steps": 25}'
```

### 10. Остановите инстанс после работы
- Вернитесь на https://vast.ai/
- Перейдите в "Instances"
- Нажмите "Stop" на вашем инстансе

## Альтернативный подход через API

Если хотите автоматизировать, используйте этот Python код для поиска инстансов с большим диском:

```python
import requests
import json

api_key = "ваш_api_ключ"
headers = {"Authorization": f"Bearer {api_key}"}

# Поиск с фильтрами
search_url = "https://console.vast.ai/api/v0/bundles/"
search_params = {
    "q": {
        "verified": {"eq": True},
        "rentable": {"eq": True},
        "gpu_ram": {"gte": 24000},  # 24GB
        "disk_space": {"gte": 100},  # 100GB
        "order": [["dph_total", "asc"]],
        "limit": 10
    }
}

response = requests.put(search_url, headers=headers, json=search_params)
print(json.dumps(response.json(), indent=2))
```

## Рекомендации по выбору инстанса:

### Лучшие варианты:
1. **RTX 4090** - 24GB VRAM, быстрая генерация
2. **RTX 3090** - 24GB VRAM, хорошая цена
3. **A100 40GB** - дороже, но быстрее
4. **V100 32GB** - хороший баланс цена/качество

### Избегайте:
- Инстансы с диском < 100GB
- Неверифицированные хосты
- Очень дешевые инстансы (могут быть медленными)

## Стоимость:
- Загрузка Docker: 20-40 мин = $0.10-$0.30
- Генерация видео: 5-15 мин = $0.05-$0.15
- **Итого**: $0.15-$0.45 за один запуск

## Мониторинг:
- Консоль Vast AI: https://vast.ai/
- SSH доступ для отладки
- Логи в реальном времени через веб-интерфейс

## Устранение проблем:

### Если диск мал:
```
Ошибка: No space left on device
Решение: Выберите инстанс с диском >= 100GB
```

### Если Docker не загружается:
```
Решение: Проверьте логи в веб-интерфейсе
         Убедитесь что образ доступен
```

### Если нет SSH доступа:
```
Решение: Включите SSH при создании инстанса
         Или используйте Jupyter доступ
```

## Контакты для помощи:
- Vast AI Support: https://vast.ai/docs/
- GitLab репозиторий: registry.gitlab.com/gfever/vastai_interup