#!/usr/bin/env python3
"""
Скрипт для запуска пайплайна text2image image2video на Vast AI.

Использует существующий Docker образ registry.gitlab.com/gfever/vastai_interup:video-gen
и код для аренды инстансов на Vast AI.

Примеры использования:
1. Text-to-Video:
   python run_video_gen_vastai.py --mode text2video --prompts "A cat dancing" "Sunset over ocean"

2. Image-to-Video:
   python run_video_gen_vastai.py --mode image2video --prompts "Make it dance" --input-images "https://example.com/cat.jpg"

3. С параметрами:
   python run_video_gen_vastai.py --mode text2video --prompts "Cyberpunk city" --num-frames 49 --guidance-scale 7.5
"""

import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional

# Добавляем путь к модулям проекта
sys.path.insert(0, str(Path(__file__).parent))

def create_job_json(
    mode: str,
    prompts: List[str],
    input_images: Optional[List[str]] = None,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    guidance_scale: float = 7.5,
    num_inference_steps: int = 30,
    num_frames: int = 49,
    fps: int = 8,
    output_prefix: str = "vastai_generation/"
) -> str:
    """
    Создает JSON спецификацию для задания генерации.
    
    Args:
        mode: Режим генерации ('text2video' или 'image2video')
        prompts: Список промптов
        input_images: Список URL изображений (только для image2video)
        negative_prompt: Негативный промпт
        seed: Сид для воспроизводимости
        guidance_scale: Коэффициент guidance
        num_inference_steps: Количество шагов инференса
        num_frames: Количество кадров
        fps: FPS выходного видео
        output_prefix: Префикс для выходных файлов
        
    Returns:
        JSON строка с заданием
    """
    job = {
        "mode": mode,
        "prompts": prompts,
        "negative_prompt": negative_prompt,
        "seed": seed,
        "guidance_scale": guidance_scale,
        "num_inference_steps": num_inference_steps,
        "num_frames": num_frames,
        "fps": fps,
        "output_prefix": output_prefix
    }
    
    if mode == "image2video" and input_images:
        job["input_images"] = input_images
    
    return json.dumps(job)

