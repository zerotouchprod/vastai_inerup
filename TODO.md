TODO: Краткий контекст и план для нового AI
=========================================

1) Короткая цель этого файла
---------------------------
Этот файл — краткий дневник и TODO по изменениям, которые были сделаны сегодня в репозитории, и организованный список следующих шагов / улучшений. Его можно дать новому AI или разработчику для быстрой экранной подготовки к работе над pipeline.

2) План (что я сделаю в этом файле)
----------------------------------
- Описать контекст сегодняшней работы.
- Перечислить ключевые файлы и их роль.
- Зафиксировать найденные проблемы и баги/их решения.
- Сформулировать приоритетный список улучшений (технический TODO).
- Привести команды для локального/контейнерного запуска и отладки.

3) Контекст — что сделано сегодня (кратко)
-----------------------------------------
- Исправлен и стабилизирован `run_rife_pytorch.sh` — много мелких исправлений по пайпам, here-docs и корректным использованию `ffmpeg`.
- Добавлен numeric pad (вычисление pad_w/pad_h через `ffprobe`) вместо ffmpeg-фильтра с выражениями (устраняет ошибку парсинга фильтра).
- Добавлен детальный вывод/диагностика после извлечения кадров (список файлов, hexdump первого кадра), логирование ffmpeg выдачи.
- Добавлен поддерживаемый batch-runner: скрипт ищет `/workspace/project/batch_rife.py` и запускает его, чтобы загрузить модель единожды и генерировать средние кадры (mids) в `$TMP_DIR/output`.
- Добавлен per-pair fallback: если batch не сработал, запускается `inference_img.py` по парам кадров (с таймаутом и логированием).
- Добавлен filelist-конкат в сборку финального mp4 и fallback на ffmpeg minterpolate если RIFE не дал выходов.
- Добавлены диагностические команды (nvidia-smi, torch.cuda info) и логирование batch_rife вывода.

4) Ключевые логи / как воспроизвести проблему/проверку
-----------------------------------------------------
- Типичный запуск pipeline вызывает команду вида:

```bash
python3 /workspace/project/pipeline.py --input /workspace/input.mp4 --output /workspace/output --mode interp --prefer auto --target-fps 70
```

- Или вручную можно запустить wrapper:

```bash
bash -x /apps/PycharmProjects/vastai_interup_ztp/run_rife_pytorch.sh /workspace/input.mp4 /workspace/output/output_interpolated.mp4 3 2>&1 | tee /workspace/run_rife_full.log
```

- После прогона открыть TMP_DIR (скрипт печатает TMP_DIR, например /tmp/tmp.XYZ):

```bash
# заменить TMP на то, что напечатал скрипт
TMP=/tmp/tmp.XYZ
ls -la "$TMP/input"
ls -la "$TMP/output"
sed -n '1,200p' "$TMP/batch_rife_run.log"
sed -n '1,200p' "$TMP/ff_extract.log"
```

5) Важные замечания и ошибки, найденные сегодня
-----------------------------------------------
- FFmpeg filter parsing: выражения вида pad=if(mod(iw\,32),iw+(32-mod(iw\,32)),iw) приводили к ошибке "No such filter" на некоторой сборке ffmpeg. Решение: вычислять pad значения в shell (через ffprobe) и передавать как pad=NUM:NUM.
- Tensor size mismatch в RIFE: модель ожидает размеры, кратные определённому шагу (в RIFE v3.x встречалось требование кратности 64 в train_log). Для надежности в batch_rife.py мы pad'им входы к ближайшему кратному 64; в wrapper обходим pad вопросы при извлечении (кратность 32) — это согласие между ffmpeg и моделью.
- Проблема: когда batch-runner не генерировал mids (ошибка/отсутствие скрипта), раньше wrapper мгновенно переключался на ffmpeg minterpolate. Теперь wrapper сначала попытается запустить batch_rife, затем per-pair inference, и только после этого — ffmpeg fallback.

6) Структура репозитория (ключевые файлы и папки)
--------------------------------------------------
Корневая структура (важные элементы):
- `run_rife_pytorch.sh` — главный wrapper для шага интерполяции. Отвечает за извлечение кадров, запуск batch‑runner/per‑pair inference, и сборку финального видео.
- `pipeline.py` — основной pipeline, который управляет шагами (interpolate, upscale, upload и т.д.). Вызывает `run_rife_pytorch.sh` для RIFE-интерполяции.
- `batch_rife.py` — lightweight batch runner (в корне repo) — загружает модель RIFE, обрабатывает пары кадров, пишет промежуточные mids в каталог `output`. CLI: `python3 batch_rife.py <in_dir> <out_dir> <factor>`.
- `external/RIFE/` — исходники RIFE (модель, inference_img.py, train_log/, etc.). Важные файлы здесь:
  - `inference_img.py` — per-pair inference utility (из upstream RIFE).
  - `train_log/` — подпапка с моделями (например `flownet.pkl`, `RIFE_HDv3.py`, `IFNet_HDv3.py`).
