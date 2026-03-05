#!/bin/bash
# Финальный рабочий процесс для Vast AI

set -e

echo "================================================================"
echo "🎬 ФИНАЛЬНЫЙ РАБОЧИЙ ПРОЦЕСС Vast AI"
echo "================================================================"

# Проверка API ключа
if [ -z "$VAST_API_KEY" ]; then
    echo "❌ Ошибка: VAST_API_KEY не установлен"
    echo "   export VAST_API_KEY='ваш_ключ'"
    exit 1
fi

echo "✅ API ключ установлен"

# 1. ПОСТОЯННЫЙ МОНИТОРИНГ И ОЧИСТКА
echo ""
echo "1. 🔍 ПОСТОЯННЫЙ МОНИТОРИНГ ИНСТАНСОВ"
echo "================================================================"

# Создаем скрипт для постоянного мониторинга
cat > /tmp/vastai_monitor_loop.py << 'EOF'
#!/usr/bin/env python3
"""
Постоянный мониторинг инстансов Vast AI.
Останавливает инстансы с диском < 100GB.
"""

import os
import requests
import time
import sys

api_key = os.environ.get('VAST_API_KEY')
headers = {"Authorization": f"Bearer {api_key}"}
base_url = "https://console.vast.ai/api/v0"

print("🔍 Запуск постоянного мониторинга...")
print("   Проверка каждые 2 минуты")
print("   Остановка инстансов с диском < 100GB")
print("   Нажмите Ctrl+C для остановки")

check_count = 0

try:
    while True:
        check_count += 1
        print(f"\n📊 Проверка #{check_count}")
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
                        gpu = instance.get('gpu_name', 'N/A')
                        
                        total_cost += price
                        
                        print(f"\n  Инстанс {instance_id}:")
                        print(f"    Статус: {status}")
                        print(f"    GPU: {gpu}")
                        print(f"    Диск: {disk_gb}GB")
                        print(f"    Цена: ${price:.3f}/час")
                        
                        # Проверяем диск
                        if disk_gb < 100:
                            print(f"    ❌ Диск слишком мал! {disk_gb}GB < 100GB")
                            
                            # Если инстанс активен - останавливаем
                            if status in ['running', 'loading', 'starting']:
                                print(f"    ⚠️  Останавливаем...")
                                
                                stop_url = f"{base_url}/instances/{instance_id}/"
                                try:
                                    stop_response = requests.put(stop_url, headers=headers, json={"state": "stopped"}, timeout=30)
                                    if stop_response.status_code == 200:
                                        print(f"    ✅ Остановлен")
                                        stopped_count += 1
                                    else:
                                        print(f"    ❌ Ошибка остановки: {stop_response.status_code}")
                                except Exception as e:
                                    print(f"    ❌ Ошибка: {e}")
                            else:
                                print(f"    ℹ️  Уже остановлен или завершен")
                        else:
                            print(f"    ✅ Диск достаточный")
                    
                    print(f"\n📈 Статистика:")
                    print(f"  Всего инстансов: {len(instances)}")
                    print(f"  Остановлено: {stopped_count}")
                    print(f"  Общая стоимость/час: ${total_cost:.3f}")
                    
                    # Если есть активные инстансы
                    active_instances = [i for i in instances if i.get('actual_status') in ['running', 'loading', 'starting']]
                    if active_instances:
                        print(f"\n🎯 Активные инстансы:")
                        for instance in active_instances:
                            print(f"  - {instance.get('id')}: {instance.get('actual_status')}, ${instance.get('dph_total', 0):.3f}/час, {instance.get('disk_space', 0)}GB")
                else:
                    print("ℹ️  Нет активных инстансов")
                    
            else:
                print(f"❌ Ошибка API: {response.status_code}")
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
        
        # Ждем 2 минуты
        print(f"\n⏳ Следующая проверка через 2 минуты...")
        print("=" * 60)
        time.sleep(120)
        
except KeyboardInterrupt:
    print(f"\n\n⏹️  Мониторинг остановлен пользователем")
    print(f"Всего проверок: {check_count}")

EOF

# Запускаем мониторинг в фоне
echo "🚀 Запуск мониторинга в фоновом режиме..."
python /tmp/vastai_monitor_loop.py &
MONITOR_PID=$!
echo "✅ Мониторинг запущен (PID: $MONITOR_PID)"

# 2. ИНСТРУКЦИИ ДЛЯ РУЧНОГО ЗАПУСКА
echo ""
echo "2. 📋 ИНСТРУКЦИИ ДЛЯ РУЧНОГО ЗАПУСКА"
echo "================================================================"
echo ""
echo "ПРОБЛЕМА: vast_submit.py создает инстансы с диском 10GB"
echo "РЕШЕНИЕ: Запустить инстанс вручную через веб-интерфейс"
echo ""
echo "ШАГИ ДЛЯ РУЧНОГО ЗАПУСКА:"
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

