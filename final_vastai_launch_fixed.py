#!/usr/bin/env python3
"""
Финальный скрипт для запуска инстанса Vast AI с правильными параметрами.
Использует API напрямую для указания allocated_storage=100.
"""

import os
import json
import requests
import sys
import time
from datetime import datetime

def create_instance_with_large_disk():
    """Создать инстанс с диском 100GB через API."""
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return None
    
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = "https://console.vast.ai/api/v0"
    
    print("🔍 Поиск подходящего оффера...")
    
    # Сначала найдем оффер через vast_submit.py
    import subprocess
    
    cmd = [
        sys.executable,
        "vast/vast_submit.py",
        "--list-offers",
        "--min-vram", "16",
        "--max-price", "1.0",
        "--list-count", "5"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        output = result.stdout
        
        # Парсим ID оффера
        import re
        offer_ids = re.findall(r'offer_id=(\d+)', output)
        
        if not offer_ids:
            print("❌ Не найдено офферов")
            return None
        
        offer_id = offer_ids[0]
        print(f"✅ Найден оффер: {offer_id}")
        
    except Exception as e:
        print(f"❌ Ошибка поиска оффера: {e}")
        return None
    
    print(f"\n🚀 Создание инстанса на оффере {offer_id}...")
    print(f"   Параметры: allocated_storage=100, disk_space=100")
    
    # Параметры создания инстанса
    create_data = {
        "client_id": "me",
        "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "args_str": "echo 'Starting instance with 100GB disk...' && df -h && sleep 7200",
        "allocated_storage": 100,  # Ключевой параметр!
        "disk_space": 100,  # Дублируем для надежности
        "ssh": True,
        "env": {
            "DEBUG": "true",
            "WORKSPACE": "/workspace"
        }
    }
    
    # Пробуем создать через API
    endpoints = [
        f"{base_url}/asks/{offer_id}/",
        f"{base_url}/offers/{offer_id}/"
    ]
    
    for endpoint in endpoints:
        print(f"\n  Пробуем endpoint: {endpoint}")
        
        try:
            response = requests.put(endpoint, headers=headers, json=create_data, timeout=60)
            print(f"    Статус: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Запрос успешен!")
                
                # Ищем ID инстанса
                instance_id = data.get('new_contract')
                if instance_id:
                    print(f"   ID инстанса: {instance_id}")
                    return instance_id
                else:
                    print(f"⚠️  ID инстанса не найден в ответе")
                    print(f"   Ответ: {json.dumps(data, indent=2)}")
                    return None
                    
            else:
                print(f"❌ Ошибка: {response.status_code}")
                print(f"   Ответ: {response.text[:500]}")
                
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            continue
    
    print(f"\n❌ Не удалось создать инстанс через API")
    print(f"   Пробуем альтернативный метод...")
    
    # Альтернатива: использовать vast_submit.py с комментарием
    print(f"\n⚠️  ВНИМАНИЕ: vast_submit.py создает инстансы с 10GB диском по умолчанию")
    print(f"   Нужно создавать инстанс вручную через веб-интерфейс:")
    print(f"   1. Откройте https://vast.ai/")
    print(f"   2. Нажмите 'Create'")
    print(f"   3. Установите фильтр: Disk Space >= 100GB")
    print(f"   4. Выберите инстанс с диском 100GB+")
    print(f"   5. В настройках укажите allocated_storage: 100")
    
    return None

def monitor_instance(instance_id):
    """Мониторить инстанс."""
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ VAST_API_KEY не установлен")
        return False
    
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = "https://console.vast.ai/api/v0"
    
    print(f"\n📊 Мониторинг инстанса {instance_id}...")
    print(f"   Нажмите Ctrl+C для остановки")
    
    check_count = 0
    max_checks = 30
    
    try:
        while check_count < max_checks:
            check_count += 1
            
            print(f"\n" + "=" * 60)
            print(f"📈 Проверка #{check_count}")
            print("=" * 60)
            
            # Получаем информацию об инстансе
            url = f"{base_url}/instances/{instance_id}/"
            
            try:
                response = requests.get(url, headers=headers, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    instance = data.get('instances', {})
                    
                    if not instance:
                        print("❌ Инстанс не найден")
                        time.sleep(120)
                        continue
                    
                    status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                    disk_gb = instance.get('disk_space', 0)
                    price = instance.get('dph_total', 0)
                    ssh_port = instance.get('ssh_port')
                    public_ip = instance.get('public_ipaddr', 'N/A')
                    
                    print(f"🔍 Статус инстанса:")
                    print(f"   Статус: {status}")
                    print(f"   Диск: {disk_gb}GB")
                    print(f"   Цена: ${price:.3f}/час")
                    print(f"   SSH порт: {ssh_port or 'N/A'}")
                    print(f"   IP: {public_ip}")
                    
                    # Проверяем критерии
                    if disk_gb < 100:
                        print(f"\n❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Диск {disk_gb}GB < 100GB")
                        print(f"   Docker образ 40GB не поместится!")
                        print(f"   Останавливаем инстанс...")
                        
                        # Останавливаем инстанс
                        stop_url = f"{base_url}/instances/{instance_id}/"
                        stop_response = requests.put(stop_url, headers=headers, json={"state": "stopped"}, timeout=30)
                        
                        if stop_response.status_code == 200:
                            print(f"✅ Инстанс остановлен")
                        else:
                            print(f"❌ Ошибка остановки")
                        
                        return False
                    
                    elif status == 'failed':
                        print(f"\n❌ Инстанс завершился с ошибкой")
                        return False
                    
                    elif status == 'running' and ssh_port:
                        print(f"\n🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                        print(f"\n🔗 SSH подключение:")
                        print(f"   ssh -p {ssh_port} root@{public_ip}")
                        
                        print(f"\n🎬 Запуск генерации видео:")
                        print(f"   cd /workspace")
                        print(f"   python -m src.entrypoints.run_gen \\")
                        print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset over ocean waves\"],")
                        print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
                        
                        print(f"\n💰 Стоимость:")
                        print(f"   Цена: ${price:.3f}/час")
                        print(f"   Загрузка Docker: 20-40 мин")
                        print(f"   Генерация: 5-15 мин")
                        print(f"   Итого: ~$0.15-$0.45")
                        
                        return True
                    
                    else:
                        print(f"\n⏳ Инстанс загружается...")
                        if status == 'loading':
                            print(f"   Docker образ 40GB загружается")
                            print(f"   Это может занять 20-40 минут")
                
                else:
                    print(f"❌ Ошибка API: {response.status_code}")
                    
            except Exception as e:
                print(f"❌ Ошибка запроса: {e}")
            
            # Ждем 2 минуты перед следующей проверкой
            print(f"\n⏳ Следующая проверка через 2 минуты...")
            time.sleep(120)
        
        print(f"\n⏱️  Достигнут лимит проверок ({max_checks})")
        return False
        
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Мониторинг остановлен пользователем")
        return False

def main():
    """Основная функция."""
    print("=" * 80)
    print("🚀 ФИНАЛЬНЫЙ ЗАПУСК ИНСТАНСА Vast AI С ДИСКОМ 100GB")
    print("=" * 80)
    
    print(f"\n🎯 Требования:")
    print(f"   • Docker образ: 40GB")
    print(f"   • Минимальный диск: 100GB")
    print(f"   • Параметр: allocated_storage=100")
    print(f"   • Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    
    print(f"\n⚠️  ВНИМАНИЕ:")
    print(f"   • vast_submit.py создает инстансы с 10GB диском")
    print(f"   • Нужно использовать API с параметром allocated_storage")
    print(f"   • Или создавать инстанс вручную через веб-интерфейс")
    
    confirm = input("\nПопробовать создать инстанс через API? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено")
        return 0
    
    # 1. Создание инстанса
    print(f"\n" + "=" * 80)
    print(f"1. 🚀 СОЗДАНИЕ ИНСТАНСА")
    print("=" * 80)
    
    instance_id = create_instance_with_large_disk()
    
    if not instance_id:
        print(f"\n❌ Не удалось создать инстанс через API")
        print(f"\n🔧 РЕКОМЕНДАЦИЯ:")
        print(f"   Создайте инстанс вручную через веб-интерфейс:")
        print(f"   1. https://vast.ai/")
        print(f"   2. Filter: Disk Space >= 100GB")
        print(f"   3. Image: registry.gitlab.com/gfever/vastai_interup:video-gen")
        print(f"   4. Command: sleep 7200")
        print(f"   5. SSH: Enable")
        return 1
    
    # 2. Мониторинг
    print(f"\n" + "=" * 80)
    print(f"2. 📊 МОНИТОРИНГ ИНСТАНСА {instance_id}")
    print("=" * 80)
    
    ready = monitor_instance(instance_id)
    
    # 3. Итог
    print(f"\n" + "=" * 80)
    print(f"3. 🎯 ИТОГ")
    print("=" * 80)
    
    if ready:
        print(f"✅ Инстанс {instance_id} готов к работе!")
        print(f"\n📋 Дальнейшие действия:")
        print(f"   1. Подключитесь по SSH")
        print(f"   2. Проверьте диск: df -h")
        print(f"   3. Запустите генерацию видео")
        print(f"   4. Остановите инстанс после работы")
    else:
        print(f"⚠️  Инстанс {instance_id} имеет проблемы или не готов")
        print(f"\n🔧 Проверьте:")
        print(f"   1. Консоль Vast AI: https://vast.ai/")
        print(f"   2. Instances -> {instance_id}")
        print(f"   3. Убедитесь что диск >= 100GB")
    
    print(f"\n🔗 Консоль управления: https://vast.ai/")
    print(f"   Instances -> {instance_id}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())