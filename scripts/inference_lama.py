#!/usr/bin/env python3
"""
LaMa inference script (FP32 STABLE VERSION).
Fixed for RTX 2060 / PyTorch JIT compatibility.
Disable FP16 to avoid ComplexHalf errors in Fourier layers.
"""
import torch
import cv2
import numpy as np
import os
import sys
import argparse
from pathlib import Path
from PIL import Image
import logging

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def safe_load_img(path: str, max_dim: int = 1280, is_mask: bool = False) -> np.ndarray:
    try:
        if is_mask:
            img = Image.open(path).convert('L')
        else:
            img = Image.open(path).convert('RGB')
        
        w, h = img.size
        # Resize to safe dimensions (Crucial for VRAM in FP32)
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
        
        # Align to 8 pixels (LaMa requirement)
        w, h = img.size
        w, h = (w // 8) * 8, (h // 8) * 8
        if w != img.size[0] or h != img.size[1]:
            img = img.crop((0, 0, w, h))
        
        return np.array(img)
    except Exception as e:
        logger.error(f"Failed to load image {path}: {e}")
        raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input_dir', required=True)
    parser.add_argument('--mask_dir', required=True)
    parser.add_argument('--output_dir', required=True)
    parser.add_argument('--model_path', default='/opt/lama_models/big-lama.pt')
    parser.add_argument('--max_dim', type=int, default=1280)
    parser.add_argument('--device', default='auto')
    # FP16 arg kept for compatibility but ignored/forced false
    parser.add_argument('--fp16', action='store_true') 
    
    args = parser.parse_args()
    
    # 1. Device Setup
    if args.device == 'auto':
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    else:
        device = torch.device(args.device)
    
    logger.info(f"Using device: {device}")
    
    # 2. Model Loading
    model_path = Path(args.model_path)
    if not model_path.exists():
        logger.info("Downloading model...")
        model_path.parent.mkdir(parents=True, exist_ok=True)
        torch.hub.download_url_to_file(
            "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",
            str(model_path)
        )

    logger.info(f"Loading model (FP32 Mode)...")
    try:
        model = torch.jit.load(str(model_path), map_location=device)
        model.eval()
        model.to(device) # Stay in FP32!
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        sys.exit(1)

    # 3. Processing
    input_dir = Path(args.input_dir)
    mask_dir = Path(args.mask_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    frames = sorted([f for f in os.listdir(input_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    logger.info(f"Processing {len(frames)} images...")

    processed = 0
    for fname in frames:
        try:
            img_p = input_dir / fname
            mask_p = mask_dir / fname
            
            if not mask_p.exists(): continue

            # Load & Preprocess
            img = safe_load_img(str(img_p), args.max_dim, is_mask=False)
            mask = safe_load_img(str(mask_p), args.max_dim, is_mask=True)
            
            # Resize mask if needed
            if img.shape[:2] != mask.shape[:2]:
                mask = cv2.resize(mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)

            # To Tensor (FP32)
            t_img = torch.from_numpy(img).permute(2,0,1).unsqueeze(0).to(device).float() / 255.0
            t_mask = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(device).float() / 255.0
            t_mask = (t_mask > 0.5).float()

            # Inference
            with torch.no_grad():
                output = model(t_img, t_mask)

            # Save
            output_np = output[0].permute(1, 2, 0).detach().cpu().numpy() * 255
            output_np = np.clip(output_np, 0, 255).astype(np.uint8)
            
            cv2.imwrite(str(output_dir / fname), cv2.cvtColor(output_np, cv2.COLOR_RGB2BGR))
            processed += 1
            
            if device.type == 'cuda' and processed % 10 == 0:
                torch.cuda.empty_cache()

        except Exception as e:
            logger.error(f"Error on {fname}: {e}")

    logger.info(f"Done. Processed {processed} frames.")

if __name__ == '__main__':
    main()
