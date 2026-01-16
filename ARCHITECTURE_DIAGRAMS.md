# 🏗️ Архитектурная схема ProPainter Patching System

## 📊 Общая схема потока данных

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           VAST.AI GPU INSTANCE                              │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │                         Docker Container                              │ │
│  │                                                                       │ │
│  │  ┌─────────────────┐                                                 │ │
│  │  │  pipeline_v2.py │  ◄─── 🚪 ТОЧКА ВХОДА                           │ │
│  │  └────────┬────────┘                                                 │ │
│  │           │                                                          │ │
│  │           ▼                                                          │ │
│  │  ┌──────────────────────────────┐                                   │ │
│  │  │  ProcessorFactory.__init__() │                                   │ │
│  │  └────────┬─────────────────────┘                                   │ │
│  │           │                                                          │ │
│  │           ├──► 1️⃣ _inject_pure_pytorch_corrblock()                  │ │
│  │           │         │                                                │ │
│  │           │         └──► Перезаписывает                             │ │
│  │           │              /opt/ProPainter/RAFT/corr.py               │ │
│  │           │              ┌────────────────────────┐                 │ │
│  │           │              │ Pure PyTorch CorrBlock │                 │ │
│  │           │              │ - nn.Module            │                 │ │
│  │           │              │ - @custom_fwd          │                 │ │
│  │           │              │ - .clone() fix         │                 │ │
│  │           │              │ - TF32 disable         │                 │ │
│  │           │              └────────────────────────┘                 │ │
│  │           │                                                          │ │
│  │           ├──► 2️⃣ _patch_raft_py()                                  │ │
│  │           │         │                                                │ │
│  │           │         └──► Патчит import в                            │ │
│  │           │              /opt/ProPainter/RAFT/raft.py               │ │
│  │           │              from .corr import CorrBlock # PATCHED      │ │
│  │           │                                                          │ │
│  │           └──► 3️⃣ _patch_propainter_transformer()                   │ │
│  │                   │                                                  │ │
│  │                   └──► Патчит                                        │ │
│  │                        /opt/ProPainter/model/modules/               │ │
│  │                        sparse_transformer.py                         │ │
│  │                        ┌──────────────────────────────┐             │ │
│  │                        │ att = (q @ k.transpose())    │             │ │
│  │                        │         ↓                    │             │ │
│  │                        │ att = (q @ k.transpose()     │             │ │
│  │                        │         .contiguous())       │             │ │
│  │                        └──────────────────────────────┘             │ │
│  │                                                                      │ │
│  │  ┌───────────────────────────────────────────────────────────────┐  │ │
│  │  │              ProPainter Execution Flow                        │  │ │
│  │  │                                                               │  │ │
│  │  │  Input Video ──► Frame Extraction ──► Mask Generation ──┐    │  │ │
│  │  │                                                          │    │  │ │
│  │  │  ┌───────────────────────────────────────────────────────┘    │  │ │
│  │  │  │                                                            │  │ │
│  │  │  ▼                                                            │  │ │
│  │  │  ProPainter Model                                             │  │ │
│  │  │  ├─► RAFT Flow ◄─── 🔧 Uses patched CorrBlock                │  │ │
│  │  │  │   (corr.py)                                                │  │ │
│  │  │  │                                                            │  │ │
│  │  │  ├─► Transformer Attention ◄─── 🔧 Uses patched transpose    │  │ │
│  │  │  │   (sparse_transformer.py)                                 │  │ │
│  │  │  │                                                            │  │ │
│  │  │  └─► Inpainting Network                                       │  │ │
│  │  │      ↓                                                        │  │ │
│  │  │  Inpainted Frames ──► Video Assembly ──► Output Video         │  │ │
│  │  └───────────────────────────────────────────────────────────────┘  │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Детальная схема патчинга CorrBlock

