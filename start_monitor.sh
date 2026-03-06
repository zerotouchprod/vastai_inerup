#!/bin/bash
# Запуск автоматического мониторинга инстанса Vast AI

echo "🚀 ЗАПУСК АВТОМАТИЧЕСКОГО МОНИТОРИНГА"
echo "=========================================="

# Проверяем, не запущен ли уже мониторинг
if pgrep -f "auto_monitor_service.py" > /dev/null; then
    echo "⚠️  Мониторинг уже запущен!"
    echo "   PID: $(pgrep -f "auto_monitor_service.py")"
    echo ""
    echo "📊 ПРОВЕРЬТЕ СТАТУС:"
    echo "   tail -f /tmp/vastai_monitor.log"
    echo "   cat /tmp/vastai_instance_status.json"
    echo ""
    exit 1
fi

# Запускаем мониторинг в фоне
echo "📦 ЗАПУСКАЕМ МОНИТОРИНГ..."
nohup python3 auto_monitor_service.py > /tmp/vastai_monitor_service.log 2>&1 &
MONITOR_PID=$!

echo "✅ Мониторинг запущен!"
echo "   PID: $MONITOR_PID"
echo "   Лог: /tmp/vastai_monitor_service.log"
echo "   Статус: /tmp/vastai_instance_status.json"
echo "   Готовность: /tmp/vastai_instance_ready.trigger"
echo ""

echo "📊 КОМАНДЫ ДЛЯ ПРОВЕРКИ:"
echo "1. Просмотр логов мониторинга:"
echo "   tail -f /tmp/vastai_monitor.log"
echo ""
echo "2. Проверка текущего статуса:"
echo "   cat /tmp/vastai_instance_status.json | python3 -m json.tool"
echo ""
echo "3. Проверка, готов ли инстанс:"
echo "   if [ -f /tmp/vastai_instance_ready.trigger ]; then echo '🎉 ИНСТАНС ГОТОВ!'; cat /tmp/vastai_ready.txt; fi"
echo ""
echo "4. Остановка мониторинга:"
echo "   pkill -f 'auto_monitor_service.py'"
echo ""
echo "5. Проверка процесса мониторинга:"
echo "   ps aux | grep auto_monitor_service"
echo ""

echo "⏳ МОНИТОРИНГ БУДЕТ ПРОВЕРЯТЬ СТАТУС КАЖДЫЕ 5 МИНУТ"
echo "   Максимальное время ожидания: 4 часа"
echo "   Когда инстанс будет готов, создастся файл /tmp/vastai_ready.txt"
echo ""

echo "🔔 КОГДА ИНСТАНС БУДЕТ ГОТОВ:"
echo "1. Проверьте: cat /tmp/vastai_ready.txt"
echo "2. Подключитесь по SSH"
echo "3. Запустите генерацию видео"
echo "4. Остановите инстанс"
echo ""

# Показываем текущий статус
echo "📈 ТЕКУЩИЙ СТАТУС ИНСТАНСА:"
./vast.py show instance 32437368 2>&1 | head -5

echo ""
echo "💡 СОВЕТ: Вы можете оставить этот терминал открытым и периодически проверять статус"
echo "   или вернуться позже и проверить файлы в /tmp/"