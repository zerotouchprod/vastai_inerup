#!/bin/bash
# Финальное решение для запуска пайплайна на Vast AI

set -e

echo "================================================================"
echo "🎬 ФИНАЛЬНОЕ РЕШЕНИЕ ДЛЯ ЗАПУСКА НА Vast AI"
echo "================================================================"

# Проверка API ключа
if [ -z "$VAST_API_KEY" ]; then
    echo "❌ Ошибка: VAST_API_KEY не установлен"
    echo "   export VAST_API_KEY='ваш_ключ'"
    exit 1
fi

echo "✅ API ключ установлен"

# 1. ОСТАНОВИТЬ ВСЕ СУЩЕСТВУЮЩИЕ ИНСТАНСЫ
echo ""
echo "1. 🔍 Проверка существующих инстансов..."
python -c "
import requests
import os
api_key = os.environ.get('VAST_API_KEY')
headers = {'Authorization': f'Bearer {api_key}'}
url = 'https://console.vast.ai/api/v0/instances/'
try:
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        data = response.json()
        instances = data.get('instances', [])
        print(f'Найдено инстансов: {len(instances)}')
        
        for instance in instances:
            instance_id = instance.get('id')
            status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
            price = instance.get('dph_total', 0)
            print(f'  Инстанс {instance_id}: статус={status}, цена=\${price:.3f}/час')
            
            # Останавливаем если running/loading
            if status in ['running', 'loading', 'starting']:
                stop_url = f'https://console.vast.ai/api/v0/instances/{instance_id}/'
                requests.put(stop_url, headers=headers, json={'state': 'stopped'}, timeout=30)
                print(f'    ⛔ Остановлен')
    else:
        print(f'Ошибка: {response.status_code}')
except Exception as e:
    print(f'Ошибка: {e}')
"

# 2. ПОИСК ОФФЕРОВ С ПРАВИЛЬНЫМИ ПАРАМЕТРАМИ
echo ""
echo "2. 🔍 Поиск офферов с минимум 16GB VRAM (для начала)..."
python vast/vast_submit.py --list-offers --min-vram 16 --max-price 0.8 --list-count 5

# 3. ЗАПУСК ИНСТАНСА ДЛЯ ОТЛАДКИ
echo ""
echo "3. 🚀 Запуск инстанса для отладки..."
echo ""
echo "⚠️  ВАЖНО: Docker образ 40GB, нужно минимум 100GB диска"
echo "   Но vast_submit.py не позволяет указать размер диска"
echo "   Поэтому:"
echo "   1. Сначала запустим тестовый инстанс"
echo "   2. Проверим размер диска"
echo "   3. Если диск мал - остановим и найдем другой"
echo ""

read -p "Продолжить? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено"
    exit 0
fi

# Запускаем тестовый инстанс
echo "⏳ Запуск тестового инстанса..."
TEST_INSTANCE_ID=$(python vast/vast_submit.py --image "registry.gitlab.com/gfever/vastai_interup:video-gen" --cmd "df -h && echo 'Disk check complete'" --min-vram 16 --max-price 0.5 --wait-running 2>&1 | grep -o "instance id: [0-9]*" | tail -1 | awk '{print $3}')

if [ -z "$TEST_INSTANCE_ID" ]; then
    TEST_INSTANCE_ID=$(python vast/vast_submit.py --image "registry.gitlab.com/gfever/vastai_interup:video-gen" --cmd "df -h && echo 'Disk check complete'" --min-vram 16 --max-price 0.5 --wait-running 2>&1 | grep -o "new_contract: [0-9]*" | tail -1 | awk '{print $2}')
fi

if [ -z "$TEST_INSTANCE_ID" ]; then
    echo "❌ Не удалось получить ID инстанса"
    exit 1
fi

echo "✅ Тестовый инстанс создан: ID=$TEST_INSTANCE_ID"

# 4. ПРОВЕРКА ДИСКА
echo ""
echo "4. 💾 Ожидание проверки диска (30 секунд)..."
sleep 30

echo "🔍 Проверка информации о диске..."
python -c "
import requests
import os
import time

api_key = os.environ.get('VAST_API_KEY')
headers = {'Authorization': f'Bearer {api_key}'}
instance_id = $TEST_INSTANCE_ID

