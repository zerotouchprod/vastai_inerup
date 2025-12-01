План рефакторинга проекта в стиль OOP с соблюдением SOLID

Краткое введение
----------------
Цель — преобразовать текущий скриптовый/монолитный код в понятную, тестируемую, расширяемую и поддерживаемую архитектуру на основе объектно-ориентированных принципов и SOLID. Результат: меньше "лапши" (spaghetti code), четкие контракты между компонентами, возможность подменять реализации (например, разные обёртки для Real-ESRGAN или RIFE), устойчивость к ошибкам и простота отладки в окружении контейнеров.

План — кратко
--------------
1. Разбить приложение на независимые компоненты с явными интерфейсами (Downloader, Extractor, Processor, Assembler, Uploader, Orchestrator, Config).
2. Внедрить dependency injection (через конструкторы) и фабрики для простоты тестирования и подмен.
3. Соблюдать SOLID: каждый класс — единственная ответственность; зависимости — через абстракции; поведение расширяется, не изменяется; интерфейсы компактные; разделение реализаций.
4. Поэтапно выполнить миграцию: выделять и покрывать тестами по одному модулю, потом переключать вызывающий код на новую компоненту.
5. Внедрить обработку отказов, ретраи, запись маркеров ожидания (pending marker) и централизованное логирование/мониторинг.

Чеклист действий (играет роль плана работ)
-----------------------------------------
- [ ] Определить контракт (интерфейсы/protocols) для основных компонентов.
- [ ] Создать структуру каталогов и skeleton файлов.
- [ ] Перенести функциональность по одному компоненту, покрывая unit-тестами.
- [ ] Обеспечить совместимость с текущими запускающими скриптами (плавный переход).
- [ ] Ввести CI lint/tests и простую smoke-run для контейнера.

Предлагаемая модульная структура проекта
-----------------------------------------
(в корне проекта создаём пакет `src/` или используем существующий `src/`)

- src/
  - config/
    - loader.py         # загрузка и валидация config.yaml / ENV
    - schema.py         # pydantic/voluptuous-валидация
  - io/
    - downloader.py     # скачивание исходников (http/s3/b2)
    - uploader.py       # интерфейс и реализация загрузки (boto3, transfer)
  - frames/
    - extractor.py      # извлечение кадров ffmpeg
    - assembler.py      # сборка видео из кадров (ffmpeg), fallback логика
  - processors/
    - rife.py           # интерфейс и вызов RIFE (PyTorch wrapper / ncnn / fallback)
    - realesrgan.py     # интерфейс и вызов Real-ESRGAN (PyTorch wrapper / ncnn / fallback)
  - orchestrator/
    - pipeline.py       # высокоуровневый Orchestrator (управляет рабочим процессом)
    - runner.py         # CLI entrypoint, мониторинг, сигнализация
  - utils/
    - logging.py        # централизованный логгер (стрим в stdout + файл)
    - fs.py             # утилиты для tmp dir, atomic move
    - retries.py        # retry decorator/strategy
    - metrics.py        # простая счётная статистика и ETA
- tests/
  - unit/
  - integration/
- scripts/
  - run_pipeline.py     # thin wrapper запуска в контейнере
- README.md
- requirements.txt

Короткое описание каждой подсистемы и их контрактов
---------------------------------------------------
1) Config Loader (`config/loader.py`)
   - Что делает: читает `config.yaml` и ENV, валидирует, возвращает immutable объект конфигурации.
   - Контракт: Config = dataclass/ pydantic model с полями: input_url, b2_bucket, b2_endpoint, mode, scale, interp_factor, prefer, batch_args, tmp_dir и пр.
   - Почему: централизованная настройка упрощает тесты и переключение окружений.

2) Downloader (`io/downloader.py`)
   - Что делает: скачивает input_url в локальный путь (с поддержкой ресьюмов/таймаутов), возвращает путь файла.
   - Интерфейс (пример):
     - download(url) -> LocalFile(path, metadata)
     - supports(url) -> bool
   - Переиспользуемость: можно подменить реализацию для S3, B2, http.

3) Extractor (`frames/extractor.py`)
   - Что делает: извлекает кадры ffmpeg или получает duration/fps; поддерживает трим/смоук-тест.
   - Контракт:
     - extract_frames(video_path, out_dir) -> list[FrameMeta]
     - get_fps(video_path) -> float
   - Отдельная ответственность: один модуль — один интерфейс.

