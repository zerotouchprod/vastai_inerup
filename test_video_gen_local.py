#!/usr/bin/env python3
"""
Тестовый скрипт для локальной проверки пайплайна text2image image2video.

Проверяет импорты и базовую функциональность без запуска на Vast AI.
"""

import sys
import json
from pathlib import Path

# Добавляем путь к модулям проекта
sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Проверяем что все необходимые модули импортируются."""
    print("🔍 Проверка импортов...")
    
    modules_to_test = [
        "src.services.generation.models",
        "src.services.generation.config",
        "src.services.generation.orchestrator",
        "src.shared.logging",
    ]
    
    for module_name in modules_to_test:
        try:
            __import__(module_name)
            print(f"  ✅ {module_name}")
        except ImportError as e:
            print(f"  ❌ {module_name}: {e}")
            return False
    
    return True

def test_job_creation():
    """Проверяем создание задания для генерации."""
    print("\n📋 Проверка создания задания...")
    
    try:
        from src.services.generation.models import GenJob, GenerationMode
        
        # Тестовое задание для text2video
        job = GenJob(
            mode=GenerationMode.UNIVERSAL,
            prompts=["A test cat dancing"],
            output_prefix="test_output/"
        )
        
        print(f"  ✅ Создано задание: {job.id}")
        print(f"     Mode: {job.mode}")
        print(f"     Prompts: {job.prompts}")
        print(f"     Output prefix: {job.output_prefix}")
        
        # Проверяем JSON сериализацию
        job_json = job.to_json()
        print(f"  ✅ JSON сериализация: {len(job_json)} символов")
        
        # Проверяем десериализацию
        job_from_json = GenJob.from_json(job_json)
        print(f"  ✅ JSON десериализация: {job_from_json.id}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Ошибка создания задания: {e}")
        return False

def test_config():
    """Проверяем конфигурацию."""
    print("\n⚙️  Проверка конфигурации...")
    
    try:
        from src.services.generation.config import GenerationConfig
        
        config = GenerationConfig()
        
        print(f"  ✅ Конфигурация загружена")
        print(f"     T2V модель: {config.T2V_MODEL_ID}")
        print(f"     I2V модель: {config.I2V_MODEL_ID}")
        print(f"     Default frames: {config.DEFAULT_NUM_FRAMES}")
        print(f"     Default FPS: {config.DEFAULT_FPS}")
        
        # Проверяем параметры оптимизации
        optim_kwargs = config.get_optimization_kwargs()
        print(f"  ✅ Параметры оптимизации: {len(optim_kwargs)} параметров")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Ошибка конфигурации: {e}")
        return False

def test_run_gen_help():
    """Проверяем что run_gen.py работает и показывает help."""
    print("\n🆘 Проверка run_gen.py --help...")
    
    try:
        import subprocess
        
        result = subprocess.run(
            [sys.executable, "-m", "src.entrypoints.run_gen", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        
        if result.returncode == 0:
            print("  ✅ run_gen.py --help работает")
            # Показываем первые несколько строк help
            lines = result.stdout.split('\n')[:10]
            for line in lines:
                print(f"     {line}")
            return True
        else:
            print(f"  ❌ run_gen.py --help вернул код {result.returncode}")
            print(f"     stderr: {result.stderr[:200]}")
            return False
            
    except Exception as e:
        print(f"  ❌ Ошибка запуска run_gen.py: {e}")
        return False

def test_dry_run():
    """Проверяем dry-run режим."""
    print("\n🧪 Проверка dry-run режима...")
    
    try:
        import subprocess
        
        # Создаем тестовое задание
        test_job = {
            "prompts": ["A test prompt for dry run"],
            "mode": "universal"
        }
        
        result = subprocess.run(
            [
                sys.executable, "-m", "src.entrypoints.run_gen",
                "--job", json.dumps(test_job),
                "--no-upload",
                "--verbose"
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            timeout=30  # 30 секунд таймаут
        )
        
        if result.returncode == 0:
            print("  ✅ Dry-run успешен")
            # Ищем ключевые слова в выводе
            if "Text-to-Video Generation Worker" in result.stdout:
                print("     ✓ Заголовок найден")
            if "Job ID:" in result.stdout:
                print("     ✓ Job ID найден")
            if "Worker finished" in result.stdout:
                print("     ✓ Завершение найдено")
            return True
        else:
            print(f"  ❌ Dry-run вернул код {result.returncode}")
            print(f"     stdout: {result.stdout[:500]}")
            print(f"     stderr: {result.stderr[:500]}")
            return False
            
    except subprocess.TimeoutExpired:
        print("  ⚠️  Dry-run превысил таймаут (возможно, загрузка моделей)")
        return False
    except Exception as e:
        print(f"  ❌ Ошибка dry-run: {e}")
        return False

def main():
    """Основная функция тестирования."""
    print("=" * 60)
    print("🧪 Тестирование пайплайна text2image image2video")
    print("=" * 60)
    
    tests = [
        ("Импорты", test_imports),
        ("Конфигурация", test_config),
        ("Создание задания", test_job_creation),
        ("run_gen.py --help", test_run_gen_help),
        ("Dry-run режим", test_dry_run),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            print(f"  ❌ Неожиданная ошибка в тесте {test_name}: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 60)
    print("📊 Результаты тестирования:")
    print("=" * 60)
    
    all_passed = True
    for test_name, success in results:
        status = "✅ ПРОЙДЕН" if success else "❌ ПРОВАЛЕН"
        print(f"  {test_name}: {status}")
        if not success:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 Все тесты пройдены! Пайплайн готов к запуску на Vast AI.")
        print("\nСледующие шаги:")
        print("  1. Установите VAST_API_KEY в переменные окружения")
        print("  2. Запустите: python run_video_gen_vastai.py --mode text2video --prompts 'Your prompt'")
        print("  3. Следите за статусом в консоли Vast AI")
    else:
        print("⚠️  Некоторые тесты не пройдены. Проверьте ошибки выше.")
        print("\nРекомендации:")
        print("  1. Убедитесь что все зависимости установлены")
        print("  2. Проверьте структуру проекта")
        print("  3. Запустите установку: pip install -r requirements.gen.txt")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())