# Ждем пока инстанс запустится
for i in range(10):
    url = f'https://console.vast.ai/api/v0/instances/{instance_id}/'
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            instance = data.get('instances', {})
            status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
            disk_space = instance.get('disk_space', 0)
            disk_name = instance.get('disk_name', 'N/A')
            
            print(f'Проверка {i+1}: статус={status}, диск={disk_space}GB ({disk_name})')
            
            if disk_space >= 100:
                print('✅ Диск достаточного размера!')
                print(f'   Можно использовать для генерации видео')
                break
            elif disk_space >= 80:
                print('⚠️  Диск минимального размера')
                print(f'   Может быть недостаточно для 40GB Docker образа')
                break
            else:
                print('❌ Диск слишком мал!')
                print(f'   Нужно минимум 100GB, текущий: {disk_space}GB')
                print(f'   Останавливаем инстанс...')
                
                # Останавливаем инстанс
                stop_url = f'https://console.vast.ai/api/v0/instances/{instance_id}/'
                requests.put(stop_url, headers=headers, json={'state': 'stopped'}, timeout=30)
                print(f'   Инстанс остановлен')
                break
        else:
            print(f'Ошибка API: {response.status_code}')
    except Exception as e:
        print(f'Ошибка: {e}')
    
    time.sleep(10)
"

# 5. ИНСТРУКЦИИ ДЛЯ РУЧНОГО ЗАПУСКА
echo ""
echo "================================================================"
echo "📋 ИНСТРУКЦИИ ДЛЯ РУЧНОГО ЗАПУСКА НА Vast AI"
echo "================================================================"
echo ""
echo "ПРОБЛЕМА: vast_submit.py не позволяет указать размер диска"
echo "РЕШЕНИЕ: Запустить инстанс вручную через веб-интерфейс"
echo ""
echo "ШАГИ:"
echo "1. Откройте https://vast.ai/"
echo "2. Нажмите 'Create'"
echo "3. Установите фильтры:"
echo "   - GPU RAM: >= 24GB"
echo "   - Disk Space: >= 100GB"
echo "   - Price: <= $1.0/hour"
echo "   - Verified: Yes"
echo "4. Выберите инстанс с:"
echo "   - RTX 3090/4090, A100, V100 (24GB+ VRAM)"
echo "   - Диск 100GB+ (лучше 200GB+)"
echo "5. Настройте:"
echo "   - Image: registry.gitlab.com/gfever/vastai_interup:video-gen"
echo "   - Command: sleep 36000  # 10 часов для отладки"
echo "   - SSH: Enable"
echo "6. Нажмите 'Rent'"
echo "7. Ждите 20-40 минут загрузки Docker образа"
echo "8. Подключитесь по SSH:"
echo "   ssh -p <PORT> root@<IP>"
echo "9. Запустите генерацию:"
echo "   cd /workspace"
echo "   python -m src.entrypoints.run_gen \\"
echo "     --job '{\"mode\": \"text2video\", \"prompts\": [\"your prompt\"]}'"
echo "10. Остановите инстанс после работы"
echo ""
echo "💰 СТОИМОСТЬ:"
echo "   - Загрузка Docker: 20-40 мин = \$0.10-\$0.30"
echo "   - Генерация видео: 5-15 мин = \$0.05-\$0.15"
echo "   - ИТОГО: \$0.15-\$0.45"
echo ""
echo "🔗 ДОПОЛНИТЕЛЬНО:"
echo "   - manual_vastai_setup.md - полная инструкция"
echo "   - run_video_gen_vastai.py - скрипт для запуска"
echo "   - https://vast.ai/ - консоль управления"
echo ""

# 6. АЛЬТЕРНАТИВНЫЙ ВАРИАНТ
echo ""
echo "================================================================"
echo "🔄 АЛЬТЕРНАТИВНЫЙ ВАРИАНТ: Запуск через vast_submit.py"
echo "================================================================"
echo ""
echo "Если хотите рискнуть с диском 10GB:"
echo ""
echo "python vast/vast_submit.py \\"
echo "  --image 'registry.gitlab.com/gfever/vastai_interup:video-gen' \\"
echo "  --cmd 'python -m src.entrypoints.run_gen --job \"{\\\"mode\\\": \\\"text2video\\\", \\\"prompts\\\": [\\\"test\\\"]}\"' \\"
echo "  --min-vram 16 \\"
echo "  --max-price 0.5 \\"
echo "  --wait-running \\"
echo "  --max-hours 1"
echo ""
echo "⚠️  ПРЕДУПРЕЖДЕНИЕ:"
echo "   - Docker образ 40GB"
echo "   - Диск инстанса 10GB"
echo "   - Вероятность ошибки 'No space left on device': 99%"
echo ""

exit 0