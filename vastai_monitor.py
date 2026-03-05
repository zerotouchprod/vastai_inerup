#!/usr/bin/env python3
"""
Мониторинг инстансов Vast AI и проверка соответствия критериям.
Постоянно проверяет:
1. Размер диска (должен быть >= 100GB)
2. Статус инстанса
3. Стоимость
4. Автоматически останавливает несоответствующие инстансы
"""

import os
import json
import requests
import sys
import time
from datetime import datetime

class VastAIMonitor:
    def __init__(self):
        self.api_key = os.environ.get('VAST_API_KEY')
        if not self.api_key:
            raise ValueError("VAST_API_KEY не установлен")
        
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.base_url = "https://console.vast.ai/api/v0"
        
        # Критерии для инстансов
        self.min_disk_gb = 100  # Минимум 100GB диска
        self.max_price_per_hour = 1.0  # Максимум $1/час
        self.min_vram_gb = 16  # Минимум 16GB VRAM
        
        # Статистика
        self.stats = {
            'total_checks': 0,
            'instances_checked': 0,
            'instances_stopped': 0,
            'problems_found': 0,
            'last_check': None
        }
    
    def get_all_instances(self):
        """Получить все инстансы."""
        url = f"{self.base_url}/instances/"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('instances', [])
            else:
                print(f"❌ Ошибка получения инстансов: {response.status_code}")
                return []
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            return []
    
    def check_instance_criteria(self, instance):
        """Проверить инстанс на соответствие критериям."""
        instance_id = instance.get('id')
        status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
        disk_space = instance.get('disk_space', 0)
        price_per_hour = instance.get('dph_total', 0)
        gpu_ram = instance.get('gpu_ram', 0) / 1024  # Конвертируем MB в GB
        
        problems = []
        
        # Проверка 1: Размер диска
        if disk_space < self.min_disk_gb:
            problems.append(f"Диск слишком мал: {disk_space}GB (нужно {self.min_disk_gb}GB+)")
        
        # Проверка 2: Стоимость
        if price_per_hour > self.max_price_per_hour:
            problems.append(f"Слишком дорого: ${price_per_hour:.3f}/час (макс ${self.max_price_per_hour}/час)")
        
        # Проверка 3: VRAM
        if gpu_ram < self.min_vram_gb:
            problems.append(f"Мало VRAM: {gpu_ram:.1f}GB (нужно {self.min_vram_gb}GB+)")
        
        # Проверка 4: Статус
        if status == 'failed':
            problems.append(f"Инстанс завершился с ошибкой")
        
        return {
            'id': instance_id,
            'status': status,
            'disk_gb': disk_space,
            'price_per_hour': price_per_hour,
            'gpu_ram_gb': gpu_ram,
            'problems': problems,
            'should_stop': len(problems) > 0 and status in ['running', 'loading', 'starting']
        }
    
    def stop_instance(self, instance_id):
        """Остановить инстанс."""
        url = f"{self.base_url}/instances/{instance_id}/"
        
        try:
            response = requests.put(url, headers=self.headers, json={"state": "stopped"}, timeout=30)
            if response.status_code == 200:
                print(f"    ✅ Инстанс {instance_id} остановлен")
                return True
            else:
                print(f"    ❌ Ошибка остановки {instance_id}: {response.status_code}")
                return False
        except Exception as e:
            print(f"    ❌ Ошибка остановки {instance_id}: {e}")
            return False
    
    def monitor_loop(self, check_interval_minutes=5, max_checks=None):
        """Основной цикл мониторинга."""
        print("=" * 80)
        print("🔍 МОНИТОРИНГ ИНСТАНСОВ Vast AI")
        print("=" * 80)
        print(f"Критерии:")
        print(f"  - Диск: >= {self.min_disk_gb}GB")
        print(f"  - Цена: <= ${self.max_price_per_hour}/час")
        print(f"  - VRAM: >= {self.min_vram_gb}GB")
        print(f"  - Интервал проверки: {check_interval_minutes} минут")
        print("=" * 80)
        
        check_count = 0
        
        try:
            while True:
                if max_checks and check_count >= max_checks:
                    print(f"\n⏹️  Достигнуто максимальное количество проверок: {max_checks}")
                    break
                
                check_count += 1
                self.stats['total_checks'] = check_count
                self.stats['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                print(f"\n📊 Проверка #{check_count} ({self.stats['last_check']})")
                print("-" * 80)
                
                # Получаем все инстансы
                instances = self.get_all_instances()
                
                if not instances:
                    print("ℹ️  Нет активных инстансов")
                else:
                    print(f"Найдено инстансов: {len(instances)}")
                    
                    instances_to_stop = []
                    
                    for instance in instances:
                        self.stats['instances_checked'] += 1
                        
                        instance_id = instance.get('id')
                        status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                        
                        print(f"\n  Инстанс {instance_id}:")
                        print(f"    Статус: {status}")
                        
                        # Проверяем критерии
                        check_result = self.check_instance_criteria(instance)
                        
                        if check_result['problems']:
                            self.stats['problems_found'] += 1
                            print(f"    ❌ Проблемы:")
                            for problem in check_result['problems']:
                                print(f"      - {problem}")
                            
                            if check_result['should_stop']:
                                print(f"    ⚠️  Требуется остановка")
                                instances_to_stop.append(instance_id)
                        else:
                            print(f"    ✅ Соответствует критериям")
                            print(f"      Диск: {check_result['disk_gb']}GB")
                            print(f"      Цена: ${check_result['price_per_hour']:.3f}/час")
                            print(f"      VRAM: {check_result['gpu_ram_gb']:.1f}GB")
                
                # Останавливаем проблемные инстансы
                if instances_to_stop:
                    print(f"\n🛑 Остановка проблемных инстансов:")
                    for instance_id in instances_to_stop:
                        if self.stop_instance(instance_id):
                            self.stats['instances_stopped'] += 1
                
                # Выводим статистику
                print(f"\n📈 Статистика:")
                print(f"  Всего проверок: {self.stats['total_checks']}")
                print(f"  Проверено инстансов: {self.stats['instances_checked']}")
                print(f"  Найдено проблем: {self.stats['problems_found']}")
                print(f"  Остановлено инстансов: {self.stats['instances_stopped']}")
                print(f"  Последняя проверка: {self.stats['last_check']}")
                
                # Если есть активные инстансы, покажем их статус
                active_instances = [i for i in instances if i.get('actual_status') in ['running', 'loading', 'starting']]
                if active_instances:
                    print(f"\n🎯 Активные инстансы:")
                    for instance in active_instances:
                        instance_id = instance.get('id')
                        status = instance.get('actual_status', instance.get('cur_state', 'unknown'))
                        price = instance.get('dph_total', 0)
                        disk = instance.get('disk_space', 0)
                        print(f"  - {instance_id}: {status}, ${price:.3f}/час, {disk}GB диск")
                
                # Ждем перед следующей проверкой
                if check_count < (max_checks or float('inf')):
                    print(f"\n⏳ Следующая проверка через {check_interval_minutes} минут...")
                    print("=" * 80)
                    time.sleep(check_interval_minutes * 60)
                
        except KeyboardInterrupt:
            print(f"\n\n⏹️  Мониторинг остановлен пользователем")
        
        # Финальная статистика
        print(f"\n" + "=" * 80)
        print(f"📊 ФИНАЛЬНАЯ СТАТИСТИКА")
        print("=" * 80)
        for key, value in self.stats.items():
            print(f"  {key}: {value}")
        
        return self.stats
    
    def check_specific_instance(self, instance_id):
        """Проверить конкретный инстанс."""
        url = f"{self.base_url}/instances/{instance_id}/"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                instance = data.get('instances', {})
                
                if instance:
                    print(f"\n🔍 Проверка инстанса {instance_id}:")
                    check_result = self.check_instance_criteria(instance)
                    
                    print(f"  Статус: {check_result['status']}")
                    print(f"  Диск: {check_result['disk_gb']}GB")
                    print(f"  Цена: ${check_result['price_per_hour']:.3f}/час")
                    print(f"  VRAM: {check_result['gpu_ram_gb']:.1f}GB")
                    
                    if check_result['problems']:
                        print(f"  ❌ Проблемы:")
                        for problem in check_result['problems']:
                            print(f"    - {problem}")
                        
                        if check_result['should_stop']:
                            print(f"\n  ⚠️  Инстанс не соответствует критериям!")
                            confirm = input(f"  Остановить инстанс {instance_id}? (y/N): ").strip().lower()
                            if confirm == 'y':
                                self.stop_instance(instance_id)
                    else:
                        print(f"  ✅ Инстанс соответствует критериям")
                    
                    return check_result
                else:
                    print(f"❌ Инстанс {instance_id} не найден")
                    return None
                    
            else:
                print(f"❌ Ошибка: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return None

def main():
    """Основная функция."""
    print("=" * 80)
    print("🔍 МОНИТОР ИНСТАНСОВ Vast AI")
    print("=" * 80)
    
    try:
        monitor = VastAIMonitor()
    except ValueError as e:
        print(f"❌ {e}")
        print(f"   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    print(f"\n🎯 Выберите действие:")
    print(f"   1. Запустить постоянный мониторинг")
    print(f"   2. Проверить конкретный инстанс")
    print(f"   3. Проверить все текущие инстансы")
    print(f"   4. Настроить критерии")
    print(f"   5. Выход")
    
    choice = input("\nВаш выбор (1-5): ").strip()
    
    if choice == '1':
        print(f"\n🚀 Запуск постоянного мониторинга...")
        print(f"   Нажмите Ctrl+C для остановки")
        
        interval = input("Интервал проверки (минут, по умолчанию 5): ").strip()
        interval_minutes = int(interval) if interval.isdigit() else 5
        
        max_checks_input = input("Максимальное количество проверок (оставьте пустым для бесконечности): ").strip()
        max_checks = int(max_checks_input) if max_checks_input.isdigit() else None
        
        monitor.monitor_loop(check_interval_minutes=interval_minutes, max_checks=max_checks)
        
    elif choice == '2':
        instance_id = input("Введите ID инстанса: ").strip()
        if instance_id.isdigit():
            monitor.check_specific_instance(int(instance_id))
        else:
            print("❌ Неверный ID инстанса")
    
    elif choice == '3':
        print(f"\n🔍 Проверка всех текущих инстансов...")
        instances = monitor.get_all_instances()
        
        if not instances:
            print("ℹ️  Нет активных инстансов")
        else:
            print(f"Найдено инстансов: {len(instances)}")
            
            for instance in instances:
                instance_id = instance.get('id')
                print(f"\n--- Инстанс {instance_id} ---")
                monitor.check_instance_criteria(instance)
    
    elif choice == '4':
        print(f"\n⚙️  Настройка критериев:")
        
        min_disk = input(f"Минимальный диск (GB, текущий {monitor.min_disk_gb}): ").strip()
        if min_disk.isdigit():
            monitor.min_disk_gb = int(min_disk)
        
        max_price = input(f"Максимальная цена ($/час, текущий {monitor.max_price_per_hour}): ").strip()
        if max_price.replace('.', '', 1).isdigit():
            monitor.max_price_per_hour = float(max_price)
        
        min_vram = input(f"Минимальный VRAM (GB, текущий {monitor.min_vram_gb}): ").strip()
        if min_vram.isdigit():
            monitor.min_vram_gb = int(min_vram)
        
        print(f"\n✅ Критерии обновлены:")
        print(f"   Диск: >= {monitor.min_disk_gb}GB")
        print(f"   Цена: <= ${monitor.max_price_per_hour}/час")
        print(f"   VRAM: >= {monitor.min_vram_gb}GB")
    
    elif choice == '5':
        print("Выход")
        return 0
    
    else:
        print("❌ Неверный выбор")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())