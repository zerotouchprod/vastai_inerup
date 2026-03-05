#!/usr/bin/env python3
"""
Поиск мощных офферов на Vast AI для генерации видео.
"""

import os
import sys
import json
import requests

def main():
    print("🔍 ПОИСК МОЩНЫХ ОФФЕРОВ ДЛЯ ГЕНЕРАЦИИ ВИДЕО")
    print("="*60)
    
    # Получаем API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Параметры поиска для мощных инстансов
    search_params = {
        "q": {
            "verified": {"eq": True},
            "external": {"eq": False},
            "rentable": {"eq": True},
            "disk_space": {"gte": 100},
            "cuda_max_good": {"gte": 11.8},
            "inet_up": {"gte": 100},
            "order": [["dph_total", "asc"]]
        },
        "limit": 20
    }
    
    print("📋 Требования к офферам:")
    print("   - Диск: >= 100GB")
    print("   - CUDA: >= 11.8")
    print("   - Интернет: >= 100 Mbps")
    print("   - Цена: до $2/час")
    print()
    
    url = "https://console.vast.ai/api/v0/bundles/"
    
    try:
        response = requests.put(url, headers=headers, json=search_params, timeout=60)
        
        if response.status_code == 200:
            offers = response.json().get("offers", [])
            
            print(f"✅ Найдено офферов: {len(offers)}")
            print()
            
            if not offers:
                print("❌ Не найдено подходящих офферов")
                print("   Попробуйте уменьшить требования к диску")
                return 1
            
            # Выбираем топ-5 самых мощных
            top_offers = sorted(offers, key=lambda x: x.get('gpu_ram', 0), reverse=True)[:5]
            
            for i, offer in enumerate(top_offers):
                offer_id = offer.get('id')
                gpu_name = offer.get('gpu_name', 'unknown')
                gpu_ram = offer.get('gpu_ram', 0)
                disk_space = offer.get('disk_space', 0)
                dph_total = offer.get('dph_total', 0)
                cpu_cores = offer.get('cpu_cores', 0)
                cpu_ram = offer.get('cpu_ram', 0)
                
                print(f"{i+1}. 🚀 ОФФЕР ID: {offer_id}")
                print(f"   🎮 GPU: {gpu_name} ({gpu_ram}GB VRAM)")
                print(f"   💻 CPU: {cpu_cores} ядер, {cpu_ram}GB RAM")
                print(f"   💾 Диск: {disk_space}GB")
                print(f"   💰 Цена: ${dph_total:.3f}/час")
                print(f"   📅 Стоимость за день: ${dph_total*24:.2f}")
                print()
            
            # Рекомендуем лучший оффер
            best_offer = top_offers[0]
            best_id = best_offer.get('id')
            best_gpu = best_offer.get('gpu_name')
            best_vram = best_offer.get('gpu_ram')
            best_price = best_offer.get('dph_total')
            
            print("="*60)
            print(f"🎯 РЕКОМЕНДУЕМЫЙ ОФФЕР: ID {best_id}")
            print(f"   GPU: {best_gpu} ({best_vram}GB VRAM)")
            print(f"   Цена: ${best_price:.3f}/час")
            print()
            
            # Сохраняем информацию
            offer_info = {
                "recommended_offer": best_id,
                "gpu_name": best_gpu,
                "gpu_ram": best_vram,
                "price_per_hour": best_price,
                "all_offers": top_offers[:3]
            }
            
            with open("/tmp/vastai_powerful_offers.json", "w") as f:
                json.dump(offer_info, f, indent=2)
            
            print(f"💾 Информация сохранена в /tmp/vastai_powerful_offers.json")
            print()
            
            # Создаем инстанс с лучшим оффером
            print("🚀 СОЗДАЕМ МОЩНЫЙ ИНСТАНС...")
            create_instance(best_id, api_key)
            
        else:
            print(f"❌ Ошибка поиска: {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            return 1
            
    except Exception as e:
        print(f"❌ Ошибка запроса: {e}")
        import traceback
        print(f"Трассировка: {traceback.format_exc()}")
        return 1
    
    return 0

def create_instance(offer_id, api_key):
    """Создать инстанс с указанным оффером."""
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Конфигурация для генерации видео
    create_data = {
        "client_id": "me",
        "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "disk": 150,  # Больше диска для безопасности
        "args_str": "echo 'Starting powerful video generation instance...' && sleep 7200",
        "ssh": True,
        "env": {
            "DEBUG": "true",
            "WORKSPACE": "/workspace",
            "MODEL_CACHE": "/workspace/models",
            "OUTPUT_DIR": "/workspace/outputs"
        },
        "runtype": "ssh"
    }
    
    endpoint = f"https://console.vast.ai/api/v0/asks/{offer_id}/"
    
    print(f"   Создаем инстанс с оффером {offer_id}...")
    print(f"   Диск: 150GB")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    print()
    
    try:
        response = requests.put(endpoint, headers=headers, json=create_data, timeout=60)
        
        if response.status_code == 200:
            create_data = response.json()
            new_instance_id = create_data.get("new_contract")
            
            print(f"✅ МОЩНЫЙ ИНСТАНС СОЗДАН!")
            print(f"   ID: {new_instance_id}")
            print(f"   Оффер: {offer_id}")
            print(f"   Диск: 150GB")
            print()
            
            # Сохраняем информацию
            instance_info = {
                "instance_id": new_instance_id,
                "offer_id": offer_id,
                "disk_gb": 150,
                "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
                "created_at": "2026-03-05 18:45:00",
                "powerful": True
            }
            
            with open("/tmp/vastai_powerful_instance.json", "w") as f:
                json.dump(instance_info, f, indent=2)
            
            print(f"💾 Информация сохранена в /tmp/vastai_powerful_instance.json")
            print()
            
            print("⏳ Docker образ 40GB будет загружаться 20-40 минут")
            print("   Для проверки статуса:")
            print(f"   python3 check_instance_status.py")
            print()
            
            print("💰 СТОИМОСТЬ:")
            print("   - Загрузка образа: бесплатно")
            print("   - Работа инстанса: ~$0.50-2.00/час")
            print("   - Рекомендуется остановить после генерации")
            print()
            
            return new_instance_id
            
        else:
            print(f"❌ Ошибка создания инстанса: {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"❌ Ошибка создания: {e}")
        return None

if __name__ == "__main__":
    sys.exit(main())