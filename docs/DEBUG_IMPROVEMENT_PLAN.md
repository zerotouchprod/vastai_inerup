# 🐛 Улучшение отладки Shell Scripts

## Проблема
Shell скрипты `run_realesrgan_pytorch.sh` и `run_rife_pytorch.sh` **сложно отлаживать**:
- ❌ Нет step-by-step debugging
- ❌ Трудно отследить состояние переменных
- ❌ Логи размазаны по файлам
- ❌ Непонятно где именно упало

## ✅ Решение: Улучшить отладку БЕЗ полной переписки

### Вариант 1: Debug Mode для Shell Scripts (БЫСТРО) ⚡

Добавим подробное логирование в существующие скрипты:

```bash
# В начало run_realesrgan_pytorch.sh
DEBUG_MODE="${DEBUG_MODE:-0}"

log_debug() {
    if [ "$DEBUG_MODE" = "1" ]; then
        echo "[DEBUG $(date +%H:%M:%S)] $*" >&2
    fi
}

log_var() {
    if [ "$DEBUG_MODE" = "1" ]; then
        echo "[VAR] $1=${!1}" >&2
    fi
}

# Использование:
log_debug "Starting frame extraction"
log_var "INPUT_FILE"
log_var "OUTPUT_DIR"
```

Использование:
```bash
DEBUG_MODE=1 python pipeline_v2.py --mode upscale
```

---

### Вариант 2: Python Debug Wrapper (СРЕДНЕ) 🔍

Создать Python обёртку с подробным логированием:

```python
# src/infrastructure/processors/debug_wrapper.py
"""Debug wrapper for shell script processors."""

import subprocess
import time
from pathlib import Path

class DebugShellWrapper:
    """Wrapper that logs everything shell script does."""
    
    def __init__(self, script_path, log_file=None):
        self.script_path = script_path
        self.log_file = log_file or Path("/tmp/debug_shell.log")
    
    def run(self, *args, env=None):
        """Run shell script with detailed logging."""
        with open(self.log_file, 'w') as f:
            f.write(f"=== Shell Debug Log ===\n")
            f.write(f"Script: {self.script_path}\n")
            f.write(f"Args: {args}\n")
            f.write(f"Env: {env}\n")
            f.write(f"Started: {time.time()}\n\n")
        
        # Run with verbose output
        result = subprocess.run(
            [self.script_path, *args],
            env=env,
            capture_output=True,
            text=True
        )
        
        # Log everything
        with open(self.log_file, 'a') as f:
            f.write(f"\n=== STDOUT ===\n")
            f.write(result.stdout)
            f.write(f"\n=== STDERR ===\n")
            f.write(result.stderr)
            f.write(f"\n=== Exit Code: {result.returncode} ===\n")
        
        return result
```

---

### Вариант 3: Hybrid Approach (РЕКОМЕНДУЮ) 🎯

**Создать Python версии ТОЛЬКО для отладки**, а shell оставить для production:

```python
# src/infrastructure/processors/realesrgan/pytorch_debug.py
"""Debug version of Real-ESRGAN processor (pure Python)."""

class RealESRGANPytorchDebug(BaseProcessor):
    """
    Pure Python implementation for DEBUGGING.
    Use shell version for production.
    """
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.logger.info("🐛 Using DEBUG version (pure Python)")
    
    def _execute_processing(self, input_frames, output_dir, options):
        """Process with detailed logging."""
        import torch
        from realesrgan import RealESRGANer
        from basicsr.archs.rrdbnet_arch import RRDBNet
        
        scale = options.get('scale', 2)
        
        self.logger.info(f"🔍 Loading model...")
        model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, 
                       num_block=23, num_grow_ch=32, scale=4)
        
        upsampler = RealESRGANer(
            scale=4,
            model_path='weights/RealESRGAN_x4plus.pth',
            model=model,
            tile=512,
            tile_pad=10,
            pre_pad=0,
            half=torch.cuda.is_available()
        )
        
        self.logger.info(f"🔍 Processing {len(input_frames)} frames")
        
        output_frames = []
        for i, frame_path in enumerate(input_frames):
            self.logger.info(f"🔍 Frame {i+1}/{len(input_frames)}: {frame_path.name}")
            
            try:
                # Load
                import cv2
                img = cv2.imread(str(frame_path))
                self.logger.debug(f"  Loaded: shape={img.shape}, dtype={img.dtype}")
                
                # Process
                output, _ = upsampler.enhance(img, outscale=scale)
                self.logger.debug(f"  Enhanced: shape={output.shape}")
                
                # Save
                output_path = output_dir / frame_path.name
                cv2.imwrite(str(output_path), output)
                self.logger.info(f"  ✅ Saved: {output_path.name}")
                
                output_frames.append(output_path)
                
            except Exception as e:
                self.logger.error(f"  ❌ Failed frame {i+1}: {e}")
                raise
        
        self.logger.info(f"🎉 Completed: {len(output_frames)} frames")
        return output_frames
```

