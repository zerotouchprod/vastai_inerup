тся #!/usr/bin/env python3
"""
Автоматическая загрузка моделей на RunPod Network Volume
Выполняется внутри pod через runpodctl exec
"""

import os
import sys
import time
import subprocess
from pathlib import Path

def run_command(cmd, description):
    """Выполнить команду и вывести результат"""
    print(f"\n📋 {description}")
    print(f"   Команда: {cmd}")
    
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=3600  # 1 час таймаут
        )
        
        if result.returncode == 0:
            print(f"   ✅ Успешно")
            if result.stdout.strip():
                print(f"   Вывод: {result.stdout[:200]}...")
        else:
            print(f"   ❌ Ошибка (код: {result.returncode})")
            print(f"   Stderr: {result.stderr[:500]}")
            return False
            
        return True
        
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  Таймаут команды")
        return False
    except Exception as e:
        print(f"   ❌ Исключение: {e}")
        return False

def main():
    print("=" * 70)
    print("🤖 АВТОМАТИЧЕСКАЯ ЗАГРУЗКА МОДЕЛЕЙ НА RUNPOD NETWORK VOLUME")
    print("=" * 70)
    
    # Проверка, что мы в pod с сетевым томом
    volume_path = Path("/runpod-volume")
    if not volume_path.exists():
        print("❌ ОШИБКА: /runpod-volume не найден!")
        print("   Убедитесь, что сетевой том подключен к pod")
        return 1
    
    print(f"✅ Сетевой том найден: {volume_path}")
    print(f"   Свободное место: {subprocess.getoutput('df -h /runpod-volume | tail -1')}")
    
    # 1. Установка huggingface_hub
    if not run_command("pip install huggingface_hub --upgrade", "Установка huggingface_hub"):
        print("⚠️  Пробую установить через pip3...")
        if not run_command("pip3 install huggingface_hub --upgrade", "Установка через pip3"):
            return 1
    
    # 2. Создание директорий для моделей
    models_path = volume_path / "models"
    dreamshaper_path = models_path / "dreamshaper-xl-lightning"
    cogvideox_path = models_path / "CogVideoX-5b-I2V"
    
    for path in [models_path, dreamshaper_path, cogvideox_path]:
        path.mkdir(parents=True, exist_ok=True)
        print(f"✅ Создана директория: {path}")
    
    # 3. Загрузка DreamShaper XL Lightning
    print("\n" + "=" * 70)
    print("1. ЗАГРУЗКА DREAMSHAPER XL LIGHTNING")
    print("=" * 70)
    
    dreamshaper_file = dreamshaper_path / "sdxl_lightning_4step_unet.safetensors"
    
    if dreamshaper_file.exists():
        size_mb = dreamshaper_file.stat().st_size / (1024 * 1024)
        print(f"✅ DreamShaper уже загружен: {dreamshaper_file}")
        print(f"   Размер: {size_mb:.2f} MB")
    else:
        print(f"📥 Загружаю DreamShaper в: {dreamshaper_path}")
        
        download_script = f"""
import sys
sys.path.append('/opt/venv/lib/python3.11/site-packages')
from huggingface_hub import hf_hub_download
import os

print("Начинаю загрузку DreamShaper...")
try:
    hf_hub_download(
        repo_id="ByteDance/SDXL-Lightning",
        filename="sdxl_lightning_4step_unet.safetensors",
        local_dir="{dreamshaper_path}",
        local_dir_use_symlinks=False,
        resume_download=True
    )
    print("✅ DreamShaper успешно загружен!")
    
    # Проверка
    file_path = os.path.join("{dreamshaper_path}", "sdxl_lightning_4step_unet.safetensors")
    if os.path.exists(file_path):
        size = os.path.getsize(file_path) / (1024 * 1024)
        print(f"Файл: {{file_path}}")
        print(f"Размер: {{size:.2f}} MB")
    else:
        print("❌ Файл не найден после загрузки")
        
except Exception as e:
    print(f"❌ Ошибка загрузки: {{e}}")
    sys.exit(1)
"""
        
        # Сохраняем скрипт и выполняем
        script_path = "/tmp/download_dreamshaper.py"
        with open(script_path, "w") as f:
            f.write(download_script)
        
        if not run_command(f"python3 {script_path}", "Загрузка DreamShaper"):
            return 1
    
    # 4. Загрузка CogVideoX-5b-I2V
    print("\n" + "=" * 70)
    print("2. ЗАГРУЗКА COGVIDEOX-5b-I2V")
    print("=" * 70)
    print("⚠️  ВНИМАНИЕ: Это большая модель (~15GB), загрузка займет 30-60 минут")
    
    # Проверяем, есть ли уже файлы
    cog_files = list(cogvideox_path.glob("*"))
    if cog_files:
        total_size = sum(f.stat().st_size for f in cog_files if f.is_file())
        total_size_gb = total_size / (1024**3)
        print(f"✅ CogVideoX уже частично загружен: {len(cog_files)} файлов")
        print(f"   Текущий размер: {total_size_gb:.2f} GB")
        print("   Продолжаем загрузку...")
    
    # Запускаем загрузку в фоне
    download_script = f"""
import sys
sys.path.append('/opt/venv/lib/python3.11/site-packages')
from huggingface_hub import snapshot_download
import os
import time

print("Начинаю загрузку CogVideoX-5b-I2V...")
print("Это займет 30-60 минут...")

try:
    start_time = time.time()
    
    snapshot_download(
        repo_id="THUDM/CogVideoX-5b",
        local_dir="{cogvideox_path}",
        local_dir_use_symlinks=False,
        ignore_patterns=["*.bin", "*.msgpack", "*.h5", "*.ot"],
        resume_download=True
    )
    
    download_time = time.time() - start_time
    
    # Подсчет файлов и размера
    files = [f for f in os.listdir("{cogvideox_path}") if os.path.isfile(os.path.join("{cogvideox_path}", f))]
    total_size = sum(os.path.getsize(os.path.join("{cogvideox_path}", f)) for f in files)
    total_size_gb = total_size / (1024**3)
    
    print("✅ CogVideoX успешно загружен!")
    print(f"Файлов: {{len(files)}}")
    print(f"Общий размер: {{total_size_gb:.2f}} GB")
    print(f"Время загрузки: {{download_time/60:.1f}} минут")
    print(f"Скорость: {{total_size_gb/(download_time/3600):.2f}} GB/час")
    
except Exception as e:
    print(f"❌ Ошибка загрузки: {{e}}")
    sys.exit(1)
"""
    
    # Сохраняем скрипт
    script_path = "/tmp/download_cogvideox.py"
    with open(script_path, "w") as f:
        f.write(download_script)
    
    # Запускаем в фоне и мониторим
    print("🚀 Запускаю загрузку CogVideoX в фоне...")
    print("📊 Мониторинг прогресса (обновляется каждые 30 секунд):")
    
    # Запуск в фоне
    bg_process = subprocess.Popen(
        f"python3 {script_path} > /tmp/cogvideox.log 2>&1",
        shell=True
    )
    
    # Мониторинг
    try:
        for i in range(120):  # Мониторим до 60 минут (120 * 30 сек)
            time.sleep(30)
            
            # Проверяем статус процесса
            if bg_process.poll() is not None:
                print("✅ Загрузка CogVideoX завершена!")
                break
            
            # Показываем прогресс
            if os.path.exists("/tmp/cogvideox.log"):
                with open("/tmp/cogvideox.log", "r") as f:
                    lines = f.readlines()
                    if lines:
                        last_line = lines[-1].strip()
                        print(f"   Прогресс: {last_line}")
            
            # Показываем размер директории
            if cogvideox_path.exists():
                size_cmd = f"du -sh {cogvideox_path} 2>/dev/null | cut -f1 || echo '0'"
                size = subprocess.getoutput(size_cmd)
                print(f"   Текущий размер: {size}")
                
        else:
            print("⚠️  Загрузка все еще продолжается...")
            print("   Можно оставить работать в фоне")
            
    except KeyboardInterrupt:
        print("\n⚠️  Прервано пользователем")
        bg_process.terminate()
        return 1
    
    # 5. Финальная проверка
    print("\n" + "=" * 70)
    print("📦 ФИНАЛЬНАЯ ПРОВЕРКА")
    print("=" * 70)
    
    # DreamShaper
    if dreamshaper_file.exists():
        size_mb = dreamshaper_file.stat().st_size / (1024 * 1024)
        print(f"✅ DreamShaper: {size_mb:.2f} MB")
    else:
        print(f"❌ DreamShaper не найден!")
        return 1
    
    # CogVideoX
    cog_files = list(cogvideox_path.glob("*"))
    if cog_files:
        total_size = sum(f.stat().st_size for f in cog_files if f.is_file())
        total_size_gb = total_size / (1024**3)
        print(f"✅ CogVideoX: {len(cog_files)} файлов, {total_size_gb:.2f} GB")
        
        print("   Первые 10 файлов:")
        for f in cog_files[:10]:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"     - {f.name} ({size_mb:.1f} MB)")
    else:
        print(f"❌ CogVideoX не загружен!")
        return 1
    
    # Общий размер
    total_size_cmd = f"du -sh {models_path}"
    total_size = subprocess.getoutput(total_size_cmd)
    print(f"\n📊 Общий размер моделей: {total_size}")
    
    # Свободное место
    free_space = subprocess.getoutput("df -h /runpod-volume | tail -1")
    print(f"📊 Свободное место на томе: {free_space}")
    
    print("\n" + "=" * 70)
    print("🎉 ВСЕ МОДЕЛИ УСПЕШНО ЗАГРУЖЕНЫ!")
    print("=" * 70)
    print("\nСледующие шаги:")
    print("1. Перезапустите handler: pkill -f 'python -m src.entrypoints.runpod_handler'")
    print("2. Handler автоматически перезапустится и обнаружит модели")
    print("3. Endpoint будет готов принимать запросы на генерацию видео")
    print("\nТестовый запрос:")
    print("""
curl -X POST http://<pod-ip>:8000/runsync \\
  -H "Content-Type: application/json" \\
  -d '{
    "input": {
      "prompt": "a beautiful sunset over mountains",
      "t2i_steps": 4,
      "num_inference_steps": 25
    }
  }'
""")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())