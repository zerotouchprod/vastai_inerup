#!/usr/bin/env python3
"""
Поиск офферов с большим диском через анализ веб-интерфейса Vast AI.
Так как API не показывает размер диска, нужно искать вручную.
"""

import os
import sys
import json
import time

def suggest_search_methods():
    """Предложить методы поиска офферов с большим диском."""
    print("=" * 80)
    print("🔍 ПОИСК ОФФЕРОВ С БОЛЬШИМ ДИСКОМ (100GB+)")
    print("=" * 80)
    
    print("\n❌ ПРОБЛЕМА: API Vast AI не показывает размер диска в офферах")
    print("   Параметр allocated_storage не работает")
    print("   Инстансы создаются с диском 10GB по умолчанию")
    
    print("\n🎯 РЕШЕНИЕ: Искать офферы которые уже имеют большой диск")
    
    print("\n🔧 МЕТОДЫ ПОИСКА:")
    print("=" * 80)
    
    print("\n1. 📱 РУЧНОЙ ПОИСК ЧЕРЕЗ ВЕБ-ИНТЕРФЕЙС:")
    print("   • Откройте: https://vast.ai/")
    print("   • Нажмите 'Create'")
    print("   • Установите фильтр: Disk Space >= 100GB")
    print("   • Найдите оффер с диском 100GB+")
    print("   • Запишите ID оффера")
    
    print("\n2. 🤖 АВТОМАТИЧЕСКИЙ ПОИСК (ЭКСПЕРИМЕНТАЛЬНЫЙ):")
    print("   • Использовать Selenium для парсинга веб-страницы")
    print("   • Искать элементы с текстом 'GB' или 'TB'")
    print("   • Фильтровать по размеру диска")
    
    print("\n3. 📊 АНАЛИЗ СУЩЕСТВУЮЩИХ ИНСТАНСОВ:")
    print("   • Найти уже запущенные инстансы с большим диском")
    print("   • Посмотреть на каком оффере они созданы")
    print("   • Использовать тот же оффер")
    
    print("\n4. 🗺️ ПОИСК ПО РЕГИОНАМ:")
    print("   • Некоторые регионы имеют инстансы с большими дисками")
    print("   • US-East, EU-West часто имеют хорошие варианты")
    print("   • Искать офферы в этих регионах")
    
    print("\n🎯 РЕКОМЕНДАЦИЯ:")
    print("   Используйте ручной поиск через веб-интерфейс")
    print("   Это самый надежный способ")
    
    return None

def check_cloudflare_credentials():
    """Проверить credentials для загрузки в облако."""
    print("\n🔑 ПРОВЕРКА CLOUDFLARE R2 CREDENTIALS:")
    print("=" * 80)
    
    # Проверяем переменные окружения
    env_vars = [
        'R2_ACCOUNT_ID',
        'R2_ACCESS_KEY_ID', 
        'R2_SECRET_ACCESS_KEY',
        'R2_BUCKET_NAME',
        'R2_PUBLIC_URL'
    ]
    
    missing_vars = []
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            print(f"✅ {var}: установлен")
        else:
            print(f"❌ {var}: не установлен")
            missing_vars.append(var)
    
    if missing_vars:
        print(f"\n⚠️  Отсутствуют переменные: {missing_vars}")
        print("   Видео не сможет загрузиться в облако")
        return False
    else:
        print(f"\n✅ Все credentials установлены")
        return True

def create_instance_on_large_disk_offer(offer_id):
    """Создать инстанс на оффере с большим диском."""
    print(f"\n🚀 СОЗДАНИЕ ИНСТАНСА НА ОФФЕРЕ {offer_id}")
    print("=" * 80)
    
    import requests
    
    api_key = os.environ.get('VAST_API_KEY')
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Параметры создания
    create_data = {
        "client_id": "me",
        "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "args_str": "echo 'Checking disk size...' && df -h && echo 'Waiting for commands...' && sleep 7200",
        "ssh": True,
        "env": {
            "DEBUG": "true",
            "WORKSPACE": "/workspace"
        }
    }
    
    # Пробуем создать
    endpoints = [
        f"https://console.vast.ai/api/v0/asks/{offer_id}/",
        f"https://console.vast.ai/api/v0/offers/{offer_id}/"
    ]
    
    for endpoint in endpoints:
        print(f"\nПробуем endpoint: {endpoint}")
        
        try:
            response = requests.put(endpoint, headers=headers, json=create_data, timeout=60)
            print(f"Статус: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Запрос успешен!")
                
                instance_id = data.get('new_contract')
                if instance_id:
                    print(f"\n🎉 Инстанс создан! ID: {instance_id}")
                    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
                    print(f"   SSH: включен")
                    print(f"   Команда: проверка диска + ожидание")
                    
                    return instance_id
                else:
                    print(f"⚠️  ID инстанса не найден")
                    print(f"   Ответ: {json.dumps(data, indent=2)}")
                    
            else:
                print(f"❌ Ошибка: {response.status_code}")
                print(f"   Ответ: {response.text[:500]}")
                
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            continue
    
    print(f"\n❌ Не удалось создать инстанс")
    return None

