#!/usr/bin/env python3
"""
Быстрый тест для проверки работы с Vast AI без установки всех зависимостей.
Проверяет только базовую функциональность и создание JSON заданий.
"""

import json
import sys
from pathlib import Path

def test_json_creation():
    """Тест создания JSON заданий для пайплайна."""
    print("🧪 Тест создания JSON заданий")
    print("=" * 50)
    
    # Тест 1: Text-to-Video
    print("\n1. Text-to-Video задание:")
    t2v_job = {
        "mode": "text2video",
        "prompts": ["A cat dancing in the rain"],
        "guidance_scale": 7.5,
        "num_inference_steps": 30,
        "num_frames": 49,
        "fps": 8,
        "output_prefix": "test_t2v/"
    }
    
    t2v_json = json.dumps(t2v_job)
    print(f"   JSON: {t2v_json[:80]}...")
    print(f"   Длина: {len(t2v_json)} символов")
    
    # Проверяем что JSON валиден
    try:
        parsed = json.loads(t2v_json)
        print(f"   ✅ JSON валиден")
        print(f"   Промптов: {len(parsed['prompts'])}")
    except Exception as e:
        print(f"   ❌ Ошибка JSON: {e}")
        return False
    
    # Тест 2: Image-to-Video
    print("\n2. Image-to-Video задание:")
    i2v_job = {
        "mode": "image2video",
        "prompts": ["Make it dance"],
        "input_images": ["https://example.com/image.jpg"],
        "guidance_scale": 7.5,
        "num_inference_steps": 30,
        "num_frames": 49,
        "fps": 8,
        "output_prefix": "test_i2v/"
    }
    
    i2v_json = json.dumps(i2v_job)
    print(f"   JSON: {i2v_json[:80]}...")
    print(f"   Длина: {len(i2v_json)} символов")
    
    try:
        parsed = json.loads(i2v_json)
        print(f"   ✅ JSON валиден")
        print(f"   Промптов: {len(parsed['prompts'])}")
        print(f"   Изображений: {len(parsed['input_images'])}")
    except Exception as e:
        print(f"   ❌ Ошибка JSON: {e}")
        return False
    
    # Тест 3: Пакетная обработка
    print("\n3. Пакетное задание:")
    batch_job = {
        "mode": "text2video",
        "prompts": ["Scene 1", "Scene 2", "Scene 3"],
        "guidance_scale": 7.5,
        "num_inference_steps": 25,
        "num_frames": 32,
        "fps": 12,
        "output_prefix": "batch_processing/",
        "seed": 42
    }
    
    batch_json = json.dumps(batch_job, indent=2)
    print(f"   Промптов: {len(batch_job['prompts'])}")
    print(f"   Кадров: {batch_job['num_frames']}")
    print(f"   FPS: {batch_job['fps']}")
    print(f"   Seed: {batch_job['seed']}")
    
    return True

def test_vast_submit_import():
    """Тест импорта модуля vast_submit."""
    print("\n🔧 Тест импорта модулей Vast AI")
    print("=" * 50)
    
    vast_path = Path(__file__).parent / "vast" / "vast_submit.py"
    
    if not vast_path.exists():
        print(f"   ❌ Файл не найден: {vast_path}")
        return False
    
    print(f"   ✅ Файл найден: {vast_path}")
    
    # Проверяем что файл читается
    try:
        content = vast_path.read_text()[:500]
        print(f"   ✅ Файл читается ({len(content)} символов прочитано)")
        
        # Проверяем наличие ключевых функций
        if "def search_offers" in content:
            print("   ✅ Функция search_offers найдена")
        else:
            print("   ⚠️  Функция search_offers не найдена")
            
        if "def pick_offer" in content:
            print("   ✅ Функция pick_offer найдена")
        else:
            print("   ⚠️  Функция pick_offer не найдена")
            
        return True
        
    except Exception as e:
        print(f"   ❌ Ошибка чтения файла: {e}")
        return False

def test_run_gen_import():
    """Тест импорта модуля run_gen."""
    print("\n🎬 Тест импорта модуля run_gen")
    print("=" * 50)
    
    run_gen_path = Path(__file__).parent / "src" / "entrypoints" / "run_gen.py"
    
    if not run_gen_path.exists():
        print(f"   ❌ Файл не найден: {run_gen_path}")
        return False
    
    print(f"   ✅ Файл найден: {run_gen_path}")
    
    # Проверяем что файл читается
    try:
        content = run_gen_path.read_text()[:500]
        print(f"   ✅ Файл читается ({len(content)} символов прочитано)")
        
        # Проверяем наличие ключевых функций
        if "def parse_arguments" in content:
            print("   ✅ Функция parse_arguments найдена")
        else:
            print("   ⚠️  Функция parse_arguments не найдена")
            
        if "def main" in content:
            print("   ✅ Функция main найдена")
        else:
            print("   ⚠️  Функция main не найдена")
            
        return True
        
    except Exception as e:
        print(f"   ❌ Ошибка чтения файла: {e}")
        return False

