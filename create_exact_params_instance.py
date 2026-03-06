#!/usr/bin/env python3
"""
Создание инстанса с точными параметрами из конфига.
"""

import os
import sys
import json
import requests

def main():
    print("🚀 СОЗДАНИЕ ИНСТАНСА С ТОЧНЫМИ ПАРАМЕТРАМИ")
    print("="*60)
    
    # Получаем API ключ
    api_key = os.environ.get('VAST_API_KEY')
    if not api_key:
        print("❌ Ошибка: VAST_API_KEY не установлен")
        return 1
    
    headers = {"Authorization": f"Bearer {api_key}"}
    
    # Параметры из конфига (игнорируем host_whitelist)
    params = {
        "gpu_models": None,
        "gpu_whitelist": [],
        "gpu_blacklist": [],
        "gpu_required": False,
        "gpu_priority": True,
        "min_vram": 24000,  # 24GB VRAM
        "min_price": 0.01,
        "max_price": 0.15,  # MAX_PRICE_DEFAULT
        "min_reliability": 0.85,
        "min_dlperf": 20,
        "min_dlperf_per_dphtotal": 100,
        "min_cuda": 11.2,
        "compute_cap": 750,
        "min_inet_down": 100,
        "min_inet_up": 50,
        "min_cpu_cores": 6,
        "min_cpu_ram": 8,
        "min_disk_bw": 100,
        "min_gpu_mem_bw": 400,
        "datacenter": None,
        "verified": True,
        "type": "bid",
        "wait": False,
        "download": True,
        "allocated_storage": 100,
        "disk_space": 100,
        "host_blacklist": [
            67349, 156822, 282563, 283255, 344939, 152728, 55116, 296571,
            160473, 34742, 51981, 124072, 312826, 155386, 319870, 124171,
            81456, 28229362, 85323, 28230170
        ]
    }
    
    print("📋 ПАРАМЕТРЫ ПОИСКА:")
    print(f"   - Min VRAM: {params['min_vram']}MB ({params['min_vram']/1024:.1f}GB)")
    print(f"   - Price range: ${params['min_price']} - ${params['max_price']}/час")
    print(f"   - Min CUDA: {params['min_cuda']}")
    print(f"   - Compute Capability: {params['compute_cap']}")
    print(f"   - Verified only: {params['verified']}")
    print(f"   - Disk space: {params['disk_space']}GB")
    print(f"   - Hosts in blacklist: {len(params['host_blacklist'])}")
    print()
    
    # Создаем параметры поиска для API
    search_params = {
        "q": {
            "verified": {"eq": params['verified']},
            "external": {"eq": False},
            "rentable": {"eq": True},
            "gpu_ram": {"gte": params['min_vram']},
            "dph_total": {"gte": params['min_price'], "lte": params['max_price']},
            "cuda_max_good": {"gte": params['min_cuda']},
            "compute_cap": {"gte": params['compute_cap']},
            "inet_down": {"gte": params['min_inet_down']},
            "inet_up": {"gte": params['min_inet_up']},
            "cpu_cores": {"gte": params['min_cpu_cores']},
            "cpu_ram": {"gte": params['min_cpu_ram']},
            "disk_bw": {"gte": params['min_disk_bw']},
            "gpu_mem_bw": {"gte": params['min_gpu_mem_bw']},
            "dlperf": {"gte": params['min_dlperf']},
            "dlperf_per_dphtotal": {"gte": params['min_dlperf_per_dphtotal']},
            "reliability2": {"gte": params['min_reliability']},
            "disk_space": {"gte": params['disk_space']},
            "order": [["dph_total", "asc"]]
        },
        "limit": 10
    }
    
    # Исключаем хосты из blacklist
    if params['host_blacklist']:
        search_params['q']['id'] = {"not_in": params['host_blacklist']}
    
    print("🔍 ИЩЕМ ПОДХОДЯЩИЕ ОФФЕРЫ...")
    url = "https://console.vast.ai/api/v0/bundles/"
    
    try:
        response = requests.put(url, headers=headers, json=search_params, timeout=60)
        
        if response.status_code == 200:
            data = response.json()
            offers = data.get("offers", [])
            
            print(f"✅ Найдено офферов: {len(offers)}")
            print()
            
            if not offers:
                print("❌ Не найдено подходящих офферов")
                print("   Попробуйте ослабить требования")
                return 1
            
            # Показываем найденные офферы
            for i, offer in enumerate(offers[:5]):
                offer_id = offer.get("id")
                gpu_name = offer.get("gpu_name", "unknown")
                gpu_ram = offer.get("gpu_ram", 0)
                disk_space = offer.get("disk_space", 0)
                dph_total = offer.get("dph_total", 0)
                cpu_cores = offer.get("cpu_cores", 0)
                cpu_ram = offer.get("cpu_ram", 0)
                cuda_max_good = offer.get("cuda_max_good", 0)
                dlperf = offer.get("dlperf", 0)
                reliability = offer.get("reliability2", 0)
                host_id = offer.get("host_id", 0)
                
                print(f"{i+1}. ОФФЕР ID: {offer_id}")
                print(f"   GPU: {gpu_name} ({gpu_ram}MB = {gpu_ram/1024:.1f}GB VRAM)")
                print(f"   CPU: {cpu_cores} ядер, {cpu_ram}MB RAM")
                print(f"   Диск: {disk_space}GB")
                print(f"   CUDA: {cuda_max_good}")
                print(f"   DLPerf: {dlperf:.1f}")
                print(f"   Надежность: {reliability:.3f}")
                print(f"   Хост ID: {host_id}")
                print(f"   Цена: ${dph_total:.3f}/час")
                print()
            
            # Выбираем лучший оффер (самый дешевый)
            best_offer = offers[0]
            best_id = best_offer.get("id")
            best_gpu = best_offer.get("gpu_name")
            best_vram = best_offer.get("gpu_ram")
            best_price = best_offer.get("dph_total")
            
            print("="*60)
            print(f"🎯 ВЫБРАН ОФФЕР: ID {best_id}")
            print(f"   GPU: {best_gpu} ({best_vram}MB VRAM)")
            print(f"   Цена: ${best_price:.3f}/час")
            print()
            
            # СОЗДАЕМ ИНСТАНС
            print("🚀 СОЗДАЕМ ИНСТАНС...")
            
            create_data = {
                "client_id": "me",
                "image": "registry.gitlab.com/gfever/vastai_interup:video-gen",
                "disk": params["disk_space"],  # 100GB как в параметрах
                "args_str": "echo \"Starting video generation with exact parameters...\" && sleep 7200",
                "ssh": True,
                "env": {
                    "DEBUG": "true",
                    "WORKSPACE": "/workspace",
                    "MODEL_CACHE": "/workspace/models",
                    "OUTPUT_DIR": "/workspace/outputs"
                }
            }
            
            endpoint = f"https://console.vast.ai/api/v0/asks/{best_id}/"
            
            create_response = requests.put(endpoint, headers=headers, json=create_data, timeout=60)
            
            if create_response.status_code == 200:
                create_data = create_response.json()
                new_instance_id = create_data.get("new_contract")
                
                print(f"✅ ИНСТАНС СОЗДАН УСПЕШНО!")
                print(f"   ID: {new_instance_id}")
                print(f"   Оффер: {best_id}")
                print(f"   Диск: {params['disk_space']}GB")
                print(f"   GPU: {best_gpu}")
                print(f"   Цена: ${best_price:.3f}/час")
                print()
                
                # Сохраняем информацию
                instance_info = {
                    "instance_id": new_instance_id,
                    "offer_id": best_id,
                    "disk_gb": params["disk_space"],
                    "gpu_name": best_gpu,
                    "gpu_vram_mb": best_vram,
                    "price_per_hour": best_price,
                    "created_at": "2026-03-05 20:40:00",
                    "parameters_used": params,
                    "image": "registry.gitlab.com/gfever/vastai_interup:video-gen"
                }
                
                with open("/tmp/vastai_exact_params_instance.json", "w") as f:
                    json.dump(instance_info, f, indent=2)
                
                print(f"💾 Информация сохранена в /tmp/vastai_exact_params_instance.json")
                print()
                
                print("⏳ Docker образ 40GB будет загружаться 20-40 минут")
                print("   Для проверки статуса:")
                print(f"   python3 check_instance_status.py")
                print()
                
                print("💰 СТОИМОСТЬ:")
                print(f"   - Инстанс: ${best_price:.3f}/час")
                print(f"   - Загрузка образа: бесплатно")
                print(f"   - Диск {params['disk_space']}GB: включено")
                print()
                
                print("🎯 ДЛЯ ЗАПУСКА ГЕНЕРАЦИИ:")
                print("   1. Дождитесь статуса 'running'")
                print("   2. Запустите: python3 auto_video_gen.py")
                print("   3. Или: ./quick_video_gen.sh")
                print()
                
                print("🔧 МОНИТОРИНГ:")
                print("   tail -f /tmp/vastai_powerful_monitor.log")
                
                return 0
                
            else:
                print(f"❌ Ошибка создания инстанса: {create_response.status_code}")
                print(f"   Ответ: {create_response.text[:200]}")
                return 1
                
        else:
            print(f"❌ Ошибка поиска: {response.status_code}")
            print(f"   Ответ: {response.text[:200]}")
            return 1
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        print(f"Трассировка: {traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    sys.exit(main())