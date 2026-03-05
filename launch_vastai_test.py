#!/usr/bin/env python3
"""
Скрипт для запуска тестового задания на Vast AI.
Пытается получить API ключ из различных источников и запустить инстанс.
"""

import os
import sys
import json
import subprocess
from pathlib import Path

def get_vast_api_key():
    """Получить API ключ Vast AI из различных источников."""
    sources = [
        # 1. Переменная окружения
        ("Переменная окружения VAST_API_KEY", os.environ.get("VAST_API_KEY")),
        # 2. Переменная окружения с другим именем
        ("Переменная окружения vastai_api_key", os.environ.get("vastai_api_key")),
        # 3. Файл с ключом
        ("Файл .vast_api_key", read_file_if_exists(".vast_api_key")),
        # 4. Файл в домашней директории
        ("Файл ~/.vastai/key", read_file_if_exists(os.path.expanduser("~/.vastai/key"))),
    ]
    
    print("🔑 Поиск API ключа Vast AI...")
    for source_name, key in sources:
        if key:
            print(f"   ✅ Найден в {source_name}")
            # Проверяем что ключ выглядит валидным
            if len(key) > 20 and key.startswith("vast-"):
                print(f"   ✅ Ключ выглядит валидным (длина: {len(key)})")
                return key
            else:
                print(f"   ⚠️  Ключ может быть невалидным (длина: {len(key)})")
                return key
    
    print("   ❌ API ключ не найден")
    return None

def read_file_if_exists(filepath):
    """Прочитать файл если он существует."""
    path = Path(filepath)
    if path.exists():
        try:
            return path.read_text().strip()
        except:
            return None
    return None

def test_api_key(key):
    """Протестировать API ключ с простым запросом."""
    print("\n🧪 Тестирование API ключа...")
    
    # Импортируем requests если доступен
    try:
        import requests
    except ImportError:
        print("   ⚠️  Библиотека requests не установлена, пропускаем тест")
        return True
    
    # Пробуем сделать простой запрос к API
    headers = {"Authorization": f"Bearer {key}"}
    test_urls = [
        "https://api.vast.ai/v0/users/current/",
        "https://console.vast.ai/api/v0/users/current/",
    ]
    
    for url in test_urls:
        try:
            print(f"   Тестируем {url}...")
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                print(f"   ✅ API ключ работает (статус: {response.status_code})")
                return True
            else:
                print(f"   ⚠️  API ответил с кодом {response.status_code}")
        except Exception as e:
            print(f"   ❌ Ошибка подключения: {e}")
    
    print("   ⚠️  Не удалось проверить API ключ, продолжаем...")
    return True

def create_test_job():
    """Создать тестовое задание для генерации."""
    print("\n📋 Создание тестового задания...")
    
    job = {
        "mode": "text2video",
        "prompts": ["A simple test animation of a rotating cube, minimalistic"],
        "guidance_scale": 7.5,
        "num_inference_steps": 20,  # Меньше для теста
        "num_frames": 16,  # Меньше для теста
        "fps": 8,
        "output_prefix": "test_run/",
        "seed": 12345
    }
    
    job_json = json.dumps(job)
    print(f"   ✅ Задание создано")
    print(f"   Промпт: {job['prompts'][0]}")
    print(f"   Кадров: {job['num_frames']}")
    print(f"   Шагов: {job['num_inference_steps']}")
    
    return job_json

def run_vast_submit(api_key, job_json):
    """Запустить vast_submit.py с заданием."""
    print("\n🚀 Запуск на Vast AI...")
    
    # Устанавливаем API ключ в переменные окружения
    os.environ["VAST_API_KEY"] = api_key
    
    # Создаем команду для выполнения
    cmd = [
        sys.executable,
        str(Path(__file__).parent / "vast" / "vast_submit.py"),
        "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "--cmd", f"python -m src.entrypoints.run_gen --job '{job_json}' --no-upload",
        "--min-vram", "16",  # Меньше для теста
        "--max-price", "0.5",  # Дешевле для теста
        "--verbose"
    ]
    
    print(f"   Команда: {' '.join(cmd[:5])}...")
    print(f"   Min VRAM: 16GB")
    print(f"   Max цена: $0.5/час")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    
    try:
        # Запускаем процесс
        print("\n   ⏳ Запуск процесса...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Читаем вывод в реальном времени
        print("\n   📊 Вывод процесса:")
        print("   " + "=" * 50)
        
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(f"   {output.strip()}")
        
        # Получаем код возврата
        return_code = process.poll()
        
        print("\n   " + "=" * 50)
        if return_code == 0:
            print("   ✅ Процесс завершился успешно")
            return True
        else:
            print(f"   ❌ Процесс завершился с кодом {return_code}")
            # Выводим ошибки
            stderr = process.stderr.read()
            if stderr:
                print(f"\n   Ошибки:")
                print(f"   {stderr[:500]}")
            return False
            
    except Exception as e:
        print(f"   ❌ Ошибка запуска процесса: {e}")
        return False

def main():
    """Основная функция."""
    print("=" * 60)
    print("🚀 Запуск тестового задания на Vast AI")
    print("=" * 60)
    
    # 1. Получить API ключ
    api_key = get_vast_api_key()
    if not api_key:
        print("\n❌ API ключ Vast AI не найден!")
        print("\nСпособы предоставить ключ:")
        print("  1. Установите переменную окружения:")
        print("     export VAST_API_KEY='ваш_ключ'")
        print("  2. Создайте файл .vast_api_key в текущей директории")
        print("  3. Передайте ключ как аргумент командной строки")
        print("\nФормат ключа: vast-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx")
        return 1
    
    # 2. Протестировать API ключ
    if not test_api_key(api_key):
        print("⚠️  Проблемы с API ключом, но продолжаем...")
    
    # 3. Создать тестовое задание
    job_json = create_test_job()
    
    # 4. Запросить подтверждение
    print("\n" + "=" * 60)
    print("⚠️  ВНИМАНИЕ: Это создаст инстанс на Vast AI")
    print("   Будет списана оплата за время использования!")
    print("=" * 60)
    
    confirm = input("\nПродолжить? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено пользователем")
        return 0
    
    # 5. Запустить на Vast AI
    print("\n" + "=" * 60)
    print("Начало запуска...")
    print("=" * 60)
    
    success = run_vast_submit(api_key, job_json)
    
    print("\n" + "=" * 60)
    if success:
        print("✅ Задание успешно отправлено на Vast AI!")
        print("\nСледующие шаги:")
        print("  1. Проверьте статус инстанса на https://vast.ai/")
        print("  2. Следите за логами в реальном времени")
        print("  3. После завершения проверьте результаты")
    else:
        print("❌ Не удалось запустить задание")
        print("\nВозможные причины:")
        print("  1. Проблемы с API ключом")
        print("  2. Нет доступных инстансов")
        print("  3. Проблемы с сетью")
        print("  4. Docker образ недоступен")
    
    print("\n📚 Дополнительная информация:")
    print("  - INSTRUCTIONS_VASTAI_VIDEO_GEN.md - полная инструкция")
    print("  - https://vast.ai/ - консоль управления")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())