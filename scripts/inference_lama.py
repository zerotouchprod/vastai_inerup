#!/usr/bin/env python3
import torch
import cv2
import numpy as np
import os
import sys
import argparse
import logging
from pathlib import Path
from PIL import Image

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [LaMa] %(message)s')
logger = logging.getLogger(__name__)

def pad_img_to_modulo(img, mod):
    channels, h, w = img.shape
    out_h = ((h + mod - 1) // mod) * mod
    out_w = ((w + mod - 1) // mod) * mod
    return np.pad(img, ((0,0), (0, out_h - h), (0, out_w - w)), mode='reflect')

def get_gaussian_weight(height, width, sigma_scale=0.25):
    # Создаем весовую маску для плавного склеивания тайлов
    x = np.linspace(-1, 1, width)
    y = np.linspace(-1, 1, height)
    x_grid, y_grid = np.meshgrid(x, y)
    d = np.sqrt(x_grid*x_grid + y_grid*y_grid)
    sigma = min(height, width) * sigma_scale
    g = np.exp(-(d**2) / (2.0 * 0.5**2))
    return torch.from_numpy(g).float()

def predict_tiled(model, img_t, mask_t, device, tile_size=1536, overlap=128):
    """
    Прогоняет изображение через модель по частям (тайлам) с перекрытием.
    Позволяет обрабатывать 4K+ на любой карте.
    img_t: [1, 3, H, W]
    mask_t: [1, 1, H, W]
    """
    b, c, h, w = img_t.shape
    
    # Результирующие канвасы
    out_img = torch.zeros_like(img_t)
    out_weights = torch.zeros(b, 1, h, w).to(device)
    
    # Сетка тайлов
    grid_h = range(0, h, tile_size - overlap)
    grid_w = range(0, w, tile_size - overlap)

    for y in grid_h:
        for x in grid_w:
            # Координаты текущего тайла
            y_end = min(y + tile_size, h)
            x_end = min(x + tile_size, w)
            y_start = max(0, y_end - tile_size)
            x_start = max(0, x_end - tile_size)

            # Вырезаем
            chunk_img = img_t[:, :, y_start:y_end, x_start:x_end]
            chunk_mask = mask_t[:, :, y_start:y_end, x_start:x_end]

            # Инференс
            with torch.no_grad():
                res = model(chunk_img, chunk_mask) # LaMa output

            # Весовая маска для блендинга (убирает швы)
            # Для простоты используем равномерный вес + mask (где была инпейнт зона)
            # Или простое сложение с усреднением
            
            # Простое наложение в output
            out_img[:, :, y_start:y_end, x_start:x_end] += res
            out_weights[:, :, y_start:y_end, x_start:x_end] += 1.0

    # Нормализация (деление на количество наложений)
    out_img = out_img / out_weights
    return out_img

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_dir', required=True)
    parser.add_argument('--mask_dir', required=True)
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--model_path', default='/opt/lama_models/big-lama.pt')
    parser.add_argument('--tile_size', type=int, default=2048, help="Размер тайла. Для 16GB VRAM ставь 2048 или больше.")
    parser.add_argument('--dilation', type=int, default=8, help="Насколько расширять маску (пиксели)")
    args = parser.parse_args()

    # 1. Device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logger.info(f"Device: {device} (FP32 Mode)")

    # 2. Model
    if not os.path.exists(args.model_path):
        logger.info("Downloading model...")
        Path(args.model_path).parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(
            "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",
            args.model_path
        )
    
    logger.info("Loading model...")
    # FP32 loading for stability
    model = torch.jit.load(args.model_path, map_location=device)
    model.eval().to(device)

    # 3. Processing
    input_dir = Path(args.input_dir)
    mask_dir = Path(args.mask_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    frames = sorted([f for f in os.listdir(input_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    logger.info(f"Processing {len(frames)} frames with Tiling (Size={args.tile_size}) and Dilation={args.dilation}...")

    processed = 0
    kernel = np.ones((args.dilation, args.dilation), np.uint8) if args.dilation > 0 else None

    for fname in frames:
        try:
            img_p = input_dir / fname
            mask_p = mask_dir / fname
            if not mask_p.exists(): continue

            # Load (Native Resolution)
            img = np.array(Image.open(img_p).convert('RGB'))
            mask = np.array(Image.open(mask_p).convert('L'))

            # Dilation (Fixes "HA" and halos)
            if kernel is not None:
                mask = cv2.dilate(mask, kernel, iterations=1)

            # Pad to mod 8 (LaMa requirement)
            img = pad_img_to_modulo(img.transpose(2,0,1), 8).transpose(1,2,0)
            # Mask pad logic needs to match image exactly or reshape
            h, w = img.shape[:2]
            mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)

            # To Tensor
            t_img = torch.from_numpy(img).permute(2,0,1).unsqueeze(0).to(device).float() / 255.0
            t_mask = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(device).float() / 255.0
            t_mask = (t_mask > 0.5).float()

            # Smart Inference
            if h <= args.tile_size and w <= args.tile_size:
                # Direct inference if small enough
                with torch.no_grad():
                    res = model(t_img, t_mask)
            else:
                # Tiled inference for huge images
                res = predict_tiled(model, t_img, t_mask, device, tile_size=args.tile_size)

            # Save
            out_np = res[0].permute(1,2,0).detach().cpu().numpy() * 255
            out_np = np.clip(out_np, 0, 255).astype(np.uint8)
            
            # Crop padding back if needed (optional, keeping it simple for now)
            
            cv2.imwrite(str(output_dir / fname), cv2.cvtColor(out_np, cv2.COLOR_RGB2BGR))
            processed += 1

        except Exception as e:
            logger.error(f"Error {fname}: {e}")

    logger.info(f"Done. {processed} images.")

if __name__ == '__main__':
    main()
