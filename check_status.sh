#!/bin/bash
# Быстрая проверка статуса инстанса и мониторинга

echo "📊 БЫСТРАЯ ПРОВЕРКА СТАТУСА"
echo "=============================="

# Проверяем, запущен ли мониторинг
echo "🔍 МОНИТОРИНГ:"
if pgrep -f "auto_monitor_service.py" > /dev/null; then
    echo "   ✅ Запущен"
    echo "   PID: $(pgrep -f "auto_monitor_service.py")"
    echo "   Время работы: $(ps -o etime= -p $(pgrep -f "auto_monitor_service.py") 2>/dev/null || echo "неизвестно")"
else
    echo "   ❌ Не запущен"
    echo "   Запустите: ./start_monitor.sh"
fi
echo ""

# Проверяем файл статуса
echo "📁 ФАЙЛ СТАТУСА:"
if [ -f "/tmp/vastai_instance_status.json" ]; then
    echo "   ✅ Существует"
    LAST_CHECK=$(python3 -c "import json; f=open('/tmp/vastai_instance_status.json'); d=json.load(f); print(d.get('last_check', 'неизвестно'))" 2>/dev/null || echo "ошибка чтения")
    STATUS=$(python3 -c "import json; f=open('/tmp/vastai_instance_status.json'); d=json.load(f); print(d.get('status', 'неизвестно'))" 2>/dev/null || echo "ошибка чтения")
    CHECKS=$(python3 -c "import json; f=open('/tmp/vastai_instance_status.json'); d=json.load(f); print(d.get('checks_completed', 0))" 2>/dev/null || echo "0")
    echo "   Последняя проверка: $LAST_CHECK"
    echo "   Статус: $STATUS"
    echo "   Проверок выполнено: $CHECKS"
else
    echo "   ❌ Не существует"
fi
echo ""

# Проверяем, готов ли инстанс
echo "🎯 ГОТОВНОСТЬ ИНСТАНСА:"
if [ -f "/tmp/vastai_instance_ready.trigger" ]; then
    echo "   🎉 ИНСТАНС ГОТОВ К РАБОТЕ!"
    echo ""
    echo "   📋 ИНФОРМАЦИЯ:"
    cat /tmp/vastai_ready.txt 2>/dev/null || echo "   (файл с информацией не найден)"
elif [ -f "/tmp/vastai_ready.txt" ]; then
    echo "   🎉 ИНСТАНС ГОТОВ К РАБОТЕ!"
    echo ""
    cat /tmp/vastai_ready.txt
else
    echo "   ⏳ Инстанс еще не готов"
    echo "   Проверьте логи: tail -f /tmp/vastai_monitor.log"
fi
echo ""

# Проверяем текущий статус инстанса
echo "🔧 ТЕКУЩИЙ СТАТУС ИНСТАНСА:"
./vast.py show instance 32437368 2>&1 | head -10
echo ""

# Показываем последние логи
echo "📝 ПОСЛЕДНИЕ СООБЩЕНИЯ ИЗ ЛОГА:"
tail -10 /tmp/vastai_monitor.log 2>/dev/null || echo "   Лог файл не найден"
echo ""

echo "🚀 КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ:"
echo "1. Запустить мониторинг: ./start_monitor.sh"
echo "2. Остановить мониторинг: pkill -f 'auto_monitor_service.py'"
echo "3. Просмотр логов: tail -f /tmp/vastai_monitor.log"
echo "4. Детальный статус: cat /tmp/vastai_instance_status.json | python3 -m json.tool"
echo "5. Проверка инстанса: ./vast.py show instance 32437368"
echo ""

# Если инстанс готов, показываем команды для запуска
if [ -f "/tmp/vastai_ready.txt" ]; then
    echo "🎬 КОМАНДЫ ДЛЯ ЗАПУСКА ГЕНЕРАЦИИ:"
    grep -A5 "🚀 ДЛЯ ЗАПУСКА:" /tmp/vastai_ready.txt 2>/dev/null || echo "   (команды не найдены)"
    echo ""
    echo "💰 НЕ ЗАБУДЬТЕ ОСТАНОВИТЬ ИНСТАНС:"
    echo "   ./vast.py stop instance 32437368"
fi