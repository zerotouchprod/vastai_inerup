Цель
=====
Документ — практический план рефакторинга существующего приложения в OOP-стиль с применением принципов SOLID. Цель — улучшить поддерживаемость, тестируемость, возможность расширения и надёжность в production (Vast.ai контейнеры, GPU-пайплайны).

Краткий чеклист (начать с этого)
-------------------------------
- [ ] Добавить файл с архитектурным планом (этот файл).  Done.
- [ ] Разбить код на модули/классы по ответственности (см. структура ниже).
- [ ] Ввести интерфейсы (абстракции) для внешних зависимостей: RIFE, Real-ESRGAN, ffmpeg, B2/Uploader.
- [ ] Написать набор unit-тестов и интеграционных smoke-тестов (GPU-ускоренные тесты — опционально в CI).
- [ ] Мигрировать поэтапно: встраивать новые классы, оставляя совместимость внешнего CLI.
- [ ] Настроить CI: lint, typecheck (mypy), unit tests, smoke tests.

Архитектурное видение (в двух предложениях)
-------------------------------------------
Приложение становится набором небольших классов с одной ответственностью: ConfigLoader, PipelineOrchestrator, Extractor, Interpolator (RIFE adapter), Upscaler (Real-ESRGAN adapter), BatchManager, Assembler, Uploader и Monitor. Взаимодействие происходит через чёткие контрактные DTO (Data Transfer Objects) — InputJob, FrameBatch, AssemblyResult — и через явно определённые интерфейсы для внешних команд/скриптов, что позволяет подменять реализации для тестов и обходных вариантов.

1. Модули и классы (предложенная структура файлов)
-------------------------------------------------
src/
 - __init__.py
 - config/
   - loader.py             # ConfigLoader (read/validate/merge remote)
   - schema.py             # pydantic схемы конфигурации (включая validation)
 - pipeline/
   - orchestrator.py       # PipelineOrchestrator (высший уровень)
   - job.py                # Job/DTO: InputJob, JobResult, JobStatus
 - io/
   - extractor.py          # FrameExtractor (wraps ffmpeg extraction)
   - assembler.py          # FrameAssembler (concat/filelist/ffmpeg assembly)
   - uploader.py           # Uploader interface + B2Uploader implementation
 - models/
   - rife_adapter.py       # RIFEAdapter (interface + PyTorch impl + batch-runner controller)
   - realesrgan_adapter.py # RealESRGANAdapter (interface + batch-runner impl)
 - runners/
   - batch_manager.py      # BatchRunnerManager (invokes external batch_rife.py / batch upscaler)
   - pair_runner.py        # Per-pair runner fallback (inference_img.py wrapper)
 - monitor/
   - monitor.py            # Monitor for job progress, stop instance, upload watch
 - utils/
   - logging.py            # central logging config (structured JSON optionally)
   - shell.py              # helpers to run subprocesses with timeout, capture, streaming
   - validation.py         # small helpers
tests/
 - unit/
 - integration/

2. Контракты (интерфейсы) — ключевые методы
-------------------------------------------
(описано питоновскими интерфейсами / abstract base classes)

class IExtractor:
    def extract_frames(self, input_path: str, dest_dir: str, pad_to: Optional[int]) -> ExtractResult

class IInterpolator:
    def run_pairwise(self, in_dir: str, out_dir: str, factor: int) -> InterpResult
    def run_batch(self, in_dir: str, out_dir: str, factor: int, batch_cfg: dict) -> InterpResult

class IUpscaler:
    def run_batch(self, in_dir: str, out_dir: str, scale: int, batch_cfg: dict) -> UpscaleResult

class IAssembler:
    def assemble(self, frames_filelist: List[str], audio_file: Optional[str], out_path: str, fps: float) -> AssemblyResult

class IUploader:
    def upload(self, local_path: str, bucket: str, key: str) -> UploadResult

Зачем: при тестах мы можем подменять IInterpolator на mock-реализацию, чтобы не требовать GPU.

3. DTO / data shapes
---------------------
- InputJob: { job_id, source_bucket, source_key, local_input_path, video_meta }
- ExtractResult: { frames_count, input_width, input_height, pad_w, pad_h, frame_pattern, audio_path }
- InterpResult: { mids_count, output_pattern, success, logs }
- UpscaleResult: { output_frames_count, tile_info, resource_usage }
- AssemblyResult: { success, output_path, size_bytes, duration }
- UploadResult: { success, key, url, attempts }

4. SOLID-принципы — как применяются
-----------------------------------
Single Responsibility: каждый класс — ровно одна обязанность (e.g., FrameExtractor только отвечает за извлечение кадров и аудио). 

Open/Closed: внедрим интерфейсы; добавление новой реализации (например, другой апскейлер) — через реализацию интерфейса без модификации orchestrator.