def main():
    """Основная функция."""
    print("=" * 80)
    print("🎯 ПОИСК И ЗАПУСК НА ИНСТАНСАХ С БОЛЬШИМ ДИСКОМ")
    print("=" * 80)
    
    # Проверка API ключа
    if not os.environ.get('VAST_API_KEY'):
        print("❌ Ошибка: VAST_API_KEY не установлен")
        print("   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    # 1. Предложить методы поиска
    suggest_search_methods()
    
    # 2. Проверить Cloudflare credentials
    cloudflare_ok = check_cloudflare_credentials()
    
    # 3. Запросить ID оффера
    print("\n" + "=" * 80)
    print("🎯 ВВОД ID ОФФЕРА С БОЛЬШИМ ДИСКОМ")
    print("=" * 80)
    
    print("\n📋 Инструкция:")
    print("   1. Откройте https://vast.ai/")
    print("   2. Нажмите 'Create'")
    print("   3. Установите фильтр: Disk Space >= 100GB")
    print("   4. Найдите оффер с диском 100GB+")
    print("   5. Скопируйте ID оффера (например: 12345678)")
    
    offer_id = input("\nВведите ID оффера с диском >= 100GB: ").strip()
    
    if not offer_id.isdigit():
        print("❌ Неверный ID оффера")
        return 1
    
    # 4. Создать инстанс
    print("\n" + "=" * 80)
    print("🚀 СОЗДАНИЕ ИНСТАНСА")
    print("=" * 80)
    
    instance_id = create_instance_on_large_disk_offer(offer_id)
    
    if not instance_id:
        print("❌ Не удалось создать инстанс")
        return 1
    
    # 5. Инструкции для мониторинга
    print("\n" + "=" * 80)
    print("📊 МОНИТОРИНГ И ЗАПУСК")
    print("=" * 80)
    
    print(f"\n🔍 Мониторить инстанс:")
    print(f"   python -c \"\"\"")
    print(f"   import requests, time")
    print(f"   api_key = '{os.environ.get('VAST_API_KEY')[:20]}...'")
    print(f"   headers = {{'Authorization': f'Bearer {{api_key}}'}}")
    print(f"   instance_id = {instance_id}")
    print(f"   ")
    print(f"   while True:")
    print(f"       url = f'https://console.vast.ai/api/v0/instances/{{instance_id}}/'")
    print(f"       response = requests.get(url, headers=headers)")
    print(f"       if response.status_code == 200:")
    print(f"           data = response.json()")
    print(f"           instance = data.get('instances', {{}})")
    print(f"           status = instance.get('actual_status', 'unknown')")
    print(f"           disk_gb = instance.get('disk_space', 0)")
    print(f"           ssh_port = instance.get('ssh_port')")
    print(f"           print(f'Статус: {{status}}, Диск: {{disk_gb}}GB, SSH: {{ssh_port}}')")
    print(f"           ")
    print(f"           if status == 'running' and ssh_port:")
    print(f"               print('✅ Инстанс готов!')")
    print(f"               break")
    print(f"       time.sleep(30)")
    print(f"   \"\"\"")
    
    print(f"\n🎬 Запуск генерации после подключения:")
    print(f"   ssh -p <PORT> root@<IP>")
    print(f"   cd /workspace")
    print(f"   python -m src.entrypoints.run_gen \\")
    print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"],")
    print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
    
    if not cloudflare_ok:
        print(f"\n⚠️  ВНИМАНИЕ: Cloudflare credentials не установлены!")
        print(f"   Видео не загрузится в облако")
        print(f"   Установите переменные окружения:")
        print(f"   export R2_ACCOUNT_ID='ваш_id'")
        print(f"   export R2_ACCESS_KEY_ID='ваш_key'")
        print(f"   export R2_SECRET_ACCESS_KEY='ваш_secret'")
        print(f"   export R2_BUCKET_NAME='ваш_bucket'")
        print(f"   export R2_PUBLIC_URL='ваш_url'")
    
    print(f"\n🔗 Консоль управления: https://vast.ai/")
    print(f"   Instances -> {instance_id}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())