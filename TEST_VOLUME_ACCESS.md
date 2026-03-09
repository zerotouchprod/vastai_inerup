# 🔍 Тест доступа к Network Volume

## Проблема:
Pod запускается, но загружает образ (это нормально при первом запуске). Нужно проверить, доступны ли модели на Network Volume.

## Команды для проверки (через Web Terminal):

### 1. Откройте Web Terminal для pod `video-gen-test-final`:
- Перейдите в [RunPod Console](https://www.runpod.io/console/pods)
- Найдите pod `video-gen-test-final`
- Нажмите "Connect" → "Launch Web Terminal"

### 2. В Web Terminal выполните:

```bash
# Проверьте, смонтирован ли Network Volume
ls -la /runpod-volume/
ls -la /runpod-volume/models/

# Проверьте DreamShaper
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/

# Проверьте CogVideoX
ls -lh /runpod-volume/models/CogVideoX-5b-I2V/ | head -10

# Проверьте entrypoint логи
cat /tmp/entrypoint.log 2>/dev/null || echo "Логи entrypoint не найдены"

# Запустите проверку вручную
cd /app
python3 -c "
import os
import sys

print('=== Проверка моделей на Network Volume ===')
print(f'Текущая директория: {os.getcwd()}')

t2i_path = '/runpod-volume/models/dreamshaper-xl-lightning/sdxl_lightning_4step_unet.safetensors'
i2v_dir = '/runpod-volume/models/CogVideoX-5b-I2V'

print(f'\\n1. DreamShaper: {t2i_path}')
if os.path.exists(t2i_path):
    size = os.path.getsize(t2i_path)
    print(f'   ✅ Найден! Размер: {size / (1024**3):.2f} GB')
else:
    print(f'   ❌ Не найден!')
    print(f'   Содержимое директории:')
    dir_path = os.path.dirname(t2i_path)
    if os.path.exists(dir_path):
        for f in os.listdir(dir_path):
            print(f'   - {f}')

print(f'\\n2. CogVideoX: {i2v_dir}')
if os.path.exists(i2v_dir):
    files = [f for f in os.listdir(i2v_dir) if os.path.isfile(os.path.join(i2v_dir, f))]
    dirs = [d for d in os.listdir(i2v_dir) if os.path.isdir(os.path.join(i2v_dir, d))]
    print(f'   ✅ Найден!')
    print(f'   Файлов: {len(files)}')
    print(f'   Директорий: {len(dirs)}')
    if dirs:
        print(f'   Директории: {dirs[:5]}' + ('...' if len(dirs) > 5 else ''))
else:
    print(f'   ❌ Не найден!')

print(f'\\n3. Network Volume доступен?')
volume_root = '/runpod-volume'
if os.path.exists(volume_root):
    print(f'   ✅ {volume_root} существует')
    print(f'   Содержимое: {os.listdir(volume_root)}')
else:
    print(f'   ❌ {volume_root} не существует')
"
```

### 3. Если модели не найдены, проверьте монтирование:

```bash
# Проверьте точки монтирования
mount | grep runpod-volume
df -h | grep runpod-volume

# Проверьте права доступа
ls -la /runpod-volume/
stat /runpod-volume/models/
```

### 4. Если Network Volume не смонтирован:
```bash
# Попробуйте смонтировать вручную (если возможно)
mkdir -p /mnt/test-volume
mount -t nfs или другая команда монтирования
```

## Возможные проблемы и решения:

### 1. **Network Volume не смонтирован**:
- Проверьте настройки pod в RunPod Console
- Убедитесь, что Network Volume ID правильный: `gwmcixcs3e`
- Перезапустите pod

### 2. **Модели в другой директории**:
```bash
# Поиск моделей
find /runpod-volume -name "*.safetensors" -type f 2>/dev/null
find /runpod-volume -name "CogVideoX*" -type d 2>/dev/null
```

### 3. **Права доступа**:
```bash
# Измените права (если нужно)
chmod -R 755 /runpod-volume/models/
```

## После исправления:
1. Entrypoint должен найти модели
2. Handler запустится автоматически
3. API будет доступен на порту 8000

**Выполните проверку через Web Terminal и сообщите результаты.** 🔧