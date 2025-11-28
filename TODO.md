TODO — контекст и планы (сводка работы 2025-11-26/27)
=====================================

Краткая цель
------------
Репозиторий запускает пайплайн по апскейлу и интерполяции видео (Real-ESRGAN + RIFE) в контейнере на vast.ai. Важные сценарии: автоматический запуск внутри контейнера, GPU-ускорение, сборка кадров, создание итогового .mp4 и автозагрузка результата на Backblaze B2 (S3-совместимый API).

Что сделано сегодня (сводка)
---------------------------
- Диагностика множества запусков: обнаружены баги и flaky-места в `run_rife_pytorch.sh` и `run_realesrgan_pytorch.sh`.
- Добавлен/улучшен batch-runner для RIFE (используется `batch_rife.py` если доступен) — теперь модель загружается один раз и генерирует множественные промежуточные кадры.
- В `run_realesrgan_pytorch.sh` реализовано более описательное имя объекта при автозагрузке на B2: если `B2_KEY` не задан, ключ формируется как <ориг_имя>_<mode>_<YYYYmmdd_HHMMSS>.<ext> (mode = upscaled/interpolated/both/result). Это пофиксил в `maybe_upload_b2()`.
- Внедрён filelist (concat) сборщик и печать головы `filelist.txt` в лог при сборке (для отладки порядка кадров).
- Добавил/отладил вывод прогресса (убрал буферизацию Python при запуске бэтч-скриптов: `PYTHONUNBUFFERED=1` / `export PYTHONUNBUFFERED=1`) и предложил использование `stdbuf`/`unbuffer` для недостающих оболочек; замечены случаи, где `stdbuf` было вызвано неправильно.
- Добавлены диагностические логи: проверка размеров кадров после pad, печать образца первых 20 строк filelist, сбор метаданных ffprobe и aia.

Наблюдаемые проблемы и причины
-----------------------------
1) Ошибки синтаксиса оболочки и heredoc в `run_rife_pytorch.sh` / `run_realesrgan_pytorch.sh` при редактировании — приводят к непредсказуемым падениям. Требуется `bash -n` проверка и коррекция блоков if/fi и here-docs.
2) `batch_rife.py` / inlined heredoc версии иногда имеют indentation/syntax ошибки (Python `IndentationError`) — надо вынести в отдельный файл `batch_rife.py` (не heredoc) и `git`-контролировать.
3) RIFE иногда падает с RuntimeError: "Sizes of tensors must match... Expected size 512 but got 480" — причина: несовпадение pad-логики между ffmpeg (pad->multiple of 32) и моделью (ожидает кратность 32 или 64 в некоторых слоях). Решение: унифицировать pad (в ffmpeg и в inference_pad) к 32 (уже обсуждали). Также добавил лог "DEBUG: input shapes after pad" для отлова таких пар.
4) FFmpeg extraction падал из-за некорректного ffmpeg-фильтра (ошибка "No such filter: 'iw+(32-mod(iw,32))'") — проще вычислять pad заранее в bash и передавать фиксированное pad=<W>:<H> (мы это сделали в `run_rife_pytorch.sh`).
5) Иногда CV2 не читает файлы (imread возвращает None) — это указывает на повреждение/неполную запись файла: добавлена проверка существования и hexdump первых байтов для удалённого дебага.
6) Реал-ESRGAN batch авто-тюн и torch.compile микросвипы могут падать на некоторых образах/драйверах (libcuda.so симлинк/inductor проблемы). Для стабильности вынесены флаги `TORCH_COMPILE_DISABLE`, `FAST_COMPILE`, `AUTO_TUNE_BATCH`.
7) `realesrgan_batch_upscale.py` в рабочем дереве имеет синтаксические ошибки (pycompile падает) — нужно исправить или заменить на проверенную версию; до этого включена логика fallback на video method.
8) `monitor.py` — авто-стоп инстанса после загрузки на B2 не работает (нужно отладить механизм, который следит за result JSON / sentinel file). Это критично для экономии средств.

Приоритетные улучшения (рекомендуемый список задач)
-------------------------------------------------
(краткий и понятный для передачи другому ИИ/разработчику)

1) Исправить `realesrgan_batch_upscale.py` синтаксис/отступы и прогнать unit/pycompile.
   - Результат: batch-ускорение будет работоспособным на большинстве машин.
2) Вынести `batch_rife.py` в отдельный файл (если ещё не сделано) и обеспечить корректную печать прогресса (использовать PYTHONUNBUFFERED=1 при запуске). Убедиться, что он печатает "Batch-runner: pair X/Y done" и статистику скорости/ETA.
3) Унифицировать pad=32 повсеместно: в ffmpeg-extract и в inference padding (RIFE). Добавить sanity-check логирования для каждой пары (input shapes after pad). Если размер не совпадает — записывать offending pair в отдельный debug JSON и продолжать.
4) Filelist concat: использовать явный filelist.txt и `ffmpeg -f concat -safe 0 -i filelist.txt ...` (это уже добавлено в сборщик). Добавить печать head(filelist.txt) (первые 20 строк) для удалённого дебага.
5) Прогресс и логи:
   - Запуск batch-скриптов с `PYTHONUNBUFFERED=1` (или `python3 -u`) — уже сделано для batch_rife.
   - Убрать/сократить избыточные debug lines (например "inference_img.py found — showing head") — оставить только в нейковом DEBUG режиме.
   - Форматировать ffmpeg progress в одну строку (user asked) — можно использовать progress pipe + small formatter (есть `progress_collapse` реализованный) — применить к всём ffmpeg вызовам.
