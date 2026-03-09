то падает с ошиькой#!/bin/bash
# Скрипт для быстрой загрузки моделей через Web Terminal RunPod

echo "=========================================="
echo "RunPod Model Upload Script"
echo "=========================================="
echo ""

# 1. Проверка зависимостей
echo "🔍 Проверяю зависимости..."
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден"
    exit 1
fi

# 2. Установка huggingface_hub
echo "📦 Устанавливаю huggingface_hub..."
pip install huggingface_hub -q

# 3. Создание директорий
echo "📁 Создаю директории для моделей..."
mkdir -p /runpod-volume/models/dreamshaper-xl-lightning
mkdir -p /runpod-volume/models/CogVideoX-5b-I2V

# 4. Загрузка DreamShaper
echo "📥 Загружаю DreamShaper XL Lightning (~2GB)..."
cd /runpod-volume/models/dreamshaper-xl-lightning

python3 -c "
import os
import sys
from huggingface_hub import hf_hub_download

print('Начинаю загрузку DreamShaper...')
try:
    hf_hub_download(
        repo_id='ByteDance/SDXL-Lightning',
        filename='sdxl_lightning_4step_unet.safetensors',
        local_dir='.',
        local_dir_use_symlinks=False,
        resume_download=True
    )
    
    if os.path.exists('sdxl_lightning_4step_unet.safetensors'):
        size = os.path.getsize('sdxl_lightning_4step_unet.safetensors')
        print(f'✅ DreamShaper загружен!')
        print(f'   Размер: {size / (1024**3):.2f} GB')
        print(f'   Путь: {os.path.abspath(\"sdxl_lightning_4step_unet.safetensors\")}')
    else:
        print('❌ Ошибка: файл не найден после загрузки')
        sys.exit(1)
        
except Exception as e:
    print(f'❌ Ошибка загрузки: {e}')
    sys.exit(1)
"

# 5. Загрузка CogVideoX (в фоне)
echo "📥 Загружаю CogVideoX-5b-I2V (~15GB, в фоне)..."
cd /runpod-volume/models/CogVideoX-5b-I2V

python3 -c "
import os
import sys
import time
from huggingface_hub import snapshot_download

print('Начинаю загрузку CogVideoX...')
print('Это займет 30-60 минут...')

try:
    start_time = time.time()
    
    snapshot_download(
        repo_id='THUDM/CogVideoX-5b',
        local_dir='.',
        local_dir_use_symlinks=False,
        ignore_patterns=['*.bin', '*.msgpack', '*.h5', '*.ot'],
        resume_download=True
    )
    
    download_time = time.time() - start_time
    files = [f for f in os.listdir('.') if os.path.isfile(f)]
    total_size = sum(os.path.getsize(f) for f in files)
    
    print('✅ CogVideoX загружен!')
    print(f'   Файлов: {len(files)}')
    print(f'   Общий размер: {total_size / (1024**3):.2f} GB')
    print(f'   Время загрузки: {download_time/60:.1f} минут')
    
except Exception as e:
    print(f'❌ Ошибка загрузки: {e}')
    sys.exit(1)
" > /tmp/cogvideo_download.log 2>&1 &

echo "📊 Мониторинг загрузки CogVideoX:"
echo "   tail -f /tmp/cogvideo_download.log"
echo ""

# 6. Проверка
echo "=========================================="
echo "Проверка загрузки:"
echo "=========================================="
echo "DreamShaper:"
ls -lh /runpod-volume/models/dreamshaper-xl-lightning/ 2>/dev/null || echo "   Директория не существует"
echo ""
echo "CogVideoX (прогресс):"
ls -la /runpod-volume/models/CogVideoX-5b-I2V/ 2>/dev/null | wc -l | xargs echo "   Файлов:"
du -sh /runpod-volume/models/CogVideoX-5b-I2V/ 2>/dev/null || echo "   Директория не существует"
echo ""
echo "Общий размер:"
du -sh /runpod-volume/models/ 2>/dev/null || echo "   Директория не существует"
echo ""
echo "=========================================="
echo "✅ Скрипт запущен!"
echo "   DreamShaper загружается сейчас"
echo "   CogVideoX загружается в фоне"
echo "   Проверяйте прогресс: tail -f /tmp/cogvideo_download.log"
echo "=========================================="