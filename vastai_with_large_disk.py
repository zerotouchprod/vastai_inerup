#!/usr/bin/env python3
"""
Создание инстанса Vast AI с большим диском (100GB) через API.
Использует параметры allocated_storage и disk_space.
"""

import os
import json
import requests
import sys
import time

class VastAIWithLargeDisk:
    def __init__(self):
        self.api_key = os.environ.get('VAST_API_KEY')
        if not self.api_key:
            raise ValueError("VAST_API_KEY не установлен")
        
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.base_url = "https://console.vast.ai/api/v0"
        self.instance_id = None
    
    def search_offers(self, min_vram_gb=24, max_price=1.0, min_disk_gb=100):
        """Поиск офферов с фильтрами."""
        print(f"🔍 Поиск офферов: VRAM>={min_vram_gb}GB, Диск>={min_disk_gb}GB, Цена<${max_price}/час")
        
        # Пробуем разные endpoints
        endpoints = [
            f"{self.base_url}/bundles/",
            f"{self.base_url}/asks/"
        ]
        
        for endpoint in endpoints:
            print(f"  Пробуем {endpoint}...")
            
            # Параметры поиска
            search_params = {
                "q": {
                    "verified": {"eq": True},
                    "rentable": {"eq": True},
                    "gpu_ram": {"gte": min_vram_gb * 1024},  # Конвертируем GB в MB
                    "disk_space": {"gte": min_disk_gb},
                    "dph_total": {"lte": max_price},
                    "order": [["dph_total", "asc"]],
                    "limit": 10
                }
            }
            
            try:
                response = requests.put(endpoint, headers=self.headers, json=search_params, timeout=60)
                print(f"    Статус: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Проверяем разные форматы ответа
                    offers = data.get('offers', [])
                    if not offers:
                        offers = data.get('asks', [])
                    
                    if offers:
                        print(f"✅ Найдено офферов: {len(offers)}")
                        return offers
                    else:
                        print(f"⚠️  Офферы не найдены")
                        
                elif response.status_code == 404:
                    print(f"    Endpoint не найден")
                    continue
                else:
                    print(f"    Ошибка: {response.status_code}")
                    print(f"    Ответ: {response.text[:200]}")
                    
            except Exception as e:
                print(f"    Ошибка запроса: {e}")
                continue
        
        print(f"❌ Не удалось найти офферы через API")
        return []
    
    def display_offers(self, offers):
        """Отобразить найденные офферы."""
        if not offers:
            print("❌ Нет офферов для отображения")
            return
        
        print(f"\n📋 НАЙДЕННЫЕ ОФФЕРЫ:")
        print("=" * 80)
        
        for i, offer in enumerate(offers[:5]):  # Показываем первые 5
            print(f"\n{i+1}. Оффер ID: {offer.get('id', 'N/A')}")
            print(f"   GPU: {offer.get('gpu_name', 'N/A')}")
            print(f"   VRAM: {offer.get('gpu_ram', 0)/1024:.1f}GB")
            print(f"   Диск: {offer.get('disk_space', 0)}GB ({offer.get('disk_name', 'N/A')})")
            print(f"   Цена: ${offer.get('dph_total', 0):.3f}/час")
            print(f"   Релиабильность: {offer.get('reliability2', 0):.2f}")
            print(f"   Host ID: {offer.get('host_id', 'N/A')}")
            print(f"   Локация: {offer.get('geolocation', 'N/A')}")
    
    def create_instance_with_large_disk(self, offer_id, disk_gb=100):
        """Создать инстанс с указанным размером диска."""
        print(f"\n🚀 Создание инстанса на оффере {offer_id} с диском {disk_gb}GB...")
        
        # Параметры создания инстанса
        create_data = {
            "client_id": "me",
            "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
            "args_str": "sleep 7200",  # 2 часа для отладки
            "allocated_storage": disk_gb,  # Ключевой параметр!
            "disk_space": disk_gb,  # Дополнительный параметр
            "ssh": True,  # Включить SSH
            "env": {
                "DEBUG": "true",
                "WORKSPACE": "/workspace"
            },
            "onstart": f"echo 'Starting instance with {disk_gb}GB disk...' && df -h"
        }
        
        # Пробуем создать инстанс
        endpoints = [
            f"{self.base_url}/asks/{offer_id}/",
            f"{self.base_url}/offers/{offer_id}/"
        ]
        
        for endpoint in endpoints:
            print(f"  Пробуем создать через {endpoint}...")
            
            try:
                response = requests.put(endpoint, headers=self.headers, json=create_data, timeout=60)
                print(f"    Статус: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    print(f"✅ Инстанс создан!")
                    
                    # Извлекаем ID инстанса
                    instance_id = data.get('new_contract')
                    if instance_id:
                        print(f"   ID инстанса: {instance_id}")
                        self.instance_id = instance_id
                        return instance_id
                    else:
                        print(f"⚠️  ID инстанса не найден в ответе")
                        print(f"   Ответ: {json.dumps(data, indent=2)}")
                        return None
                        
                else:
                    print(f"❌ Ошибка: {response.status_code}")
                    print(f"   Ответ: {response.text[:500]}")
                    
            except Exception as e:
                print(f"❌ Ошибка запроса: {e}")
                continue
        
        print(f"❌ Не удалось создать инстанс")
        return None
    
    def wait_for_instance_ready(self, timeout_minutes=30):
        """Ожидать пока инстанс станет ready."""
        if not self.instance_id:
            print("❌ Нет ID инстанса")
            return False
        
        print(f"\n⏳ Ожидание готовности инстанса {self.instance_id}...")
        print(f"   Docker образ 40GB загружается...")
        print(f"   Таймаут: {timeout_minutes} минут")
        
        start_time = time.time()
        
        for i in range(timeout_minutes * 2):  # Проверяем каждые 30 секунд
            elapsed_minutes = (time.time() - start_time) / 60
            
            if i % 4 == 0:  # Выводим статус каждые 2 минуты
                print(f"\n⏱️  Проверка {i//2 + 1}/{timeout_minutes} мин ({elapsed_minutes:.1f} мин)...")
            
            # Проверяем статус
            instance_info = self.get_instance_info()
            if not instance_info:
                time.sleep(30)
                continue
            
            status = instance_info.get('actual_status', instance_info.get('cur_state', 'unknown'))
            
            if i % 4 == 0:  # Выводим статус каждые 2 минуты
                print(f"   Статус: {status}")
            
            # Проверяем SSH
            ssh_port = instance_info.get('ssh_port')
            if ssh_port:
                print(f"   SSH порт: {ssh_port}")
            
            # Если инстанс running и есть SSH - готово
            if status == 'running' and ssh_port:
                print(f"\n✅ Инстанс готов!")
                print(f"   SSH: порт {ssh_port}")
                print(f"   IP: {instance_info.get('public_ipaddr', 'N/A')}")
                return True
            
            # Если ошибка
            if status == 'failed':
                print(f"\n❌ Инстанс завершился с ошибкой")
                return False
            
            time.sleep(30)
        
        print(f"\n⏱️  Таймаут ожидания ({timeout_minutes} минут)")
        return False
    
    def get_instance_info(self):
        """Получить информацию об инстансе."""
        if not self.instance_id:
            return None
        
        url = f"{self.base_url}/instances/{self.instance_id}/"
        
        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return data.get('instances', {})
            else:
                return None
        except Exception as e:
            print(f"   Ошибка запроса: {e}")
            return None
    
    def print_connection_info(self):
        """Вывести информацию для подключения."""
        if not self.instance_id:
            print("❌ Нет ID инстанса")
            return
        
        instance_info = self.get_instance_info()
        if not instance_info:
            print("❌ Не удалось получить информацию об инстансе")
            return
        
        ssh_port = instance_info.get('ssh_port')
        ssh_host = instance_info.get('public_ipaddr')
        
        if ssh_port and ssh_host:
            print(f"\n" + "=" * 80)
            print(f"🔑 SSH ДОСТУП НАСТРОЕН")
            print("=" * 80)
            
            print(f"\n🔌 Подключение:")
            print(f"   ssh -p {ssh_port} root@{ssh_host}")
            
            print(f"\n📝 Пароль:")
            print(f"   Будет запрошен при первом подключении")
            
            print(f"\n🎬 Запуск генерации видео:")
            print(f"   cd /workspace")
            print(f"   python -m src.entrypoints.run_gen \\")
            print(f"     --job '{{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"],")
            print(f"              \"num_frames\": 24, \"fps\": 8, \"num_inference_steps\": 25}}'")
            
            print(f"\n💰 Стоимость:")
            print(f"   Цена: ${instance_info.get('dph_total', 0):.3f}/час")
            print(f"   Загрузка Docker: 20-40 мин = $0.10-$0.30")
            print(f"   Генерация: 5-15 мин = $0.05-$0.15")
            print(f"   Итого: $0.15-$0.45")
        else:
            print(f"\n⚠️  SSH не настроен")
            print(f"   Jupyter токен: {instance_info.get('jupyter_token', 'N/A')[:20]}...")

def main():
    """Основная функция."""
    print("=" * 80)
    print("🚀 СОЗДАНИЕ ИНСТАНСА Vast AI С БОЛЬШИМ ДИСКОМ (100GB)")
    print("=" * 80)
    
    try:
        launcher = VastAIWithLargeDisk()
    except ValueError as e:
        print(f"❌ {e}")
        print(f"   export VAST_API_KEY='ваш_ключ'")
        return 1
    
    # 1. Поиск офферов
    offers = launcher.search_offers(min_vram_gb=16, max_price=0.8, min_disk_gb=80)
    
    if not offers:
        print(f"\n❌ Не найдено подходящих офферов")
        print(f"   Попробуйте уменьшить требования:")
        print(f"   - VRAM: с 24GB до 16GB")
        print(f"   - Диск: с 100GB до 80GB")
        print(f"   - Цена: увеличить до $1.0/час")
        return 1
    
    # 2. Отображение офферов
    launcher.display_offers(offers)
    
    # 3. Выбор оффера
    print(f"\n🎯 ВЫБОР ОФФЕРА:")
    
    # Берем первый оффер
    offer = offers[0]
    offer_id = offer.get('id')
    disk_space = offer.get('disk_space', 0)
    
    print(f"   Выбран оффер: {offer_id}")
    print(f"   GPU: {offer.get('gpu_name', 'N/A')}")
    print(f"   Диск: {disk_space}GB")
    print(f"   Цена: ${offer.get('dph_total', 0):.3f}/час")
    
    # 4. Подтверждение
    print(f"\n⚠️  ВНИМАНИЕ:")
    print(f"   Docker образ: 40GB")
    print(f"   Требуется диск: минимум 100GB")
    print(f"   Диск оффера: {disk_space}GB")
    
    if disk_space < 100:
        print(f"   ⚠️  Диск оффера меньше 100GB!")
        print(f"   Но попробуем запросить 100GB через allocated_storage")
    
    confirm = input(f"\nСоздать инстанс? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено")
        return 0
    
    # 5. Создание инстанса
    print(f"\n" + "=" * 80)
    print(f"🔄 СОЗДАНИЕ ИНСТАНСА")
    print("=" * 80)
    
    # Запрашиваем 100GB диска независимо от оффера
    instance_id = launcher.create_instance_with_large_disk(offer_id, disk_gb=100)
    
    if not instance_id:
        print(f"❌ Не удалось создать инстанс")
        return 1
    
    # 6. Ожидание загрузки
    print(f"\n" + "=" * 80)
    print(f"📦 ЗАГРУЗКА DOCKER ОБРАЗА (40GB)")
    print("=" * 80)
    
    ready = launcher.wait_for_instance_ready(timeout_minutes=45)
    
    if ready:
        # 7. Вывод информации для подключения
        launcher.print_connection_info()
        
        print(f"\n" + "=" * 80)
        print(f"🎉 ИНСТАНС ГОТОВ К РАБОТЕ!")
        print("=" * 80)
        
        print(f"\n📋 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ:")
        print(f"   1. Подключитесь по SSH")
        print(f"   2. Проверьте диск: df -h")
        print(f"   3. Проверьте Docker: docker ps")
        print(f"   4. Запустите генерацию видео")
        print(f"   5. Остановите инстанс после работы")
        
        print(f"\n🔗 Консоль управления: https://vast.ai/")
        print(f"   Instances -> {instance_id}")
    else:
        print(f"\n❌ Проблема с загрузкой инстанса")
        print(f"   Проверьте консоль Vast AI")
        print(f"   Инстанс ID: {instance_id}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())