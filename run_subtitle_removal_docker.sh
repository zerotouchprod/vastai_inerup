#!/bin/bash
# Скрипт для запуска удаления субтитров через Docker
# Использует профиль .env.precision_improved для оптимальных настроек

set -e  # Выход при ошибке

echo "🚀 Запуск удаления субтитров через Docker..."

# Проверяем наличие входного видео
INPUT_VIDEO="tests/video/1smaho.mp4"
if [ ! -f "$INPUT_VIDEO" ]; then
    echo "❌ Входное видео не найдено: $INPUT_VIDEO"
    echo "Доступные видео в tests/video/:"
    ls -la tests/video/ 2>/dev/null || echo "Директория tests/video/ не существует"
    exit 1
fi

echo "✅ Входное видео: $INPUT_VIDEO"

# Создаём выходную директорию
OUTPUT_DIR="output/docker_subtitle_removal_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"
echo "✅ Выходная директория: $OUTPUT_DIR"

# Копируем профиль настроек
if [ -f ".env.precision_improved" ]; then
    cp .env.precision_improved "$OUTPUT_DIR/.env"
    echo "✅ Используется профиль: .env.precision_improved"
else
    echo "⚠️  Профиль .env.precision_improved не найден, будут использованы настройки по умолчанию"
fi

# Проверяем, запущен ли Docker
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Docker не запущен или нет прав"
    echo "Запустите Docker и попробуйте снова"
    exit 1
fi

# Проверяем наличие образа
if ! docker image inspect registry.gitlab.com/gfever/vastai_interup:pytorch-fat-291225 > /dev/null 2>&1; then
    echo "⚠️  Docker образ не найден локально, будет загружен из registry..."
fi

echo "🔧 Настройки конфигурации:"
if [ -f "$OUTPUT_DIR/.env" ]; then
    grep -E "^(OCR_CONFIDENCE_THRESHOLD|BBOX_EXPAND_HORIZONTAL|DILATION_ITERATIONS_INITIAL)=" "$OUTPUT_DIR/.env" || echo "  (используются значения по умолчанию)"
fi

echo ""
echo "📊 Запуск pipeline_v2.py через Docker..."
echo "=========================================="

# Запускаем Docker контейнер (пропускаем entrypoint, запускаем напрямую)
docker run --rm \
  --gpus all \
  --entrypoint "" \
  -e FORCE_CPU=1 \
  -v "$(pwd)/$INPUT_VIDEO:/workspace/input_video.mp4:ro" \
  -v "$(pwd)/$OUTPUT_DIR:/workspace/output" \
  -v "$(pwd)/$OUTPUT_DIR/.env:/workspace/project/.env:ro" \
  registry.gitlab.com/gfever/vastai_interup:pytorch-fat-291225 \
  bash -c "
    echo '=== Запуск с FORCE_CPU=1 (CPU fallback) ===' && \
    echo 'Текущая директория: \$(pwd)' && \
    echo 'FORCE_CPU=\$FORCE_CPU' && \
    cd /workspace/project && \
    echo 'Содержимое .env:' && \
    cat .env 2>/dev/null | grep -v '^#' | head -20 || echo '(.env не найден или пуст)' && \
    echo '' && \
    echo 'Запуск pipeline_v2.py...' && \
    python pipeline_v2.py \
      --mode 'remove-subtitles' \
      --subs-lang 'ru' \
      --roi '0.05,0.5,0.9,0.3' \
      --input /workspace/input_video.mp4 \
      --output /workspace/output/result
  "

# Проверяем результат
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Обработка завершена успешно!"
    echo ""
    echo "📁 Результаты сохранены в: $OUTPUT_DIR"
    echo ""
    echo "Содержимое выходной директории:"
    ls -la "$OUTPUT_DIR/"
    
    # Ищем обработанное видео
    RESULT_VIDEO=$(find "$OUTPUT_DIR" -name "*.mp4" -o -name "*.avi" -o -name "*.mkv" | head -1)
    if [ -n "$RESULT_VIDEO" ]; then
        echo ""
        echo "🎬 Обработанное видео: $RESULT_VIDEO"
        echo ""
        echo "Для просмотра результата:"
        echo "  vlc '$RESULT_VIDEO'  # или другой видеоплеер"
    fi
    
    # Сохраняем логи
    echo ""
    echo "📋 Логи сохранены в: $OUTPUT_DIR/logs.txt"
    echo "Для просмотра логов: cat $OUTPUT_DIR/logs.txt"
    
else
    echo ""
    echo "❌ Ошибка при обработке видео"
    echo "Проверьте логи выше для диагностики"
    exit 1
fi

echo ""
echo "=========================================="
echo "🎉 Удаление субтитров завершено!"
echo "=========================================="
