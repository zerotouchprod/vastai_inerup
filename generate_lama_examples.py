#!/usr/bin/env python3
"""
Generate example images showing LaMaAdapter results.
Creates before/after comparison images for documentation.
"""
import os
import sys
from pathlib import Path
import cv2
import numpy as np

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.infrastructure.inpainting.lama_adapter import LaMaAdapter
from src.core.config import get_config

def create_example_frame(width=640, height=360):
    """Create a simple example frame with text and background."""
    # Create a gradient background
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    for i in range(height):
        color = int(100 + (i / height) * 100)
        frame[i, :] = (color, color, color)
    
    # Add some objects
    cv2.rectangle(frame, (50, 50), (200, 150), (0, 100, 200), -1)  # Blue rectangle
    cv2.circle(frame, (400, 100), 40, (200, 100, 0), -1)  # Orange circle
    
    # Add text to be removed (simulating subtitle)
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(frame, 'REMOVE THIS', (150, 250), font, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, 'SUBTITLE TEXT', (130, 280), font, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    return frame

def create_example_mask(width=640, height=360):
    """Create mask covering the text area."""
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # Mask the text area
    cv2.rectangle(mask, (130, 230), (450, 300), 255, -1)
    
    # Dilate slightly to cover text edges
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)
    
    return mask