4) Processors (realtime model wrappers)
   Общая идея: каждый heavy-процесс — реализация интерфейса `Processor`.

   Processor интерфейс (абстрактный):
   - class Processor:
       def process(self, inputs: list[str], out_dir: str, options: ProcessorOptions) -> ProcessorResult
   - ProcessorResult содержит: success, output_files, metrics, logs

   - `processors/rife.py`:
       - Реализации: `RifePytorchWrapper`, `RifeNcnnWrapper`, `RifeFallback`.
       - Логика: orchestration (batch runner) инкапсулирована внутри Processor.
   - `processors/realesrgan.py` аналогично.

5) Assembler (`frames/assembler.py`)
   - Что делает: собирает кадры в видео. Выбирает encoder (h264_nvenc vs libx264) автоматически.
   - Контракт:
     - assemble_from_pattern(pattern: str, outpath: str, fps: int) -> AssemblyResult
   - Поведение: если первая попытка с nvenc не работает — fallback на libx264 с понятной диагностикой.

6) Uploader (`io/uploader.py`)
   - Интерфейс `Uploader` с методами:
     - upload(file_path: str, bucket: str, key: str) -> UploadResult
     - resume_pending() -> list[UploadResult]
   - Реализация `B2S3Uploader(boto3)`:
     - использует TransferConfig, multipart, retries, persist pending marker.
   - Важная особенность: uploader не должен решать, когда вызываться — Orchestrator вызывает его после успеха.

7) Orchestrator (`orchestrator/pipeline.py`)
   - Высокоуровневый контроллер порядка выполнения:
     1. Получить конфигурацию
     2. Скачивание входа
     3. (опционально) smoke-test
     4. Экстракция кадров
     5. Вызов Processors (RIFE / Real-ESRGAN) по выбранной стратегии
     6. Ассемблирование
     7. Вызов Uploader; управление retries и pending marker
     8. Emit final marker и return status

   - Orchestrator работает с абстракциями (Downloader, Processor, Assembler, Uploader), а не с shell-скриптами напрямую.

8) Runner / Entrypoint (`orchestrator/runner.py` / `scripts/run_pipeline.py`)
   - Небольшой «тонкий» слой для контейнерной обёртки: преобразует ENV -> Config, вызывает Orchestrator.run(config) и затем печатает мониторы/прогресс.

9) Utils (логирование, retry, FS)
   - retry decorator с jitter/backoff; fs.atomic_move(src, dst) и helpers для tmp dir.
   - logging: один логгер (JSON линен/человекочитаем) с метками этапов и префиксами для автоматического парсинга.

Взаимодействие подсистем (Sequence)
----------------------------------
1. `runner` получает ENV/args и вызывает `ConfigLoader`.
2. `Orchestrator` создаётся с реализациями: downloader, processors_factory, assembler, uploader, logger.
3. `Orchestrator.run()` выполняет шаги в порядке и получает результаты с метриками и логами.
4. Если на любом шаге — фатальная ошибка, Orchestrator вызывает `uploader.resume_pending()` (если конфиг разрешает) или пишет маркер и выходим с кодом != 0.
5. На успешном окончании Orchestrator вызывает `uploader.upload(final_output)` и после успешной загрузки печатает финальный маркер.

Принципы SOLID — как применить на практике
-----------------------------------------
- Single Responsibility (S): каждый класс делает одно — Downloader скачивает, Assembler собирает, Processor запускает ML модель.
- Open/Closed (O): добавление нового процессора (другая версия RIFE) = создать новый Processor-класс и зарегистрировать в factory — Orchestrator не меняется.
- Liskov Substitution (L): интерфейс Processor/Downloader/Uploader должен быть достаточно узким и документированным; реализации не ломают контракт (методы возвращают стандартный результат).
- Interface Segregation (I): не создавать огромного интерфейса с множеством методов; вместо этого — маленькие протоколы (Downloader.download, Downloader.head, Uploader.upload, Uploader.resume_pending).
- Dependency Inversion (D): Orchestrator зависит от абстракций (протоколов), конкретные реализации передаются извне (фабрики/DI).

Примеры контрактов (псевдокод)
------------------------------
(писать в Markdown нет кода изменений; ниже — для понимания)

- class Downloader(Protocol):
    def download(self, url: str, dest: str) -> LocalFile

- class Processor(Protocol):
    def process(self, input_dir: str, output_dir: str, options: dict) -> ProcessorResult

- class Assembler(Protocol):
    def assemble(self, frames_dir: str, out_video: str, fps: int) -> AssemblyResult

- class Uploader(Protocol):
    def upload(self, path: str, bucket: str, key: str) -> UploadResult
    def resume_pending(self) -> list[UploadResult]

