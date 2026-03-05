#!/bin/bash
# Стартовый скрипт для рабочего процесса Vast AI

set -e

echo "================================================================"
echo "🚀 СТАРТ РАБОЧЕГО ПРОЦЕССА Vast AI"
echo "================================================================"

# Проверка API ключа
if [ -z "$VAST_API_KEY" ]; then
    echo "❌ Ошибка: VAST_API_KEY не установлен"
    echo "   export VAST_API_KEY='2dcd17021ab5f1613be725d63df1013292a0318238fa0a4547574209bf098600'"
    exit 1
fi

echo "✅ API ключ установлен"

# 1. Очистка существующих инстансов
echo ""
echo "1. 🧹 ОЧИСТКА СУЩЕСТВУЮЩИХ ИНСТАНСОВ"
echo "================================================================"

python3 -c "
import requests
import os

api_key = os.environ.get('VAST_API_KEY')
headers = {'Authorization': f'Bearer {api_key}'}
url = 'https://console.vast.ai/api/v0/instances/'

print('🔍 Проверка инстансов...')
try:
    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 200:
        data = response.json()
        instances = data.get('instances', [])
        
        print(f'Найдено инстансов: {len(instances)}')
        
        stopped_count = 0
        for instance in instances:
            instance_id = instance.get('id')
            status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
            disk_gb = instance.get('disk_space', 0)
            
            print(f'  Инстанс {instance_id}: статус={status}, диск={disk_gb}GB')
            
            # Останавливаем если активен
            if status in ['running', 'loading', 'starting']:
                print(f'    ⚠️  Останавливаем...')
                stop_url = f'https://console.vast.ai/api/v0/instances/{instance_id}/'
                requests.put(stop_url, headers=headers, json={'state': 'stopped'}, timeout=30)
                stopped_count += 1
        
        if stopped_count > 0:
            print(f'✅ Остановлено инстансов: {stopped_count}')
        else:
            print(f'✅ Нет активных инстансов')
            
    else:
        print(f'❌ Ошибка: {response.status_code}')
        
except Exception as e:
    print(f'❌ Ошибка: {e}')
"

# 2. Запуск мониторинга
echo ""
echo "2. 🔍 ЗАПУСК МОНИТОРИНГА"
echo "================================================================"

# Создаем скрипт мониторинга
cat > /tmp/vastai_auto_monitor.py << 'EOF'
#!/usr/bin/env python3
"""
Автоматический мониторинг инстансов Vast AI.
Останавливает инстансы с диском < 100GB.
"""

import os
import requests
import time
import sys

api_key = os.environ.get('VAST_API_KEY')
if not api_key:
    print("❌ VAST_API_KEY не установлен")
    sys.exit(1)

headers = {"Authorization": f"Bearer {api_key}"}
base_url = "https://console.vast.ai/api/v0"

print("🔍 Автоматический мониторинг запущен")
print("   Проверка каждые 3 минуты")
print("   Остановка инстансов с диском < 100GB")
print("   Нажмите Ctrl+C для остановки")

check_count = 0

try:
    while True:
        check_count += 1
        current_time = time.strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n📊 Проверка #{check_count} - {current_time}")
        print("-" * 60)
        
        # Получаем все инстансы
        url = f"{base_url}/instances/"
        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                instances = data.get('instances', [])
                
                print(f"Найдено инстансов: {len(instances)}")
                
                if instances:
                    total_cost = 0
                    stopped_count = 0
                    
                    for instance in instances:
                        instance_id = instance.get('id')
                        status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                        disk_gb = instance.get('disk_space', 0)
                        price = instance.get('dph_total', 0)
                        
                        total_cost += price
                        
                        # Проверяем диск
                        if disk_gb < 100 and status in ['running', 'loading', 'starting']:
                            print(f"  ❌ Инстанс {instance_id}: диск {disk_gb}GB < 100GB")
                            print(f"     ⚠️  Останавливаем...")
                            
                            stop_url = f"{base_url}/instances/{instance_id}/"
                            try:
                                stop_response = requests.put(stop_url, headers=headers, json={"state": "stopped"}, timeout=30)
                                if stop_response.status_code == 200:
                                    print(f"     ✅ Остановлен")
                                    stopped_count += 1
                                else:
                                    print(f"     ❌ Ошибка остановки")
                            except Exception as e:
                                print(f"     ❌ Ошибка: {e}")
                    
                    print(f"\n📈 Статистика:")
                    print(f"  Всего инстансов: {len(instances)}")
                    print(f"  Остановлено: {stopped_count}")
                    print(f"  Общая стоимость/час: ${total_cost:.3f}")
                    
                    # Если есть активные инстансы
                    active_instances = [i for i in instances if i.get('actual_status') in ['running', 'loading', 'starting']]
                    if active_instances:
                        print(f"\n🎯 Активные инстансы:")
                        for instance in active_instances:
                            disk = instance.get('disk_space', 0)
                            status = instance.get('actual_status')
                            price = instance.get('dph_total', 0)
                            print(f"  - {instance.get('id')}: {status}, ${price:.3f}/час, {disk}GB диск")
                else:
                    print("ℹ️  Нет активных инстансов")
                    
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
        
        # Ждем 3 минуты
        print(f"\n⏳ Следующая проверка через 3 минуты...")
        print("=" * 60)
        time.sleep(180)
        
except KeyboardInterrupt:
    print(f"\n\n⏹️  Мониторинг остановлен пользователем")
    print(f"Всего проверок: {check_count}")

