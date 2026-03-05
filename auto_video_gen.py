#!/usr/bin/env python3
"""
Автоматический запуск генерации видео на Vast AI.
Ожидает готовности инстанса, подключается по SSH и запускает генерацию.
"""

import os
import sys
import time
import json
import paramiko
import requests
from datetime import datetime
import subprocess

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
    except Exception as e:
        print(f"❌ Ошибка проверки статуса: {e}")
    
    return None

def wait_for_instance_ready(instance_id, api_key, max_wait_minutes=60):
    """Ожидать готовности инстанса."""
    print(f"⏳ Ожидаем готовности инстанса {instance_id}...")
    print(f"   Docker образ 40GB загружается (20-40 минут)")
    
    check_interval = 30  # секунд
    max_checks = (max_wait_minutes * 60) // check_interval
    
    for check_num in range(1, max_checks + 1):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n📊 Проверка #{check_num} - {timestamp}")
        
        status_info = check_instance_status(instance_id, api_key)
        
        if status_info:
            status = status_info['status']
            disk_gb = status_info['disk_gb']
            ssh_port = status_info['ssh_port']
            ssh_host = status_info['ssh_host']
            
            print(f"   Статус: {status}")
            print(f"   Диск: {disk_gb}GB")
            
            if ssh_host and ssh_port:
                print(f"   SSH: {ssh_host}:{ssh_port}")
            
            if status == 'running' and ssh_port:
                print(f"\n✅ ИНСТАНС ГОТОВ!")
                print(f"   Подключение: {ssh_host}:{ssh_port}")
                return status_info
            elif status == 'loading':
                print(f"   ⏳ Загрузка Docker образа...")
                print(f"   Прогресс: {check_num}/{max_checks} проверок")
                print(f"   Осталось ждать: {(max_checks - check_num) * check_interval // 60} минут")
            elif status == 'failed':
                print(f"   ❌ Инстанс не удалось запустить")
                return None
        else:
            print(f"   ⚠️  Не удалось получить статус")
        
        if check_num < max_checks:
            time.sleep(check_interval)
    
    print(f"\n❌ Превышено время ожидания ({max_wait_minutes} минут)")
    return None

def run_ssh_command(host, port, command, timeout=300):
    """Выполнить команду по SSH."""
    try:
        # Создаем SSH клиент
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        print(f"🔗 Подключаемся к {host}:{port}...")
        
        # Подключаемся (пароль не требуется для Vast AI)
        ssh.connect(
            hostname=host,
            port=port,
            username='root',
            timeout=10
        )
        
        print(f"✅ Подключение успешно")
        print(f"🚀 Выполняем команду: {command}")
        
        # Выполняем команду
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        
        # Получаем вывод
        output = stdout.read().decode('utf-8', errors='ignore')
        error = stderr.read().decode('utf-8', errors='ignore')
        
        # Закрываем соединение
        ssh.close()
        
        return {
            'success': True,
            'output': output,
            'error': error,
            'exit_code': stdout.channel.recv_exit_status()
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'output': '',
            'exit_code': -1
        }

def run_video_generation(ssh_host, ssh_port):
    """Запустить генерацию видео."""
    print("\n" + "="*80)
    print("🎬 ЗАПУСК ГЕНЕРАЦИИ ВИДЕО")
    print("="*80)
    
    # 1. Проверяем диск
    print("\n1️⃣  Проверяем диск...")
    disk_check = run_ssh_command(ssh_host, ssh_port, "df -h")
    
    if disk_check['success']:
        print("✅ Диск проверен:")
        print(disk_check['output'])
    else:
        print(f"❌ Ошибка проверки диска: {disk_check['error']}")
        return False
    
    # 2. Проверяем рабочую директорию
    print("\n2️⃣  Проверяем рабочую директорию...")
    dir_check = run_ssh_command(ssh_host, ssh_port, "cd /workspace && pwd && ls -la")
    
    if dir_check['success']:
        print("✅ Рабочая директория:")
        print(dir_check['output'])
    else:
        print(f"❌ Ошибка проверки директории: {dir_check['error']}")
        return False
    
    # 3. Запускаем генерацию видео
    print("\n3️⃣  Запускаем генерацию видео...")
    
    # Создаем job для генерации
    job_config = {
        "mode": "text2video",
        "prompts": ["A beautiful sunset over mountains with clouds, cinematic, 4k"],
        "num_frames": 24,
        "fps": 8,
        "num_inference_steps": 25,
        "output_dir": "/workspace/outputs",
        "seed": 42
    }
    
    job_json = json.dumps(job_config).replace('"', '\\"')
    
    # Команда для запуска генерации
    gen_command = f"""
    cd /workspace && \
    echo "Starting video generation..." && \
    python -m src.entrypoints.run_gen \
      --job '{job_json}' \
      --verbose
    """
    
    print(f"📝 Конфигурация job:")
    print(json.dumps(job_config, indent=2))
    
    # Запускаем генерацию с большим таймаутом (может занять 10-30 минут)
    print(f"\n⏳ Запускаем генерацию (может занять 10-30 минут)...")
    result = run_ssh_command(ssh_host, ssh_port, gen_command, timeout=1800)  # 30 минут
    
    if result['success']:
        print("✅ Генерация запущена!")
        print("\n📤 Вывод:")
        print(result['output'][-2000:])  # Последние 2000 символов
        
        if result['error']:
            print("\n⚠️  Ошибки:")
            print(result['error'][-1000:])
        
        print(f"\n📊 Код завершения: {result['exit_code']}")
        
        # 4. Проверяем результаты
        print("\n4️⃣  Проверяем результаты...")
        check_results = run_ssh_command(ssh_host, ssh_port, "ls -la /workspace/outputs/ && find /workspace/outputs/ -type f -name '*.mp4' -o -name '*.gif' | head -10")
        
        if check_results['success']:
            print("📁 Содержимое outputs/:")
            print(check_results['output'])
        else:
            print(f"❌ Ошибка проверки результатов: {check_results['error']}")
        
        return True
    else:
        print(f"❌ Ошибка запуска генерации: {result['error']}")
        return False

