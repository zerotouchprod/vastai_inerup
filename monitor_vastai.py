#!/usr/bin/env python3
"""
Скрипт для мониторинга статуса инстанса Vast AI и настройки SSH доступа.
"""

import os
import json
import time
import requests
import subprocess
import sys

class VastAIMonitor:
    def __init__(self, api_key):
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.base_url = "https://console.vast.ai/api/v0"
    
    def get_instance_status(self, instance_id):
        """Получить статус инстанса."""
        url = f"{self.base_url}/instances/{instance_id}/"
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('instances', {})
            else:
                print(f"Ошибка получения статуса: {response.status_code}")
                return None
        except Exception as e:
            print(f"Ошибка запроса: {e}")
            return None
    
    def wait_for_instance_ready(self, instance_id, timeout_minutes=30):
        """Ожидать пока инстанс станет ready."""
        print(f"⏳ Ожидание готовности инстанса {instance_id}...")
        print(f"   Таймаут: {timeout_minutes} минут")
        
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        last_status = None
        
        while time.time() - start_time < timeout_seconds:
            instance = self.get_instance_status(instance_id)
            if not instance:
                time.sleep(30)
                continue
            
            status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
            
            # Выводим статус только если он изменился
            if status != last_status:
                print(f"   Статус: {status}")
                last_status = status
            
            # Проверяем готовность
            if status == 'running':
                ssh_port = instance.get('ssh_port')
                if ssh_port:
                    print(f"✅ Инстанс готов! SSH порт: {ssh_port}")
                    return instance
                else:
                    print(f"   Инстанс running, но SSH порт еще не назначен")
            
            elif status == 'failed':
                print(f"❌ Инстанс failed")
                return None
            
            # Ждем перед следующей проверкой
            time.sleep(30)
        
        print(f"⏱️  Таймаут ожидания")
        return None
    
    def setup_ssh_access(self, instance_id):
        """Настроить SSH доступ к инстансу."""
        print(f"\n🔧 Настройка SSH доступа для инстанса {instance_id}...")
        
        # Сначала проверим текущий статус
        instance = self.get_instance_status(instance_id)
        if not instance:
            print("❌ Не удалось получить информацию об инстансе")
            return None
        
        ssh_port = instance.get('ssh_port')
        ssh_host = instance.get('public_ipaddr')
        
        if ssh_port and ssh_host:
            print(f"✅ SSH уже настроен:")
            print(f"   Host: {ssh_host}")
            print(f"   Port: {ssh_port}")
            return {"host": ssh_host, "port": ssh_port}
        
        # Если SSH не настроен, попробуем перезапустить инстанс с SSH
        print("⚠️  SSH не настроен. Попробуем перезапустить инстанс...")
        
        # Остановим инстанс
        stop_url = f"{self.base_url}/instances/{instance_id}/"
        stop_data = {"state": "stopped"}
        
        try:
            response = requests.put(stop_url, headers=self.headers, json=stop_data, timeout=30)
            if response.status_code == 200:
                print("✅ Инстанс остановлен")
            else:
                print(f"❌ Ошибка остановки: {response.status_code}")
                return None
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None
        
        # Подождем остановки
        time.sleep(10)
        
        # Запустим инстанс с SSH
        print("🔄 Запуск инстанса с SSH...")
        
        # Получим текущую конфигурацию
        instance = self.get_instance_status(instance_id)
        if not instance:
            print("❌ Не удалось получить конфигурацию")
            return None
        
        # Создадим новую конфигурацию с SSH
        start_data = {
            "state": "running",
            "image": instance.get('image_uuid', ''),
            "args_str": "sleep infinity",  # Простая команда для отладки
            "ssh": True  # Включить SSH
        }
        
        try:
            response = requests.put(stop_url, headers=self.headers, json=start_data, timeout=30)
            if response.status_code == 200:
                print("✅ Инстанс запущен с SSH")
                
                # Подождем и проверим SSH порт
                for _ in range(10):
                    time.sleep(30)
                    instance = self.get_instance_status(instance_id)
                    if instance and instance.get('ssh_port'):
                        ssh_port = instance.get('ssh_port')
                        ssh_host = instance.get('public_ipaddr')
                        print(f"✅ SSH настроен:")
                        print(f"   Host: {ssh_host}")
                        print(f"   Port: {ssh_port}")
                        return {"host": ssh_host, "port": ssh_port}
                
                print("⚠️  SSH порт не назначен после запуска")
                return None
                
            else:
                print(f"❌ Ошибка запуска: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None
    
    def test_ssh_connection(self, host, port):
        """Протестировать SSH соединение."""
        print(f"\n🔌 Тестирование SSH соединения...")
        print(f"   Host: {host}")
        print(f"   Port: {port}")
        
        # Простая проверка с помощью netcat
        try:
            result = subprocess.run(
                ["nc", "-z", "-w", "5", host, str(port)],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                print("✅ Порт открыт")
                return True
            else:
                print(f"❌ Порт закрыт или недоступен")
                print(f"   Ошибка: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка тестирования: {e}")
            return False
    
    def monitor_progress(self, instance_id, check_interval=60):
        """Мониторить прогресс загрузки и выполнения."""
        print(f"\n📊 Мониторинг прогресса инстанса {instance_id}")
        print("=" * 60)
        
        start_time = time.time()
        last_update = start_time
        
        while True:
            current_time = time.time()
            elapsed_minutes = (current_time - start_time) / 60
            
            instance = self.get_instance_status(instance_id)
            if not instance:
                print("❌ Не удалось получить статус")
                time.sleep(check_interval)
                continue
            
            status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
            gpu_util = instance.get('gpu_util')
            cpu_util = instance.get('cpu_util')
            
            # Выводим обновление каждые 2 минуты или при изменении статуса
            if current_time - last_update > 120 or status != last_status:
                print(f"\n⏱️  Время: {elapsed_minutes:.1f} мин")
                print(f"   Статус: {status}")
                if gpu_util is not None:
                    print(f"   GPU загрузка: {gpu_util}%")
                if cpu_util is not None:
                    print(f"   CPU загрузка: {cpu_util}%")
                
                last_update = current_time
                last_status = status
            
            # Проверяем завершение
            if status == 'exited' or status == 'stopped':
                print(f"\n✅ Инстанс завершил работу")
                print(f"   Финальный статус: {status}")
                break
            
            # Проверяем ошибки
            if status == 'failed':
                print(f"\n❌ Инстанс завершился с ошибкой")
                break
            
            time.sleep(check_interval)
        
        return instance

def main():
    """Основная функция."""
    print("=" * 60)
    print("🔍 Мониторинг инстанса Vast AI")
    print("=" * 60)
    
    # API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    # ID инстанса
    instance_id = 32408214
    
    # Создаем монитор
    monitor = VastAIMonitor(api_key)
    
    # 1. Проверим текущий статус
    print(f"\n1. Проверка текущего статуса инстанса {instance_id}...")
    instance = monitor.get_instance_status(instance_id)
    
    if not instance:
        print("❌ Не удалось получить информацию об инстансе")
        return 1
    
    status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
    print(f"   Текущий статус: {status}")
    print(f"   Образ: {instance.get('image_uuid', 'N/A')}")
    print(f"   GPU: {instance.get('gpu_name', 'N/A')}")
    print(f"   Цена: ${instance.get('dph_total', 0):.3f}/час")
    
    # 2. Если инстанс loading, ждем готовности
    if status == 'loading':
        print(f"\n2. Ожидание загрузки Docker образа (40GB)...")
        print("   Это может занять 20-40 минут")
        
        ready_instance = monitor.wait_for_instance_ready(instance_id, timeout_minutes=45)
        if not ready_instance:
            print("❌ Инстанс не стал ready в течение таймаута")
            return 1
        
        instance = ready_instance
    
    # 3. Настроим SSH доступ
    print(f"\n3. Настройка SSH доступа...")
    ssh_info = monitor.setup_ssh_access(instance_id)
    
    if ssh_info:
        print(f"✅ SSH доступ настроен")
        print(f"   Команда для подключения:")
        print(f"   ssh -p {ssh_info['port']} root@{ssh_info['host']}")
        
        # Протестируем соединение
        if monitor.test_ssh_connection(ssh_info['host'], ssh_info['port']):
            print(f"\n🎉 Готово! Можно подключаться по SSH для отладки")
        else:
            print(f"\n⚠️  SSH порт открыт, но требуется дополнительная настройка")
    else:
        print(f"⚠️  Не удалось настроить SSH доступ")
        print(f"   Можно использовать Jupyter: {instance.get('jupyter_token', 'N/A')[:20]}...")
    
    # 4. Мониторинг прогресса
    print(f"\n4. Запуск мониторинга прогресса...")
    print("   Нажмите Ctrl+C для остановки")
    
    try:
        monitor.monitor_progress(instance_id, check_interval=60)
    except KeyboardInterrupt:
        print("\n⏹️  Мониторинг остановлен пользователем")
    
    print("\n" + "=" * 60)
    print("📋 Итог:")
    print(f"   Инстанс ID: {instance_id}")
    print(f"   Статус: {status}")
    print(f"   Стоимость: ${instance.get('dph_total', 0):.3f}/час")
    
    if ssh_info:
        print(f"   SSH: root@{ssh_info['host']}:{ssh_info['port']}")
    
    print("\n🔧 Дальнейшие действия:")
    print("   1. Подключитесь по SSH для отладки")
    print("   2. Запустите генерацию видео вручную")
    print("   3. Проверьте логи в реальном времени")
    print("   4. Остановите инстанс после завершения")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())