# 3. АЛЬТЕРНАТИВНЫЙ ВАРИАНТ ЧЕРЕЗ API
echo ""
echo "3. 🔧 АЛЬТЕРНАТИВНЫЙ ВАРИАНТ ЧЕРЕЗ API"
echo "================================================================"
echo ""
echo "Если хотите попробовать создать инстанс через API с allocated_storage:"
echo ""
cat > /tmp/create_via_api.py << 'EOF2'
#!/usr/bin/env python3
import os
import requests
import json

api_key = os.environ.get('VAST_API_KEY')
headers = {"Authorization": f"Bearer {api_key}"}

# Нужно найти оффер ID вручную
offer_id = "ВАШ_ОФФЕР_ID"  # Замените на реальный ID оффера

payload = {
    "client_id": "me",
    "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
    "args_str": "sleep 3600",
    "allocated_storage": 100,  # Запрашиваем 100GB
    "disk_space": 100,         # Дублируем
    "ssh": True
}

url = f"https://console.vast.ai/api/v0/asks/{offer_id}/"

try:
    response = requests.put(url, headers=headers, json=payload, timeout=60)
    print(f"Статус: {response.status_code}")
    print(f"Ответ: {json.dumps(response.json(), indent=2)}")
except Exception as e:
    print(f"Ошибка: {e}")
EOF2

echo "Скрипт для создания через API сохранен в: /tmp/create_via_api.py"
echo "Замените 'ВАШ_ОФФЕР_ID' на реальный ID оффера"
echo ""

# 4. УПРАВЛЕНИЕ МОНИТОРИНГОМ
echo ""
echo "4. ⚙️  УПРАВЛЕНИЕ МОНИТОРИНГОМ"
echo "================================================================"
echo ""
echo "Мониторинг запущен с PID: $MONITOR_PID"
echo ""
echo "Команды управления:"
echo "  • Проверить статус: ps aux | grep $MONITOR_PID"
echo "  • Остановить мониторинг: kill $MONITOR_PID"
echo "  • Просмотреть логи: tail -f /tmp/vastai_monitor.log"
echo ""
echo "Мониторинг будет:"
echo "  • Проверять инстансы каждые 2 минуты"
echo "  • Останавливать инстансы с диском < 100GB"
echo "  • Выводить статистику"
echo ""

# 5. ФАЙЛЫ И РЕСУРСЫ
echo ""
echo "5. 📁 ФАЙЛЫ И РЕСУРСЫ"
echo "================================================================"
echo ""
echo "Созданные файлы:"
echo "  • manual_vastai_setup.md - полная инструкция"
echo "  • vastai_monitor.py - скрипт мониторинга"
echo "  • launch_and_monitor.py - запуск с мониторингом"
echo "  • final_solution_vastai.sh - финальное решение"
echo ""
echo "Полезные ссылки:"
echo "  • Vast AI: https://vast.ai/"
echo "  • Docker образ: registry.gitlab.com/gfever/vastai_interup:video-gen"
echo "  • Код пайплайна: src/entrypoints/run_gen.py"
echo ""

# 6. РЕКОМЕНДАЦИИ
echo ""
echo "6. 💡 РЕКОМЕНДАЦИИ"
echo "================================================================"
echo ""
echo "1. ДЛЯ НАДЕЖНОСТИ:"
echo "   • Используйте веб-интерфейс Vast AI"
echo "   • Выбирайте инстансы с диском >= 100GB"
echo "   • Включайте SSH для отладки"
echo ""
echo "2. ДЛЯ ЭКОНОМИИ:"
echo "   • Останавливайте инстансы сразу после работы"
echo "   • Используйте мониторинг для автоматической очистки"
echo "   • Выбирайте инстансы в дешевых регионах"
echo ""
echo "3. ДЛЯ ОТЛАДКИ:"
echo "   • Подключайтесь по SSH для проверки"
echo "   • Проверяйте диск: df -h"
echo "   • Проверяйте Docker: docker ps"
echo "   • Запускайте генерацию вручную для теста"
echo ""

echo "================================================================"
echo "🎯 РАБОЧИЙ ПРОЦЕСС НАСТРОЕН"
echo "================================================================"
echo ""
echo "✅ Мониторинг запущен и проверяет инстансы"
echo "✅ Инструкции для ручного запуска готовы"
echo "✅ Проблемные инстансы будут автоматически останавливаться"
echo ""
echo "Теперь вы можете:"
echo "1. Запустить инстанс вручную через веб-интерфейс"
echo "2. Подождать загрузки Docker образа (20-40 мин)"
echo "3. Подключиться по SSH и запустить генерацию"
echo "4. Остановить инстанс после завершения"
echo ""
echo "💰 Не забывайте останавливать инстансы после работы!"
echo ""

exit 0