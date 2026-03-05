#!/usr/bin/env python3
"""
Запуск инстанса Vast AI с правильными параметрами:
- Минимум 100GB диск
- Минимум 24GB VRAM
- SSH доступ
- Команда для отладки
"""

import os
import json
import subprocess
import sys
import time

def check_existing_instances():
    """Проверить существующие инстансы."""
    print("🔍 Проверка существующих инстансов...")
    
    cmd = [sys.executable, "vast/vast_submit.py", "--list-offers", "--list-count", "1"]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if "Listing up to" in result.stdout:
            print("✅ Скрипт vast_submit работает")
        else:
            print(f"⚠️  Неожиданный вывод: {result.stdout[:200]}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False
    
    return True

def create_instance_with_ssh():
    """Создать инстанс с SSH доступом."""
    print("\n🚀 Создание нового инстанса с правильными параметрами...")
    
    # Команда для отладки - просто ждем
    debug_cmd = "sleep 3600"  # 1 час для отладки
    
    # Параметры запуска
    cmd = [
        sys.executable,
        "vast/vast_submit.py",
        "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "--cmd", debug_cmd,
        "--min-vram", "24",  # 24GB VRAM минимум
        "--max-price", "1.0",  # До $1/час
        "--wait-running",  # Ждем запуска
        "--max-hours", "2"  # Максимум 2 часа
    ]
    
    print(f"🔧 Параметры запуска:")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    print(f"   Min VRAM: 24GB")
    print(f"   Max цена: $1.0/час")
    print(f"   Команда: {debug_cmd}")
    print(f"   Max время: 2 часа")
    
    print(f"\n⚠️  ВНИМАНИЕ: Docker образ 40GB, загрузка займет 20-40 минут")
    print("   Убедитесь что у инстанса достаточно диска (минимум 100GB)")
    
    confirm = input("\nПродолжить? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено пользователем")
        return None
    
    print(f"\n⏳ Запуск инстанса...")
    print("=" * 60)
    
    try:
        # Запускаем процесс
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
        
        # Ждем завершения
        process.wait()
        
        # Получаем stderr
        stderr = process.stderr.read()
        if stderr:
            print(f"\n⚠️  STDERR:")
            print(f"   {stderr[:500]}")
        
        # Парсим ID инстанса из вывода
        instance_id = None
        for line in output_lines:
            if "new_contract" in line or "instance id:" in line.lower():
                # Ищем число в строке
                import re
                numbers = re.findall(r'\d+', line)
                if numbers:
                    instance_id = int(numbers[-1])
                    break
        
        print("\n" + "=" * 60)
        if process.returncode == 0 and instance_id:
            print(f"✅ Инстанс создан! ID: {instance_id}")
            return instance_id
        else:
            print(f"❌ Ошибка создания инстанса (код: {process.returncode})")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка запуска процесса: {e}")
        return None

def monitor_instance_loading(instance_id):
    """Мониторить загрузку инстанса."""
    print(f"\n📊 Мониторинг загрузки инстанса {instance_id}...")
    print("   Docker образ 40GB загружается...")
    print("   Это может занять 20-40 минут")
    print("   Нажмите Ctrl+C для прерывания")
    
    try:
        # Будем проверять статус каждые 2 минуты
        for i in range(30):  # 30 * 2 = 60 минут максимум
            print(f"\n⏱️  Проверка {i+1}/30 (прошло {i*2} минут)...")
            
            # Используем vast_submit для проверки статуса
            check_cmd = [
                sys.executable,
                "vast/vast_submit.py",
                "--offer-id", str(instance_id),
                "--offline"
            ]
            
            try:
                result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=30)
                output = result.stdout.lower()
                
                if "running" in output:
                    print("✅ Инстанс запущен и готов!")
                    
                    # Пробуем получить SSH информацию
                    if "ssh_port" in output or "ssh" in output:
                        print("🔑 SSH доступ настроен")
                        # Парсим SSH информацию
                        lines = result.stdout.split('\n')
                        for line in lines:
                            if "ssh" in line.lower() and "port" in line.lower():
                                print(f"   {line.strip()}")
                            if "public_ip" in line.lower() or "ipaddr" in line.lower():
                                print(f"   {line.strip()}")
                    
                    return True
                    
                elif "loading" in output or "starting" in output:
                    print("   Статус: загрузка...")
                elif "failed" in output or "error" in output:
                    print("❌ Инстанс завершился с ошибкой")
                    return False
                else:
                    print(f"   Статус: неизвестен")
                    print(f"   Вывод: {output[:200]}")
                    
            except Exception as e:
                print(f"   Ошибка проверки: {e}")
            
            # Ждем 2 минуты
            time.sleep(120)
        
        print("⏱️  Таймаут ожидания (60 минут)")
        return False
        
    except KeyboardInterrupt:
        print("\n⏹️  Мониторинг прерван пользователем")
        return False

