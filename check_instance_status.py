#!/usr/bin/env python3
"""
Проверка статуса инстанса Vast AI.
"""

import os
import sys
import json
import requests
from datetime import datetime

def main():
    print("🔍 ПРОВЕРКА СТАТУСА ИНСТАНСА Vast AI")
    print("="*50)
    
    # Получаем API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    # Пробуем загрузить информацию об инстансе
    instance_id = None
    try:
        with open('/tmp/vastai_instance_info.json', 'r') as f:
            instance_info = json.load(f)
            instance_id = instance_info.get('instance_id')
    except FileNotFoundError:
        print("📝 Введите ID инстанса вручную")
        instance_id = input("   ID инстанса: ").strip()
    
    if not instance_id:
        print("❌ Не указан ID инстанса")
        return 1
    
    print(f"   Инстанс ID: {instance_id}")
    print(f"   Время проверки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Проверяем статус
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://console.vast.ai/api/v0/instances/{instance_id}/"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            instances = data.get('instances', {})
            
            if isinstance(instances, dict):
                status = instances.get('actual_status', 'unknown')
                disk_gb = instances.get('disk_space', 0)
                ssh_port = instances.get('ssh_port')
                ssh_host = instances.get('ssh_host')
                public_ipaddr = instances.get('public_ipaddr')
                
                print(f"📊 СТАТУС: {status.upper()}")
                print(f"   Диск: {disk_gb}GB")
                print(f"   IP: {public_ipaddr}")
                print(f"   SSH порт: {ssh_port}")
                print(f"   SSH хост: {ssh_host}")
                print()
                
                if status == 'running' and ssh_port:
                    print("🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                    print("="*50)
                    print()
                    print("🚀 ДЛЯ ЗАПУСКА ГЕНЕРАЦИИ ВИДЕО:")
                    print()
                    print(f"1. Подключитесь по SSH:")
                    print(f"   ssh -p {ssh_port} root@{ssh_host}")
                    print()
                    print("2. Проверьте рабочую директорию:")
                    print(f"   cd /workspace && ls -la")
                    print()
                    print("3. Запустите генерацию видео:")
                    print(f"   python -m src.entrypoints.run_gen \\")
                    print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"],")
                    print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
                    print()
                    print("4. Или используйте готовый скрипт:")
                    print(f"   ./quick_video_gen.sh")
                    print()
                    
                    # Сохраняем SSH информацию
                    ssh_info = {
                        'instance_id': instance_id,
                        'ssh_host': ssh_host,
                        'ssh_port': ssh_port,
                        'public_ipaddr': public_ipaddr,
                        'status': status,
                        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }
                    
                    with open('/tmp/vastai_current_instance.json', 'w') as f:
                        json.dump(ssh_info, f, indent=2)
                    
                    print(f"💾 Информация сохранена в /tmp/vastai_current_instance.json")
                    
                elif status == 'loading':
                    print("⏳ ИНСТАНС ЗАГРУЖАЕТСЯ")
                    print("="*50)
                    print()
                    print("📦 Загружается Docker образ 40GB")
                    print("   Ожидаемое время загрузки: 20-40 минут")
                    print(f"   Текущий статус: {status}")
                    print(f"   Диск: {disk_gb}GB (достаточно для образа 40GB)")
                    print()
                    print("⏰ Примерное время готовности:")
                    print(f"   Начало загрузки: 18:35 UTC")
                    print(f"   Ожидаемое завершение: 19:15-19:35 UTC")
                    print()
                    print("🔧 Для следующей проверки:")
                    print(f"   python3 {sys.argv[0]}")
                    print()
                    
                elif status == 'failed':
                    print("❌ ИНСТАНС НЕ УДАЛОСЬ ЗАПУСТИТЬ")
                    print("="*50)
                    print()
                    print("🔧 Проверьте логи в веб-интерфейсе:")
                    print(f"   https://cloud.vast.ai/instances/")
                    print()
                    
                else:
                    print(f"⚠️  Неизвестный статус: {status}")
                    print("   Проверьте в веб-интерфейсе:")
                    print(f"   https://cloud.vast.ai/instances/")
                    
            else:
                print("❌ Неверный формат данных от API")
                print(f"   Ответ: {response.text[:500]}")
                
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())