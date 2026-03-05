#!/bin/bash
# Простой скрипт для запуска тестового задания на Vast AI

set -e

echo "🚀 Запуск тестового задания на Vast AI"
echo "========================================"

# Проверяем API ключ
if [ -z "$VAST_API_KEY" ]; then
    echo "❌ Ошибка: VAST_API_KEY не установлен"
    echo "   export VAST_API_KEY='ваш_ключ'"
    exit 1
fi

echo "✅ API ключ установлен (длина: ${#VAST_API_KEY})"

# Создаем тестовое задание JSON
JOB_JSON='{
  "mode": "text2video",
  "prompts": ["A simple test animation of a rotating geometric shape, minimalistic, white background"],
  "guidance_scale": 7.5,
  "num_inference_steps": 20,
  "num_frames": 16,
  "fps": 8,
  "output_prefix": "test_run/",
  "seed": 12345
}'

echo "📋 Тестовое задание создано:"
echo "$JOB_JSON" | python -m json.tool

# Экранируем JSON для командной строки
ESCAPED_JSON=$(echo "$JOB_JSON" | python -c "import json, sys; print(json.dumps(sys.stdin.read().strip()))")

echo ""
echo "🔧 Параметры запуска:"
echo "   Образ: registry.gitlab.com/gfever/vastai_interup:video-gen"
echo "   Min VRAM: 16GB"
echo "   Max цена: $0.5/час"
echo "   Кадров: 16"
echo "   Шагов: 20"

echo ""
echo "⚠️  ВНИМАНИЕ: Это создаст инстанс на Vast AI"
echo "   Будет списана оплата за время использования!"
echo ""
read -p "Продолжить? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Отменено пользователем"
    exit 0
fi

echo ""
echo "⏳ Запуск на Vast AI..."
echo "========================================"

# Запускаем vast_submit.py
cd /workspace/vastai_inerup

python vast/vast_submit.py \
  --image "registry.gitlab.com/gfever/vastai_interup:video-gen" \
  --cmd "python -m src.entrypoints.run_gen --job '$JOB_JSON' --no-upload" \
  --min-vram 16 \
  --max-price 0.5 \
  --verbose

EXIT_CODE=$?

echo ""
echo "========================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Задание успешно отправлено на Vast AI!"
    echo ""
    echo "Следующие шаги:"
    echo "  1. Проверьте статус инстанса на https://vast.ai/"
    echo "  2. Следите за логами в реальном времени"
    echo "  3. После завершения проверьте результаты"
else
    echo "❌ Не удалось запустить задание (код: $EXIT_CODE)"
    echo ""
    echo "Возможные причины:"
    echo "  1. Проблемы с API ключом"
    echo "  2. Нет доступных инстансов"
    echo "  3. Проблемы с сетью"
    echo "  4. Docker образ недоступен"
fi

echo ""
echo "📚 Дополнительная информация:"
echo "  - INSTRUCTIONS_VASTAI_VIDEO_GEN.md - полная инструкция"
echo "  - https://vast.ai/ - консоль управления"