- `external/Real-ESRGAN` — реализация Real-ESRGAN (для upscale).
- `requirements.txt` — pip зависимости для контейнера/venv.
- вспомогательные: `pipeline.py`, `run_realesrgan_pytorch.sh`, `run_rife_pytorch.sh`, `scripts/*`.

6.1) Project entrypoint and monitor (important)
----------------------------------------------
- Important: the canonical single entrypoint used in production runs is `run_with_config_batch_sync.py` (this is the top-level runner invoked by the orchestration, not `pipeline.py` directly).
- `monitor.py` (also referenced as `monitor_instance.py` in some scripts) is the instance watchdog: it should detect successful upload to Backblaze B2 (or S3-compatible endpoint) and automatically stop the VM/container once the final file is uploaded to avoid extra charges.
- Current status: the automatic stop logic in `monitor.py` is not functioning reliably — the monitor does not consistently detect the completed B2 upload event and therefore does not trigger the instance shutdown. This needs to be fixed and tested.

10.1) Add monitor fix to TODO (high priority)
---------------------------------------------
- [ ] M1 — Fix automatic stop in `monitor.py`:
  - Ensure monitor reliably detects successful upload completion to B2 (check upload manifest, returned ETag / file size, or use the same put result acknowledgement that uploader uses).
  - If uploader uses a two-step (upload temp -> move/rename) flow, monitor must detect the final filename (or listen to uploader success hook).
  - On detection, monitor should perform a safe shutdown API call (or call host agent) and log the event; it must also handle transient listing/latency issues (re-verify N times over a short window before stopping).
  - Add diagnostics: log B2 keys, upload events, exact check used (size/sha1/etag), and a final "STOPPING INSTANCE" message with timestamp and reason.

10.2) Tests for monitor fix
---------------------------
- Add small smoke test that simulates uploader completing a file (e.g., write a marker file or call the same B2 API) and asserts that monitor triggers shutdown logic (for test: replace shutdown with writing a sentinel file or calling a dry-run endpoint).
- Add steps to run monitor locally in "dry-run" mode to validate detection logic:
  - `python3 monitor.py --dry-run --watch-dir /tmp/test_uploads --check-interval 5 --confirm 3`
  - Then simulate uploader by copying the final file to `/tmp/test_uploads` and verify monitor prints final detection and sentinel creation.

7) Интерфейс `batch_rife.py` (что он принимает/возвращает)
---------------------------------------------------------
- Позиционные аргументы: `in_dir` `out_dir` `factor`
- Environment: использует `REPO_DIR` (по умолчанию `/workspace/project/external/RIFE`) для поиска `train_log` с моделью.
- Ведёт лог в stdout: прогресс для каждой пары `Batch-runner: pair i/N done (M mids)` и diagnostic lines `DEBUG: input shapes after pad t0=(...)`.
- Output: файлы в `out_dir` с шаблоном `frame_%06d_mid[_XX].png`.

8) Быстрая инструкция «как локально/контейнерно прогнать»
-----------------------------------------------------
- Запуск проекта (в контейнере на vast.ai контейнере с CUDA):

```bash
# пример вызова pipeline (как на vast.ai)
python3 /workspace/project/pipeline.py --input /workspace/input.mp4 --output /workspace/output --mode interp --prefer auto --target-fps 70
```

- Запуск только RIFE wrapper (быстрый debug):

```bash
bash -x /apps/PycharmProjects/vastai_interup_ztp/run_rife_pytorch.sh /workspace/input.mp4 /workspace/output/output_interpolated.mp4 3 2>&1 | tee /workspace/run_rife_full.log
```

- Локальное тестирование batch_rife (на извлечённых кадрах):

```bash
# подготовьте каталоги
mkdir -p /workspace/tmp_test/input /workspace/tmp_test/output
# положите туда несколько frame_*.png
python3 /apps/PycharmProjects/vastai_interup_ztp/batch_rife.py /workspace/tmp_test/input /workspace/tmp_test/output 3
ls -la /workspace/tmp_test/output
```

9) Предложенные улучшения (приоритеты)
-------------------------------------
High (сделать в ближайшие спринты):
- A1: Добавить в `batch_rife.py` печать использования CUDA, текущую память GPU и версию torch (в логе). Сейчас wrapper печатает nvidia-smi и torch info, но полезно видеть это с контекста model loader.
- A2: Добавить в `batch_rife.py` скорость обработки и ETA: каждые N пар печатать `rate`, `pairs_done/total` и ETA. Это даст полезный live‑progress.
- A3: Сделать `BATCH_TIMEOUT` конфигурируемым (через env var) вместо жёстких 600s в wrapper.

