#!/bin/bash
# Быстрый запуск генерации видео на готовом инстансе Vast AI

echo "🚀 БЫСТРЫЙ ЗАПУСК ГЕНЕРАЦИИ ВИДЕО"
echo "=================================="

# Проверяем SSH информацию
if [ -f "/tmp/vastai_ssh_ready.json" ]; then
    echo "📁 Найдена SSH информация из предыдущего запуска"
    SSH_HOST=$(grep -o '"ssh_host":"[^"]*"' /tmp/vastai_ssh_ready.json | cut -d'"' -f4)
    SSH_PORT=$(grep -o '"ssh_port":[0-9]*' /tmp/vastai_ssh_ready.json | cut -d':' -f2)
    INSTANCE_ID=$(grep -o '"instance_id":"[^"]*"' /tmp/vastai_ssh_ready.json | cut -d'"' -f4)
    
    echo "   Инстанс: $INSTANCE_ID"
    echo "   SSH: $SSH_HOST:$SSH_PORT"
    
    read -p "   Использовать эти данные? (y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "✅ Используем сохраненные данные"
    else
        SSH_HOST=""
        SSH_PORT=""
    fi
fi

# Если нет сохраненных данных, запрашиваем
if [ -z "$SSH_HOST" ] || [ -z "$SSH_PORT" ]; then
    echo "🔧 Введите SSH данные инстанса:"
    read -p "   SSH хост: " SSH_HOST
    read -p "   SSH порт: " SSH_PORT
    read -p "   ID инстанса: " INSTANCE_ID
    
    # Сохраняем для будущего использования
    echo "{
  \"instance_id\": \"$INSTANCE_ID\",
  \"ssh_host\": \"$SSH_HOST\",
  \"ssh_port\": $SSH_PORT,
  \"configured_at\": \"$(date '+%Y-%m-%d %H:%M:%S')\"
}" > /tmp/vastai_ssh_manual.json
    
    echo "💾 Данные сохранены в /tmp/vastai_ssh_manual.json"
fi

echo ""
echo "🔍 Проверяем подключение к инстансу..."
echo "   Команда: ssh -p $SSH_PORT root@$SSH_HOST 'echo ✅ Подключение успешно'"

# Пробуем подключиться
ssh -p $SSH_PORT -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@$SSH_HOST 'echo ✅ SSH подключение успешно; df -h | grep /workspace' 2>&1

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Подключение успешно!"
    echo ""
    
    # Создаем job конфигурацию
    JOB_CONFIG='{
      "mode": "text2video",
      "prompts": ["A beautiful sunset over mountains with clouds, cinematic, 4k"],
      "num_frames": 24,
      "fps": 8,
      "num_inference_steps": 25,
      "output_dir": "/workspace/outputs",
      "seed": 42
    }'
    
    echo "📝 Конфигурация генерации:"
    echo "$JOB_CONFIG" | python3 -m json.tool
    
    echo ""
    read -p "🚀 Запустить генерацию видео? (y/n): " -n 1 -r
    echo
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "⏳ Запускаем генерацию видео..."
        echo "   Это может занять 10-30 минут"
        echo ""
        
        # Экранируем JSON для передачи через SSH
        ESCAPED_JOB=$(echo "$JOB_CONFIG" | sed 's/"/\\"/g')
        
        # Команда для запуска генерации
        SSH_CMD="cd /workspace && python -m src.entrypoints.run_gen --job '$ESCAPED_JOB' --verbose"
        
        echo "🔧 Выполняемая команда:"
        echo "   $SSH_CMD"
        echo ""
        echo "📤 Вывод (последние 1000 символов):"
        echo "-----------------------------------"
        
        # Запускаем генерацию и показываем вывод в реальном времени
        ssh -p $SSH_PORT -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@$SSH_HOST "$SSH_CMD" 2>&1 | tail -1000
        
        echo ""
        echo "-----------------------------------"
        echo ""
        
        # Проверяем результаты
        echo "🔍 Проверяем результаты..."
        ssh -p $SSH_PORT -o ConnectTimeout=10 -o StrictHostKeyChecking=no root@$SSH_HOST "ls -la /workspace/outputs/ 2>/dev/null || echo 'Директория outputs не найдена'; find /workspace/outputs/ -type f -name '*.mp4' -o -name '*.gif' 2>/dev/null | head -10 || echo 'Файлы не найдены'"
        
        echo ""
        echo "💰 Не забудьте остановить инстанс после завершения:"
        echo "   curl -X PUT -H \"Authorization: Bearer \$VAST_API_KEY\" \\"
        echo "     https://console.vast.ai/api/v0/instances/$INSTANCE_ID/stop/"
        
    else
        echo "❌ Генерация отменена"
    fi
    
else
    echo ""
    echo "❌ Не удалось подключиться к инстансу"
    echo ""
    echo "🔧 Возможные причины:"
    echo "   1. Инстанс еще не готов (статус: loading)"
    echo "   2. Неправильные SSH данные"
    echo "   3. Инстанс остановлен"
    echo ""
    echo "📊 Проверьте статус инстанса:"
    echo "   https://cloud.vast.ai/instances/"
    echo ""
    echo "⏳ Если инстанс в статусе 'loading', подождите 20-40 минут"
    echo "   для загрузки Docker образа 40GB"
fi