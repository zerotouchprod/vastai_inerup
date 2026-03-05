#!/usr/bin/env python3
"""
Поиск офферов Vast AI с большим диском (минимум 100GB).
"""

import requests
import os
import json
import sys

def search_offers_with_large_disk():
    """Поиск офферов с минимум 100GB диска."""
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return []
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Пробуем разные API endpoints
    endpoints = [
        "https://console.vast.ai/api/v0/bundles/",
        "https://console.vast.ai/api/v0/offers/"
    ]
    
    for endpoint in endpoints:
        print(f"\n🔍 Поиск на {endpoint}...")
        
        # Параметры поиска
        search_params = {
            "q": {
                "verified": {"eq": True},
                "rentable": {"eq": True},
                "gpu_ram": {"gte": 24000},  # 24GB VRAM
                "disk_space": {"gte": 100},  # 100GB диск
                "order": [["dph_total", "asc"]],
                "limit": 20
            }
        }
        
        try:
            response = requests.put(endpoint, headers=headers, json=search_params, timeout=60)
            print(f"Статус: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                # Проверяем разные форматы ответа
                offers = data.get('offers', [])
                if not offers:
                    offers = data.get('bundles', [])
                
                if offers:
                    print(f"✅ Найдено офферов: {len(offers)}")
                    return offers
                else:
                    print(f"⚠️  Офферы не найдены в ответе")
                    print(f"   Структура ответа: {list(data.keys())}")
                    
            elif response.status_code == 404:
                print(f"⚠️  Endpoint не найден: {endpoint}")
                continue
            else:
                print(f"❌ Ошибка: {response.status_code}")
                print(f"   Ответ: {response.text[:500]}")
                
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            continue
    
    print(f"\n❌ Не удалось найти офферы через API")
    print(f"   Пробуем альтернативный метод...")
    
    # Альтернативный метод - поиск через веб-интерфейс
    return []

def display_offers(offers):
    """Отобразить найденные офферы."""
    if not offers:
        print("❌ Нет офферов для отображения")
        return
    
    print(f"\n📋 НАЙДЕННЫЕ ОФФЕРЫ С БОЛЬШИМ ДИСКОМ:")
    print("=" * 80)
    
    for i, offer in enumerate(offers[:10]):  # Показываем первые 10
        print(f"\n{i+1}. Оффер ID: {offer.get('id', 'N/A')}")
        print(f"   GPU: {offer.get('gpu_name', 'N/A')}")
        print(f"   VRAM: {offer.get('gpu_ram', 0)/1024:.1f}GB")
        print(f"   Диск: {offer.get('disk_space', 0)}GB ({offer.get('disk_name', 'N/A')})")
        print(f"   Цена: ${offer.get('dph_total', 0):.3f}/час")
        print(f"   Релиабильность: {offer.get('reliability2', 0):.2f}")
        print(f"   Host ID: {offer.get('host_id', 'N/A')}")
        print(f"   Локация: {offer.get('geolocation', 'N/A')}")
        
        # Дополнительная информация
        cpu = offer.get('cpu_name', 'N/A')
        cpu_cores = offer.get('cpu_cores', 0)
        if cpu and cpu_cores:
            print(f"   CPU: {cpu} ({cpu_cores} cores)")
        
        # Проверяем достаточно ли диска
        disk_space = offer.get('disk_space', 0)
        if disk_space >= 100:
            print(f"   ✅ Диск достаточный: {disk_space}GB")
        elif disk_space >= 80:
            print(f"   ⚠️  Диск минимальный: {disk_space}GB (нужно 100GB)")
        else:
            print(f"   ❌ Диск слишком мал: {disk_space}GB (нужно 100GB)")
    
    print(f"\n📊 Итого: {len(offers)} офферов с большим диском")

def create_instance_directly(offer_id):
    """Создать инстанс напрямую через API."""
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return None
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    print(f"\n🚀 Создание инстанса на оффере {offer_id}...")
    
    # Параметры создания инстанса
    create_data = {
        "client_id": "me",
        "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "args_str": "sleep 3600",  # 1 час для отладки
        "disk": 100,  # Запросим 100GB диска
        "ssh": True,  # Включить SSH
        "onstart": "echo 'Starting debug session...'",
        "env": {
            "DEBUG": "true"
        }
    }
    
    # Пробуем разные endpoints для создания
    endpoints = [
        f"https://console.vast.ai/api/v0/asks/{offer_id}/",
        f"https://console.vast.ai/api/v0/offers/{offer_id}/"
    ]
    
    for endpoint in endpoints:
        print(f"Попытка создания через {endpoint}...")
        
        try:
            response = requests.put(endpoint, headers=headers, json=create_data, timeout=60)
            print(f"Статус: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Инстанс создан!")
                print(f"   Ответ: {json.dumps(data, indent=2)}")
                
                # Извлекаем ID инстанса
                instance_id = data.get('new_contract')
                if instance_id:
                    print(f"   ID инстанса: {instance_id}")
                    return instance_id
                else:
                    print(f"⚠️  ID инстанса не найден в ответе")
                    return None
                    
            else:
                print(f"❌ Ошибка: {response.status_code}")
                print(f"   Ответ: {response.text[:500]}")
                
        except Exception as e:
            print(f"❌ Ошибка запроса: {e}")
            continue
    
    print(f"❌ Не удалось создать инстанс")
    return None

def main():
    """Основная функция."""
    print("=" * 80)
    print("🔍 ПОИСК ОФФЕРОВ Vast AI С БОЛЬШИМ ДИСКОМ (100GB+)")
    print("=" * 80)
    
    # 1. Поиск офферов
    offers = search_offers_with_large_disk()
    
    if not offers:
        print(f"\n❌ Не найдено офферов с 100GB+ диском")
        print(f"\n🔧 РЕКОМЕНДАЦИИ:")
        print(f"   1. Увеличьте бюджет (--max-price)")
        print(f"   2. Уменьшите требования к VRAM (с 24GB до 16GB)")
        print(f"   3. Ищите вручную на https://vast.ai/")
        print(f"   4. Используйте фильтр: disk_space >= 100")
        return 1
    
    # 2. Отображение офферов
    display_offers(offers)
    
    # 3. Выбор оффера
    print(f"\n🎯 ВЫБЕРИТЕ ОФФЕР ДЛЯ ЗАПУСКА:")
    print(f"   1. Использовать первый оффер (ID: {offers[0].get('id', 'N/A')})")
    print(f"   2. Ввести ID оффера вручную")
    print(f"   3. Отмена")
    
    choice = input("\nВаш выбор (1/2/3): ").strip()
    
    if choice == '3':
        print("Отменено")
        return 0
    elif choice == '1':
        offer_id = offers[0].get('id')
    elif choice == '2':
        offer_id = input("Введите ID оффера: ").strip()
    else:
        print("❌ Неверный выбор")
        return 1
    
    if not offer_id:
        print("❌ ID оффера не указан")
        return 1
    
    # 4. Создание инстанса
    print(f"\n" + "=" * 80)
    print(f"🚀 СОЗДАНИЕ ИНСТАНСА НА ОФФЕРЕ {offer_id}")
    print("=" * 80)
    
    confirm = input(f"\nСоздать инстанс на оффере {offer_id}? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено")
        return 0
    
    instance_id = create_instance_directly(offer_id)
    
    if instance_id:
        print(f"\n🎉 ИНСТАНС СОЗДАН!")
        print(f"   ID: {instance_id}")
        print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
        print(f"   Диск: 100GB (запрошено)")
        print(f"   SSH: включен")
        print(f"\n🔗 Консоль управления: https://vast.ai/")
        print(f"   Перейдите в Instances -> {instance_id}")
        
        print(f"\n📋 ДАЛЬНЕЙШИЕ ДЕЙСТВИЯ:")
        print(f"   1. Дождитесь загрузки Docker образа (20-40 минут)")
        print(f"   2. Подключитесь по SSH когда будет готово")
        print(f"   3. Запустите генерацию видео вручную")
        print(f"   4. Остановите инстанс после завершения")
    else:
        print(f"\n❌ НЕ УДАЛОСЬ СОЗДАТЬ ИНСТАНС")
        print(f"\n🔧 АЛЬТЕРНАТИВНЫЕ ВАРИАНТЫ:")
        print(f"   1. Создать инстанс через веб-интерфейс")
        print(f"   2. Использовать vast_submit.py с другим оффером")
        print(f"   3. Искать офферы с меньшим диском (80GB)")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())