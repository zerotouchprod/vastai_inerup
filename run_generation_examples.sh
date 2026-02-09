#!/bin/bash
# Примеры запуска генерации видео с загрузкой в B2/S3/R2

set -e

echo "🚀 Примеры запуска Universal Video Generation Pipeline"
echo "========================================================"

# Установите переменные окружения для B2/S3
export B2_KEY="your_access_key_here"
export B2_SECRET="your_secret_key_here"
export B2_BUCKET="your-bucket-name"
export B2_ENDPOINT="https://s3.us-west-000.backblazeb2.com"
export B2_REGION="us-west-000"

echo ""
echo "📋 Пример 1: UNIVERSAL режим (двухэтапный T2I → I2V)"
echo "----------------------------------------------------"
echo "Генерация видео из текстового промпта:"
echo "1. Создает изображение с помощью SDXL Lightning"
echo "2. Очищает VRAM"
echo "3. Анимирует изображение с помощью CogVideoX-5b-I2V"
echo ""

cat > /tmp/job_universal.json << 'EOF'
{
  "mode": "universal",
  "prompts": ["Saitama vs Sonic epic battle, anime style, dynamic action"],
  "guidance_scale": 6.0,
  "num_inference_steps": 50,
  "num_frames": 49,
  "fps": 8,
  "output_prefix": "generated/anime/",
  "t2i_steps": 4,
  "t2i_guidance_scale": 0.0
}
EOF

echo "Команда для запуска:"
echo "python -m src.entrypoints.run_gen \\"
echo "  --job '$(cat /tmp/job_universal.json | tr -d '\n' | sed 's/"/\\"/g')' \\"
echo "  --bucket \$B2_BUCKET \\"
echo "  --b2-endpoint \$B2_ENDPOINT \\"
echo "  --b2-key \$B2_KEY \\"
echo "  --b2-secret \$B2_SECRET \\"
echo "  --b2-region \$B2_REGION"

echo ""
echo "📋 Пример 2: IMAGE2VIDEO режим (одноэтапный I2V)"
echo "------------------------------------------------"
echo "Анимация существующего изображения по URL:"
echo ""

cat > /tmp/job_i2v.json << 'EOF'
{
  "mode": "image2video",
  "prompts": ["Make the character dance with epic moves"],
  "input_images": ["https://example.com/anime_character.jpg"],
  "guidance_scale": 7.0,
  "num_inference_steps": 30,
  "num_frames": 32,
  "fps": 8,
  "output_prefix": "generated/i2v/"
}
EOF

echo "Команда для запуска:"
echo "python -m src.entrypoints.run_gen \\"
echo "  --job '$(cat /tmp/job_i2v.json | tr -d '\n' | sed 's/"/\\"/g')' \\"
echo "  --bucket \$B2_BUCKET \\"
echo "  --b2-endpoint \$B2_ENDPOINT \\"
echo "  --b2-key \$B2_KEY \\"
echo "  --b2-secret \$B2_SECRET"

echo ""
echo "📋 Пример 3: Пакетная обработка (batch)"
echo "----------------------------------------"
echo "Генерация нескольких видео в одном задании:"
echo ""

cat > /tmp/job_batch.json << 'EOF'
{
  "mode": "universal",
  "prompts": [
    "Sunset over ocean with dramatic waves",
    "Cyberpunk city at night with flying cars",
    "Fantasy dragon flying over mountains"
  ],
  "guidance_scale": 6.5,
  "num_inference_steps": 40,
  "num_frames": 49,
  "fps": 8,
  "output_prefix": "generated/batch_001/"
}
EOF

echo "Команда для запуска:"
echo "python -m src.entrypoints.run_gen \\"
echo "  --job '$(cat /tmp/job_batch.json | tr -d '\n' | sed 's/"/\\"/g')' \\"
echo "  --bucket \$B2_BUCKET \\"
echo "  --b2-endpoint \$B2_ENDPOINT \\"
echo "  --b2-key \$B2_KEY \\"
echo "  --b2-secret \$B2_SECRET \\"
echo "  --verbose"

echo ""
echo "📋 Пример 4: Тестовый запуск без загрузки"
echo "------------------------------------------"
echo "Генерация видео без загрузки в B2 (для тестирования):"
echo ""

cat > /tmp/job_test.json << 'EOF'
{
  "mode": "universal",
  "prompts": ["Test generation - simple scene"],
  "num_inference_steps": 10,
  "num_frames": 16,
  "fps": 8,
  "output_prefix": "test/"
}
EOF

echo "Команда для запуска:"
echo "python -m src.entrypoints.run_gen \\"
echo "  --job '$(cat /tmp/job_test.json | tr -d '\n' | sed 's/"/\\"/g')' \\"
echo "  --no-upload \\"
echo "  --verbose"

echo ""
echo "🔧 Параметры командной строки:"
echo "-----------------------------"
echo "  --job JSON              : Спецификация задания (обязательно)"
echo "  --bucket, -b BUCKET     : Имя бакета B2/S3"
echo "  --b2-endpoint URL       : Endpoint B2/S3"
echo "  --b2-key KEY            : Access key"
echo "  --b2-secret SECRET      : Secret key"
echo "  --b2-region REGION      : Регион (опционально)"
echo "  --no-upload             : Пропустить загрузку в B2"
echo "  --verbose, -v           : Подробный вывод"
echo "  --config FILE           : Файл конфигурации"
echo "  --output-format FORMAT  : Формат вывода (json/minimal)"

echo ""
echo "📝 Параметры JSON задания:"
echo "--------------------------"
echo "  mode           : 'universal' или 'image2video'"
echo "  prompts        : Массив текстовых промптов"
echo "  input_images   : Массив URL изображений (только для image2video)"
echo "  guidance_scale : Коэффициент guidance (1.0-20.0)"
echo "  num_inference_steps : Количество шагов инференса"
echo "  num_frames     : Количество кадров в видео"
echo "  fps            : FPS выходного видео"
echo "  output_prefix  : Префикс для выходных файлов"
echo "  t2i_steps      : Шаги для T2I этапа (только universal, 4-8)"
echo "  t2i_guidance_scale : Guidance для T2I (0.0 для Lightning)"

echo ""
echo "✅ Готово! Замените значения переменных окружения своими учетными данными B2/S3."
echo "   Для запуска скопируйте команду и выполните в терминале."