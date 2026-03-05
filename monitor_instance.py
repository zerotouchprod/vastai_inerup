#!/usr/bin/env python3
"""
Мониторинг конкретного инстанса Vast AI.
Специально для инстанса 32410634 с диском 100GB.
"""

import os
import sys
import time
import json
import requests
from datetime import datetime

def load_instance_info():
    """Загрузить информацию об инстансе."""
    try:
        with open('/tmp/vastai_instance_info.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print("❌ Файл с информацией об инстансе не найден")
        return None

def check_instance_status(instance_id, api_key):
    """Проверить статус инстанса."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://console.vast.ai/api/v0/instances/{instance_id}/"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            instances = data.get('instances', {})
            
            if isinstance(instances, dict):
                # Получаем информацию об инстансе
                status = instances.get('actual_status', 'unknown')
                disk_gb = instances.get('disk_space', 0)
                ssh_port = instances.get('ssh_port')
                ssh_host = instances.get('ssh_host')
                public_ipaddr = instances.get('public_ipaddr')
                
                return {
                    'status': status,
                    'disk_gb': disk_gb,
                    'ssh_port': ssh_port,
                    'ssh_host': ssh_host,
                    'public_ipaddr': public_ipaddr,
                    'raw_data': instances
                }
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
    
    return None

def main():
    """Основная функция мониторинга."""
    print("=" * 80)
    print("🎯 МОНИТОРИНГ ИНСТАНСА Vast AI")
    print("=" * 80)
    
    # Загружаем информацию об инстансе
    instance_info = load_instance_info()
    if not instance_info:
        print("❌ Не удалось загрузить информацию об инстансе")
        return 1
    
    instance_id = instance_info.get('instance_id')
    offer_id = instance_info.get('offer_id')
    disk_gb = instance_info.get('disk_gb', 100)
    
    print(f"📊 Информация об инстансе:")
    print(f"   ID инстанса: {instance_id}")
    print(f"   ID оффера: {offer_id}")
    print(f"   Запрошенный диск: {disk_gb}GB")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    print(f"   Размер образа: ~40GB")
    print()
    
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    print("⏳ Начинаем мониторинг...")
    print("   Docker образ 40GB будет загружаться 20-40 минут")
    print()
    
    check_count = 0
    max_checks = 120  # 120 проверок * 30 секунд = 60 минут
    
    while check_count < max_checks:
        check_count += 1
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"📊 Проверка #{check_count} - {timestamp}")
        print("-" * 60)
        
        # Проверяем статус
        status_info = check_instance_status(instance_id, api_key)
        
        if status_info:
            status = status_info['status']
            actual_disk_gb = status_info['disk_gb']
            ssh_port = status_info['ssh_port']
            ssh_host = status_info['ssh_host']
            public_ipaddr = status_info['public_ipaddr']
            
            print(f"   Статус: {status}")
            print(f"   Диск: {actual_disk_gb}GB")
            
            if ssh_port and ssh_host:
                print(f"   SSH: {ssh_host}:{ssh_port}")
            
            if public_ipaddr:
                print(f"   IP: {public_ipaddr}")
            
            # Проверяем, готов ли инстанс
            if status == 'running' and ssh_port:
                print()
                print("✅ ИНСТАНС ГОТОВ!")
                print("=" * 60)
                print("🎬 Инструкции для запуска генерации видео:")
                print()
                
                if ssh_host and ssh_port:
                    print(f"1. Подключитесь по SSH:")
                    print(f"   ssh -p {ssh_port} root@{ssh_host}")
                    print()
                
                print("2. Проверьте диск:")
                print(f"   df -h")
                print()
                
                print("3. Запустите генерацию видео:")
                print(f"   cd /workspace")
                print(f"   python -m src.entrypoints.run_gen \\")
                print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"],")
                print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
                print()
                
                print("4. Проверьте загрузку в облако:")
                print(f"   ls -la /workspace/outputs/")
                print()
                
                print("5. Остановите инстанс после завершения:")
                print(f"   # Через веб-интерфейс: https://cloud.vast.ai/instances/")
                print(f"   # Или через API: curl -X PUT \\")
                print(f"     -H \"Authorization: Bearer {api_key[:20]}...\" \\")
                print(f"     https://console.vast.ai/api/v0/instances/{instance_id}/stop/")
                print()
                
                # Сохраняем SSH информацию
                ssh_info = {
                    'instance_id': instance_id,
                    'ssh_host': ssh_host,
                    'ssh_port': ssh_port,
                    'public_ipaddr': public_ipaddr,
                    'ready_at': timestamp
                }
                
                with open('/tmp/vastai_ssh_info.json', 'w') as f:
                    json.dump(ssh_info, f, indent=2)
                
                print(f"💾 SSH информация сохранена в /tmp/vastai_ssh_info.json")
                return 0
            
            elif status == 'loading':
                print(f"   ⏳ Загрузка Docker образа... (40GB)")
                print(f"   Ожидаемое время: 20-40 минут")
                print(f"   Прогресс: {check_count}/{max_checks} проверок")
            
            elif status == 'failed':
                print(f"   ❌ Инстанс не удалось запустить")
                print(f"   Проверьте логи в веб-интерфейсе")
                return 1
            
        else:
            print(f"   ⚠️  Не удалось получить статус")
        
        print()
        
        # Ждем перед следующей проверкой
        if check_count < max_checks:
            print(f"⏳ Следующая проверка через 30 секунд...")
            print("=" * 80)
            time.sleep(30)
    
    print("❌ Превышено время ожидания (60 минут)")
    print("   Проверьте инстанс в веб-интерфейсе: https://cloud.vast.ai/instances/")
    return 1

if __name__ == "__main__":
    sys.exit(main())