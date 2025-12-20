import cv2
import numpy as np
import os


def test_detection(image_path):
    if not os.path.exists(image_path):
        print(f"Error: {image_path} not found!")
        return

    print(f"Processing {image_path}...")
    img = cv2.imread(image_path)
    h, w = img.shape[:2]

    # --- МЕТОД 1: ПОИСК НАСЫЩЕННОСТИ (Для цветного текста на ч/б) ---
    # Переводим в HSV. Канал S (Saturation) показывает "силу" цвета.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    s_channel = hsv[:, :, 1]
    # Всё, что имеет насыщенность > 40 — это цветное пятно.
    _, mask_sat = cv2.threshold(s_channel, 40, 255, cv2.THRESH_BINARY)
    cv2.imwrite("debug_1_saturation.jpg", mask_sat)
    print("Saved debug_1_saturation.jpg (Ищет фиолетовое/цветное)")

    # --- МЕТОД 2: ПОИСК ЯРКОСТИ (Для белого текста) ---
    # Переводим в LAB. Канал L (Lightness) показывает яркость.
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel = lab[:, :, 0]
    # Всё, что ярче 245 (почти чисто белый) — это текст.
    _, mask_white = cv2.threshold(l_channel, 245, 255, cv2.THRESH_BINARY)
    cv2.imwrite("debug_2_white.jpg", mask_white)
    print("Saved debug_2_white.jpg (Ищет ярко-белое)")

    # --- МЕТОД 3: SOBEL (Границы) ---
    # Классический поиск краев, но только вертикальных (бока букв).
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_16S, 1, 0, ksize=3)
    abs_grad_x = cv2.convertScaleAbs(grad_x)
    _, mask_sobel = cv2.threshold(abs_grad_x, 30, 255, cv2.THRESH_BINARY)
    # Склеиваем шум
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 3))
    mask_sobel = cv2.morphologyEx(mask_sobel, cv2.MORPH_CLOSE, kernel)
    cv2.imwrite("debug_3_sobel.jpg", mask_sobel)
    print("Saved debug_3_sobel.jpg (Ищет края букв)")

    # --- МЕТОД 4: ГИБРИД (Лучшая ставка) ---
    # Берем Цвет + Белый, чистим шум и склеиваем в слова.
    combined = cv2.bitwise_or(mask_sat, mask_white)

    # Морфология: склеиваем буквы (ширина 20, высота 5)
    kernel_connect = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 5))
    connected = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel_connect)

    # Фильтр мусора (убираем мелкие точки)
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    final_mask = np.zeros_like(gray)
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        # Если пятно больше 10px шириной и 8px высотой — оставляем
        if cw > 10 and ch > 8:
            cv2.rectangle(final_mask, (x, y), (x + cw, y + ch), 255, -1)

    # Накладываем маску на оригинал для наглядности (Красным)
    vis = img.copy()
    vis[final_mask > 0] = (0, 0, 255)

    cv2.imwrite("debug_4_FINAL.jpg", vis)
    print("Saved debug_4_FINAL.jpg (Итоговый результат)")


if __name__ == "__main__":
    test_detection("test_frame.jpg")