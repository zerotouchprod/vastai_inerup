#!/usr/bin/env python3
"""
Автоматический мониторинг инстанса Vast AI.
Проверяет статус каждые 5 минут и сохраняет информацию.
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timedelta
import signal

INSTANCE_ID = 32437368
CHECK_INTERVAL = 300  # 5 минут
MAX_CHECKS = 48  # 4 часа
STATUS_FILE = "/tmp/vastai_instance_status.json"
READY_FILE = "/tmp/vastai_instance_ready.trigger"
LOG_FILE = "/tmp/vastai_monitor.log"

def log_message(message):
    """Записать сообщение в лог."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    
    with open(LOG_FILE, "a") as f:
        f.write(log_entry)
    
    print(log_entry.strip())

def check_instance_status():
    """Проверить статус инстанса через Vast CLI."""
    try:
        result = subprocess.run(
            ["./vast.py", "show", "instance", str(INSTANCE_ID)],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            
            # Парсим вывод
            if len(lines) >= 3:
                data_line = lines[2]
                parts = data_line.split()
                
                if len(parts) >= 15:
                    status = parts[2]
                    ssh_host = parts[10] if len(parts) > 10 else ""
                    ssh_port = parts[11] if len(parts) > 11 else ""
                    gpu_model = parts[5] if len(parts) > 5 else ""
                    price = parts[12] if len(parts) > 12 else ""
                    
                    return {
                        'success': True,
                        'status': 'running' if status == 'running' else 'loading',
                        'ssh_host': ssh_host,
                        'ssh_port': ssh_port,
                        'gpu_model': gpu_model,
                        'price_per_hour': price,
                        'raw_output': result.stdout
                    }
        
        return {'success': False, 'status': 'unknown', 'error': 'parse_error'}
        
    except subprocess.TimeoutExpired:
        return {'success': False, 'status': 'timeout'}
    except Exception as e:
        return {'success': False, 'status': 'error', 'error': str(e)}

def save_status_info(status_info):
    """Сохранить информацию о статусе."""
    status_data = {
        'instance_id': INSTANCE_ID,
        'last_check': datetime.now().isoformat(),
        'status': status_info.get('status', 'unknown'),
        'ssh_host': status_info.get('ssh_host', ''),
        'ssh_port': status_info.get('ssh_port', ''),
        'gpu_model': status_info.get('gpu_model', ''),
        'price_per_hour': status_info.get('price_per_hour', ''),
        'ready': status_info.get('status') == 'running' and status_info.get('ssh_port'),
        'checks_completed': 0,
        'next_check': (datetime.now() + timedelta(seconds=CHECK_INTERVAL)).isoformat()
    }
    
    with open(STATUS_FILE, "w") as f:
        json.dump(status_data, f, indent=2)
    
    return status_data

def create_ready_trigger(status_info):
    """Создать файл-триггер когда инстанс готов."""
    ready_data = {
        'instance_id': INSTANCE_ID,
        'ready_time': datetime.now().isoformat(),
        'ssh_host': status_info.get('ssh_host', ''),
        'ssh_port': status_info.get('ssh_port', ''),
        'gpu_model': status_info.get('gpu_model', ''),
        'price_per_hour': status_info.get('price_per_hour', ''),
        'command': f"ssh -p {status_info.get('ssh_port', '')} root@{status_info.get('ssh_host', '')}",
        'generation_command': f"cd /workspace && python -m src.entrypoints.run_gen --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"]}}'"
    }
    
    with open(READY_FILE, "w") as f:
        json.dump(ready_data, f, indent=2)
    
    # Создаем простой текстовый файл для быстрого просмотра
    with open("/tmp/vastai_ready.txt", "w") as f:
        f.write(f"🎉 ИНСТАНС ГОТОВ К РАБОТЕ!\n")
        f.write(f"================================\n")
        f.write(f"ID: {INSTANCE_ID}\n")
        f.write(f"GPU: {status_info.get('gpu_model', '')}\n")
        f.write(f"SSH: {status_info.get('ssh_host', '')}:{status_info.get('ssh_port', '')}\n")
        f.write(f"Цена: ${status_info.get('price_per_hour', '')}/час\n")
        f.write(f"\n")
        f.write(f"🚀 ДЛЯ ЗАПУСКА:\n")
        f.write(f"ssh -p {status_info.get('ssh_port', '')} root@{status_info.get('ssh_host', '')}\n")
        f.write(f"cd /workspace\n")
        f.write(f"python -m src.entrypoints.run_gen \\\n")
        f.write(f"  --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"]}}'\n")
        f.write(f"\n")
        f.write(f"💰 ОСТАНОВИТЬ ИНСТАНС:\n")
        f.write(f"./vast.py stop instance {INSTANCE_ID}\n")
    
    return ready_data

def signal_handler(signum, frame):
    """Обработчик сигналов для graceful shutdown."""
    log_message(f"📴 Получен сигнал {signum}, завершаем мониторинг...")
    sys.exit(0)

