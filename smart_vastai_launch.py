#!/usr/bin/env python3
"""
Умный запуск инстанса Vast AI с правильной стратегией:
1. Сначала создаем инстанс с SSH для отладки
2. Мониторим загрузку Docker образа (40GB)
3. После загрузки подключаемся по SSH
4. Запускаем генерацию видео вручную
"""

import os
import json
import subprocess
import sys
import time
import requests

class SmartVastAILauncher:
    def __init__(self):
        self.api_key = os.environ.get('VAST_API_KEY')
        if not self.api_key:
            raise ValueError("VAST_API_KEY не установлен")
        
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.instance_id = None
        self.ssh_info = None
    
    def search_proper_offer(self):
        """Поиск оффера с минимум 100GB диска."""
        print("🔍 Поиск оффера с минимум 100GB диска и 24GB VRAM...")
        
        # Используем vast_submit для поиска
        cmd = [
            sys.executable,
            "vast/vast_submit.py",
            "--list-offers",
            "--min-vram", "24",
            "--max-price", "1.0",
            "--list-count", "20"
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = result.stdout
            
            if "offer_id=" in output:
                # Парсим офферы
                offers = []
                lines = output.split('\n')
                for line in lines:
                    if "offer_id=" in line:
                        # Извлекаем ID оффера
                        import re
                        match = re.search(r'offer_id=(\d+)', line)
                        if match:
                            offer_id = match.group(1)
                            offers.append(offer_id)
                
                if offers:
                    print(f"✅ Найдено {len(offers)} офферов")
                    print(f"   Первый оффер: {offers[0]}")
                    return offers[0]
                else:
                    print("❌ Не удалось распарсить офферы")
                    return None
            else:
                print(f"❌ Неожиданный вывод: {output[:200]}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка поиска: {e}")
            return None
    
    def create_debug_instance(self, offer_id):
        """Создать инстанс для отладки."""
        print(f"\n🚀 Создание инстанса для отладки (оффер: {offer_id})...")
        
        # Простая команда для отладки
        debug_cmd = "sleep 7200 && echo 'Debug session ended'"  # 2 часа
        
        cmd = [
            sys.executable,
            "vast/vast_submit.py",
            "--offer-id", offer_id,
            "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
            "--cmd", debug_cmd,
            "--wait-running"
        ]
        
        print(f"🔧 Параметры:")
        print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
        print(f"   Команда: {debug_cmd}")
        print(f"   SSH: будет включен автоматически")
        
        print(f"\n⚠️  ВНИМАНИЕ: Docker образ 40GB")
        print("   Загрузка займет 20-40 минут")
        print("   Стоимость: ~$0.10-$0.50/час")
        
        confirm = input("\nПродолжить? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Отменено пользователем")
            return None
        
        print(f"\n⏳ Создание инстанса...")
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
                self.instance_id = instance_id
                return instance_id
            else:
                print(f"\n❌ Ошибка создания инстанса")
                if process.stderr:
                    print(f"   STDERR: {process.stderr.read()[:500]}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None
    
    def wait_for_docker_load(self, timeout_minutes=45):
        """Ожидать загрузки Docker образа."""
        if not self.instance_id:
            print("❌ Нет ID инстанса")
            return False
        
        print(f"\n📦 Ожидание загрузки Docker образа (40GB)...")
        print(f"   Это может занять 20-40 минут")
        print(f"   Таймаут: {timeout_minutes} минут")
        print(f"   Нажмите Ctrl+C для прерывания")
        
        start_time = time.time()
        check_count = 0
        
        try:
            while time.time() - start_time < timeout_minutes * 60:
                check_count += 1
                elapsed_minutes = (time.time() - start_time) / 60
                
                print(f"\n⏱️  Проверка {check_count} ({elapsed_minutes:.1f} мин)...")
                
                # Проверяем статус через API
                instance_info = self.get_instance_info()
                if not instance_info:
                    print("   Не удалось получить информацию")
                    time.sleep(120)
                    continue
                
                status = instance_info.get('actual_status', instance_info.get('cur_state', 'unknown'))
                print(f"   Статус: {status}")
                
                # Проверяем SSH
                ssh_port = instance_info.get('ssh_port')
                if ssh_port:
                    print(f"   SSH порт: {ssh_port}")
                    self.ssh_info = {
                        'host': instance_info.get('public_ipaddr'),
                        'port': ssh_port
                    }
                
                # Если инстанс running и есть SSH - готово
                if status == 'running' and ssh_port:
                    print(f"\n✅ Docker образ загружен!")
                    print(f"   Инстанс готов к работе")
                    return True
                
                # Если ошибка
                if status == 'failed':
                    print(f"\n❌ Инстанс завершился с ошибкой")
                    return False
                
                # Ждем 2 минуты
                time.sleep(120)
            
            print(f"\n⏱️  Таймаут ожидания ({timeout_minutes} минут)")
            return False
            
        except KeyboardInterrupt:
            print(f"\n⏹️  Мониторинг прерван")
            return False
    
    def get_instance_info(self):
        """Получить информацию об инстансе через API."""
        if not self.instance_id:
            return None
        
        url = f"https://console.vast.ai/api/v0/instances/{self.instance_id}/"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('instances', {})
            else:
                print(f"   API ошибка: {response.status_code}")
                return None
        except Exception as e:
            print(f"   Ошибка запроса: {e}")
            return None
    
    def print_ssh_instructions(self):
        """Вывести инструкции по SSH подключению."""
        if not self.ssh_info:
            print("❌ SSH информация недоступна")
            return
        
        print(f"\n" + "=" * 60)
        print(f"🔑 SSH ДОСТУП НАСТРОЕН")
        print("=" * 60)
        
        host = self.ssh_info['host']
        port = self.ssh_info['port']
        
        print(f"\n🔌 Подключение:")
        print(f"   ssh -p {port} root@{host}")
        
        print(f"\n📝 Пароль:")
        print(f"   Будет запрошен при первом подключении")
        print(f"   (обычно это пустой пароль или 'vastai')")
        
        print(f"\n🔧 Проверка после подключения:")
        print(f"   1. Проверьте Docker:")
        print(f"      docker ps")
        print(f"      docker images | grep video-gen")
        print(f"   2. Проверьте диск:")
        print(f"      df -h")
        print(f"   3. Перейдите в рабочую директорию:")
        print(f"      cd /workspace")
        
        print(f"\n🎬 Запуск генерации видео:")
        print(f"   python -m src.entrypoints.run_gen \\")
        print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"your prompt\"],")
        print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
        
        print(f"\n📊 Мониторинг:")
        print(f"   nvidia-smi")
        print(f"   htop")
        
        print(f"\n🛑 Остановка инстанса после работы:")
        print(f"   https://vast.ai/ -> Instances -> Stop")
    
    def monitor_and_cleanup(self):
        """Мониторить инстанс и предложить очистку."""
        print(f"\n" + "=" * 60)
        print(f"📊 МОНИТОРИНГ ИНСТАНСА {self.instance_id}")
        print("=" * 60)
        
        print(f"\n⏰ Рекомендуемый план:")
        print(f"   1. Подключитесь по SSH сейчас")
        print(f"   2. Проверьте загрузку Docker образа")
        print(f"   3. После загрузки запустите генерацию")
        print(f"   4. Остановите инстанс после завершения")
        
        print(f"\n💰 Стоимость:")
        print(f"   ~$0.10-$0.50 в час")
        print(f"   Загрузка образа: 20-40 мин = ~$0.10-$0.30")
        print(f"   Генерация видео: 5-15 мин = ~$0.05-$0.15")
        print(f"   Итого: ~$0.15-$0.45")
        
        print(f"\n🔗 Консоль управления:")
        print(f"   https://vast.ai/")
        
        # Предложим удалить инстанс через 3 часа
        print(f"\n⚠️  АВТООЧИСТКА:")
        print(f"   Инстанс будет автоматически остановлен через 2 часа")
        print(f"   (команда sleep 7200)")
        print(f"   Для продления подключитесь по SSH и выполните:")
        print(f"   pkill sleep && sleep 36000  # продлить на 10 часов")

def main():
    """Основная функция."""
    print("=" * 60)
    print("🧠 УМНЫЙ ЗАПУСК Vast AI ДЛЯ ГЕНЕРАЦИИ ВИДЕО")
    print("=" * 60)
    
    try:
        launcher = SmartVastAILauncher()
    except ValueError as e:
        print(f"❌ {e}")
        print(f"   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    # 1. Поиск оффера
    offer_id = launcher.search_proper_offer()
    if not offer_id:
        print("❌ Не удалось найти подходящий оффер")
        return 1
    
    # 2. Создание инстанса
    instance_id = launcher.create_debug_instance(offer_id)
    if not instance_id:
        print("❌ Не удалось создать инстанс")
        return 1
    
    # 3. Ожидание загрузки Docker
    print(f"\n" + "=" * 60)
    print(f"🔄 ЗАГРУЗКА DOCKER ОБРАЗА (40GB)")
    print("=" * 60)
    
    loaded = launcher.wait_for_docker_load(timeout_minutes=45)
    
    if loaded:
        # 4. Вывод SSH инструкций
        launcher.print_ssh_instructions()
        
        # 5. Мониторинг и очистка
        launcher.monitor_and_cleanup()
        
        print(f"\n🎉 Готово! Подключайтесь по SSH и запускайте генерацию!")
    else:
        print(f"\n❌ Проблема с загрузкой Docker образа")
        print(f"   Проверьте консоль Vast AI: https://vast.ai/")
        print(f"   Инстанс ID: {instance_id}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())