6) Автоматический подбор `--batch-size`: уже добавлена VRAM->batch mapping plus quick probe. Улучшить heurистику probe для широкого диапазона GPU (12GB..48GB) и сделать fallback быстрым (не больше 1–2 micro-sweeps).
7) Monitor / auto-stop: починить `monitor_instance.py` (или `monitor.py`) чтобы при загрузке файла на B2 он корректно завершал/останавливал инстанс. Точки контроля:
   - Создание `/workspace/VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY` sentinel
   - Сохранение upload result JSON (`realesrgan_upload_result.json`) — monitor должен чекать этот JSON or B2_HEAD и только после успешного upload вызывать shutdown.
8) Поддержка разных контейнерных файлов-форматов (`.mkv`, `.mp4`): расширить входной парсинг и убедиться что ffmpeg-extract поддерживает все кодеки; исправить smoke-test, который ожидает `/workspace/smoke/frame_01.png` (возможно mismatch с именованием).

Низко-рисковые улучшения (быстрые выигрыши)
-------------------------------------------
- Логическое имя для автозагрузки (выполнил в `run_realesrgan_pytorch.sh`).
- Добавить head of filelist (внедрено) и печать первых 20 строк.
- При ошибках RIFE (tensor size mismatch) — логировать пары и размеры в отдельный `rife_pad_errors.json` и пропускать пару или fallback к ffmpeg.
- Добавить `--upload-mode` CLI/ENV (upscaled/interpolated/both) чтобы явно управлять режимом в автоматике.

Структура проекта (коротко, для передачи новой модели)
----------------------------------------------------
(файлы и их роль)

- pipeline.py — главный Python-пайплайн (запускает RIFE/Real-ESRGAN, управляет TMP и upload). Точка интеграции с vast.ai.
- run_with_config_batch_sync.py — главный entry-point для запуска на vast.ai (ваша основная точка запуска)
- monitor_instance.py (или monitor.py) — контролирует завершение и auto-stop инстанса после загрузки результатов (нужен фикс)
- run_realesrgan_pytorch.sh — оболочка для запуска Real-ESRGAN (включает batch upscaler, pad/extract, reassembly, upload)
- run_rife_pytorch.sh — оболочка для запуска RIFE (интерполяция + batch-runner integration + assembly + upload)
- batch_rife.py — (batch runner) скрипт для парного inference RIFE (один запуск — много пар) — должен загружать модель один раз
- realesrgan_batch_upscale.py — batch upscaler (на основании Real-ESRGAN). Требует синтаксической проверки и фиксов.
- upload_b2.py — утилита на boto3 для загрузки в Backblaze B2 (S3-совместимый), генерирует presign URL
- scripts/ — дополнительные утилиты: run_slim_vast.py, container_config_runner.py, utils.py и т.д.
- external/Real-ESRGAN, external/RIFE — внешние репозитории (модели и inference scripts); модельные файлы обычно в /opt/* или в REPO_DIR/train_log

Важные env vars и файлы
-----------------------
- B2_KEY / B2_SECRET / B2_ENDPOINT / B2_BUCKET — для автоматической загрузки
- AUTO_UPLOAD_B2=1/0 — включить/отключить автоматическую загрузку
- UPLOAD_RESULT_JSON (по умолчанию /workspace/realesrgan_upload_result.json)
- VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY — sentinel файл, используемый внешними мониторами

How to run (typical)
--------------------
- Локально/контейнер: python3 /workspace/project/pipeline.py --input /workspace/input.mp4 --output /workspace/output --mode upscalе/interp/both
- Или через entrypoint: run_with_config_batch_sync.py (конфиг в config.yaml)

Рекомендации для следующего шага (порядок работ)
-----------------------------------------------
1) Исправить `realesrgan_batch_upscale.py` (pycompile) — high priority.
2) Перенести/починить `batch_rife.py` (если ещё в heredoc) и добавить unit smoke tests: два кадра -> 1 mid-frame, и 16 кадров -> N mids.
3) Протестировать полный pipeline на разных образцах: small (8s), medium (30s), large (several min). Проверить: pad一致ность, batch-runner outputs assemble correctly, filelist order correct, upload naming.
4) Починить monitor auto-stop: trigger shutdown only after successful presigned URL appears in upload result JSON and sentinel exists.
5) Документировать конфиг: env vars, expected model locations (/opt/rife_models, /opt/realesrgan_models).

Appendix: полезные проверки (команды)
------------------------------------
- Быстрая синтакс-проверка bash: bash -n run_realesrgan_pytorch.sh
- Python pycompile: python3 -m py_compile realesrgan_batch_upscale.py
- Запустить smoke-test вручную: python3 /workspace/project/pipeline.py --input smoke_input.mp4 --output /workspace/output --mode both --target-fps 70

Если хочешь, я могу:
- Исправить `realesrgan_batch_upscale.py` (починить отступы и упавшие блоки try/except). Это займёт немного времени, но решит большинство падений.
- Вынести/переписать `batch_rife.py` как отдельный проверенный модуль и добавить автоматическое логирование прогресса + ETA.
- Починить `monitor_instance.py` авто-остановку и добавить unit-симуляцию (создание upload_result JSON и проверка поведения).

---

Формат: если хочешь, я сразу применю исправления (например, поправлю `realesrgan_batch_upscale.py` и `batch_rife.py`) — скажи "почини realesrgan_batch_upscale.py" или "вынеси batch_rife.py", и я начну.