def main():
    """Основная функция мониторинга."""
    # Настраиваем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    log_message(f"🚀 ЗАПУСК АВТОМАТИЧЕСКОГО МОНИТОРИНГА")
    log_message(f"Инстанс ID: {INSTANCE_ID}")
    log_message(f"Интервал проверки: {CHECK_INTERVAL} секунд")
    log_message(f"Максимум проверок: {MAX_CHECKS}")
    log_message(f"Лог файл: {LOG_FILE}")
    log_message(f"Файл статуса: {STATUS_FILE}")
    log_message(f"Файл готовности: {READY_FILE}")
    log_message("=" * 50)
    
    checks_completed = 0
    
    while checks_completed < MAX_CHECKS:
        checks_completed += 1
        
        log_message(f"📊 Проверка {checks_completed}/{MAX_CHECKS}")
        log_message(f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Проверяем статус
        status_info = check_instance_status()
        
        if status_info['success']:
            status = status_info['status']
            ssh_port = status_info.get('ssh_port')
            
            # Сохраняем статус
            status_data = save_status_info(status_info)
            status_data['checks_completed'] = checks_completed
            
            if status == 'running' and ssh_port:
                log_message("🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                log_message(f"GPU: {status_info.get('gpu_model', '')}")
                log_message(f"SSH: {status_info.get('ssh_host', '')}:{ssh_port}")
                log_message(f"Цена: ${status_info.get('price_per_hour', '')}/час")
                
                # Создаем файл-триггер
                ready_data = create_ready_trigger(status_info)
                
                log_message(f"✅ Файл готовности создан: {READY_FILE}")
                log_message(f"✅ Текстовый файл: /tmp/vastai_ready.txt")
                log_message(f"✅ Проверок выполнено: {checks_completed}")
                log_message(f"✅ Время ожидания: {(checks_completed-1)*5} минут")
                
                # Сохраняем финальный статус
                with open(STATUS_FILE, "w") as f:
                    json.dump(status_data, f, indent=2)
                
                log_message("=" * 50)
                log_message("📋 ИНСТРУКЦИЯ:")
                log_message(f"1. Проверьте файл: cat /tmp/vastai_ready.txt")
                log_message(f"2. Подключитесь: ssh -p {ssh_port} root@{status_info.get('ssh_host', '')}")
                log_message(f"3. Запустите генерацию: cd /workspace && python -m src.entrypoints.run_gen")
                log_message(f"4. Остановите инстанс: ./vast.py stop instance {INSTANCE_ID}")
                
                return 0
                
            elif status == 'loading':
                log_message(f"⏳ Загрузка Docker образа...")
                log_message(f"Прогресс: {checks_completed}/{MAX_CHECKS} проверок")
                
                if checks_completed > 1:
                    remaining_minutes = (MAX_CHECKS - checks_completed) * 5
                    log_message(f"Осталось ждать: ~{remaining_minutes} минут")
                    
                    ready_time = datetime.now() + timedelta(minutes=remaining_minutes)
                    log_message(f"Примерное время готовности: {ready_time.strftime('%H:%M')}")
            else:
                log_message(f"Статус: {status}")
        else:
            log_message(f"⚠️ Не удалось получить статус: {status_info.get('error', 'unknown')}")
        
        # Сохраняем текущий статус
        status_data = save_status_info(status_info)
        status_data['checks_completed'] = checks_completed
        
        # Ждем перед следующей проверкой
        if checks_completed < MAX_CHECKS:
            next_check = datetime.now() + timedelta(seconds=CHECK_INTERVAL)
            log_message(f"⏳ Следующая проверка: {next_check.strftime('%H:%M:%S')}")
            
            # Ждем с периодическими сообщениями
            for i in range(CHECK_INTERVAL // 60):  # Каждую минуту
                time.sleep(60)
                if i % 5 == 4:  # Каждые 5 минут
                    remaining = CHECK_INTERVAL // 60 - i - 1
                    log_message(f"   Осталось: {remaining} минут до следующей проверки")
        
        log_message("-" * 40)
    
    # Если превышено время ожидания
    log_message("❌ ПРЕВЫШЕНО ВРЕМЯ ОЖИДАНИЯ (4 часа)")
    log_message(f"Проверок выполнено: {checks_completed}")
    log_message(f"Время ожидания: {checks_completed * 5} минут")
    
    final_status = {
        'instance_id': INSTANCE_ID,
        'status': 'timeout',
        'last_check': datetime.now().isoformat(),
        'checks_completed': checks_completed,
        'message': 'Превышено время ожидания (4 часа)',
        'recommendation': 'Проверьте инстанс вручную: ./vast.py show instance 32437368'
    }
    
    with open(STATUS_FILE, "w") as f:
        json.dump(final_status, f, indent=2)
    
    return 1

if __name__ == "__main__":
    sys.exit(main())