def run_vast_submit(
    image: str,
    command: str,
    min_vram: int = 24,
    max_price: float = 1.0,
    input_url: Optional[str] = None,
    offline: bool = False,
    offer_id: Optional[int] = None
) -> bool:
    """
    Запускает vast_submit.py для создания инстанса на Vast AI.
    
    Args:
        image: Docker образ
        command: Команда для выполнения
        min_vram: Минимальный VRAM в GB
        max_price: Максимальная цена в USD/час
        input_url: URL входного файла (опционально)
        offline: Пропустить поиск офферов
        offer_id: ID конкретного оффера
        
    Returns:
        True если успешно, False если ошибка
    """
    vast_submit_path = Path(__file__).parent / "vast" / "vast_submit.py"
    
    if not vast_submit_path.exists():
        print(f"❌ Файл vast_submit.py не найден: {vast_submit_path}")
        return False
    
    # Собираем аргументы
    cmd = [
        sys.executable, str(vast_submit_path),
        "--image", image,
        "--cmd", command,
        "--min-vram", str(min_vram),
        "--max-price", str(max_price)
    ]
    
    if input_url:
        cmd.extend(["--input-url", input_url])
    
    if offline:
        cmd.append("--offline")
    
    if offer_id:
        cmd.extend(["--offer-id", str(offer_id)])
    
    print(f"🚀 Запуск vast_submit.py с командой:")
    print(f"   Образ: {image}")
    print(f"   Команда: {command}")
    print(f"   Min VRAM: {min_vram}GB")
    print(f"   Max цена: ${max_price}/час")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Инстанс успешно создан на Vast AI")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Ошибка при запуске vast_submit.py:")
        print(f"   Статус: {e.returncode}")
        print(f"   STDOUT: {e.stdout}")
        print(f"   STDERR: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description="Запуск пайплайна text2image image2video на Vast AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  # Text-to-Video с одним промптом
  python run_video_gen_vastai.py --mode text2video --prompts "A cat dancing"
  
  # Image-to-Video с URL изображения
  python run_video_gen_vastai.py --mode image2video \\
    --prompts "Make it dance" \\
    --input-images "https://example.com/cat.jpg"
  
  # Пакетная генерация с кастомными параметрами
  python run_video_gen_vastai.py --mode text2video \\
    --prompts "Sunset" "Ocean waves" "City at night" \\
    --num-frames 64 --guidance-scale 8.0 --seed 42
  
  # Использование конкретного оффера на Vast AI
  python run_video_gen_vastai.py --mode text2video \\
    --prompts "Test" --offer-id 123456
        """
    )
    
    # Основные параметры
    parser.add_argument(
        "--mode",
        choices=["text2video", "image2video"],
        required=True,
        help="Режим генерации: text2video или image2video"
    )
    
    parser.add_argument(
        "--prompts",
        nargs="+",
        required=True,
        help="Промпты для генерации (один или несколько)"
    )
    
    parser.add_argument(
        "--input-images",
        nargs="+",
        help="URL изображений для image2video режима (должно совпадать с количеством промптов)"
    )
    
    # Параметры генерации
    parser.add_argument(
        "--negative-prompt",
        help="Негативный промпт (что исключить из генерации)"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        help="Сид для воспроизводимости"
    )
    
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=7.5,
        help="Коэффициент guidance (по умолчанию: 7.5)"
    )
    
    parser.add_argument(
        "--num-inference-steps",
        type=int,
        default=30,
        help="Количество шагов инференса (по умолчанию: 30)"
    )
    
    parser.add_argument(
        "--num-frames",
        type=int,
        default=49,
        help="Количество кадров в видео (по умолчанию: 49)"
    )
    
    parser.add_argument(
        "--fps",
        type=int,
        default=8,
        help="FPS выходного видео (по умолчанию: 8)"
    )
    
    parser.add_argument(
        "--output-prefix",
        default="vastai_generation/",
        help="Префикс для выходных файлов (по умолчанию: vastai_generation/)"
    )
    
    # Параметры Vast AI
    parser.add_argument(
        "--image",
        default="registry.gitlab.com/gfever/vastai_interup:video-gen",
        help="Docker образ (по умолчанию: registry.gitlab.com/gfever/vastai_interup:video-gen)"
    )
    
    parser.add_argument(
        "--min-vram",
        type=int,
        default=24,
        help="Минимальный VRAM в GB (по умолчанию: 24)"
    )
    
    parser.add_argument(
        "--max-price",
        type=float,
        default=1.0,
        help="Максимальная цена в USD/час (по умолчанию: 1.0)"
    )
    
    parser.add_argument(
        "--input-url",
        help="URL входного файла (если нужен для пайплайна)"
    )
    
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Пропустить поиск офферов (использовать --offer-id)"
    )
    
    parser.add_argument(
        "--offer-id",
        type=int,
        help="ID конкретного оффера на Vast AI"
    )
    
    parser.add_argument(
        "--no-upload",
        action="store_true",
        help="Не загружать результаты в B2 (для тестирования)"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Подробный вывод"
    )
    
    args = parser.parse_args()
    
    # Валидация
    if args.mode == "image2video" and not args.input_images:
        parser.error("Для режима image2video требуется --input-images")
    
    if args.input_images and len(args.input_images) != len(args.prompts):
        parser.error("Количество input-images должно совпадать с количеством промптов")
    
    # Создаем JSON задание
    job_json = create_job_json(
        mode=args.mode,
        prompts=args.prompts,
        input_images=args.input_images,
        negative_prompt=args.negative_prompt,
        seed=args.seed,
        guidance_scale=args.guidance_scale,
        num_inference_steps=args.num_inference_steps,
        num_frames=args.num_frames,
        fps=args.fps,
        output_prefix=args.output_prefix
    )
    
    print("📋 Создано задание для генерации:")
    print(json.dumps(json.loads(job_json), indent=2))
    print()
    
    # Создаем команду для запуска в контейнере
    cmd_parts = [
        "python -m src.entrypoints.run_gen",
        f"--job '{job_json}'",
        f"--output-format json"
    ]
    
    if args.verbose:
        cmd_parts.append("--verbose")
    
    if args.no_upload:
        cmd_parts.append("--no-upload")
    
    command = " ".join(cmd_parts)
    
    # Запускаем на Vast AI
    print("🌐 Запуск на Vast AI...")
    success = run_vast_submit(
        image=args.image,
        command=command,
        min_vram=args.min_vram,
        max_price=args.max_price,
        input_url=args.input_url,
        offline=args.offline,
        offer_id=args.offer_id
    )
    
    if success:
        print("✅ Задание успешно отправлено на Vast AI")
        print("📊 Мониторинг инстанса:")
        print("   - Проверьте статус в консоли Vast AI")
        print("   - Результаты будут загружены в B2 (если настроено)")
        print("   - Логи будут доступны через мониторинг инстанса")
    else:
        print("❌ Не удалось запустить задание на Vast AI")
        sys.exit(1)

if __name__ == "__main__":
    main()