def create_comparison_image(original, mask, result):
    """Create a side-by-side comparison image."""
    h, w = original.shape[:2]
    
    # Convert mask to 3-channel for display
    mask_display = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    
    # Create labels
    font = cv2.FONT_HERSHEY_SIMPLEX
    label_height = 30
    
    # Add label to original
    original_labeled = original.copy()
    cv2.putText(original_labeled, 'ORIGINAL', (10, 25), font, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Add label to mask
    mask_labeled = mask_display.copy()
    cv2.putText(mask_labeled, 'MASK', (10, 25), font, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Add label to result
    result_labeled = result.copy()
    cv2.putText(result_labeled, 'INPAINTED', (10, 25), font, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    
    # Create comparison (original | mask | result)
    comparison = np.hstack([original_labeled, mask_labeled, result_labeled])
    
    # Add separator lines
    cv2.line(comparison, (w, 0), (w, h), (255, 255, 255), 2)
    cv2.line(comparison, (w*2, 0), (w*2, h), (255, 255, 255), 2)
    
    # Add title
    title = np.zeros((50, w*3, 3), dtype=np.uint8)
    cv2.putText(title, 'LaMa Inpainting Example - Subtitle Removal', (10, 35), font, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    
    final_image = np.vstack([title, comparison])
    return final_image

def main():
    print("=" * 60)
    print("Generating LaMaAdapter Example Images")
    print("=" * 60)
    
    output_dir = Path("examples/lama_results")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create example frame and mask
    print("Creating example frame and mask...")
    frame = create_example_frame()
    mask = create_example_mask()
    
    # Save original and mask
    cv2.imwrite(str(output_dir / "example_original.png"), frame)
    cv2.imwrite(str(output_dir / "example_mask.png"), mask)
    
    # Initialize LaMaAdapter with temporary config
    print("Initializing LaMaAdapter...")
    
    # Create temporary directory for model
    import tempfile
    temp_dir = tempfile.mkdtemp()
    temp_model_path = Path(temp_dir) / "big-lama.pt"
    
    # Monkey-patch the config
    config = get_config()
    original_model_path = config.LAMA_MODEL_PATH
    config.LAMA_MODEL_PATH = temp_model_path
    
    try:
        adapter = LaMaAdapter()
        print(f"✅ LaMaAdapter initialized")
        
        # Process the frame
        print("Processing frame with LaMa...")
        from src.schemas.roi import InpaintConfig
        inpaint_config = InpaintConfig(
            method='lama',
            padding_px=20,
            use_roi_optimization=True,
            fallback_to_cv2=True
        )
        
        result = adapter.process_with_roi(frame, mask, inpaint_config)
        
        # Save result
        cv2.imwrite(str(output_dir / "example_result.png"), result)
        
        # Create comparison image
        comparison = create_comparison_image(frame, mask, result)
        cv2.imwrite(str(output_dir / "example_comparison.png"), comparison)
        
        # Calculate and display metrics
        mask_bool = mask > 0
        original_region = frame[mask_bool]
        inpainted_region = result[mask_bool]
        
        diff = np.mean(np.abs(original_region.astype(float) - inpainted_region.astype(float)))
        
        print(f"\n✅ Example generation successful!")
        print(f"   Output directory: {output_dir.absolute()}")
        print(f"   Generated files:")
        print(f"     - example_original.png: Original frame with text")
        print(f"     - example_mask.png: Mask covering text area")
        print(f"     - example_result.png: Inpainted result")
        print(f"     - example_comparison.png: Side-by-side comparison")
        print(f"\n   Inpainting metrics:")
        print(f"     - Mean difference in masked region: {diff:.2f}")
        print(f"     - Original region mean: {np.mean(original_region):.2f}")
        print(f"     - Inpainted region mean: {np.mean(inpainted_region):.2f}")
        
        if diff > 10:
            print(f"     - ✅ Significant change detected - inpainting worked!")
        else:
            print(f"     - ⚠️  Minimal change - may be using lightweight model")
        
        # Create a simple HTML viewer
        create_html_viewer(output_dir)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Restore original config
        config.LAMA_MODEL_PATH = original_model_path
        # Cleanup temp directory
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    print("\n" + "=" * 60)
    print("Example generation completed!")
    print("=" * 60)

def create_html_viewer(output_dir):
    """Create a simple HTML file to view the results."""
    html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>LaMa Inpainting Results</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .container {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .image-card {
            background: white;
            border-radius: 8px;
            padding: 15px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .image-card h3 {
            margin-top: 0;
            color: #444;
            border-bottom: 2px solid #4CAF50;
            padding-bottom: 10px;
        }
        .image-card img {
            width: 100%;
            height: auto;
            border-radius: 4px;
        }
        .comparison {
            grid-column: 1 / -1;
            text-align: center;
        }
        .comparison img {
            max-width: 100%;
            height: auto;
        }
        .info {
            background: #e8f5e9;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
        }
        .info h3 {
            color: #2e7d32;
            margin-top: 0;
        }
    </style>
</head>
<body>
    <h1>LaMa Inpainting Example Results</h1>
    
    <div class="container">
        <div class="image-card">
            <h3>Original Image</h3>
            <img src="example_original.png" alt="Original image with text">
            <p>Original frame with simulated subtitle text.</p>
        </div>
        
        <div class="image-card">
            <h3>Mask</h3>
            <img src="example_mask.png" alt="Mask covering text">
            <p>Binary mask indicating the region to inpaint (text area).</p>
        </div>
        
        <div class="image-card">
            <h3>Inpainted Result</h3>
            <img src="example_result.png" alt="Inpainted result">
            <p>Result after LaMa inpainting - text removed.</p>
        </div>
    </div>
    
    <div class="comparison">
        <h2>Side-by-Side Comparison</h2>
        <img src="example_comparison.png" alt="Comparison">
        <p>Comparison showing original, mask, and result side by side.</p>
    </div>
    
    <div class="info">
        <h3>About LaMa Inpainting</h3>
        <p>LaMa (Large Mask Inpainting) is a deep learning model for image inpainting that can remove objects or text from images while preserving context and texture.</p>
        <p>This example demonstrates how LaMaAdapter integrates into the vastai_inerup project for subtitle removal in videos.</p>
        <p><strong>Key features:</strong></p>
        <ul>
            <li>High-quality inpainting even with large masks</li>
            <li>Fast inference with GPU acceleration</li>
            <li>ROI optimization for processing only relevant regions</li>
            <li>Integration with the project's clean architecture</li>
        </ul>
    </div>
</body>
</html>
    """
    
    html_path = output_dir / "index.html"
    with open(html_path, 'w') as f:
        f.write(html_content)
    
    print(f"   Created HTML viewer: {html_path}")

if __name__ == "__main__":
    main()
