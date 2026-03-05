#!/usr/bin/env python3
"""
Финальный скрипт для запуска пайплайна text2image image2video на Vast AI.
"""

import os
import json
import subprocess
import sys
import time

def setup_environment():
    """Настройка переменных окружения."""
    # Vast AI API ключ
    os.environ['VAST_API_KEY'] = '2dcd17021ab5f1613be725d63df1013292a0318238fa0a4547574209bf098600'
    
    # R2 credentials для загрузки результатов
    os.environ['B2_KEY'] = '38d76603a9bf203a2578011fff337f32'
    os.environ['B2_SECRET'] = '7d519dead51176583788cd4e74d347ac07d7eaccb7fb468c5addd76f536748a0'
    os.environ['B2_BUCKET'] = 'videos'
    os.environ['B2_ENDPOINT'] = 'https://c0601da55592f50ef5c7e8b8bc18f62d.r2.cloudflarestorage.com'
    os.environ['B2_REGION'] = 'EEUR'
    
    print("✅ Переменные окружения установлены")

def create_video_job():
    """Создать задание для генерации видео."""
    print("\n📋 Создание задания для генерации видео...")
    
    # Простое тестовое задание
    job = {
        "mode": "text2video",
        "prompts": ["A beautiful sunset over ocean waves, cinematic, 4k quality"],
        "guidance_scale": 7.5,
        "num_inference_steps": 25,
        "num_frames": 24,  # 3 секунды при 8 FPS
        "fps": 8,
        "output_prefix": "vastai_generation/",
        "seed": 42
    }
    
    job_json = json.dumps(job)
    print(f"✅ Задание создано")
    print(f"   Промпт: {job['prompts'][0]}")
    print(f"   Кадров: {job['num_frames']}")
    print(f"   FPS: {job['fps']}")
    print(f"   Шагов: {job['num_inference_steps']}")
    
    return job_json

def run_vastai_job(job_json):
    """Запустить задание на Vast AI."""
    print("\n🚀 Запуск на Vast AI...")
    
    # Команда для выполнения в контейнере
    cmd_in_container = f"python -m src.entrypoints.run_gen --job '{job_json}'"
    
    # Команда для запуска vast_submit.py
    cmd = [
        sys.executable,
        "vast/vast_submit.py",
        "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "--cmd", cmd_in_container,
        "--min-vram", "16",
        "--max-price", "0.5",
        "--wait-running",  # Ждем запуска инстанса
        "--max-hours", "1"  # Максимум 1 час
    ]
    
    print(f"🔧 Параметры запуска:")
    print(f"   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen")
    print(f"   Min VRAM: 16GB")
    print(f"   Max цена: $0.5/час")
    print(f"   Max время: 1 час")
    
    print(f"\n⏳ Запуск команды...")
    print("=" * 60)
    
    try:
        # Запускаем процесс
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Читаем вывод в реальном времени
        print("\n📊 Вывод процесса:")
        print("-" * 50)
        
        # Простой способ чтения вывода
        for line in process.stdout:
            print(f"   {line.strip()}")
            sys.stdout.flush()
        
        # Ждем завершения
        process.wait()
        
        # Получаем stderr
        stderr = process.stderr.read()
        if stderr:
            print(f"\n⚠️  STDERR:")
            print(f"   {stderr[:500]}")
        
        print("\n" + "=" * 60)
        if process.returncode == 0:
            print("✅ Задание успешно запущено на Vast AI!")
            return True
        else:
            print(f"❌ Ошибка запуска (код: {process.returncode})")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка запуска процесса: {e}")
        return False

def main():
    """Основная функция."""
    print("=" * 60)
    print("🎬 Запуск пайплайна генерации видео на Vast AI")
    print("=" * 60)
    
    # 1. Настройка окружения
    setup_environment()
    
    # 2. Создание задания
    job_json = create_video_job()
    
    # 3. Подтверждение
    print("\n" + "=" * 60)
    print("⚠️  ВНИМАНИЕ: Это создаст инстанс на Vast AI")
    print("   Будет списана оплата за время использования!")
    print("   Примерная стоимость: $0.10-$0.30")
    print("=" * 60)
    
    confirm = input("\nПродолжить? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено пользователем")
        return 0
    
    # 4. Запуск задания
    print("\n" + "=" * 60)
    print("Начало запуска...")
    print("=" * 60)
    
    success = run_vastai_job(job_json)
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 Пайплайн успешно запущен!")
        print("\n📋 Что происходит:")
        print("   1. Vast AI создает инстанс с GPU")
        print("   2. Загружается Docker образ с моделью")
        print("   3. Запускается генерация видео")
        print("   4. Результаты загружаются в R2 хранилище")
        print("\n⏱️  Ожидаемое время: 5-15 минут")
        print("💵 Примерная стоимость: $0.10-$0.30")
    else:
        print("❌ Не удалось запустить пайплайн")
        print("\n🔧 Возможные решения:")
        print("   1. Проверьте баланс на Vast AI")
        print("   2. Увеличьте --max-price")
        print("   3. Уменьшите --min-vram")
        print("   4. Проверьте доступность Docker образа")
    
    print("\n📚 Дополнительная информация:")
    print("   - https://vast.ai/ - консоль управления")
    print("   - INSTRUCTIONS_VASTAI_VIDEO_GEN.md - полная инструкция")
    print("   - run_video_gen_vastai.py - основной скрипт запуска")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())