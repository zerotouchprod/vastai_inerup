#!/usr/bin/env python3
"""
Запуск инстанса Vast AI с мониторингом.
Постоянно проверяет:
1. Размер диска (должен быть >= 100GB)
2. Статус инстанса
3. Останавливает если проблемы
"""

import os
import json
import requests
import sys
import time
import subprocess
from datetime import datetime

def check_existing_instances():
    """Проверить существующие инстансы и остановить проблемные."""
    print("🔍 Проверка существующих инстансов...")
    
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ VAST_API_KEY не установлен")
        return []
    
    headers = {"Authorization": f"Bearer {api_key}"}
    url = "https://console.vast.ai/api/v0/instances/"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            instances = data.get('instances', [])
            
            print(f"Найдено инстансов: {len(instances)}")
            
            problematic_instances = []
            
            for instance in instances:
                instance_id = instance.get('id')
                status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                disk_gb = instance.get('disk_space', 0)
                price = instance.get('dph_total', 0)
                
                print(f"\n  Инстанс {instance_id}:")
                print(f"    Статус: {status}")
                print(f"    Диск: {disk_gb}GB")
                print(f"    Цена: ${price:.3f}/час")
                
                # Проверяем критерии
                problems = []
                
                if disk_gb < 100:
                    problems.append(f"Диск {disk_gb}GB < 100GB")
                
                if price > 1.0:
                    problems.append(f"Цена ${price:.3f}/час > $1.0/час")
                
                if status == 'failed':
                    problems.append("Инстанс завершился с ошибкой")
                
                if problems:
                    print(f"    ❌ Проблемы:")
                    for problem in problems:
                        print(f"      - {problem}")
                    
                    # Если инстанс активен и имеет проблемы - останавливаем
                    if status in ['running', 'loading', 'starting']:
                        print(f"    ⚠️  Останавливаем...")
                        
                        stop_url = f"https://console.vast.ai/api/v0/instances/{instance_id}/"
                        try:
                            stop_response = requests.put(stop_url, headers=headers, json={"state": "stopped"}, timeout=30)
                            if stop_response.status_code == 200:
                                print(f"    ✅ Остановлен")
                                problematic_instances.append(instance_id)
                            else:
                                print(f"    ❌ Ошибка остановки: {stop_response.status_code}")
                        except Exception as e:
                            print(f"    ❌ Ошибка: {e}")
                else:
                    print(f"    ✅ Соответствует критериям")
            
            return problematic_instances
            
        else:
            print(f"❌ Ошибка получения инстансов: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return []

def create_proper_instance():
    """Создать инстанс с правильными параметрами."""
    print("\n🚀 Создание нового инстанса...")
    
    # Используем vast_submit.py с минимальными параметрами
    cmd = [
        sys.executable,
        "vast/vast_submit.py",
        "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "--cmd", "echo 'Starting debug session...' && df -h && sleep 3600",
        "--min-vram", "16",
        "--max-price", "0.8",
        "--wait-running"
    ]
    
    print(f"🔧 Параметры:")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    print(f"   Min VRAM: 16GB")
    print(f"   Max цена: $0.8/час")
    print(f"   Команда: проверка диска + sleep 1 час")
    
    print(f"\n⚠️  ВНИМАНИЕ:")
    print(f"   • Docker образ 40GB")
    print(f"   • Нужен диск минимум 100GB")
    print(f"   • vast_submit.py может создать инстанс с 10GB диском")
    print(f"   • Мониторинг проверит и остановит если диск мал")
    
    confirm = input("\nПродолжить? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено")
        return None
    
    print(f"\n⏳ Запуск инстанса...")
    print("=" * 60)
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Читаем вывод
        output_lines = []
        for line in process.stdout:
            print(f"   {line.strip()}")
            output_lines.append(line.strip())
            sys.stdout.flush()
        
        process.wait()
        
        # Парсим ID инстанса
        instance_id = None
        for line in output_lines:
            if "new_contract" in line:
                import re
                numbers = re.findall(r'\d+', line)
                if numbers:
                    instance_id = int(numbers[-1])
                    break
            elif "instance id:" in line.lower():
                import re
                numbers = re.findall(r'\d+', line)
                if numbers:
                    instance_id = int(numbers[-1])
                    break
        
        if process.returncode == 0 and instance_id:
            print(f"\n✅ Инстанс создан! ID: {instance_id}")
            return instance_id
        else:
            print(f"\n❌ Ошибка создания инстанса")
            if process.stderr:
                print(f"   STDERR: {process.stderr.read()[:500]}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

def monitor_instance(instance_id, check_interval_minutes=2, max_checks=30):
    """Мониторить инстанс."""
    print(f"\n📊 Запуск мониторинга инстанса {instance_id}...")
    print(f"   Интервал: {check_interval_minutes} минут")
    print(f"   Макс. проверок: {max_checks}")
    print(f"   Нажмите Ctrl+C для остановки")
    
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ VAST_API_KEY не установлен")
        return
    
    headers = {"Authorization": f"Bearer {api_key}"}
    base_url = "https://console.vast.ai/api/v0"
    
    check_count = 0
    instance_ready = False
    
    try:
        while not instance_ready and check_count < max_checks:
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
                        time.sleep(check_interval_minutes * 60)
                        continue
                    
                    status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                    disk_gb = instance.get('disk_space', 0)
                    price = instance.get('dph_total', 0)
                    ssh_port = instance.get('ssh_port')
                    public_ip = instance.get('public_ipaddr', 'N/A')
                    
                    print(f"🔍 Статус инстанса {instance_id}:")
                    print(f"   Статус: {status}")
                    print(f"   Диск: {disk_gb}GB")
                    print(f"   Цена: ${price:.3f}/час")
                    print(f"   SSH порт: {ssh_port or 'N/A'}")
                    print(f"   IP: {public_ip}")
                    
                    # Проверяем критерии
                    problems = []
                    
                    if disk_gb < 100:
                        problems.append(f"Диск {disk_gb}GB < 100GB")
                    
                    if price > 1.0:
                        problems.append(f"Цена ${price:.3f}/час > $1.0/час")
                    
                    if status == 'failed':
                        problems.append("Инстанс завершился с ошибкой")
                    
                    if problems:
                        print(f"\n❌ Проблемы обнаружены:")
                        for problem in problems:
                            print(f"   - {problem}")
                        
                        # Если серьезные проблемы - останавливаем
                        if status in ['failed', 'stopped'] or disk_gb < 80:
                            print(f"\n⚠️  Серьезные проблемы! Останавливаем инстанс...")
                            
                            stop_url = f"{base_url}/instances/{instance_id}/"
                            stop_response = requests.put(stop_url, headers=headers, json={"state": "stopped"}, timeout=30)
                            
                            if stop_response.status_code == 200:
                                print(f"✅ Инстанс остановлен")
                                break
                            else:
                                print(f"❌ Ошибка остановки: {stop_response.status_code}")
                                break
                        else:
                            print(f"⚠️  Есть проблемы, но продолжаем мониторинг")
                    
                    else:
                        print(f"\n✅ Инстанс соответствует критериям")
                        
                        # Проверяем готовность
                        if status == 'running' and ssh_port:
                            print(f"\n🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
                            print(f"\n🔗 SSH подключение:")
                            print(f"   ssh -p {ssh_port} root@{public_ip}")
                            
                            print(f"\n🎬 Запуск генерации видео:")
                            print(f"   cd /workspace")
                            print(f"   python -m src.entrypoints.run_gen \\")
                            print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"test prompt\"]}}'")
                            
                            print(f"\n💰 Стоимость:")
                            print(f"   Цена: ${price:.3f}/час")
                            print(f"   Загрузка Docker: 20-40 мин = $0.10-$0.30")
                            print(f"   Генерация: 5-15 мин = $0.05-$0.15")
                            print(f"   Итого: $0.15-$0.45")
                            
                            instance_ready = True
                            break
                
                else:
                    print(f"❌ Ошибка API: {response.status_code}")
                    
            except Exception as e:
                print(f"❌ Ошибка запроса: {e}")
            
            # Ждем перед следующей проверкой
            if not instance_ready and check_count < max_checks:
                print(f"\n⏳ Следующая проверка через {check_interval_minutes} минут...")
                time.sleep(check_interval_minutes * 60)
        
        if not instance_ready:
            print(f"\n⏱️  Достигнут лимит проверок ({max_checks})")
            print(f"   Инстанс все еще не готов")
        
    except KeyboardInterrupt:
        print(f"\n\n⏹️  Мониторинг остановлен пользователем")
    
    print(f"\n" + "=" * 60)
    print(f"📊 ИТОГ МОНИТОРИНГА")
    print("=" * 60)
    print(f"Инстанс ID: {instance_id}")
    print(f"Проверок выполнено: {check_count}")
    print(f"Статус: {'готов' if instance_ready else 'не готов'}")
    
    if instance_ready:
        print(f"\n🎉 Инстанс готов! Подключайтесь по SSH и запускайте генерацию!")
    else:
        print(f"\n⚠️  Инстанс не готов или имеет проблемы")
        print(f"   Проверьте консоль Vast AI: https://vast.ai/")
        print(f"   Instances -> {instance_id}")
    
    return instance_ready

def main():
    """Основная функция."""
    print("=" * 80)
    print("🚀 ЗАПУСК И МОНИТОРИНГ ИНСТАНСА Vast AI")
    print("=" * 80)
    
    # Проверка API ключа
    if not os.environ.get('VAST_API_KEY'):
        print("❌ Ошибка: VAST_API_KEY не установлен")
        print("   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    # 1. Проверить и остановить проблемные инстансы
    print("\n1. 🔍 Проверка существующих инстансов...")
    stopped_instances = check_existing_instances()
    
    if stopped_instances:
        print(f"\n✅ Остановлено проблемных инстансов: {len(stopped_instances)}")
        print(f"   ID: {stopped_instances}")
    else:
        print(f"\n✅ Нет проблемных инстансов")
    
    # 2. Создать новый инстанс
    print("\n2. 🚀 Создание нового инстанса...")
    instance_id = create_proper_instance()
    
    if not instance_id:
        print("❌ Не удалось создать инстанс")
        return 1
    
    # 3. Мониторинг инстанса
    print("\n3. 📊 Мониторинг инстанса...")
    ready = monitor_instance(instance_id, check_interval_minutes=2, max_checks=30)
    
    # 4. Итог
    print("\n" + "=" * 80)
    print("🎯 ИТОГ")
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
        print(f"\n🔧 Рекомендации:")
        print(f"   1. Проверьте консоль Vast AI")
        print(f"   2. Убедитесь что диск >= 100GB")
        print(f"   3. Попробуйте создать инстанс вручную через веб-интерфейс")
    
    print(f"\n🔗 Консоль управления: https://vast.ai/")
    print(f"   Instances -> {instance_id}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())