def get_ssh_connection_info(instance_id):
    """Получить информацию для SSH подключения."""
    print(f"\n🔑 Получение SSH информации для инстанса {instance_id}...")
    
    # Пробуем получить информацию через API
    import requests
    
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ VAST_API_KEY не установлен")
        return None
    
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://console.vast.ai/api/v0/instances/{instance_id}/"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 200:
            data = response.json()
            instance = data.get('instances', {})
            
            ssh_port = instance.get('ssh_port')
            ssh_host = instance.get('public_ipaddr')
            
            if ssh_port and ssh_host:
                print(f"✅ SSH информация получена:")
                print(f"   Host: {ssh_host}")
                print(f"   Port: {ssh_port}")
                print(f"\n🔌 Команда для подключения:")
                print(f"   ssh -p {ssh_port} root@{ssh_host}")
                print(f"\n📝 Пароль: будет запрошен при первом подключении")
                
                return {"host": ssh_host, "port": ssh_port}
            else:
                print(f"⚠️  SSH информация недоступна")
                print(f"   Jupyter токен: {instance.get('jupyter_token', 'N/A')[:20]}...")
                return None
                
        else:
            print(f"❌ Ошибка API: {response.status_code}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return None

def main():
    """Основная функция."""
    print("=" * 60)
    print("🚀 Запуск инстанса Vast AI с правильными параметрами")
    print("=" * 60)
    
    # Проверяем API ключ
    if not os.environ.get('VAST_API_KEY'):
        print("❌ Ошибка: VAST_API_KEY не установлен")
        print("   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    # 1. Проверяем существующие инстансы
    if not check_existing_instances():
        print("❌ Проблема с проверкой инстансов")
        return 1
    
    # 2. Создаем новый инстанс
    instance_id = create_instance_with_ssh()
    if not instance_id:
        print("❌ Не удалось создать инстанс")
        return 1
    
    # 3. Мониторим загрузку
    print(f"\n" + "=" * 60)
    print(f"🔄 Мониторинг загрузки инстанса {instance_id}")
    print("=" * 60)
    
    loaded = monitor_instance_loading(instance_id)
    
    if loaded:
        # 4. Получаем SSH информацию
        print(f"\n" + "=" * 60)
        print(f"🔧 Настройка доступа к инстансу {instance_id}")
        print("=" * 60)
        
        ssh_info = get_ssh_connection_info(instance_id)
        
        if ssh_info:
            print(f"\n🎉 Готово! Инстанс настроен для отладки")
            print(f"\n📋 Дальнейшие действия:")
            print(f"   1. Подключитесь по SSH:")
            print(f"      ssh -p {ssh_info['port']} root@{ssh_info['host']}")
            print(f"   2. Проверьте загрузку Docker образа:")
            print(f"      docker ps")
            print(f"      docker images")
            print(f"   3. Запустите генерацию видео вручную:")
            print(f"      cd /workspace")
            print(f"      python -m src.entrypoints.run_gen --help")
            print(f"   4. После отладки остановите инстанс:")
            print(f"      vast.ai консоль -> Instances -> Stop")
        else:
            print(f"\n⚠️  SSH не настроен, но инстанс запущен")
            print(f"   Проверьте консоль Vast AI для Jupyter доступа")
    else:
        print(f"\n❌ Проблема с загрузкой инстанса")
        print(f"   Проверьте логи в консоли Vast AI")
    
    print(f"\n" + "=" * 60)
    print(f"📊 Итог:")
    print(f"   Инстанс ID: {instance_id}")
    print(f"   Статус: {'готов' if loaded else 'проблема'}")
    print(f"   Стоимость: ~$0.10-$0.50/час")
    print(f"\n🔗 Консоль управления: https://vast.ai/")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())