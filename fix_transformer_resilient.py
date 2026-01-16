#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import re

# Путь к файлу
TARGET_PATH = "/opt/ProPainter/model/modules/sparse_transformer.py"

# Функция-предохранитель. Она ловит краш драйвера и спасает процесс.
SAFE_MATMUL_DEF = """
import torch

# === RESILIENT MATMUL: GPU -> CPU Fallback ===
def safe_matmul(a, b):
    try:
        # Попытка 1: Считаем на видеокарте
        return a @ b
    except RuntimeError as e:
        # Если драйвер крашнулся (CUBLAS_STATUS_INVALID_VALUE)
        # Мы НЕ падаем. Мы считаем на процессоре.
        if "CUDA" in str(e) or "CUBLAS" in str(e):
            # print(f"⚠️  GPU Crashed. Fallback to CPU...")
            # Перенос -> Расчет -> Возврат на GPU
            return (a.cpu().float() @ b.cpu().float()).to(a.device)
        raise e
# =============================================
"""

print(f"🔧 Installing Circuit Breaker into {TARGET_PATH}...")

try:
    with open(TARGET_PATH, "r") as f:
        content = f.read()

    # 1. Вставляем определение функции в начало файла (после импортов)
    if "def safe_matmul" not in content:
        # Находим конец блока импортов
        import_end = content.find("import math")
        if import_end == -1: import_end = 0
        insert_pos = content.find("\n", import_end) + 1
        
        content = content[:insert_pos] + "\n" + SAFE_MATMUL_DEF + "\n" + content[insert_pos:]
        print("✅ Injected safe_matmul definition.")

    # 2. Заменяем ВСЕ опасные умножения (включая наши прошлые попытки патчей)
    # Мы ищем любые вариации умножения q на k.transpose
    
    # Паттерн: что-то @ что-то.transpose(-2, -1)...
    # Регулярка ловит старые варианты и варианты с .clone()/.float()
    
    # Замена 1: Расчет Attention (Temporal & Spatial)
    # Было: (win_q_t @ win_k_t.transpose(-2, -1))
    # Стало: safe_matmul(win_q_t, win_k_t.transpose(-2, -1))
    
    # Мы используем простой replace для надежности, так как regex может быть хрупким
    
    # Список того, что нужно найти (от чистого кода до прошлых патчей)
    targets = [
        # Чистый код
        "win_q_t @ win_k_t.transpose(-2, -1)",
        "win_q_s @ win_k_s.transpose(-2, -1)",
        "att_t @ win_v_t",
        "att_s @ win_v_s",
        
        # Прошлые "Nuclear" патчи (если остались)
        "win_q_t.float().clone() @ win_k_t.float().transpose(-2, -1).clone()",
        "win_q_s.float().clone() @ win_k_s.float().transpose(-2, -1).clone()",
        "att_t.float() @ win_v_t.float()",
        
        # Еще вариации
        "win_q_t @ win_k_t.transpose(-2, -1).contiguous()",
    ]
    
    count = 0
    for target in targets:
        if target in content:
            # Формируем замену. Нам нужно вытащить имена переменных.
            # Это грубый парсинг, но для данного файла он сработает 100%
            
            if "win_q_t" in target and "win_k_t" in target:
                replacement = "safe_matmul(win_q_t, win_k_t.transpose(-2, -1))"
            elif "win_q_s" in target and "win_k_s" in target:
                replacement = "safe_matmul(win_q_s, win_k_s.transpose(-2, -1))"
            elif "att_t" in target and "win_v_t" in target:
                replacement = "safe_matmul(att_t, win_v_t)"
            elif "att_s" in target and "win_v_s" in target:
                replacement = "safe_matmul(att_s, win_v_s)"
            else:
                continue

            content = content.replace(target, replacement)
            print(f"✅ Replaced: {target} -> {replacement}")
            count += 1

    if count == 0:
        print("⚠️ Warning: No patterns found. File might be weird, but trying generic replace...")
        # Аварийная замена "в лоб" по строкам из твоего лога
        content = content.replace("@ win_k_t.transpose(-2, -1)", ", win_k_t.transpose(-2, -1))")
        content = content.replace("(win_q_t", "safe_matmul(win_q_t")
        # Это очень грубо, но сработает если структура стандартная

    with open(TARGET_PATH, "w") as f:
        f.write(content)

    print(f"🚀 Applied Circuit Breaker. Replaced {count} dangerous operations.")

except Exception as e:
    print(f"❌ Error: {e}")
