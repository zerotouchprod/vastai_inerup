#!/usr/bin/env python3
"""
CLI script for removing text from images using PaddleOCR + SAM 2 + OpenCV inpainting.
"""

import sys
import os
import argparse
import time
from pathlib import Path

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

import cv2
import numpy as np
from src.infrastructure.ocr.paddle_wrapper import PaddleWrapper
from src.infrastructure.segmentation.sam2_wrapper import SAM2ImageWrapper
from src.shared.logging import get_logger

logger = get_logger(__name__)

def process_image(image_path: str, output_dir: str = None, debug: bool = False) -> str:
    """
    Process single image to remove text.
    
    Args:
        image_path: Path to input image
        output_dir: Output directory (default: same as input)
        debug: Save debug mask if True
        
    Returns:
        Path to processed image
    """
    start_time = time.time()
    
    # Validate input
    input_path = Path(image_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    
    # Determine output path
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{input_path.stem}_cleaned{input_path.suffix}"
    else:
        output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"
    
    # Load image
    logger.info(f"Loading image: {input_path}")
    image = cv2.imread(str(input_path))
    if image is None:
        raise ValueError(f"Failed to load image: {input_path}")
    
    h, w = image.shape[:2]
    logger.info(f"Image size: {w}x{h}")
    
    # Step 1: Detect text with PaddleOCR
    logger.info("Step 1/3: Detecting text with PaddleOCR...")
    ocr = PaddleWrapper(lang='en', use_gpu=True)
    bboxes = ocr.detect_text(image, confidence_threshold=0.6)
    
    if not bboxes:
        logger.info("No text detected in image. Copying original image.")
        cv2.imwrite(str(output_path), image)
        elapsed = time.time() - start_time
        logger.info(f"Processing completed in {elapsed:.2f}s (no text found)")
        return str(output_path)
    
    logger.info(f"Detected {len(bboxes)} text regions")
    
    # Step 2: Generate precise mask with SAM 2
    logger.info("Step 2/3: Generating precise mask with SAM 2...")
    sam2 = SAM2ImageWrapper()
    mask = sam2.get_mask(image, bboxes)
    
    # Dilate mask slightly to ensure complete text removal
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)
    
    # Save debug mask if requested
    if debug:
        debug_mask_path = output_path.parent / f"{input_path.stem}_mask.png"
        cv2.imwrite(str(debug_mask_path), mask)
        logger.info(f"Debug mask saved: {debug_mask_path}")
    
    # Step 3: Inpaint using Telea algorithm
    logger.info("Step 3/3: Inpainting with OpenCV...")
    
    # Convert mask to required format (0 or 255)
    mask_uint8 = mask.astype(np.uint8)
    
    # Use Telea algorithm for inpainting
    result = cv2.inpaint(image, mask_uint8, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    
    # Save result
    cv2.imwrite(str(output_path), result)
    
    elapsed = time.time() - start_time
    logger.info(f"Processing completed in {elapsed:.2f}s")
    logger.info(f"Output saved: {output_path}")
    
    return str(output_path)

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Remove text from images using PaddleOCR + SAM 2 + OpenCV inpainting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --image test.jpg
  %(prog)s --image test.jpg --output ./results
  %(prog)s --image test.jpg --debug
        """
    )
    
    parser.add_argument(
        "--image",
        required=True,
        help="Path to input image"
    )
    
    parser.add_argument(
        "--output",
        help="Output directory (default: same as input)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save debug mask for verification"
    )
    
    parser.add_argument(
        "--lang",
        default="en",
        help="Language for OCR (default: en)"
    )
    
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.6,
        help="Confidence threshold for text detection (default: 0.6)"
    )
    
    args = parser.parse_args()
    
    try:
        # Process image
        output_path = process_image(
            image_path=args.image,
            output_dir=args.output,
            debug=args.debug
        )
        
        print(f"\n✅ Success! Processed image saved to: {output_path}")
        if args.debug:
            mask_path = Path(output_path).parent / f"{Path(args.image).stem}_mask.png"
            print(f"✅ Debug mask saved to: {mask_path}")
        
        sys.exit(0)
        
    except Exception as e:
        logger.error(f"Processing failed: {e}", exc_info=True)
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
