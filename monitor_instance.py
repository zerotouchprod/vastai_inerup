#!/usr/bin/env python3
"""
Мониторинг конкретного инстанса с постоянным обновлением логов
Использование: python monitor_instance.py <instance_id>
"""
import sys
import time
import argparse
import os
import json
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, '.')

import vast_submit
import requests

# File to persist last stopped job info so monitor won't react to older runs
LAST_JOB_FILE = Path('.last_stopped_job')


def _load_last_job():
    try:
        if LAST_JOB_FILE.exists():
            data = json.loads(LAST_JOB_FILE.read_text(encoding='utf-8'))
            jid = data.get('job_id')
            start = data.get('start')
            if jid and start:
                try:
                    ts = datetime.fromisoformat(start)
                except Exception:
                    ts = None
                return {'job_id': jid, 'start': ts}
    except Exception:
        pass
    return None


def _save_last_job(job_id: str, start_iso: str):
    try:
        LAST_JOB_FILE.write_text(json.dumps({'job_id': job_id, 'start': start_iso}, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def monitor_instance(inst_id, tail_lines=200, interval=5):
    """Мониторит инстанс и показывает новые логи"""

    print(f"=== Мониторинг инстанса {inst_id} ===")
    print(f"    Строк логов: {tail_lines}")
    print(f"    Интервал обновления: {interval}с\n")

    # Получаем информацию об инстансе
    try:
        info = vast_submit.get_instance(inst_id)
        if not info:
            print(f"❌ Инстанс {inst_id} не найден")
            return

        inst = info.get('instances', {})
        gpu = inst.get('gpu_name', 'Unknown')
        status = inst.get('actual_status', 'unknown')
        state = inst.get('cur_state', 'unknown')
        price = inst.get('dph_total', 0)
        ssh_host = inst.get('ssh_host', 'N/A')
        ssh_port = inst.get('ssh_port', 'N/A')

        print(f"📍 Инстанс: {inst_id}")
        print(f"   GPU: {gpu}")
        print(f"   Status: {status}")
        print(f"   State: {state}")
        print(f"   Price: ${price:.4f}/hr")
        if ssh_host != 'N/A':
            print(f"   SSH: ssh -p {ssh_port} root@{ssh_host}")
        print()

    except Exception as e:
        print(f"❌ Ошибка получения информации: {e}")
        return

    print("=== Мониторинг логов (Ctrl+C для выхода) ===")
    print("Обновление каждые 5 секунд...\n")

    last_log_lines = []
    check_count = 0
    last_status = None
    stop_sent = False  # ensure stop request sent only once
    # Auto-stop configuration: enabled by env AUTO_STOP_ON_SUCCESS (defaults to true)
    auto_stop_env = os.environ.get('AUTO_STOP_ON_SUCCESS', '1')
    AUTO_STOP_ENABLED = str(auto_stop_env).lower() not in ('0', 'false', 'no', '')
    # Additional flag: allow stopping on simple remote_runner success messages (default: disabled)
    auto_remote_env = os.environ.get('AUTO_STOP_ON_REMOTE_SUCCESS', '0')
    AUTO_STOP_ON_REMOTE = str(auto_remote_env).lower() not in ('0', 'false', 'no', '')

    # Default pattern includes named captures for job id and start timestamp (ISO format)
    DEFAULT_STOP_PATTERNS = [
        r"===\s*VASTAI_PIPELINE_COMPLETED_SUCCESSFULLY\s*===\s*job_id=(?P<job>[0-9a-f\-]+)\s*start=(?P<start>\S+)"
    ]

    # Allow overriding patterns via env: AUTO_STOP_PATTERNS with '||' as separator
    raw_patterns = os.environ.get('AUTO_STOP_PATTERNS')
    if raw_patterns:
        try:
            patterns = [p for p in raw_patterns.split('||') if p.strip()]
        except Exception:
            patterns = DEFAULT_STOP_PATTERNS
    else:
        patterns = DEFAULT_STOP_PATTERNS

    # Compile regexes (case-insensitive)
    import re
    try:
        STOP_REGEXS = [re.compile(p, re.IGNORECASE) for p in patterns]
    except Exception:
        # fallback to simple substring checks if regex compile fails
        STOP_REGEXS = []

    # Load last seen/stopped job to avoid reacting to older runs
    last_job = _load_last_job()

    while True:
        try:
            check_count += 1
            current_time = time.strftime('%H:%M:%S')

            # Получаем статус
            info = vast_submit.get_instance(inst_id)
            if not info:
                print(f"\n❌ Инстанс {inst_id} больше не найден")
                break

            inst = info.get('instances', {})
            current_state = inst.get('cur_state', 'unknown')
            current_status = inst.get('actual_status', 'unknown')

            # Показываем статус только если изменился
            status_str = f"{current_state} / {current_status}"
            if status_str != last_status:
                print(f"\n[{current_time}] 📊 Статус: {status_str}")
                last_status = status_str

            # Каждые 10 проверок показываем "живой" индикатор
            if check_count % 2 == 0:
                print(f"[{current_time}] 🔄 Проверка #{check_count}...", end='\r', flush=True)

            # Запрашиваем логи
            try:
                res = vast_submit.api_put(f'/instances/request_logs/{inst_id}/', {'tail': str(tail_lines)})

                if 'temp_download_url' in res:
                    time.sleep(1.5)  # Небольшая пауза для подготовки логов

                    r = requests.get(res['temp_download_url'], timeout=15)
                    if r.status_code == 200:
                        current_lines = r.text.strip().split('\n')

                        # Находим новые строки (если были предыдущие логи). На первом запросе new_lines будет пустым,
                        # чтобы избежать реакции на старые маркеры из прошлых запусков.
                        new_lines = []
                        if last_log_lines:
                            # Более надёжный алгоритм: ищем последнюю уникальную строку из старых логов
                            # и считаем всё, что шло после неё, как новые строки.
                            last_non_empty = [l for l in last_log_lines[-20:] if l.strip()]
                            # take up to last 5 non-empty as signature
                            last_non_empty = last_non_empty[-5:] if last_non_empty else []

                            if last_non_empty:
                                last_marker = last_non_empty[-1]
                                try:
                                    marker_idx = len(current_lines) - 1 - current_lines[::-1].index(last_marker)
                                    new_lines = current_lines[marker_idx + 1:]
                                except ValueError:
                                    # Если не нашли, покажем последние 30 строк как "новые"
                                    new_lines = current_lines[-30:]
                            else:
                                new_lines = current_lines[-30:]

                        # Показываем новые строки (если есть)
                        if new_lines:
                            shown_lines = 0
                            for line in new_lines:
                                if not line.strip():
                                    continue
                                print(line)
                                shown_lines += 1
                            if shown_lines > 0:
                                print()  # Пустая строка после блока логов
                        else:
                            # Первый запрос - показываем последние 50 строк (больше контекста)
                            if not last_log_lines:
                                print("--- Последние логи (50 строк) ---")
                                for line in current_lines[-50:]:
                                    if line.strip():
                                        print(line)
                                print("---\n")

                        # Теперь обновим last_log_lines
                        last_log_lines = current_lines

                        # Detect container-side success marker ONLY in newly appended lines
                        try:
                            if AUTO_STOP_ENABLED and (not stop_sent) and new_lines:
                                recent_new_text = '\n'.join(new_lines)
                                matched = False
                                used_pattern = None
                                match_obj = None
                                # Try regexes first (we expect named groups 'job' and 'start')
                                for rx in STOP_REGEXS:
                                    try:
                                        m = rx.search(recent_new_text)
                                        if m:
                                            matched = True
                                            used_pattern = rx.pattern
                                            match_obj = m
                                            break
                                    except Exception:
                                        continue

                                # If no compiled regexes (or none matched), fall back to simple substring matching
                                if (not matched) and (not STOP_REGEXS):
                                    for p in patterns:
                                        if p.lower() in recent_new_text.lower():
                                            matched = True
                                            used_pattern = p
                                            break

                                if matched:
                                    # Try to extract job id and start timestamp from regex match
                                    job_id = None
                                    job_start_iso = None
                                    job_start_dt = None
                                    if match_obj:
                                        try:
                                            job_id = match_obj.groupdict().get('job')
                                            job_start_iso = match_obj.groupdict().get('start')
                                        except Exception:
                                            job_id = None
                                            job_start_iso = None

                                    # Fallback: try simple parse from recent_new_text
                                    if not job_id:
                                        # look for 'job_id=' token
                                        import re as _re
                                        m2 = _re.search(r"job_id=([0-9a-f\-]+)", recent_new_text, _re.IGNORECASE)
                                        if m2:
                                            job_id = m2.group(1)
                                    if not job_start_iso:
                                        import re as _re
                                        m3 = _re.search(r"start=([0-9T:\-+.]+)", recent_new_text)
                                        if m3:
                                            job_start_iso = m3.group(1)

                                    if job_start_iso:
                                        try:
                                            job_start_dt = datetime.fromisoformat(job_start_iso)
                                        except Exception:
                                            job_start_dt = None

                                    # If we have no job metadata but remote-success flag set, treat as immediate stop
                                    if not job_id and not job_start_iso and AUTO_STOP_ON_REMOTE:
                                        # synthesize a job id and timestamp for persistence
                                        try:
                                            synth_id = f"remote_success_{datetime.now(timezone.utc).isoformat()}"
                                            synth_start = datetime.now(timezone.utc).isoformat()
                                        except Exception:
                                            synth_id = 'remote_success'
                                            synth_start = datetime.now().isoformat()
                                        try:
                                            print(f"\nInstance will be stopped due to remote_runner success (instance {inst_id})")
                                        except Exception:
                                            print(f"\nInstance will be stopped (instance {inst_id})")
                                        try:
                                            resp = vast_submit.stop_instance(inst_id)
                                            print(f"Stop request sent. Response: {resp}")
                                        except Exception as _e:
                                            print(f"Warning: failed to stop instance {inst_id}: {_e}")
                                        stop_sent = True
                                        try:
                                            _save_last_job(synth_id, synth_start)
                                            last_job = {'job_id': synth_id, 'start': datetime.fromisoformat(synth_start)}
                                        except Exception:
                                            pass
                                        continue

                                    # Decide whether to act: if we have a stored last_job, ignore if this job is older or same
                                    do_stop = True
                                    if last_job and job_start_dt:
                                        try:
                                            last_start = last_job.get('start')
                                            last_jid = last_job.get('job_id')
                                            if last_start and job_start_dt <= last_start:
                                                do_stop = False
                                            if last_jid and job_id and job_id == last_jid:
                                                do_stop = False
                                        except Exception:
                                            pass

                                    if not do_stop:
                                        try:
                                            print(f"\nDetected final pipeline marker for older/already-handled job (job_id={job_id}, start={job_start_iso}) — ignoring for instance {inst_id}")
                                        except Exception:
                                            print("\nDetected final pipeline marker for older/already-handled job — ignoring")
                                        # do not set stop_sent
                                        continue

                                    # Proceed to stop: log intention, call API, persist last_job
                                    try:
                                        print(f"\nInstance will be stopped for job_id={job_id} start={job_start_iso} (instance {inst_id})")
                                    except Exception:
                                        print(f"\nInstance will be stopped (instance {inst_id})")
                                    try:
                                        resp = vast_submit.stop_instance(inst_id)
                                        print(f"Stop request sent. Response: {resp}")
                                    except Exception as _e:
                                        print(f"Warning: failed to stop instance {inst_id}: {_e}")
                                    stop_sent = True
                                    # Persist last job info so future monitors won't re-act
                                    if job_id and job_start_iso:
                                        try:
                                            _save_last_job(job_id, job_start_iso)
                                            last_job = {'job_id': job_id, 'start': datetime.fromisoformat(job_start_iso)}
                                        except Exception:
                                            pass
                        except Exception:
                            # non-fatal — continue monitoring
                            pass

                        # Проверяем на завершение - ТОЛЬКО в последних 100 строках!
                        recent_log = '\n'.join(current_lines[-100:])

                        # Проверяем что pipeline активен (есть недавние сообщения)
                        is_active = any(marker in recent_log for marker in [
                            'Starting pipeline', 'Processing', 'Interpolation', 'Upscaling',
                            'pairs/sec', 'GPU:', 'frames'
                        ])

                        # Успешное завершение - только если есть в последних строках
                        if ('Pipeline finished' in recent_log or 'Pipeline completed successfully' in recent_log):
                            # Дополнительная проверка - должна быть строка с Duration или Upload successful
                            has_completion = any(marker in recent_log for marker in [
                                'Duration:', 'Upload successful', 'completed successfully'
                            ])

                            if has_completion:
                                print("\n" + "="*60)
                                print("🎉 УСПЕХ! Pipeline завершён!")
                                print("="*60)

                                # Ищем финальные результаты
                                for line in current_lines[-50:]:
                                    if any(kw in line for kw in ['Output file:', 'Duration:', 'Upload successful', 'https://', 'Pipeline completed']):
                                        print(line)

                                print(f"\n✅ Обработка завершена успешно!")
                                print(f"   Инстанс: {inst_id}")
                                print(f"   GPU: {gpu}")
                                print(f"\n📌 Команды:")
                                print(f"   Скачать логи: python scripts/show_logs.py {inst_id} > logs_{inst_id}.txt")
                                print(f"   Остановить:   python scripts/manage_instance.py {inst_id} --stop")
                                break

                        # Проверяем на критические ошибки - тоже только в последних строках
                        if 'Pipeline failed' in recent_log or 'FATAL' in recent_log:
                            print("\n" + "="*60)
                            print("❌ ОШИБКА! Pipeline упал")
                            print("="*60)

                            # Показываем последние ошибки
                            for line in current_lines[-30:]:
                                if any(kw in line for kw in ['ERROR', 'Failed', 'Exception', 'Traceback']):
                                    print(line)

                            print(f"\n❌ Обработка завершена с ошибкой")
                            print(f"\n📌 Команды:")
                            print(f"   Полные логи:  python scripts/show_logs.py {inst_id}")
                            print(f"   Остановить:   python scripts/manage_instance.py {inst_id} --stop")
                            break

                        # Проверяем на AccessDenied в последних строках
                        if 'AccessDenied' in recent_log:
                            # Считаем сколько раз в последних 100 строках
                            count = recent_log.count('AccessDenied')
                            if count > 2:  # Если больше 2 раз в последних 100 строках - проблема
                                print(f"\n⚠️  ВНИМАНИЕ: AccessDenied появляется {count} раз в последних логах!")
                                print("   Возможно проблема с правами B2 или curl командой")

                else:
                    print(f"[{current_time}] ⚠️  Логи пока недоступны (чек #{check_count})")

            except Exception as e:
                print(f"[{current_time}] ⚠️  Ошибка получения логов: {e}")

            # Если инстанс остановлен
            if current_state in ['stopped', 'exited']:
                print(f"\n⚠️  Инстанс остановлен (state: {current_state})")
                print("\nПоследние логи:")
                if last_log_lines:
                    for line in last_log_lines[-20:]:
                        if line.strip():
                            print(line)
                break

            # Ждём перед следующей проверкой
            time.sleep(interval)

        except KeyboardInterrupt:
            print("\n\n⏸️  Мониторинг прерван пользователем")
            print(f"\n📌 Инстанс продолжает работать: {inst_id}")
            print(f"\n   Команды:")
            print(f"   Возобновить:      python monitor_instance.py {inst_id}")
            print(f"   Показать логи:    python scripts/show_logs.py {inst_id}")
            print(f"   Остановить:       python scripts/manage_instance.py {inst_id} --stop")
            break
        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(10)

    print("\n=== Мониторинг завершён ===")


def main():
    parser = argparse.ArgumentParser(description='Мониторинг инстанса Vast.ai')
    parser.add_argument('instance_id', help='ID инстанса для мониторинга')
    parser.add_argument('--tail', type=int, default=200, help='Количество строк логов (по умолчанию: 200)')
    parser.add_argument('--interval', type=int, default=5, help='Интервал обновления в секундах (по умолчанию: 5)')

    args = parser.parse_args()

    monitor_instance(args.instance_id, tail_lines=args.tail, interval=args.interval)


if __name__ == '__main__':
    main()
