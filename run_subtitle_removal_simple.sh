#!/bin/bash
# Простая команда для запуска удаления субтитров через Docker
# Пропускаем entrypoint и используем FORCE_CPU для обхода GPU проверки

echo "🚀 Запуск удаления субтитров (FORCE_CPU=1, пропускаем entrypoint)..."
echo ""

# Базовая команда Docker
docker run --rm \
  --gpus all \
  --entrypoint "" \
  -e FORCE_CPU=1 \
  -v "$(pwd)/tests/video/1smaho.mp4:/workspace/input_video.mp4:ro" \
  -v "$(pwd)/output/docker_result:/workspace/output" \
  -v "$(pwd)/.env.precision_improved:/workspace/project/.env:ro" \
  registry.gitlab.com/gfever/vastai_interup:pytorch-fat-291225 \
  bash -c "
    cd /workspace/project && \
    python pipeline_v2.py \
      --mode 'remove-subtitles' \
      --subs-lang 'ru' \
      --roi '0.05,0.5,0.9,0.3' \
      --input /workspace/input_video.mp4 \
      --output /workspace/output/result
  "

echo ""
echo "📋 Команда для копирования:"
echo "docker run --rm --gpus all --entrypoint \"\" -e FORCE_CPU=1 \\"
echo "  -v \"\$(pwd)/tests/video/1smaho.mp4:/workspace/input_video.mp4:ro\" \\"
echo "  -v \"\$(pwd)/output/docker_result:/workspace/output\" \\"
echo "  -v \"\$(pwd)/.env.precision_improved:/workspace/project/.env:ro\" \\"
echo "  registry.gitlab.com/gfever/vastai_interup:pytorch-fat-291225 \\"
echo "  bash -c \"cd /workspace/project && python pipeline_v2.py \\"
echo "    --mode 'remove-subtitles' \\"
echo "    --subs-lang 'ru' \\"
echo "    --roi '0.05,0.5,0.9,0.3' \\"
echo "    --input /workspace/input_video.mp4 \\"
echo "    --output /workspace/output/result\""
#/workspace/project/tests/video/
 #1smaho.mp4