```
┌────────────────────────────────────────────────────────────────────────────┐
│                      RAFT Correlation Patching Flow                        │
└────────────────────────────────────────────────────────────────────────────┘

ОРИГИНАЛЬНЫЙ КОД (проблемный):
┌──────────────────────────────────────────────────────────────┐
│ /opt/ProPainter/RAFT/corr.py                                 │
│ ─────────────────────────────────────────────────────────    │
│ import spatial_correlation_sampler as correlation            │  ❌ C++ Extension
│                                                              │  ❌ Требует компиляции
│ class CorrBlock:                                             │  ❌ Падает на RTX 50xx
│     def __init__(self, fmap1, fmap2):                        │
│         corr = correlation.SpatialCorrelationSampler(...)    │
└──────────────────────────────────────────────────────────────┘
                             │
                             │ Runtime Injection ⚡
                             ▼
┌──────────────────────────────────────────────────────────────┐
│ ПРОПАТЧЕННЫЙ КОД (генерируется в runtime):                  │
│ /opt/ProPainter/RAFT/corr.py                                 │
│ ─────────────────────────────────────────────────────────    │
│ import torch                                                 │  ✅ Pure PyTorch
│ import torch.nn as nn                                        │  ✅ Работает везде
│ from torch.cuda.amp import custom_fwd                        │  ✅ Нет компиляции
│                                                              │
│ class CorrBlock(nn.Module):                                  │
│     def __init__(self, fmap1, fmap2, *args, **kwargs):      │
│         super().__init__()                                   │
│         self.calculate_correlation_pyramid(fmap1, fmap2)    │
│                                                              │
│     def calculate_correlation_pyramid(self, fmap1, fmap2):  │
│         # ULTIMATE FIX v4                                    │
│         torch.backends.cuda.matmul.allow_tf32 = False       │  🔧 Отключить TF32
│         fmap1_t = fmap1.transpose(1,2).clone()              │  🔧 .clone() fix
│         fmap2_c = fmap2.clone()                              │
│         try:                                                 │
│             corr = torch.bmm(fmap1_t, fmap2_c)              │  🔧 BMM fallback
│         except RuntimeError:                                 │
│             # Поэлементное умножение                         │
│             for b in range(batch):                           │
│                 res = torch.matmul(...)                      │
│                                                              │
│     @custom_fwd(cast_inputs=torch.float32)                  │  🔧 Auto float32
│     def __call__(self, coords):                             │
│         # ... sampling logic ...                            │
└──────────────────────────────────────────────────────────────┘
```

---

## 🔄 Схема патчинга Transformer

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   Transformer Attention Patching Flow                      │
└────────────────────────────────────────────────────────────────────────────┘

ПРОБЛЕМА: transpose() + @ создаёт non-contiguous tensor
┌────────────────────────────────────────────────┐
│ sparse_transformer.py (ОРИГИНАЛ)               │
│ ───────────────────────────────────────────    │
│ # Temporal attention                           │
│ att_t = (win_q_t @ win_k_t.transpose(-2, -1)) │  ❌ stride error
│                     └──────┬──────┘             │
│                            │                    │
│                    Non-contiguous view          │
│                    (strides не выровнены)       │
└────────────────────────────────────────────────┘
                    │
                    │ cuBLAS call
                    ▼
┌────────────────────────────────────────────────┐
│ CUDA cuBLAS Library                            │
│ ───────────────────────────────────────────    │
│ cublasSgemmStridedBatched(...)                 │
│     ↓                                          │
│ ❌ CUBLAS_STATUS_INVALID_VALUE                │  Reject: invalid stride
│     "Invalid memory alignment"                 │
└────────────────────────────────────────────────┘

РЕШЕНИЕ: Добавить .contiguous()
┌────────────────────────────────────────────────────────┐
│ sparse_transformer.py (ПРОПАТЧЕН)                      │
│ ───────────────────────────────────────────────────    │
│ # Temporal attention                                   │
│ att_t = (win_q_t @ win_k_t.transpose(-2, -1)          │
│                           .contiguous())  # PATCHED    │  ✅ OK
│                     └──────┬──────┘                     │
│                            │                            │
│                    Contiguous copy created              │
│                    (strides выровнены)                  │
└────────────────────────────────────────────────────────┘
                    │
                    │ cuBLAS call
                    ▼