Использование:
```python
# config.yaml
debug_mode: true  # Использовать Python debug версии

# или через ENV
export DEBUG_PROCESSORS=1
python pipeline_v2.py --mode upscale
```

---

## 🚀 Быстрое решение (30 минут)

Создам **Debug Mode** который можно включить прямо сейчас:

### 1. Debug Logger для существующих wrappers

```python
# src/infrastructure/processors/debug.py
"""Debug utilities for processors."""

import os
import logging
from pathlib import Path
from datetime import datetime

class ProcessorDebugger:
    """Debug helper for processor wrappers."""
    
    def __init__(self, name: str):
        self.name = name
        self.enabled = os.getenv('DEBUG_PROCESSORS', '0') == '1'
        self.log_file = Path(f"/tmp/{name}_debug.log")
        
        if self.enabled:
            self.logger = self._setup_logger()
    
    def _setup_logger(self):
        logger = logging.getLogger(f"debug.{self.name}")
        logger.setLevel(logging.DEBUG)
        
        # File handler with detailed format
        fh = logging.FileHandler(self.log_file)
        fh.setLevel(logging.DEBUG)
        
        formatter = logging.Formatter(
            '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s'
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        
        return logger
    
    def log_start(self, **kwargs):
        if self.enabled:
            self.logger.info(f"=== START {self.name} ===")
            for k, v in kwargs.items():
                self.logger.info(f"  {k}: {v}")
    
    def log_step(self, step: str, **kwargs):
        if self.enabled:
            self.logger.debug(f"STEP: {step}")
            for k, v in kwargs.items():
                self.logger.debug(f"  {k}: {v}")
    
    def log_error(self, error: Exception):
        if self.enabled:
            self.logger.error(f"ERROR: {error}", exc_info=True)
    
    def log_end(self, success: bool, **kwargs):
        if self.enabled:
            status = "SUCCESS" if success else "FAILED"
            self.logger.info(f"=== END {self.name}: {status} ===")
            for k, v in kwargs.items():
                self.logger.info(f"  {k}: {v}")
```

### 2. Обновить wrappers

```python
# src/infrastructure/processors/realesrgan/pytorch_wrapper.py
from ..debug import ProcessorDebugger

class RealESRGANPytorchWrapper(BaseProcessor):
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.debugger = ProcessorDebugger('realesrgan')
    
    def _execute_processing(self, input_frames, output_dir, options):
        self.debugger.log_start(
            num_frames=len(input_frames),
            output_dir=str(output_dir),
            options=options
        )
        
        try:
            self.debugger.log_step("calling_shell_script",
                script=str(self.WRAPPER_SCRIPT),
                exists=self.WRAPPER_SCRIPT.exists()
            )
            
            # Original shell call
            result = subprocess.run(...)
            
            self.debugger.log_step("shell_completed",
                returncode=result.returncode,
                stdout_lines=len(result.stdout.split('\n')),
                stderr_lines=len(result.stderr.split('\n'))
            )
            
            output_frames = self._collect_output_frames(output_dir)
            
            self.debugger.log_end(True, 
                frames_produced=len(output_frames)
            )
            
            return output_frames
            
        except Exception as e:
            self.debugger.log_error(e)
            self.debugger.log_end(False)
            raise
```

---

## 📊 Сравнение решений

| Подход | Время | Сложность | Отладка | Production |
|--------|-------|-----------|---------|------------|
| Debug logs в shell | 1 час | Низкая | ⭐⭐⭐ | ✅ |
| Python debug wrapper | 2 часа | Средняя | ⭐⭐⭐⭐ | ✅ |
| Hybrid (рекомендую) | 4 часа | Средняя | ⭐⭐⭐⭐⭐ | ✅ |
| Полная переписка | 40 часов | Высокая | ⭐⭐⭐⭐⭐ | ⚠️ |

---

## 🎯 Моя рекомендация

### Сделать СЕЙЧАС (2-4 часа):

1. ✅ **Добавить ProcessorDebugger** (30 мин)
2. ✅ **Обновить оба wrapper** (1 час)
3. ✅ **Создать debug версии** для локальной отладки (2 часа)
4. ✅ **Документировать** как использовать (30 мин)

### Результат:
```bash
# Production (используют shell)
python pipeline_v2.py --mode upscale

# Debug (детальные логи)
DEBUG_PROCESSORS=1 python pipeline_v2.py --mode upscale

# Debug (pure Python, step debugging)
DEBUG_MODE=native python pipeline_v2.py --mode upscale
# Можно ставить breakpoints в PyCharm!
```

---

## 🚀 Начать сейчас?

Хотите чтобы я:
1. ✅ Создал debug инфраструктуру
2. ✅ Обновил wrappers
3. ✅ Добавил pure Python debug версии
4. ✅ Написал документацию

**Это займёт ~4 часа работы, но сделает отладку в 10 раз проще!**

Что скажете? Начать? 🚀