Liskov Substitution: интерфейсы и DTO гарантируют, что замены реализаций не ломают код (включая поведение ошибок, бросаемых исключений — будем использовать согласованные исключения типа PipelineError).

Interface Segregation: разделение IExtractor/IAssembler/IInterpolator/IUploader — потребители зависят только от конкретного интерфейса, а не от одного большого API.

Dependency Inversion: Оркестратор зависит от абстракций (IInterpolator, IUpscaler), конкретики подключаются через фабрику (Factory/DI simple module) при старте. Это также даёт лёгкую возможность мокирования для тестов.

5. Ошибки и обработка исключений (смысловая схема)
-------------------------------------------------
- Ошибки низкого уровня (ffmpeg исключения, subprocess return codes) — оборачивать в специфичные исключения (ExtractionError, InterpolationError, AssemblyError, UploadError).
- Оркестратор должен различать: retryable vs fatal errors.
  - retryable: transient network upload failure, temporary GPU OOM -> повторить с backoff (и/или уменьшить batch size).
  - fatal: модель несовместима с кадром (size mismatch) -> сохранить диагностический пакет (filelist, ffmpeg logs, ffprobe outputs) и завершить с fail.
- Логи: structured logs + dump diagnostic bundle to `/workspace/logs/<job_id>/diagnostics.tar.gz` при ошибке.

6. Batch-runner и per-pair fallback
-----------------------------------
- BatchManager запускает external batch script (batch_rife.py) с `PYTHONUNBUFFERED=1` и следит за stdout; парсит метрики прогресса. Если batch-runner не produce ожидаемых файлов — сразу переходит к per-pair fallback.
- BatchManager интерфейс: `run(in_dir, out_dir, config) -> BatchResult` где BatchResult содержит counts, duration, sample_files и exit_code.
- При OOM or mismatch в batch-runner: BatchManager собирает diagnostics и возвращает failure с указанием причины; orchestrator решает fallback.

7. Ассемблер (filelist concat) — надёжность
------------------------------------------
- Ассемблер получает список файлов (filelist) и целевой fps. Перед concat он запускает quick sanity check: ffprobe первых N (e.g. 20) кадров на совпадение width,height и pix_fmt. Если есть расхождение — применяет нормализацию: scale/pad -> common size (prefer PAD computed earlier, else nearest multiple of 32). Это уже реализовано в текущем bash-скрипте, но лучше сделать в Python с помощью ffmpeg-python (или оборачивая subprocess). 
- Ассемблер возвращает детальные логи и ошибочный пример (первый mismatch).

8. Uploader — централизованная стратегия
----------------------------------------
- Вынести upload в `IUploader` и реализовать `CentralizedUploader` (использует container_upload.py через subprocess + boto3 fallback). 
- Поддержать fallback: centralized upload -> boto3 -> upload_b2.py -> transfer.sh (как сейчас), но учёт всех ошибок и запись результата в `upload_result.json`. 
- После успешного upload Orchestrator записывает `/workspace/upload_result.json` и возвращает URL.

9. Monitor (авто-стоп инстанса)
------------------------------
- Monitor слушает создание `/workspace/upload_result.json` и корректно инициирует shutdown (в текущем коде это ломалось). 
- Предложение: monitor подписывается на события в orchestrator через callback или читает файл `upload_result.json` и затем вызывает cloud API (через run_with_config script) для остановки.

10. Тесты
----------
Unit tests (pytest):
- config.loader: validate remote merging
- extractor: mock ffmpeg subprocess -> ensure correct pad args
- assembler: feed fake image files with known sizes -> ensure normalized filelist and call ffmpeg (mock) with expected args
- uploader: mock subprocess and boto3

Integration tests (CI, optional GPU runners):
- smoke-test: extract 2 frames, run RIFE smoke interpolation (small), confirm outputs
- full-run test (optional on GPU queue): small video, run batch-runner and assembler, check upload_result.json

11. Миграция по шагам (без прерывания сервиса)
--------------------------------------------
0) Создать `src/` и настроить setup/venv. Добавить mypy/flake8/pytest config.
1) Реализовать `config.loader` + pydantic schema; изменить точки входа на использование нового loader (keep old CLI env compatible)
2) Добавить `utils.shell` — безопасный запуск subprocess. Перенести вызовы ffmpeg/ffprobe в этот helper.
3) Реализовать `io.extractor` (без изменения pipeline logic). Запустить smoke tests.
4) Реализовать `io.assembler` и заменить текущие сборочные вызовы (тестировать локально).
5) Реализовать `models.rife_adapter` и `runners.batch_manager` (перенести логику batch-runner invocation). Параллельно — интеграционные тесты.
6) Реализовать `upload.uploader` (CentralizedUploader) и интеграцию с monitor.
7) Перенести `pipeline.py` logic в `pipeline.orchestrator` постепенно: вначале wrapper который делегирует по шагам, затем убрать старый procedural код.
8) Очистка: удалить устаревшие inline heredoc-скрипты, конвертировать их в модульные реализации.

