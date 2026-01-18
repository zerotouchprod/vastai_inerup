#!/usr/bin/env python3
"""
LaMa inference script optimized for RTX 2060 Mobile (6GB VRAM).
Uses TorchScript model from /opt/lama_models/big-lama.pt.
Includes FP16 support for GPU and automatic fallback to CPU.
Resizes input images to max 1280px for VRAM safety.
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
    """
    Load and resize image for memory safety.
    
    Args:
        path: Path to image file
        max_dim: Maximum dimension (width or height)
        is_mask: Whether loading a mask (grayscale)
    
    Returns:
        numpy array of image (RGB or grayscale)
    """
    try:
        if is_mask:
            img = Image.open(path).convert('L')  # Grayscale
        else:
            img = Image.open(path).convert('RGB')
        
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            logger.debug(f"Resized {Path(path).name} from {w}x{h} to {new_w}x{new_h}")
        
        # Align to 8 pixels (LaMa requirement)
        w, h = img.size
        w, h = (w // 8) * 8, (h // 8) * 8
        if w != img.size[0] or h != img.size[1]:
            img = img.crop((0, 0, w, h))
            logger.debug(f"Aligned to {w}x{h}")
        
        return np.array(img)
    except Exception as e:
        logger.error(f"Failed to load image {path}: {e}")
        raise


def main():
    parser = argparse.ArgumentParser(description='LaMa inpainting inference')
    parser.add_argument('--input_dir', required=True, help='Directory with input images')
    parser.add_argument('--mask_dir', required=True, help='Directory with mask images')
    parser.add_argument('--output_dir', required=True, help='Directory for output images')
    parser.add_argument('--model_path', default='/opt/lama_models/big-lama.pt',
                       help='Path to TorchScript model')
    parser.add_argument('--max_dim', type=int, default=1280,
                       help='Maximum dimension for resizing (default: 1280)')
    parser.add_argument('--device', choices=['auto', 'cuda', 'cpu'], default='auto',
                       help='Device to use (default: auto)')
    parser.add_argument('--fp16', action='store_true', default=True,
                       help='Use FP16 precision on GPU (default: True)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    
    # Determine device
    if args.device == 'auto':
        if torch.cuda.is_available():
            device = torch.device('cuda')
            logger.info("CUDA is available, using GPU")
        else:
            device = torch.device('cpu')
            logger.info("CUDA not available, using CPU")
    else:
        device = torch.device(args.device)
    
    logger.info(f"Using device: {device}")
    
    # Check model path
    model_path = Path(args.model_path)
    if not model_path.exists():
        logger.error(f"Model not found at {model_path}")
        logger.info("Attempting to download model...")
        try:
            model_path.parent.mkdir(parents=True, exist_ok=True)
            torch.hub.download_url_to_file(
                "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt",
                str(model_path)
            )
            logger.info(f"Model downloaded to {model_path}")
        except Exception as e:
            logger.error(f"Failed to download model: {e}")
            sys.exit(1)
    
    # Load model
    logger.info(f"Loading model from {model_path}")
    try:
        model = torch.jit.load(str(model_path), map_location=device)
        model.eval()
        logger.info("Model loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        sys.exit(1)
    
    # FP16 configuration
    use_fp16 = args.fp16 and device.type == 'cuda'
    if use_fp16:
        try:
            model = model.half()
            logger.info("Using FP16 precision")
        except Exception as e:
            logger.warning(f"Failed to convert model to FP16: {e}. Using FP32.")
            use_fp16 = False
    else:
        logger.info("Using FP32 precision")
    
    # Prepare directories
    input_dir = Path(args.input_dir)
    mask_dir = Path(args.mask_dir)
    output_dir = Path(args.output_dir)
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        sys.exit(1)
    if not mask_dir.exists():
        logger.error(f"Mask directory not found: {mask_dir}")
        sys.exit(1)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get image files
    extensions = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff')
    frames = sorted([f for f in os.listdir(input_dir) if f.lower().endswith(extensions)])
    
    if not frames:
        logger.error(f"No image files found in {input_dir}")
        sys.exit(1)
    
    logger.info(f"Found {len(frames)} images to process")
    
    # Process each frame
    processed = 0
    for fname in frames:
        img_path = input_dir / fname
        mask_path = mask_dir / fname
        
        if not mask_path.exists():
            logger.warning(f"Mask not found for {fname}, skipping")
            continue
        
        logger.debug(f"Processing {fname}")
        
        try:
            # Load images
            img = safe_load_img(str(img_path), max_dim=args.max_dim, is_mask=False)
            mask = safe_load_img(str(mask_path), max_dim=args.max_dim, is_mask=True)
            
            # Ensure mask matches image size
            if img.shape[:2] != mask.shape[:2]:
                logger.debug(f"Resizing mask to match image {img.shape[:2]}")
                mask = cv2.resize(mask, (img.shape[1], img.shape[0]), 
                                 interpolation=cv2.INTER_NEAREST)
            
            # Convert to tensors
            t_img = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).to(device).float() / 255.0
            t_mask = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(device).float() / 255.0
            t_mask = (t_mask > 0.5).float()
            
            if use_fp16:
                t_img = t_img.half()
                t_mask = t_mask.half()
            
            # Inference
            with torch.no_grad():
                output = model(t_img, t_mask)
            
            # Convert back to numpy
            output_np = output[0].permute(1, 2, 0).detach().cpu().float().numpy() * 255
            output_np = np.clip(output_np, 0, 255).astype(np.uint8)
            
            # Save result
            output_path = output_dir / fname
            # OpenCV uses BGR, convert RGB to BGR
            cv2.imwrite(str(output_path), cv2.cvtColor(output_np, cv2.COLOR_RGB2BGR))
            
            processed += 1
            logger.debug(f"Saved result to {output_path}")
            
            # Cleanup GPU memory
            if device.type == 'cuda':
                torch.cuda.empty_cache()
                
        except Exception as e:
            logger.error(f"Error processing {fname}: {e}")
            continue
    
    logger.info(f"Processing complete. Successfully processed {processed}/{len(frames)} images.")
    if processed == 0:
        logger.warning("No images were processed successfully.")
        sys.exit(1)


if __name__ == '__main__':
    main()
