#!/usr/bin/env python3
"""
Мониторинг мощного инстанса для генерации видео.
"""

import os
import sys
import json
import time
import requests
from datetime import datetime, timedelta

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
                return {
                    'status': instances.get('actual_status', 'unknown'),
                    'disk_gb': instances.get('disk_space', 0),
                    'ssh_port': instances.get('ssh_port'),
                    'ssh_host': instances.get('ssh_host'),
                    'public_ipaddr': instances.get('public_ipaddr'),
                    'gpu_name': instances.get('gpu_name', 'unknown'),
                    'gpu_ram': instances.get('gpu_ram', 0),
                    'dph_total': instances.get('dph_total', 0),
                    'success': True
                }
    except Exception as e:
        print(f"❌ Ошибка проверки статуса: {e}")
    
    return {'success': False, 'status': 'error'}

def main():
    print("🔍 МОНИТОРИНГ МОЩНОГО ИНСТАНСА Vast AI")
    print("="*60)
    
    # Получаем API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    # Загружаем информацию о новом инстансе
    try:
        with open('/tmp/vastai_powerful_instance_new.json', 'r') as f:
            instance_info = json.load(f)
        instance_id = instance_info.get('instance_id')
        disk_gb = instance_info.get('disk_gb', 200)
        created_at = instance_info.get('created_at', '2026-03-05 18:45:00')
        
        print(f"📊 ИНФОРМАЦИЯ ОБ ИНСТАНСЕ:")
        print(f"   ID: {instance_id}")
        print(f"   Диск: {disk_gb}GB")
        print(f"   Создан: {created_at}")
        print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
        print()
    except FileNotFoundError:
        print("❌ Файл с информацией об инстансе не найден")
        instance_id = input("   Введите ID инстанса: ").strip()
        disk_gb = 200
    
    print("⏳ НАЧИНАЕМ МОНИТОРИНГ...")
    print("   Docker образ 40GB загружается")
    print("   Ожидаемое время: 20-40 минут")
    print()
    
    check_count = 0
    max_checks = 48  # 48 проверок * 5 минут = 240 минут (4 часа)
    start_time = datetime.now()
    
    while check_count < max_checks:
        check_count += 1
        current_time = datetime.now()
        elapsed_minutes = (current_time - start_time).total_seconds() / 60
        
        print(f"\n📊 ПРОВЕРКА #{check_count}")
        print(f"   Время: {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Прошло: {elapsed_minutes:.1f} минут")
        print(f"   Осталось проверок: {max_checks - check_count}")
        print("-" * 40)
        
        # Проверяем статус
        status_info = check_instance_status(instance_id, api_key)
        
        if status_info['success']:
            status = status_info['status']
            disk_gb = status_info['disk_gb']
            ssh_port = status_info['ssh_port']
            ssh_host = status_info['ssh_host']
            gpu_name = status_info['gpu_name']
            gpu_ram = status_info['gpu_ram']
            price = status_info['dph_total']
            
            print(f"   Статус: {status.upper()}")
            print(f"   GPU: {gpu_name} ({gpu_ram}GB VRAM)")
            print(f"   Диск: {disk_gb}GB")
            print(f"   Цена: ${price:.3f}/час")
            
            if ssh_host and ssh_port:
                print(f"   SSH: {ssh_host}:{ssh_port}")
            
            if status == 'running' and ssh_port:
                print("\n" + "="*60)
                print("🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                print("="*60)
                print()
                print("🚀 ДЛЯ ЗАПУСКА ГЕНЕРАЦИИ ВИДЕО:")
                print()
                print(f"1. Автоматический запуск:")
                print(f"   python3 auto_video_gen.py")
                print()
                print(f"2. Быстрый запуск:")
                print(f"   ./quick_video_gen.sh")
                print()
                print(f"3. Ручной запуск:")
                print(f"   ssh -p {ssh_port} root@{ssh_host}")
                print(f"   cd /workspace")
                print(f"   python -m src.entrypoints.run_gen \\")
                print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"]}}'")
                print()
                
                # Сохраняем SSH информацию
                ssh_info = {
                    'instance_id': instance_id,
                    'ssh_host': ssh_host,
                    'ssh_port': ssh_port,
                    'public_ipaddr': status_info.get('public_ipaddr'),
                    'gpu_name': gpu_name,
                    'gpu_ram': gpu_ram,
                    'disk_gb': disk_gb,
                    'price_per_hour': price,
                    'ready_at': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'elapsed_minutes': elapsed_minutes
                }
                
                with open('/tmp/vastai_powerful_ready.json', 'w') as f:
                    json.dump(ssh_info, f, indent=2)
                
                print(f"💾 Информация сохранена в /tmp/vastai_powerful_ready.json")
                print()
                print("💰 НЕ ЗАБУДЬТЕ ОСТАНОВИТЬ ИНСТАНС ПОСЛЕ ЗАВЕРШЕНИЯ!")
                print(f"   curl -X PUT -H \"Authorization: Bearer {api_key[:20]}...\" \\")
                print(f"     https://console.vast.ai/api/v0/instances/{instance_id}/stop/")
                
                return 0
                
            elif status == 'loading':
                print(f"   ⏳ Загрузка Docker образа...")
                print(f"   Прогресс: {check_count}/{max_checks} проверок")
                
                # Оцениваем оставшееся время
                if elapsed_minutes > 10:
                    avg_time_per_check = elapsed_minutes / check_count
                    remaining_checks = max_checks - check_count
                    remaining_minutes = remaining_checks * 5
                    
                    print(f"   Осталось ждать: ~{remaining_minutes:.0f} минут")
                    print(f"   Примерное время готовности: {(current_time + timedelta(minutes=remaining_minutes)).strftime('%H:%M')}")
                    
            elif status == 'failed':
                print(f"   ❌ Инстанс не удалось запустить")
                print(f"   Проверьте в веб-интерфейсе: https://cloud.vast.ai/instances/")
                return 1
                
        else:
            print(f"   ⚠️  Не удалось получить статус")
        
        # Ждем перед следующей проверкой
        if check_count < max_checks:
            print(f"\n⏳ Следующая проверка через 5 минут...")
            for i in range(5):
                time.sleep(60)  # Спим по 1 минуте, чтобы можно было прервать
                print(f"   {5-i} минут осталось...", end='\r')
            print()
    
    print("\n" + "="*60)
    print("❌ ПРЕВЫШЕНО ВРЕМЯ ОЖИДАНИЯ (4 часа)")
    print("="*60)
    print()
    print("🔧 Возможные проблемы:")
    print("   1. Docker образ не загрузился")
    print("   2. Проблемы с сетью")
    print("   3. Недостаточно средств на балансе")
    print()
    print("📊 Проверьте вручную:")
    print(f"   python3 check_instance_status.py")
    print(f"   Или: https://cloud.vast.ai/instances/")
    print()
    
    return 1

if __name__ == "__main__":
    sys.exit(main())