┌────────────────────────────────────────────────┐
│ CUDA cuBLAS Library                            │
│ ───────────────────────────────────────────    │
│ cublasSgemmStridedBatched(...)                 │
│     ↓                                          │
│ ✅ SUCCESS                                     │  Accept: valid stride
│     Matrix multiplication complete             │
└────────────────────────────────────────────────┘
```

---

## 🎯 Места патчинга в ProPainter

```
/opt/ProPainter/
│
├── RAFT/
│   ├── corr.py                    ⭐ ПЕРЕЗАПИСЫВАЕТСЯ (Pure PyTorch)
│   ├── raft.py                    🔧 ПАТЧИТСЯ (import statement)
│   └── ...
│
├── model/
│   ├── propainter.py              ❓ ВОЗМОЖНО НУЖНО ПАТЧИТЬ
│   │                                 (текущая точка падения)
│   │
│   └── modules/
│       ├── sparse_transformer.py  ✅ ПРОПАТЧЕН (3 места)
│       │                             - att_t = ... .contiguous()
│       │                             - att = ... .contiguous()
│       │                             - x = att @ v.contiguous()
│       │
│       ├── deformable_transformer.py  ❓ ВОЗМОЖНО НУЖНО ПАТЧИТЬ
│       │
│       └── ...                     ❓ НУЖНО ПРОВЕРИТЬ
│
└── inference_propainter.py        ❌ НЕ ПАТЧИТСЯ (main script)
                                      Ошибка на строке 433:
                                      pred_img = model(...)
```

---

## 🔬 Timeline исправлений

```
ИТЕРАЦИЯ 1: Попытка установить C++ extension
└─► ❌ НЕУДАЧА: долгая компиляция, падает на RTX 50xx

ИТЕРАЦИЯ 2: Pure PyTorch CorrBlock (базовая версия)
└─► ❌ НЕУДАЧА: CUBLAS_STATUS_INVALID_VALUE (stride error)

ИТЕРАЦИЯ 3: Добавление .contiguous()
└─► ❌ НЕУДАЧА: .contiguous() недостаточно

ИТЕРАЦИЯ 4: .clone() + TF32 disable
└─► ⚠️ ЧАСТИЧНО: RAFT заработал, но Transformer упал

ИТЕРАЦИЯ 5: Патчинг Transformer
└─► ⚠️ ЧАСТИЧНО: Transformer заработал, но main model упал

ИТЕРАЦИЯ 6 (ТЕКУЩАЯ): Поиск всех transpose операций
└─► 🔄 В ПРОЦЕССЕ: нужно найти и пропатчить ВСЕ места
```

---

## 💡 Ключевые инсайты

### Почему .contiguous() не всегда помогает?

```python
# ПРОБЛЕМА:
tensor = some_tensor.transpose(1, 2)  # Создаёт view (НЕ копирует данные)
tensor = tensor.contiguous()          # Иногда просто возвращает self!

# РЕШЕНИЕ:
tensor = some_tensor.transpose(1, 2).clone()  # ВСЕГДА копирует
```

### Почему TF32 создаёт проблемы?

TensorFloat32 (TF32) - это новый режим на Ampere+ GPU:
- Использует FP32 API но FP16 точность
- Быстрее, но капризнее к выравниванию памяти
- На RTX 30/40/50 может вызывать stride errors

```python
# Отключение TF32
torch.backends.cuda.matmul.allow_tf32 = False
torch.backends.cudnn.allow_tf32 = False
```

### Почему BMM стабильнее matmul?

```python
# МЕНЕЕ СТАБИЛЬНО:
result = torch.matmul(a, b)  # Универсальная функция (broadcasting)

# БОЛЕЕ СТАБИЛЬНО:
result = torch.bmm(a, b)     # Только batch matmul (без broadcasting)
                             # Меньше edge cases → меньше багов
```

---

## 📚 Следующие шаги для агента

1. **Диагностика:**
   ```bash
   grep -rn "\.transpose.*@\|@.*\.transpose" /opt/ProPainter --include="*.py" | grep -v PATCHED
   ```

2. **Выбор стратегии:**
   - **Вариант А:** Глобальный monkey-patch (быстро, но грязно)
   - **Вариант Б:** Индивидуальный патчинг (медленно, но чисто)
   - **Вариант В:** Форк ProPainter (долго, но надёжно)

3. **Тестирование:**
   - RTX 3090 (Ampere)
   - RTX 4090 (Ada Lovelace)
   - RTX 5070 Ti (Blackwell)

4. **Документирование:**
   - Обновить CONTEXT_FOR_HANDOVER.md
   - Добавить в QUICK_DEBUG_GUIDE.md

---

**Последнее обновление:** 16 января 2026  
**Версия схемы:** 1.0

