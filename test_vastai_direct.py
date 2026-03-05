#!/usr/bin/env python3
"""
Прямой запуск тестового задания на Vast AI.
"""

import os
import json
import subprocess
import sys
import time

def main():
    print("🚀 Прямой запуск тестового задания на Vast AI")
    print("=" * 60)
    
    # Устанавливаем API ключ
    os.environ['VAST_API_KEY'] = '2dcd17021ab5f1613be725d63df1013292a0318238fa0a4547574209bf098600'
    
    # Создаем тестовое задание
    test_job = {
        "mode": "text2video",
        "prompts": ["A simple test animation of a rotating cube, minimalistic, white background"],
        "guidance_scale": 7.5,
        "num_inference_steps": 20,
        "num_frames": 16,
        "fps": 8,
        "output_prefix": "test_run/",
        "seed": 12345
    }
    
    job_json = json.dumps(test_job)
    print("📋 Тестовое задание:")
    print(json.dumps(test_job, indent=2))
    
    # Экранируем JSON для командной строки
    escaped_json = json.dumps(job_json)
    
    # Команда для запуска
    cmd = [
        sys.executable,
        "vast/vast_submit.py",
        "--image", "registry.gitlab.com/gfever/vastai_interup:video-gen",
        "--cmd", f"python -m src.entrypoints.run_gen --job '{job_json}' --no-upload",
        "--min-vram", "16",
        "--max-price", "0.5",
        "--verbose"
    ]
    
    print(f"\n🔧 Команда для запуска:")
    print(" ".join(cmd[:5]) + " ...")
    
    print("\n⚠️  ВНИМАНИЕ: Это создаст инстанс на Vast AI")
    print("   Будет списана оплата за время использования!")
    
    confirm = input("\nПродолжить? (y/N): ").strip().lower()
    if confirm != 'y':
        print("Отменено пользователем")
        return 0
    
    print("\n⏳ Запуск задания...")
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
        
        # Читаем stdout и stderr
        import select
        import fcntl
        import os as os_module
        
        # Делаем файловые дескрипторы неблокирующими
        fcntl.fcntl(process.stdout, fcntl.F_SETFL, os_module.O_NONBLOCK)
        fcntl.fcntl(process.stderr, fcntl.F_SETFL, os_module.O_NONBLOCK)
        
        start_time = time.time()
        timeout = 300  # 5 минут
        
        while True:
            # Проверяем таймаут
            if time.time() - start_time > timeout:
                print("\n⏱️  Таймаут ожидания")
                process.terminate()
                break
            
            # Проверяем завершение процесса
            return_code = process.poll()
            if return_code is not None:
                print(f"\nПроцесс завершился с кодом: {return_code}")
                break
            
            # Читаем stdout
            try:
                stdout_line = process.stdout.readline()
                if stdout_line:
                    print(f"STDOUT: {stdout_line.strip()}")
            except:
                pass
            
            # Читаем stderr
            try:
                stderr_line = process.stderr.readline()
                if stderr_line:
                    print(f"STDERR: {stderr_line.strip()}")
            except:
                pass
            
            time.sleep(0.1)
        
        # Получаем оставшийся вывод
        stdout, stderr = process.communicate(timeout=10)
        if stdout:
            print(f"\nОставшийся STDOUT:\n{stdout}")
        if stderr:
            print(f"\nОставшийся STDERR:\n{stderr}")
        
        print("\n" + "=" * 60)
        if process.returncode == 0:
            print("✅ Задание успешно отправлено на Vast AI!")
            print("\nСледующие шаги:")
            print("  1. Проверьте статус инстанса на https://vast.ai/")
            print("  2. Следите за логами в реальном времени")
            print("  3. После завершения проверьте результаты")
        else:
            print(f"❌ Не удалось запустить задание (код: {process.returncode})")
        
        return process.returncode
        
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())