Поведение при ошибках и обещание надежности
-------------------------------------------
- Каждая heavy операция (download, process, upload) — обёрнута в retry strategy с backoff и ограничением на общее время.
- Если upload не удался окончательно, пишем `/workspace/.pending_upload.json` и возвращаем code != 0. При следующем старте runner/entrypoint смотрит на этот файл и вызывает uploader.resume_pending(), записывает результат в лог.
- Для ffmpeg assembly: если nvenc не инициализируется — fallback на libx264; логирование — причина fail, stdout/stderr объединены.
- Для long-running процессов: печатать живой прогресс (по таймеру) через metrics / stdout — Orchestrator может собирать и пробрасывать метрики.

Тестирование
-----------
- Unit tests для:
  - config.loader (валидаторы),
  - utils.retries,
  - uploader (mock boto3),
  - assembler (mock subprocess ffmpeg),
  - processor (использовать моки вместо реального GPU)
- Integration тесты: тестовые небольшие видео (смoke), которые прогоняются через контейнерный образ на CI.
- Добавить smoke test в pipeline: run for 5-8s and verify output exists.

План поэтапной миграции (микро‑итерации)
----------------------------------------
1) Создать пакеты и интерфейсы (шаблоны) — без изменения функционала. (1–2 дня)
2) Реализовать `upload_b2.py` как модуль `io/uploader.py` — перепаковать текущий скрипт. Покрыть unit tests (mock boto3). (1 день)
3) Вынести `pipeline` в Orchestrator: создать thin runner, который вызывает Orchestrator, но пока использует старые функции как адаптеры (Adapter pattern). (1–2 дня)
4) Перенести Frame Assembler: выделить логику сборки и fallback на encoder. Написать unit tests (mock ffmpeg). (1 день)
5) Вынести Processor/Wrapper: создать `processors/realesrgan.py` и `processors/rife.py` интерфейсы и адаптеры к текущим shell-скриптам. (2–3 дня)
6) Постепенно заменить вызовы в Orchestrator, покрывая интеграционными smoke-тестами.
7) Рефакторинг logging/metrics и добавление pending marker behavior. (1 день)
8) Небольшая оптимизация и документирование (README). (1 день)

Критерии приёмки (Done / QA)
----------------------------
- Код разбит на модули с четкими интерфейсами.
- Каждая публичная функция имеет unit-test с >80% покрытием по критичным путям.
- При сбое загрузки создается `/workspace/.pending_upload.json` и последующий запуск автоматически пытается загрузить файл снова.
- Логи последовательны: upload-логи идут перед финальным маркером.
- Не сломана backward-совместимость: старые команды/скрипты по умолчанию работают через адаптеры до полного переключения.

Риски и mitigations
-------------------
- Большой объём изменений → брать итерациями, держать backward compatibility через адаптеры.
- Наличие GPU зависимости (torch/cuda) — тестировать fallback-пути на CPU и без torch.
- Ошибки в FFmpeg опциях (nvenc vs libx264) — логировать stderr и возвращать понятные ошибки, добавлять опцию конфигурации encoder preference.

Производительность и операционные подсказки
-------------------------------------------
- Для долгих задач (RIFE/Real-ESRGAN) сохранять промежуточные результаты и метрики (time per frame, VRAM usage) в `workdir/diagnostics.json`.
- Хранить временные файлы в /tmp или указанный tmpdir; при критических ошибках не удалять tmpdir для отладки, или предлагать опцию `--keep-tmp`.
- Продумать graceful shutdown: ловить SIGTERM и корректно флашить pending marker и логировать состояние.

Пример расписания миграции — 2 недели (агрессивный)
-------------------------------------------------
- День 1: набросок структуры, интерфейсы, config loader
- День 2: uploader + tests
- День 3: assembler + tests
- День 4–5: адаптеры для processor; интеграция с Orchestrator
- День 6: runner, signals, pending marker integration
- День 7: CI, lint, smoke tests
- День 8–10: доработка, багфиксы, тесты на реальных инстансах
- День 11–14: стабилизация, документация, релиз

Резюме — ключевые шаги, которые надо сделать прямо сейчас
--------------------------------------------------------
1. Создать `src/*` структуру и зафиксировать интерфейсы (протоколы). Это минимальный контракт для команды.
2. Перенести загрузчик (upload_b2.py) в модуль `io/uploader.py` и покрыть тестами.
3. Изолировать сборку кадров (assembler) и добавить robust fallback и логирование ошибок.
4. Создать Orchestrator, который использует абстракции и поэтапно заменяет вызовы старых скриптов адаптерами.

---

Файл подготовлен для `oop2.md`. Если хотите, я автоматически создам skeleton файлов и тестов (с шаблонами), выполню первый шаг миграции — вынесу `upload_b2.py` в `src/io/uploader.py` и добавлю unit-test с моками для boto3. Скажи, какой следующий конкретный шаг сделать: skeleton, uploader миграция, assembler, или Orchestrator?
