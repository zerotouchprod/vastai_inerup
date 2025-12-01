# 🚀 Batch Processor Quick Start

**3 шага до batch processing!**

---

## Шаг 1: Настроить ENV ✅

```bash
# Vast.ai
export VAST_API_KEY="your_key"

# B2
export B2_KEY="your_key"
export B2_SECRET="your_secret"
export B2_BUCKET="your_bucket"
```

---

## Шаг 2: Настроить config.yaml ✅

```yaml
# Git branch
git_branch: "main"

# Presets
presets:
  balanced:
    min_vram: 16
    max_price: 0.5
```

---

## Шаг 3: Запустить! ✅

```bash
# Dry run (проверить)
python batch_processor.py --input-dir input/batch1 --dry-run

# Реальная обработка
python batch_processor.py --input-dir input/batch1
```

---

## ✅ Готово!

**Старые скрипты больше не нужны!**

Полная документация: `BATCH_REFACTORING_COMPLETE.md`

---

*Quick Start: 1 декабря 2025* ✅