EOF

# Запускаем мониторинг в фоне
echo "🚀 Запуск автоматического мониторинга..."
python3 /tmp/vastai_auto_monitor.py &
MONITOR_PID=$!
echo "✅ Мониторинг запущен (PID: $MONITOR_PID)"
echo "   Останавливает инстансы с диском < 100GB каждые 3 минуты"

# 3. Инструкции для запуска
echo ""
echo "3. 📋 ИНСТРУКЦИИ ДЛЯ ЗАПУСКА ПАЙПЛАЙНА"
echo "================================================================"
echo ""
echo "🎯 ЦЕЛЬ: Запустить пайплайн text2image image2video"
echo "📁 Образ: registry.gitlab.com/gfever/vastai_interup:video-gen"
echo "💾 Требования: диск >= 100GB (Docker образ 40GB)"
echo ""
echo "🔧 ДВА ВАРИАНТА ЗАПУСКА:"
echo ""
echo "ВАРИАНТ 1: РУЧНОЙ ЧЕРЕЗ ВЕБ-ИНТЕРФЕЙС (РЕКОМЕНДУЕТСЯ)"
echo "--------------------------------------------------------"
echo "1. Откройте https://vast.ai/"
echo "2. Нажмите 'Create'"
echo "3. Установите фильтры:"
echo "   • GPU RAM: >= 24GB"
echo "   • Disk Space: >= 100GB"
echo "   • Price: <= $1.0/hour"
echo "   • Verified: Yes"
echo "4. Выберите инстанс с диском 100GB+"
echo "5. Настройте:"
echo "   • Image: registry.gitlab.com/gfever/vastai_interup:video-gen"
echo "   • Command: sleep 36000  # 10 часов для отладки"
echo "   • SSH: Enable"
echo "6. Нажмите 'Rent'"
echo "7. Ждите 20-40 минут загрузки Docker образа"
echo "8. Подключитесь по SSH и запустите генерацию"
echo ""
echo "ВАРИАНТ 2: ЧЕРЕЗ API (ЭКСПЕРИМЕНТАЛЬНЫЙ)"
echo "--------------------------------------------------------"
echo "1. Запустите: python final_vastai_launch_fixed.py"
echo "2. Скрипт попробует использовать allocated_storage=100"
echo "3. Но может не сработать (API ограничения)"
echo ""
echo "🎬 ЗАПУСК ГЕНЕРАЦИИ ПОСЛЕ ПОДКЛЮЧЕНИЯ:"
echo "--------------------------------------------------------"
echo "ssh -p <PORT> root@<IP>"
echo "cd /workspace"
echo "python -m src.entrypoints.run_gen \\"
echo "  --job '{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"],"
echo "         \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}'"
echo ""
echo "💰 СТОИМОСТЬ:"
echo "--------------------------------------------------------"
echo "• Загрузка Docker: 20-40 мин = \$0.10-\$0.30"
echo "• Генерация видео: 5-15 мин = \$0.05-\$0.15"
echo "• ИТОГО: \$0.15-\$0.45 за запуск"
echo ""

# 4. Управление
echo ""
echo "4. ⚙️  УПРАВЛЕНИЕ"
echo "================================================================"
echo ""
echo "МОНИТОРИНГ:"
echo "  PID: $MONITOR_PID"
echo "  Проверяет каждые 3 минуты"
echo "  Останавливает инстансы с диском < 100GB"
echo ""
echo "КОМАНДЫ:"
echo "  • Проверить мониторинг: ps aux | grep $MONITOR_PID"
echo "  • Остановить мониторинг: kill $MONITOR_PID"
echo "  • Проверить инстансы: python vastai_monitor.py"
echo "  • Запустить через API: python final_vastai_launch_fixed.py"
echo ""
echo "ФАЙЛЫ:"
echo "  • manual_vastai_setup.md - полная инструкция"
echo "  • vastai_monitor.py - скрипт мониторинга"
echo "  • final_vastai_launch_fixed.py - запуск через API"
echo "  • src/entrypoints/run_gen.py - пайплайн генерации"
echo ""

# 5. Запуск тестового варианта
echo ""
echo "5. 🧪 ТЕСТОВЫЙ ЗАПУСК"
echo "================================================================"
echo ""
echo "Хотите попробовать запустить через API? (может не сработать)"
read -p "Попробовать? (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Запуск тестового варианта..."
    python3 final_vastai_launch_fixed.py
else
    echo "ℹ️  Тестовый запуск пропущен"
    echo "   Используйте ручной вариант через веб-интерфейс"
fi

echo ""
echo "================================================================"
echo "🎯 РАБОЧИЙ ПРОЦЕСС НАСТРОЕН"
echo "================================================================"
echo ""
echo "✅ Автоматический мониторинг запущен"
echo "✅ Инструкции для ручного запуска готовы"
echo "✅ Проблемные инстансы будут останавливаться"
echo ""
echo "Теперь вы можете:"
echo "1. Запустить инстанс вручную через https://vast.ai/"
echo "2. Выбрать инстанс с диском >= 100GB"
echo "3. Подождать загрузки Docker образа"
echo "4. Подключиться по SSH и запустить генерацию"
echo "5. Остановить инстанс после работы"
echo ""
echo "⚠️  ВАЖНО: Всегда проверяйте размер диска!"
echo "   Docker образ 40GB требует минимум 100GB диска"
echo ""

exit 0