def main():
    """Основная функция."""
    print("="*80)
    print("🚀 АВТОМАТИЧЕСКИЙ ЗАПУСК ГЕНЕРАЦИИ ВИДЕО НА Vast AI")
    print("="*80)
    
    # Получаем API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    # Загружаем информацию об инстансе
    try:
        with open('/tmp/vastai_instance_info.json', 'r') as f:
            instance_info = json.load(f)
        instance_id = instance_info.get('instance_id')
        print(f"📊 Инстанс ID: {instance_id}")
    except FileNotFoundError:
        print("❌ Файл с информацией об инстансе не найден")
        print("   Сначала создайте инстанс с помощью final_vastai_launch.py")
        return 1
    
    # Ожидаем готовности инстанса
    status_info = wait_for_instance_ready(instance_id, api_key, max_wait_minutes=60)
    
    if not status_info:
        print("❌ Инстанс не готов в течение 60 минут")
        print("   Проверьте в веб-интерфейсе: https://cloud.vast.ai/instances/")
        return 1
    
    ssh_host = status_info['ssh_host']
    ssh_port = status_info['ssh_port']
    
    print(f"\n🔗 SSH информация:")
    print(f"   Хост: {ssh_host}")
    print(f"   Порт: {ssh_port}")
    print(f"   Команда подключения: ssh -p {ssh_port} root@{ssh_host}")
    
    # Сохраняем SSH информацию
    ssh_info = {
        'instance_id': instance_id,
        'ssh_host': ssh_host,
        'ssh_port': ssh_port,
        'ready_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    with open('/tmp/vastai_ssh_ready.json', 'w') as f:
        json.dump(ssh_info, f, indent=2)
    
    print(f"💾 SSH информация сохранена в /tmp/vastai_ssh_ready.json")
    
    # Запускаем генерацию видео
    success = run_video_generation(ssh_host, ssh_port)
    
    if success:
        print("\n" + "="*80)
        print("🎉 ГЕНЕРАЦИЯ ВИДЕО УСПЕШНО ЗАПУЩЕНА!")
        print("="*80)
        print("\n📋 Что сделано:")
        print("   1. Инстанс создан и готов")
        print("   2. Проверен диск и рабочая директория")
        print("   3. Запущена генерация видео")
        print("   4. Результаты будут в /workspace/outputs/")
        
        print(f"\n🔗 Для ручной проверки:")
        print(f"   ssh -p {ssh_port} root@{ssh_host}")
        print(f"   cd /workspace/outputs/ && ls -la")
        
        print(f"\n💰 Не забудьте остановить инстанс после завершения:")
        print(f"   curl -X PUT -H \"Authorization: Bearer {api_key[:20]}...\" \\")
        print(f"     https://console.vast.ai/api/v0/instances/{instance_id}/stop/")
        
        return 0
    else:
        print("\n" + "="*80)
        print("❌ ОШИБКА ПРИ ЗАПУСКЕ ГЕНЕРАЦИИ")
        print("="*80)
        print("\n🔧 Для отладки:")
        print(f"   1. Подключитесь вручную: ssh -p {ssh_port} root@{ssh_host}")
        print(f"   2. Проверьте рабочую директорию: cd /workspace && ls -la")
        print(f"   3. Проверьте код: ls -la src/entrypoints/")
        print(f"   4. Попробуйте запустить вручную:")
        print(f"      python -m src.entrypoints.run_gen --help")
        
        return 1

if __name__ == "__main__":
    sys.exit(main())