#!/usr/bin/env python3
"""
Автоматическая генерация видео на инстансе Vast AI через CLI.
"""

import os
import sys
import json
import time
import subprocess
import paramiko
from datetime import datetime

def check_instance_status(instance_id):
    """Проверить статус инстанса через Vast CLI."""
    try:
        result = subprocess.run(
            ["./vast.py", "show", "instance", str(instance_id)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 3:
                # Парсим строку с данными
                data_line = lines[2]
                parts = data_line.split()
                
                if len(parts) >= 15:
                    return {
                        'status': 'running' if parts[2] != '-' else 'loading',
                        'ssh_host': parts[10],
                        'ssh_port': parts[11],
                        'gpu_model': parts[5],
                        'price_per_hour': parts[12],
                        'internet_up': parts[13],
                        'internet_down': parts[14],
                        'success': True
                    }
        
        return {'success': False, 'status': 'unknown'}
        
    except Exception as e:
        print(f"❌ Ошибка проверки статуса: {e}")
        return {'success': False, 'status': 'error'}

def run_ssh_command(host, port, command, timeout=300):
    """Выполнить команду по SSH."""
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname=host, port=int(port), username='root', timeout=10)
        
        print(f"✅ Подключение SSH успешно: {host}:{port}")
        
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        output = stdout.read().decode('utf-8', errors='ignore')
        error = stderr.read().decode('utf-8', errors='ignore')
        
        ssh.close()
        
        return {
            'success': True,
            'output': output,
            'error': error
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

def main():
    print("🚀 АВТОМАТИЧЕСКАЯ ГЕНЕРАЦИЯ ВИДЕО НА Vast AI")
    print("="*60)
    
    # ID инстанса
    instance_id = 32437368
    
    print(f"📊 ИНФОРМАЦИЯ ОБ ИНСТАНСЕ:")
    print(f"   ID: {instance_id}")
    print(f"   GPU: RTX 3090 (24GB VRAM)")
    print(f"   Диск: 100GB")
    print(f"   Цена: $0.1622/час")
    print()
    
    print("🔍 ПРОВЕРЯЕМ СТАТУС ИНСТАНСА...")
    
    max_checks = 48  # 4 часа
    check_interval = 300  # 5 минут
    
    for check in range(1, max_checks + 1):
        print(f"\n📊 Проверка {check}/{max_checks}")
        print(f"   Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   Осталось проверок: {max_checks - check}")
        print("-" * 40)
        
        status_info = check_instance_status(instance_id)
        
        if status_info['success']:
            status = status_info['status']
            ssh_host = status_info.get('ssh_host')
            ssh_port = status_info.get('ssh_port')
            gpu_model = status_info.get('gpu_model')
            price = status_info.get('price_per_hour')
            internet_up = status_info.get('internet_up')
            internet_down = status_info.get('internet_down')
            
            print(f"   Статус: {status.upper()}")
            print(f"   GPU: {gpu_model}")
            print(f"   Цена: ${price}/час")
            print(f"   Интернет: ↓{internet_down}Mbps / ↑{internet_up}Mbps")
            
            if ssh_host and ssh_port:
                print(f"   SSH: {ssh_host}:{ssh_port}")
            
            if status == 'running' and ssh_port:
                print("\n" + "="*60)
                print("🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                print("="*60)
                print()
                
                # Конфигурация генерации видео
                job_config = {
                    'mode': 'text2video',
                    'prompts': [
                        'A beautiful sunset over mountains with clouds, cinematic, 4k, masterpiece',
                        'A futuristic city at night with flying cars and neon lights, cyberpunk style'
                    ],
                    'num_frames': 24,
                    'fps': 8,
                    'num_inference_steps': 25,
                    'output_dir': '/workspace/outputs',
                    'seed': 42,
                    'height': 512,
                    'width': 512
                }
                
                print("🚀 ЗАПУСКАЕМ ГЕНЕРАЦИЮ ВИДЕО...")
                print()
                print("📝 КОНФИГУРАЦИЯ:")
                print(json.dumps(job_config, indent=2))
                print()
                
                # Подготавливаем команду
                job_json = json.dumps(job_config).replace('"', '\\"')
                command = f'''cd /workspace && python -m src.entrypoints.run_gen --job '{job_json}' --verbose'''
                
                print(f"🔧 КОМАНДА:")
                print(command)
                print()
                print("⏳ ЗАПУСКАЕМ...")
                
                # Запускаем генерацию
                result = run_ssh_command(ssh_host, ssh_port, command, timeout=600)
                
                if result['success']:
                    print("✅ ГЕНЕРАЦИЯ ЗАПУЩЕНА!")
                    print()
                    print("📤 ВЫВОД:")
                    print("-" * 50)
                    
                    # Показываем последние 2000 символов вывода
                    if result['output']:
                        output_preview = result['output'][-2000:] if len(result['output']) > 2000 else result['output']
                        print(output_preview)
                    
                    print("-" * 50)
                    
                    if result['error']:
                        print("⚠️  ОШИБКИ:")
                        error_preview = result['error'][-1000:] if len(result['error']) > 1000 else result['error']
                        print(error_preview)
                    
                    print()
                    print("🔍 ПРОВЕРЯЕМ РЕЗУЛЬТАТЫ...")
                    
                    # Проверяем созданные файлы
                    check_cmd = "ls -la /workspace/outputs/ 2>/dev/null || echo 'Директория outputs не найдена'"
                    check_result = run_ssh_command(ssh_host, ssh_port, check_cmd, timeout=30)
                    
                    if check_result['success']:
                        print("📁 СОДЕРЖИМОЕ /workspace/outputs/:")
                        print(check_result['output'])
                    
                    print()
                    print("✅ ГЕНЕРАЦИЯ ЗАВЕРШЕНА!")
                    print()
                    print("💰 НЕ ЗАБУДЬТЕ ОСТАНОВИТЬ ИНСТАНС:")
                    print(f"   ./vast.py stop instance {instance_id}")
                    print(f"   Или: ./vast.py destroy instance {instance_id}")
                    print()
                    print("📊 СТАТИСТИКА:")
                    print(f"   - Время ожидания: {(check-1)*5} минут")
                    print(f"   - Стоимость ожидания: ${(check-1)*5/60*0.1622:.3f}")
                    print(f"   - Стоимость генерации: ~$0.05-0.10")
                    print(f"   - Общая стоимость: ${(check-1)*5/60*0.1622 + 0.08:.3f}")
                    
                else:
                    print(f"❌ Ошибка запуска генерации: {result['error']}")
                
                return 0
                
            elif status == 'loading':
                print(f"   ⏳ Загрузка Docker образа...")
                print(f"   Прогресс: {check}/{max_checks} проверок")
                
                # Оцениваем оставшееся время
                if check > 1:
                    remaining_minutes = (max_checks - check) * 5
                    print(f"   Осталось ждать: ~{remaining_minutes} минут")
                    print(f"   Примерное время готовности: {(datetime.now().timestamp() + remaining_minutes*60):%H:%M}")
                    
            else:
                print(f"   Статус: {status}")
                
        else:
            print(f"   ⚠️  Не удалось получить статус")
        
        # Ждем перед следующей проверкой
        if check < max_checks:
            print(f"\n⏳ Следующая проверка через 5 минут...")
            for i in range(5):
                time.sleep(60)
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
    print(f"   ./vast.py show instance {instance_id}")
    print()
    
    return 1

if __name__ == "__main__":
    # Устанавливаем paramiko если нужно
    try:
        import paramiko
    except ImportError:
        print("📦 Устанавливаем paramiko...")
        subprocess.run([sys.executable, "-m", "pip", "install", "paramiko", "-q"])
        import paramiko
    
    sys.exit(main())