def test_dockerfile():
    """Тест наличия Dockerfile."""
    print("\n🐳 Тест Dockerfile")
    print("=" * 50)
    
    dockerfiles = [
        Path(__file__).parent / "docker" / "Dockerfile.universal_no_token",
        Path(__file__).parent / "docker" / "Dockerfile.gen",
    ]
    
    found = False
    for dockerfile in dockerfiles:
        if dockerfile.exists():
            print(f"   ✅ Dockerfile найден: {dockerfile}")
            
            # Проверяем содержимое
            try:
                content = dockerfile.read_text()[:200]
                if "FROM" in content:
                    print(f"   ✅ Содержит инструкцию FROM")
                if "COPY src/" in content:
                    print(f"   ✅ Копирует исходный код")
                    
                # Проверяем метаданные
                lines = content.split('\n')
                for line in lines[:10]:
                    if line.startswith('LABEL') or line.startswith('#'):
                        print(f"   📝 {line[:60]}")
                        
                found = True
                
            except Exception as e:
                print(f"   ❌ Ошибка чтения Dockerfile: {e}")
                
    if not found:
        print("   ❌ Dockerfile не найден")
        return False
        
    return True

def generate_example_commands():
    """Генерация примеров команд для запуска."""
    print("\n🚀 Примеры команд для запуска")
    print("=" * 50)
    
    examples = [
        {
            "name": "Быстрый тест (Text-to-Video)",
            "command": """python run_video_gen_vastai.py \\
  --mode text2video \\
  --prompts "A simple test animation" \\
  --num-frames 16 \\
  --no-upload"""
        },
        {
            "name": "Производственная генерация",
            "command": """python run_video_gen_vastai.py \\
  --mode text2video \\
  --prompts "Cinematic shot of Mars landing" \\
  --num-frames 64 \\
  --guidance-scale 8.0 \\
  --min-vram 24 \\
  --max-price 1.5"""
        },
        {
            "name": "Пакетная обработка",
            "command": """python run_video_gen_vastai.py \\
  --mode text2video \\
  --prompts "Scene 1" "Scene 2" "Scene 3" \\
  --num-frames 32 \\
  --fps 12 \\
  --output-prefix "my_project/" """
        },
        {
            "name": "Ручной запуск через vast_submit",
            "command": """export VAST_API_KEY="your_api_key"
python vast/vast_submit.py \\
  --image "registry.gitlab.com/gfever/vastai_interup:video-gen" \\
  --cmd "python -m src.entrypoints.run_gen --job '{\\"prompts\\":[\\"Test\\"]}'" \\
  --min-vram 24 \\
  --max-price 1.0"""
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['name']}:")
        print("-" * 40)
        print(example['command'])
    
    return True

def main():
    """Основная функция тестирования."""
    print("=" * 60)
    print("🔍 Быстрый тест системы генерации видео на Vast AI")
    print("=" * 60)
    
    tests = [
        ("Создание JSON заданий", test_json_creation),
        ("Импорт vast_submit", test_vast_submit_import),
        ("Импорт run_gen", test_run_gen_import),
        ("Проверка Dockerfile", test_dockerfile),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            print(f"\n📋 Тест: {test_name}")
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"   ❌ Неожиданная ошибка: {e}")
            results.append((test_name, False))
    
    # Генерация примеров команд
    generate_example_commands()
    
    # Вывод результатов
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования")
    print("=" * 60)
    
    all_passed = True
    for test_name, success in results:
        status = "✅ ПРОЙДЕН" if success else "❌ ПРОВАЛЕН"
        print(f"  {test_name}: {status}")
        if not success:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 Все базовые тесты пройдены!")
        print("\nСледующие шаги:")
        print("  1. Установите VAST_API_KEY в переменные окружения")
        print("  2. Запустите один из примеров команд выше")
        print("  3. Следите за статусом в консоли Vast AI")
    else:
        print("⚠️  Некоторые тесты не пройдены")
        print("\nРекомендации:")
        print("  1. Проверьте структуру проекта")
        print("  2. Убедитесь что все файлы на месте")
        print("  3. Обратитесь к документации проекта")
    
    print("\n📚 Дополнительные ресурсы:")
    print("  - INSTRUCTIONS_VASTAI_VIDEO_GEN.md - полная инструкция")
    print("  - run_video_gen_vastai.py - основной скрипт запуска")
    print("  - vast/vast_submit.py - код для работы с Vast AI")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())