12. Quality gates / CI
----------------------
- Pre-commit: black, isort, flake8
- CI steps: install deps -> lint -> mypy -> unit tests (fast) -> integration smoke (optional GPU) -> build artifact
- For each PR: require tests + at least one integration smoke (if changed pipeline logic).

13. Производительность и адаптация под разные машины
----------------------------------------------------
- Автотюн batch_size: реализовать `BatchProbe` в `runners.batch_manager` — небольшая локальная прогонка (synthetic forward) с timeout, чтобы подобрать batch_size, затем использовать для реального запуска. Поведение:
  - быстрый check: try batch_size candidates (8,12,16,24) with TORCHDYNAMO suppressed errors (fallback to eager) and limit compile-time.
  - при OOM — понизить batch_size и retry.
- Tile-size heuristics: рассчитывать tile/patch size на основании VRAM: e.g. vram<16GB -> tile 512, else tile 1024.
- Logging: добавить per-pair and batch progress metrics (pairs/sec, frames/sec) и ETA estimation in orchestrator.

14. Документация и README
-------------------------
- README.md с quickstart, dev-setup, тесты, как развернуть на Vast.ai (пример config.yaml)
- OPERATION.md: пояснения по troubleshooting: common errors (ffmpeg: invalid option for input, missing frames, size mismatch), где смотреть diagnostics.

15. Временной план / Milestones (оценка)
---------------------------------------
(1 dev) 2–3 дня: scaffold + config.loader + extractor + utils
(1 dev) 2–3 дня: assembler + uploader + central upload_result.json + monitor fix
(1 dev) 3–4 дня: rife_adapter + batch_manager + per-pair fallback
(1 dev) 2 дня: realesrgan_adapter + batch upscaling autosize
(1 dev) 2 дня: интеграционные тесты, CI, docs
Итого ~11–14 рабочих дней для полноценного рефакторинга и тестов.

16. Доп. замечания и рекомендации
--------------------------------
- Сохранить backward-совместимость: обеспечьте CLI wrapper, который вызывает `pipeline.orchestrator` таким образом, что существующие командные строки не ломаются.
- Для GPU-зависимого кода предусмотреть mock-режим (использовать нативные images или синтетические тензоры) для CI unit tests.
- Всегда собирать diagnostics bundle при ошибках (filelist, ffmpeg logs, ffprobe outputs, batch_rife logs) — это поможет в удалённой отладке на Vast.ai.

17. Примеры интерфейсов / подписи методов (псевдокод)
---------------------------------------------------
class FrameExtractor(IExtractor):
    def extract_frames(self, input_path: str, dest_dir: str, pad_to: Optional[int] = 32) -> ExtractResult:
        """Возвращает ExtractResult с pad_w/pad_h и first_frame_path"""

class RIFEAdapter(IInterpolator):
    def run_batch(self, in_dir: str, out_dir: str, factor: int, config: dict) -> InterpResult:
        """Запускает batch_rife.py (или встроенную реализацию) и возвращает список produced files и метрики"""

class PipelineOrchestrator:
    def run_job(self, job: InputJob) -> JobResult:
        try:
            extract_res = extractor.extract_frames(job.input_path, work_dir)
            try:
                interp_res = interpolator.run_batch(work_dir/input, work_dir/output, job.factor, job.config)
            except InterpolationError as e:
                # fallback to per-pair
                interp_res = pair_runner.run(...)
            assembly_res = assembler.assemble(...)
            upload_res = uploader.upload(assembly_res.output_path,...)
            return JobResult(success=True, upload=upload_res)
        except Exception as e:
            save_diagnostics(...)
            raise

18. Риски и mitigation
----------------------
- Риск: torch.compile/backend indcutor issues on some nodes -> mitigation: provide env toggle to disable compile (fall back to eager) and graceful degrade. 
- Риск: различия в ffmpeg версиях -> mitigation: выбрать параметры, совместимые со старой ffmpeg (избегать экспериментальных фильтров) и иметь jpeg/png fallback.

Заключение
----------
Этот план даёт детальную дорожную карту по переносу procedural-скриптов в чистую OOP-архитектуру с SOLID-принципами. Я могу начать по шагам: предлагаю первый PR — «scaffold + config loader + extractor + utils», затем итеративно переносить остальной функционал.

Следующее действие от вас
------------------------
- Скажите: «Начинаем с шага 1: scaffold и config loader» — и я сделаю конкретные правки (создам `src/` и начальную структуру, добавлю pydantic схемы и tests). Или укажите, если хотите, чтобы сначала применить дополнительные ускорения (force pad=32) прямо в bash-скриптах. Если хотите — я начну внедрять первые файлы прямо сейчас.

```yaml
# quick decision:
# decide_one_of:
#  - start_scaffold
#  - force_pad_32_now
#  - wait_and_run_job
```