Medium (полезно, но риск/время):
- B1: Перевести вызов batch_runner в синхронный режим (stdout/err напрямую в pipeline), чтобы не использовать фон и wait-kill loop — упрощает отладку, но чуть меняет логирование.
- B2: Улучшить согласование паддинга между ffmpeg и моделью: возможно поддержать переменную `INFERENCE_PAD` (32 vs 64) и документировать требование к модели.
- B3: Добавить unit tests / smoke tests для разных входов (2 кадра, N кадров, видео с отсутствующим аудио) и интеграционный тест для whole pipeline.

Low (опционально):
- C1: Сделать filelist сборку по нескольким шаблонам и опцию `--filelist` в wrapper.
- C2: Переписать progress_collapse на небольшую C/Python утилиту в repo, более оптимальную.

10) Детализованный TODO (конкретные задачи)
------------------------------------------
- [ ] A1 — Add CUDA / torch diagnostics to `batch_rife.py` logs (print `torch.cuda.is_available()`, `torch.cuda.device_count()`, `torch.cuda.get_device_name(0)`, memory_reserved/allocated).
- [ ] A2 — Add ETA & rate to `batch_rife.py` (measure wall time per N pairs, compute ETA).
- [ ] A3 — Replace hardcoded WAIT_SECS=600 in `run_rife_pytorch.sh` with `BATCH_TIMEOUT=${BATCH_TIMEOUT:-600}` and document.
- [ ] B1 — Consider switching batch run to foreground (no & wait loop) for easier logs (configurable via env var RUN_BATCH_SYNC=1).
- [ ] B2 — Add config option `INFERENCE_PAD=64` or `INFERENCE_PAD=32` and align tests to avoid tensor size mismatches.
- [ ] B3 — Add smoke tests (GitHub Actions / local script) that run with 2‑3 frames and assert output exists.
- [ ] C1 — Add option `--filelist` to enable/disable filelist assembly.
- [ ] M1 — Fix automatic stop in `monitor.py`:
  - Ensure monitor reliably detects successful upload completion to B2 (check upload manifest, returned ETag / file size, or use the same put result acknowledgement that uploader uses).
  - If uploader uses a two-step (upload temp -> move/rename) flow, monitor must detect the final filename (or listen to uploader success hook).
  - On detection, monitor should perform a safe shutdown API call (or call host agent) and log the event; it must also handle transient listing/latency issues (re-verify N times over a short window before stopping).
  - Add diagnostics: log B2 keys, upload events, exact check used (size/sha1/etag), and a final "STOPPING INSTANCE" message with timestamp and reason.

11) Длинное объяснение потоков (RIFE flow)
-----------------------------------------
- Pipeline вызывает `run_rife_pytorch.sh` для шага интерполяции.
- Wrapper извлекает кадры в TMP_DIR/input (падирует до числа кратного 32 для корректной загрузки ffmpeg и базовой работы). Затем:
  - пытается запустить `batch_rife.py` (если доступен) — это основной GPU путь: модель загружается на CUDA, парами обрабатываются кадры и записываются mids в TMP_DIR/output.
  - если batch_rife отсутствует или не сгенерировал выходы, wrapper запускает per-pair `inference_img.py` (в репозитории RIFE) для каждой пары.
  - если и per-pair не дал результатов, wrapper собирает видео с помощью ffmpeg minterpolate (CPU) как последний шанс.
- После получения mids, wrapper собирает финальный файл либо через filelist concat (предпочтительно), либо по шаблону frame_%06d_mid.png и добавляет аудио, если оно есть.

12) Полезные замечания для нового AI / разработчика
-------------------------------------------------
- Логи — ваш друг: внимательно смотрите `$TMP_DIR/ff_extract.log` и `$TMP_DIR/batch_rife_run.log`.
- Частая причина падения RIFE — несовпадающие spatial dims. Если видите RuntimeError "Expected size 512 but got size 480" — подправьте padding (в batch_rife.py уже есть попытка pad/crop, но может понадобиться изменить кратность).
- Проверьте версии PyTorch/CUDA и соответствие версий с пакетами (в логах: torch 2.x + cu121 — OK).
- Для быстрого smoke‑теста достаточно 2 кадров; pipeline имеет disabled `inference_video.py` dependency (scikit-video) — поэтому мы используем pairwise inference.

13) Что я ожидаю от вас/от следующего AI
--------------------------------------
- Принять этот TODO, выполнить A1 и A2 в `batch_rife.py` (малые изменения). Я могу внести PR/патч сам при вашей команде "внедри A1/A2".
- По завершении добавить smoke‑тест в репо и настроить CI, чтобы автоматически проверять, что RIFE path работает на GPU.

14) Контакты/источники
---------------------
- upstream RIFE repo (в `external/RIFE`) — прочитать `README.md` и `inference_img.py` для деталей API.
- текущие изменения находятся в `run_rife_pytorch.sh` и `batch_rife.py`.

---

Если хотите, я могу сейчас: (а) автоматически внести A1 (печать use_cuda & memory) и A2 (ETA/rate) в `batch_rife.py`, (б) сделать WAIT_SECS конфигурируемым — скажите «внедри A1/A2», и я применю правки и запущу быструю проверку синтаксиса/логов.
