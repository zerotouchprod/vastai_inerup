#!/bin/bash
# Скрипт для мониторинга и запуска генерации видео на Vast AI

INSTANCE_ID=32437368
MAX_CHECKS=36  # 3 часа (36 * 5 минут)
CHECK_INTERVAL=300  # 5 минут

echo "🚀 МОНИТОРИНГ И ЗАПУСК ГЕНЕРАЦИИ ВИДЕО"
echo "=========================================="
echo "Инстанс ID: $INSTANCE_ID"
echo "GPU: RTX 3090 (24GB VRAM)"
echo "Диск: 100GB"
echo "Цена: \$0.1622/час"
echo "Интернет: очень быстрый (↓1652Mbps / ↑583Mbps)"
echo ""
echo "⏳ Docker образ 40GB загружается..."
echo "Ожидаемое время: 15-30 минут"
echo ""

for ((check=1; check<=MAX_CHECKS; check++)); do
    echo "📊 Проверка $check/$MAX_CHECKS"
    echo "   Время: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "   Осталось проверок: $((MAX_CHECKS - check))"
    echo "----------------------------------------"
    
    # Проверяем статус
    STATUS_OUTPUT=$(./vast.py show instance $INSTANCE_ID 2>&1)
    
    if echo "$STATUS_OUTPUT" | grep -q "running"; then
        echo "🎉 ИНСТАНС ГОТОВ К РАБОТЕ!"
        echo ""
        
        # Получаем SSH данные
        SSH_HOST=$(echo "$STATUS_OUTPUT" | awk '{print $10}')
        SSH_PORT=$(echo "$STATUS_OUTPUT" | awk '{print $11}')
        
        echo "📊 ДАННЫЕ ДЛЯ ПОДКЛЮЧЕНИЯ:"
        echo "   SSH хост: $SSH_HOST"
        echo "   SSH порт: $SSH_PORT"
        echo ""
        
        echo "🚀 ЗАПУСКАЕМ ГЕНЕРАЦИЮ ВИДЕО..."
        echo ""
        
        # Создаем конфигурацию генерации
        JOB_CONFIG='{
            "mode": "text2video",
            "prompts": [
                "A beautiful sunset over mountains with clouds, cinematic, 4k, masterpiece",
                "A futuristic city at night with flying cars and neon lights, cyberpunk style"
            ],
            "num_frames": 24,
            "fps": 8,
            "num_inference_steps": 25,
            "output_dir": "/workspace/outputs",
            "seed": 42,
            "height": 512,
            "width": 512
        }'
        
        echo "📝 КОНФИГУРАЦИЯ ГЕНЕРАЦИИ:"
        echo "$JOB_CONFIG" | python3 -m json.tool
        echo ""
        
        # Подготавливаем команду
        JOB_JSON=$(echo "$JOB_CONFIG" | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin)).replace('\"', '\\\\\"'))")
        COMMAND="cd /workspace && python -m src.entrypoints.run_gen --job '$JOB_JSON' --verbose"
        
        echo "🔧 КОМАНДА ДЛЯ ЗАПУСКА:"
        echo "$COMMAND"
        echo ""
        
        echo "🎯 ДЛЯ ЗАПУСКА ВЫПОЛНИТЕ:"
        echo "ssh -p $SSH_PORT root@$SSH_HOST"
        echo "cd /workspace"
        echo "python -m src.entrypoints.run_gen \\"
        echo "  --job '{\"mode\": \"text2video\", \"prompts\": [\"A beautiful sunset\"]}'"
        echo ""
        
        echo "💰 НЕ ЗАБУДЬТЕ ОСТАНОВИТЬ ИНСТАНС:"
        echo "./vast.py stop instance $INSTANCE_ID"
        echo "Или: ./vast.py destroy instance $INSTANCE_ID"
        echo ""
        
        echo "📊 СТАТИСТИКА:"
        echo "   - Время ожидания: $(((check-1)*5)) минут"
        WAIT_COST=$(python3 -c "print('%.3f' % (($check-1)*5/60*0.1622))")
        TOTAL_COST=$(python3 -c "print('%.3f' % (($check-1)*5/60*0.1622 + 0.08))")
        echo "   - Стоимость ожидания: \$$WAIT_COST"
        echo "   - Общая стоимость: ~\$$TOTAL_COST"
        
        exit 0
        
    elif echo "$STATUS_OUTPUT" | grep -q "loading"; then
        echo "   ⏳ Загрузка Docker образа..."
        echo "   Прогресс: $check/$MAX_CHECKS проверок"
        
        # Оцениваем оставшееся время
        if [ $check -gt 1 ]; then
            REMAINING_MINUTES=$(((MAX_CHECKS - check) * 5))
            echo "   Осталось ждать: ~${REMAINING_MINUTES} минут"
            
            # Примерное время готовности
            READY_TIME=$(date -d "+${REMAINING_MINUTES} minutes" '+%H:%M')
            echo "   Примерное время готовности: $READY_TIME"
        fi
        
    elif echo "$STATUS_OUTPUT" | grep -q "failed"; then
        echo "   ❌ Инстанс не удалось запустить"
        echo "   Проверьте логи: ./vast.py show instance $INSTANCE_ID --raw"
        exit 1
        
    else
        echo "   Статус: неизвестен"
    fi
    
    # Ждем перед следующей проверкой
    if [ $check -lt $MAX_CHECKS ]; then
        echo ""
        echo "⏳ Следующая проверка через 5 минут..."
        sleep $CHECK_INTERVAL
    fi
done

echo ""
echo "❌ ПРЕВЫШЕНО ВРЕМЯ ОЖИДАНИЯ (3 часа)"
echo "=========================================="
echo ""
echo "🔧 Возможные проблемы:"
echo "   1. Docker образ не загрузился"
echo "   2. Проблемы с сетью"
echo "   3. Недостаточно средств на балансе"
echo ""
echo "📊 Проверьте вручную:"
echo "./vast.py show instance $INSTANCE_ID"
echo ""
echo "🔄 Попробуйте пересоздать инстанс:"
echo "./vast.py destroy instance $INSTANCE_ID"
echo "./vast.py create instance 31594358 --image registry.gitlab.com/gfever/vastai_interup:video-gen --disk 100 --ssh"

exit 1